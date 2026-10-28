"""Private immutable local artifacts. No public URL; replaceable storage interface."""
import hashlib
import os
from pathlib import Path
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ArtifactStorageError(Exception):
    pass


class PrivateReportStorage:
    def __init__(self):
        configured = settings.REPORT_PRIVATE_ROOT
        root = Path(configured)
        if not configured or not root.is_absolute():
            raise ImproperlyConfigured("REPORT_PRIVATE_ROOT must be an absolute private directory")
        self.root = root.resolve()
        public = [Path(settings.BASE_DIR).resolve()]
        for name in ("STATIC_ROOT", "MEDIA_ROOT"):
            if getattr(settings, name, None):
                public.append(Path(getattr(settings, name)).resolve())
        for path in getattr(settings, "STATICFILES_DIRS", ()):
            public.append(Path(path[1] if isinstance(path, (list, tuple)) else path).resolve())
        if any(self.root == path or path in self.root.parents or self.root in path.parents for path in public):
            raise ImproperlyConfigured("Report storage must be outside checkout/static/media")

    def _path(self, key):
        if not re.fullmatch(r"[a-f0-9-]{36}/[a-f0-9-]{36}/[a-f0-9-]{36}\.(pdf|docx|jpg|png)", key):
            raise ArtifactStorageError("invalid_storage_key")
        path = self.root.joinpath(*key.split("/"))
        if any(parent.is_symlink() for parent in (self.root, *path.parents)) or path.is_symlink():
            raise ArtifactStorageError("unsafe_storage_path")
        if self.root not in path.resolve().parents:
            raise ArtifactStorageError("unsafe_storage_path")
        return path

    def save(self, key, data):
        path = self._path(key)
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.parent.parent.mkdir(mode=0o700, exist_ok=True)
            path.parent.mkdir(mode=0o700, exist_ok=True)
            # Exclusive creation: no overwrite of a previous version or execution.
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise ArtifactStorageError("artifact_storage_failed") from None

    def read(self, artifact):
        try:
            path = self._path(artifact.storage_key)
            if path.stat().st_size != artifact.size:
                raise ArtifactStorageError("artifact_integrity_failed")
            data = path.read_bytes()
        except OSError:
            raise ArtifactStorageError("artifact_missing") from None
        if hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise ArtifactStorageError("artifact_integrity_failed")
        return data

    def open_verified(self, artifact):
        """Verify in bounded memory, then hand the same open file to FileResponse.

        Published storage is immutable and writable only by the service account.
        Callers own the returned handle and must close it after streaming.
        """
        stream = None
        try:
            stream = self._path(artifact.storage_key).open("rb")
            if os.fstat(stream.fileno()).st_size != artifact.size:
                raise ArtifactStorageError("artifact_integrity_failed")
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(128 * 1024):
                size += len(chunk)
                digest.update(chunk)
            if size != artifact.size or digest.hexdigest() != artifact.sha256:
                raise ArtifactStorageError("artifact_integrity_failed")
            stream.seek(0)
            return stream
        except (OSError, ArtifactStorageError):
            if stream is not None:
                stream.close()
            raise ArtifactStorageError("artifact_unavailable") from None

    def modified_at(self, key):
        return self._path(key).stat().st_mtime

    def keys(self):
        if self.root.exists():
            for path in self.root.glob("*/*/*"):
                if path.is_file() and not path.is_symlink():
                    key = path.relative_to(self.root).as_posix()
                    self._path(key)
                    yield key

    def delete(self, key):
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            raise ArtifactStorageError("artifact_cleanup_failed") from None

    def url(self, key):
        raise NotImplementedError("Private artifacts have no public URLs")
