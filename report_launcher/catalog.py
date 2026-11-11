"""Root-owned immutable inventory; no extraction, shell or application imports."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from .protocol import Rejected, _object
from .validation import canonical, digest, CONTRACT


def trusted(path, directory=False):
    path = Path(path)
    if not path.is_absolute():
        raise Rejected("catalog_path_invalid")
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise Rejected("catalog_ownership_invalid")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise Rejected("catalog_path_invalid")
    if directory != stat.S_ISDIR(info.st_mode) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise Rejected("catalog_type_invalid")
    return path


def _read(path, limit=8*1024*1024):
    path = trusted(path)
    # O_NOFOLLOW and a second fstat also reject a replaced final component.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != 0 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
            raise Rejected("catalog_ownership_invalid")
        data = stream.read(limit+1)
    if len(data) > limit:
        raise Rejected("catalog_size_invalid")
    return data


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError):
        raise Rejected("catalog_json_invalid") from None


class Catalog:
    def __init__(self, path):
        self.data = _json(_read(path))
        if (not isinstance(self.data, dict) or set(self.data) != {"protocol", "enabled", "dispatcher_uid", "private_report_root", "releases"}
                or self.data["protocol"] != 1 or type(self.data["enabled"]) is not bool
                or type(self.data["dispatcher_uid"]) is not int or self.data["dispatcher_uid"] <= 0
                or not isinstance(self.data["releases"], dict)
                or not isinstance(self.data["private_report_root"], str)
                or not self.data["private_report_root"].startswith("/")
                or self.data["private_report_root"] == "/"
                or any(part in ("..", ".", "") for part in self.data["private_report_root"].split("/")[1:])):
            raise Rejected("catalog_invalid")

    @property
    def dispatcher_uid(self):
        return self.data["dispatcher_uid"]

    def validate(self, release_id):
        if not self.data["enabled"]:
            raise Rejected("launcher_disabled")
        record = self.data["releases"].get(release_id)
        if (not re.fullmatch(r"[a-f0-9]{40,64}", release_id) or not isinstance(record, dict)
                or set(record) != {"root", "environment_file", "manifest_sha256", "bundle_sha256"}
                or not all(isinstance(record[name], str) and re.fullmatch(r"[a-f0-9]{64}", record[name])
                           for name in ("manifest_sha256", "bundle_sha256"))):
            raise Rejected("release_not_authorized")
        root = trusted(record["root"], directory=True)
        environment = trusted(record["environment_file"])
        if environment.stat().st_mode & 0o077:
            raise Rejected("environment_permissions_invalid")
        allowed_environment = {"DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_DB_BACKEND",
            "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT",
            "REPORT_EXECUTOR_ENABLED", "REPORT_SYSTEMD_SUPERVISION_ENABLED", "REPORT_EXECUTOR_RELEASE_ID",
            "REPORT_EXECUTOR_SYSTEMD_USER", "REPORT_PRIVATE_ROOT", "REPORT_LIBREOFFICE_EXECUTABLE",
            "LANG", "LC_ALL", "TZ", "MPLCONFIGDIR", "TMPDIR"}
        environment_keys = set()
        environment_values = {}
        try:
            for line in _read(environment, limit=65536).decode("utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                if key not in allowed_environment or key in environment_keys or "\\" in value or "\x00" in value:
                    raise ValueError
                environment_keys.add(key)
                environment_values[key] = value
        except (ValueError, UnicodeError):
            raise Rejected("environment_invalid") from None
        expected_environment = {"DJANGO_DB_BACKEND": "postgresql", "DJANGO_DEBUG": "false",
            "REPORT_EXECUTOR_RELEASE_ID": release_id, "REPORT_EXECUTOR_SYSTEMD_USER": "analise_app",
            "REPORT_PRIVATE_ROOT": self.data["private_report_root"],
            "REPORT_EXECUTOR_ENABLED": "true", "REPORT_SYSTEMD_SUPERVISION_ENABLED": "true"}
        if any(environment_values.get(key) != value for key, value in expected_environment.items()):
            raise Rejected("environment_contract_invalid")
        raw = _read(root / "manifest.json")
        if hashlib.sha256(raw).hexdigest() != record["manifest_sha256"]:
            raise Rejected("manifest_mismatch")
        manifest = _json(raw)
        if (not isinstance(manifest, dict) or set(manifest) != {"protocol", "release_id", "contract", "files"}
                or manifest["protocol"] != 1 or manifest["release_id"] != release_id
                or manifest["contract"] != CONTRACT or not isinstance(manifest["files"], list)
                or not 1 <= len(manifest["files"]) <= 50000
                or digest(manifest["files"]) != record["bundle_sha256"]):
            raise Rejected("manifest_invalid")
        inventory = {}
        for item in manifest["files"]:
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                raise Rejected("inventory_invalid")
            name = item["path"]
            if (not isinstance(name, str) or not name or "\\" in name or "\x00" in name
                    or PurePosixPath(name).is_absolute() or PurePosixPath(name).as_posix() != name
                    or any(part in ("..", ".") for part in name.split("/"))
                    or name == "manifest.json" or name in inventory
                    or not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
                raise Rejected("inventory_invalid")
            inventory[name] = item["sha256"]
        actual = set()
        for directory, directories, files in os.walk(root, followlinks=False):
            trusted(directory, directory=True)
            for child in directories:
                trusted(Path(directory) / child, directory=True)
            for child in files:
                path = Path(directory) / child
                name = path.relative_to(root).as_posix()
                if name == "manifest.json":
                    continue
                actual.add(name)
                if name not in inventory:
                    raise Rejected("unlisted_release_file")
                path = trusted(path)
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
                with os.fdopen(descriptor, "rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if checksum != inventory[name]:
                    raise Rejected("release_file_mismatch")
        if actual != set(inventory) or not {"manage.py", ".venv/bin/python", ".venv/pyvenv.cfg"}.issubset(actual):
            raise Rejected("release_inventory_incomplete")
        python = root / ".venv/bin/python"
        if not python.stat().st_mode & 0o111:
            raise Rejected("interpreter_not_executable")
        # All symlinks (including venv interpreter/lib64) are deliberately rejected
        # in inventory v1: packaging must normalize them in a disposable build.
        return {**record, "release_id": release_id, "python": str(python),
                "private_report_root": self.data["private_report_root"]}


def unit_properties(release, identity_id):
    from uuid import UUID
    key = UUID(identity_id)
    root = release["root"]
    argv = [release["python"], "-B", str(Path(root) / "manage.py"),
            "execute_supervised_report", "--identity-id", str(key)]
    return {"Type": "exec", "User": "analise_app", "Group": "analise_app",
        "WorkingDirectory": root, "ExecStart": [(release["python"], argv, False)],
        "EnvironmentFiles": [(release["environment_file"], False)],
        "Restart": "no", "KillMode": "control-group", "KillSignal": 15, "SendSIGKILL": True,
        "TimeoutStopUSec": 20000000, "RuntimeMaxUSec": 180000000,
        "MemoryMax": 1536*1024*1024, "TasksMax": 64, "OOMPolicy": "kill", "Delegate": False,
        "NoNewPrivileges": True, "CapabilityBoundingSet": 0, "AmbientCapabilities": 0,
        "ProtectControlGroups": True, "ProtectSystem": "strict", "ProtectHome": "yes",
        "PrivateTmp": True, "PrivateDevices": True, "RestrictSUIDSGID": True,
        "RestrictNamespaces": 0, "UMask": 0o077,
        "ReadWritePaths": [release["private_report_root"]],
        "StandardOutput": "journal", "StandardError": "journal"}


POLICY_SHA256 = digest({"protocol": 1, "properties": "fixed-v1", "contract": CONTRACT})
