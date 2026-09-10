"""System execution utilities with dry-run support, privilege handling, and subprocess control."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Union


@dataclass
class CommandResult:
    """Represents the result of an executed system command."""
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def is_root() -> bool:
    """Check if the current process is running with root privileges (UID 0)."""
    return os.geteuid() == 0


def has_sudo() -> bool:
    """Check if sudo is available on the system."""
    return shutil.which("sudo") is not None


def is_binary_available(binary_name: str) -> bool:
    """Check if an executable binary is present in system PATH."""
    return shutil.which(binary_name) is not None


def run_command(
    command: Union[str, List[str]],
    sudo: bool = False,
    dry_run: bool = False,
    timeout: int = 120,
    check: bool = False,
    env: Optional[dict] = None,
) -> CommandResult:
    """
    Execute a shell command with optional privilege escalation and dry-run support.

    Args:
        command: Command string or list of argument strings.
        sudo: Prepend sudo if running as non-root user.
        dry_run: If True, do not execute; return a mock successful result.
        timeout: Execution timeout in seconds.
        check: If True, raises RuntimeError when returncode != 0.
        env: Optional environment variables dictionary.

    Returns:
        CommandResult with returncode, stdout, and stderr.
    """
    if isinstance(command, list):
        cmd_list = [str(item) for item in command]
        cmd_str = " ".join(cmd_list)
    else:
        cmd_str = command
        cmd_list = None

    # Handle sudo requirement
    if sudo and not is_root():
        sudo_prefix = ["sudo", "-n"] if (not os.isatty(0) or env and env.get("NON_INTERACTIVE_SUDO")) else ["sudo"]
        sudo_prefix_str = " ".join(sudo_prefix)
        if cmd_list is not None:
            cmd_list = sudo_prefix + cmd_list
            cmd_str = f"{sudo_prefix_str} {cmd_str}"
        else:
            cmd_str = f"{sudo_prefix_str} {cmd_str}"

    if dry_run:
        return CommandResult(
            command=cmd_str,
            returncode=0,
            stdout=f"[DRY-RUN] Executed: {cmd_str}",
            stderr="",
        )

    try:
        if cmd_list is not None:
            proc = subprocess.run(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                env=env,
            )
        else:
            proc = subprocess.run(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                env=env,
            )

        result = CommandResult(
            command=cmd_str,
            returncode=proc.returncode,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
        )

        if check and not result.success:
            err_msg = f"Command '{cmd_str}' failed with exit code {result.returncode}:\n{result.stderr}"
            raise RuntimeError(err_msg)

        return result

    except subprocess.TimeoutExpired as exc:
        err_msg = f"Command '{cmd_str}' timed out after {timeout} seconds."
        if check:
            raise TimeoutError(err_msg) from exc
        return CommandResult(
            command=cmd_str,
            returncode=124,
            stdout="",
            stderr=err_msg,
        )
    except Exception as exc:
        err_msg = f"Failed to execute command '{cmd_str}': {str(exc)}"
        if check:
            raise RuntimeError(err_msg) from exc
        return CommandResult(
            command=cmd_str,
            returncode=1,
            stdout="",
            stderr=err_msg,
        )
