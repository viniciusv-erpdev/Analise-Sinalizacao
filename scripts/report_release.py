"""Unprivileged release preparation. No deployment, root commands or network.

Only the explicit lib64 -> lib alias from venv may be materialized. All other
links fail closed. Catalogue ownership checks remain the external authority.
"""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import zipfile

from report_launcher.validation import canonical, digest, CONTRACT


def files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Release must be a real directory")
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("Release contains a link or special file")
            if name in {".git", ".env", "db.sqlite3"} or name.startswith(".env."):
                raise ValueError("Release contains checkout state or a secret file")
        for name in names:
            yield Path(directory) / name


def normalize_lib64(root):
    root = Path(root).absolute()
    venv = root / ".venv"
    if root.is_symlink() or venv.is_symlink() or not venv.is_dir():
        raise ValueError("Real root and venv required")
    alias = venv / "lib64"
    if not alias.is_symlink():
        return False
    if os.readlink(alias) != "lib" or (venv / "lib").is_symlink():
        raise ValueError("Only the literal lib64 -> lib alias is accepted")
    list(files(venv / "lib"))  # Refuse nested symlinks before copytree can follow them.
    copy = venv / ".lib64-copy"
    if copy.exists() or copy.is_symlink():
        raise ValueError("Unfinished normalization requires manual inspection")
    shutil.copytree(venv / "lib", copy)
    alias.unlink()  # A checked link only, never recursively delete a supplied path.
    copy.rename(alias)
    return True


def requirement_pins(root, path="requirements.txt", seen=None):
    root = Path(root).resolve()
    seen = set() if seen is None else seen
    source = root / path
    if source.resolve() != source.absolute() or root not in source.resolve().parents:
        raise ValueError("Requirement include escapes release or uses a symlink")
    if path in seen:
        raise ValueError("Recursive requirement include")
    seen = seen | {path}
    pins = {}
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            included = (Path(path).parent / line[3:].strip()).as_posix()
            incoming = requirement_pins(root, included, seen)
        else:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9_.+!-]+)", line)
            if not match:
                raise ValueError("Only exact pins or local -r includes are supported")
            incoming = {re.sub(r"[-_.]+", "-", match[1]).lower(): match[2]}
        for name, version in incoming.items():
            if name in pins and pins[name] != version:
                raise ValueError("Conflicting dependency pins")
            pins[name] = version
    return pins


def runtime_metadata(root):
    root = Path(root).absolute()
    list(files(root))
    python = root / ".venv/bin/python"
    cfg = root / ".venv/pyvenv.cfg"
    if not python.is_file() or not cfg.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Copied executable and pyvenv.cfg required")
    config = dict(line.split("=", 1) for line in cfg.read_text().splitlines() if "=" in line)
    config = {key.strip(): value.strip() for key, value in config.items()}
    if config.get("include-system-site-packages") != "false":
        raise ValueError("System site packages are forbidden")
    code = ("import sys,json,platform,importlib.metadata as m; "
        "print(json.dumps(dict(prefix=sys.prefix,base_prefix=sys.base_prefix,python=sys.version,"
        "abi=sys.implementation.cache_tag,machine=platform.machine(),"
        "packages={d.metadata['Name']:d.version for d in m.distributions()})))")
    observed = subprocess.run([str(python), "-I", "-B", "-c", code], check=True,
        capture_output=True, text=True, timeout=30, cwd=root)
    data = json.loads(observed.stdout)
    if Path(data["prefix"]).resolve() != root / ".venv" or data["prefix"] == data["base_prefix"]:
        raise ValueError("Venv was relocated or uses a wrong prefix")
    installed = {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in data["packages"].items()}
    pins = requirement_pins(root)
    if pins.get("pypdf") != "6.21.3" or any(installed.get(name) != version for name, version in pins.items()):
        raise ValueError("Installed dependencies do not match publication pins")
    locked = {}
    for line in (root / "requirements.resolved.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-z0-9][a-z0-9-]*)==([A-Za-z0-9_.+!-]+)((?: --hash=sha256:[a-f0-9]{64})+)", line)
        if not match or match[1] in locked:
            raise ValueError("Invalid complete wheel lock")
        locked[match[1]] = match[2]
    if locked != installed:
        raise ValueError("Installed distributions differ from the resolved wheel lock")
    subprocess.run([str(python), "-I", "-B", "-m", "pip", "check"], check=True,
        capture_output=True, text=True, timeout=30, cwd=root)
    return data


def write_manifest(root, release_id, metadata):
    root = Path(root).absolute()
    list(files(root))
    if not re.fullmatch(r"[a-f0-9]{40,64}", release_id):
        raise ValueError("A reviewed commit identity is required")
    if (root / "manifest.json").exists():
        raise ValueError("Never overwrite an existing manifest")
    (root / "release-runtime.json").write_bytes(canonical(metadata))
    inventory = []
    for path in sorted(files(root)):
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        inventory.append({"path": path.relative_to(root).as_posix(), "sha256": checksum})
    required = {"manage.py", ".venv/bin/python", ".venv/pyvenv.cfg", "requirements.txt", "requirements-pdf.txt",
                "requirements.resolved.txt"}
    if not required.issubset({item["path"] for item in inventory}) or len(inventory) > 50000:
        raise ValueError("Incomplete or oversized inventory")
    raw = canonical({"protocol": 1, "release_id": release_id, "contract": CONTRACT, "files": inventory})
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Manifest exceeds launcher limit")
    with (root / "manifest.json").open("xb") as stream:
        stream.write(raw)
    return {"release_id": release_id, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "bundle_sha256": digest(inventory), "files": len(inventory)}


def wheel_lock(wheelhouse):
    """Resolved wheel-only lock: all transitives included, immutable bytes pinned."""
    packages = {}
    for wheel in sorted(Path(wheelhouse).glob("*.whl")):
        if wheel.is_symlink():
            raise ValueError("Wheel links forbidden")
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError("Invalid wheel metadata")
            metadata = BytesParser().parsebytes(archive.read(names[0]))
        name = re.sub(r"[-_.]+", "-", metadata["Name"]).lower()
        version = metadata["Version"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or not re.fullmatch(r"[A-Za-z0-9_.+!-]+", version):
            raise ValueError("Invalid wheel identity")
        if name in packages and packages[name][0] != version:
            raise ValueError("Mixed wheel versions")
        with wheel.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        packages.setdefault(name, (version, []))[1].append(checksum)
    if not packages:
        raise ValueError("Wheelhouse is empty")
    return "\n".join(f"{name}=={version} " + " ".join("--hash=sha256:"+sha for sha in sorted(hashes))
                     for name, (version, hashes) in sorted(packages.items())) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    normalize = sub.add_parser("normalize-lib64")
    normalize.add_argument("root", type=Path)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("root", type=Path)
    manifest.add_argument("--release-id", required=True)
    lock = sub.add_parser("wheel-lock")
    lock.add_argument("wheelhouse", type=Path)
    args = parser.parse_args()
    if args.command == "normalize-lib64":
        print(json.dumps({"normalized": normalize_lib64(args.root)}))
    elif args.command == "manifest":
        print(json.dumps(write_manifest(args.root, args.release_id, runtime_metadata(args.root)), sort_keys=True))
    else:
        print(wheel_lock(args.wheelhouse), end="")


if __name__ == "__main__":
    main()
