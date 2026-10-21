"""
Subprocess execution manager with configurable real timeouts and process tree cancellation.
Guarantees:
- Real subprocess timeouts (independent of CLI flags like Remotion's internal --timeout).
- Process tree termination on cancellation or timeout (kills parent and all child node/ffmpeg/chromium processes).
- Never leaves orphaned background processes.
"""

import os
import sys
import time
import logging
import threading
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Callable, Dict
import psutil

from errors import ProcessTimeoutError, JobCancelledError

logger = logging.getLogger(__name__)

# Configurable defaults from environment
DEFAULT_FFMPEG_TIMEOUT = float(os.getenv("FFMPEG_TIMEOUT", "180"))
DEFAULT_REMOTION_TIMEOUT = float(os.getenv("REMOTION_RENDER_TIMEOUT", "600"))
DEFAULT_GENERAL_TIMEOUT = float(os.getenv("SUBPROCESS_TIMEOUT", "120"))


@dataclass
class ProcessOutput:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


def kill_process_tree(pid: int, timeout: float = 3.0) -> None:
    """
    Terminates an entire process tree recursively given the root PID.
    Cross-platform (Windows / Linux / macOS) using psutil.
    """
    try:
        parent = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return

    try:
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []

    # Send SIGTERM / terminate first
    for child in children:
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    try:
        parent.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    # Wait for graceful termination
    alive = []
    if children or parent:
        try:
            _, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        except Exception:
            pass

    # Force kill any lingering processes
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


class ProcessRunner:
    """
    Executes subprocess commands with:
    - Real timeout enforcement
    - Process tree cancellation
    - Output capture
    - Job PID registration hook
    """

    @staticmethod
    def run(
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        on_pid_assigned: Optional[Callable[[int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        env: Optional[Dict[str, str]] = None,
        job_id: Optional[str] = None
    ) -> ProcessOutput:
        """
        Runs a command synchronously with real timeout and cancellation support.
        """
        actual_timeout = timeout if timeout is not None else DEFAULT_GENERAL_TIMEOUT
        logger.info(f"[Job {job_id or 'sys'}] Spawning command (timeout={actual_timeout}s): {' '.join(cmd[:6])}...")

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=run_env,
            creationflags=creationflags
        )

        pid = proc.pid
        if on_pid_assigned:
            try:
                on_pid_assigned(pid)
            except Exception as e:
                logger.warning(f"Error invoking on_pid_assigned for PID {pid}: {e}")

        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []

        def _reader(stream, storage):
            try:
                content = stream.read()
                if content:
                    storage.append(content)
            except Exception:
                pass

        out_thread = threading.Thread(target=_reader, args=(proc.stdout, stdout_chunks), daemon=True)
        err_thread = threading.Thread(target=_reader, args=(proc.stderr, stderr_chunks), daemon=True)
        out_thread.start()
        err_thread.start()

        start_time = time.time()
        timed_out = False
        cancelled = False

        while True:
            # Check cancellation first
            if cancel_event and cancel_event.is_set():
                logger.warning(f"[Job {job_id or 'sys'}] Cancellation requested for PID {pid}. Terminating process tree...")
                cancelled = True
                kill_process_tree(pid)
                break

            ret = proc.poll()
            if ret is not None:
                break

            # Check timeout
            elapsed = time.time() - start_time
            if actual_timeout > 0 and elapsed >= actual_timeout:
                logger.warning(f"[Job {job_id or 'sys'}] Process PID {pid} timed out after {elapsed:.1f}s (limit={actual_timeout}s). Terminating process tree...")
                timed_out = True
                kill_process_tree(pid)
                break

            time.sleep(0.1)

        # Wait briefly for reader threads to complete
        out_thread.join(timeout=1.0)
        err_thread.join(timeout=1.0)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)

        if cancel_event and cancel_event.is_set():
            cancelled = True

        if cancelled:
            raise JobCancelledError(
                f"Job process {cmd[0]} was cancelled by user.",
                job_id=job_id
            )

        if timed_out:
            raise ProcessTimeoutError(
                f"Command '{cmd[0]}' exceeded timeout of {actual_timeout}s. Stderr: {stderr[-300:]}",
                job_id=job_id
            )

        return ProcessOutput(
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            cancelled=False
        )
