"""Subprocess runner with process-tree cancellation and real timeouts."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Any
import psutil

logger = logging.getLogger(__name__)

@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False

def kill_process_tree(pid: int, timeout: float = 3.0) -> None:
    """Recursively kill a process and all its children using psutil."""
    try:
        parent = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return

    try:
        children = parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []

    for child in children:
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    try:
        parent.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

async def run_process(
    cmd: list[str],
    cwd: str | None = None,
    timeout: float = 300.0,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
) -> ProcessResult:
    """
    Execute command as an async subprocess with argument lists (never shell strings).
    Enforces real timeout and monitors cancellation.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        logger.error(f"Failed to spawn subprocess {cmd[0]}: {e}")
        return ProcessResult(returncode=-1, stdout="", stderr=str(e))

    if on_pid:
        try:
            on_pid(proc.pid)
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    start_time = loop.time()
    timed_out = False
    cancelled = False

    while True:
        # Check cancellation
        if cancel_check and cancel_check():
            cancelled = True
            logger.warning(f"Process {proc.pid} cancelled. Terminating process tree...")
            kill_process_tree(proc.pid)
            break

        # Check timeout
        if loop.time() - start_time > timeout:
            timed_out = True
            logger.warning(f"Process {proc.pid} timed out after {timeout}s. Terminating process tree...")
            kill_process_tree(proc.pid)
            break

        # Check if process finished
        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=0.25)
            stdout_str = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
            stderr_str = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
            return ProcessResult(
                returncode=proc.returncode if proc.returncode is not None else 0,
                stdout=stdout_str,
                stderr=stderr_str,
                timed_out=False,
                cancelled=False,
            )
        except asyncio.TimeoutError:
            continue

    # Clean up after cancel or timeout
    try:
        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        stdout_str = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr_str = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
    except Exception:
        stdout_str, stderr_str = "", ""

    return ProcessResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout_str,
        stderr=stderr_str,
        timed_out=timed_out,
        cancelled=cancelled,
    )
