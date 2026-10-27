"""Bounded subprocess execution for the PDF PoC. No Django or database access."""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


class ProcessError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    # Converter output may contain document fragments/paths: never log automatically.
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


class _WindowsJob:
    """Un-named job: kill descendants on close, with an aggregate memory ceiling."""
    def __init__(self, memory_bytes):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64),
                ("flags", w.DWORD), ("min_working", c.c_size_t), ("max_working", c.c_size_t),
                ("active", w.DWORD), ("affinity", c.c_size_t),
                ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("read_ops", "write_ops", "other_ops",
                                                       "read_bytes", "write_bytes", "other_bytes")]
        class Extended(c.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", c.c_size_t),
                ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.AssignProcessToJobObject.restype = w.BOOL
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ProcessError("process_isolation_failed")
        limits = Extended()
        limits.basic.flags = 0x2000 | 0x200  # KILL_ON_JOB_CLOSE | JOB_MEMORY
        limits.job_memory = memory_bytes
        if not kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            self.close()
            raise ProcessError("process_isolation_failed")

    def assign(self, pid):
        handle = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if not handle:
            raise ProcessError("process_isolation_failed")
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                raise ProcessError("process_isolation_failed")
        finally:
            self.kernel.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


# A trusted Python launcher avoids preexec_fn in a multithreaded Django process.
# On Windows it cannot spawn the converter before assignment to the Job Object.
_LAUNCHER = """
import json, os, sys
limits = json.loads(sys.argv[1])
if os.name == 'nt':
    if sys.stdin.buffer.read(1) != b'G':
        sys.exit(125)
    import subprocess
    # Windows execv may let the launcher exit before its replacement finishes.
    # Keep the job owner alive until the actual converter has exited.
    child = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    sys.exit(child.wait())
else:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for key, value in ((resource.RLIMIT_AS, limits['memory']),
                       (resource.RLIMIT_CPU, limits['cpu']),
                       (resource.RLIMIT_FSIZE, limits['file'])):
        resource.setrlimit(key, (value, value))
os.execv(sys.argv[2], sys.argv[2:])
"""


def _workspace_size(root, ceiling):
    size, count = 0, 0
    for directory, _, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            try:
                size += path.lstat().st_size
            except FileNotFoundError:
                continue
            count += 1
            if size > ceiling or count > 4096:
                raise ProcessError("temporary_storage_limit")
    return size


def runtime_executable():
    if os.name != "nt":
        return sys.executable
    # Venv redirectors can spawn the real interpreter before job assignment.
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleFileNameW.argtypes = [w.HMODULE, w.LPWSTR, w.DWORD]
    kernel.GetModuleFileNameW.restype = w.DWORD
    buffer = c.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(None, buffer, len(buffer))
    if not length or length >= len(buffer):
        raise ProcessError("process_isolation_failed")
    return buffer.value


def run_process(command, *, cwd, env, timeout, memory_bytes, file_bytes, workspace_bytes):
    """Only call with internally constructed argv. No shell, no inherited stdin."""
    limits = json.dumps({"memory": memory_bytes, "cpu": math.ceil(timeout)+1, "file": file_bytes})
    argv = [runtime_executable(), "-B", "-c", _LAUNCHER, limits, *map(str, command)]
    job = _WindowsJob(memory_bytes) if os.name == "nt" else None
    process = None
    streams, threads = [], []
    captures = [bytearray(), bytearray()]

    def drain(stream, destination):
        while chunk := stream.read(4096):
            destination.extend(chunk)
            del destination[:-16384]  # bounded private diagnostic tails

    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, shell=False,
            stdin=subprocess.PIPE if job else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        streams = [process.stdout, process.stderr]
        for stream, capture in zip(streams, captures):
            thread = threading.Thread(target=drain, args=(stream,capture), daemon=True)
            thread.start()
            threads.append(thread)
        if job:
            job.assign(process.pid)
            process.stdin.write(b"G")
            process.stdin.close()
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            _workspace_size(cwd, workspace_bytes)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessError("conversion_timeout")
            try:
                process.wait(timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                pass
        _workspace_size(cwd, workspace_bytes)
    except OSError:
        raise ProcessError("process_start_failed") from None
    finally:
        # Always terminate the entire group/job, including children left after success.
        if job:
            job.close()
        elif process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise ProcessError("process_cleanup_failed") from None
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        for thread in threads:
            thread.join(timeout=5)
        if any(thread.is_alive() for thread in threads):
            # Do not block the Django thread forever closing a pipe held by an escaped child.
            raise ProcessError("process_cleanup_failed")
        for stream in streams:
            stream.close()
    return ProcessResult(process.returncode, bytes(captures[0]), bytes(captures[1]))
