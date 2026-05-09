from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from browseruse_bench.utils import REPO_ROOT, handle_cli_errors, load_config_file, setup_logger

# Setup logger
logger = setup_logger("service")

SUPPORTED_ACTIONS = {
    "install",
    "uninstall",
    "start",
    "stop",
    "restart",
    "status",
    "logs",
    "enable",
    "disable",
}


def configure_service_parser(parser: argparse.ArgumentParser, _config: Dict[str, Any] | None = None) -> None:
    """Configure arguments for the service command."""
    parser.add_argument(
        "action",
        choices=sorted(SUPPORTED_ACTIONS),
        help="Systemd service action",
    )


def _load_service_config() -> Dict[str, Any]:
    try:
        config = load_config_file(REPO_ROOT / "config.yaml")
    except (OSError, ValueError, TypeError) as exc:
        logger.error("Failed to load config.yaml: %s", exc)
        return {}
    if isinstance(config, dict):
        service_config = config.get("service")
        if isinstance(service_config, dict):
            return service_config
    return {}


def _get_config_value(service_config: Dict[str, Any], env_key: str, config_key: str) -> Optional[str]:
    env_value = os.getenv(env_key)
    if env_value:
        return env_value
    value = service_config.get(config_key)
    if value is None:
        return None
    return str(value)


def _get_int_config_value(
    service_config: Dict[str, Any], env_key: str, config_key: str
) -> Optional[int]:
    value = _get_config_value(service_config, env_key, config_key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        logger.error("Invalid value for %s: %s", config_key, value)
        return None


def _require_value(name: str, value: Optional[str]) -> str:
    if value is None or value == "":
        raise SystemExit(f"[FAILED] Missing service config: {name}")
    return value


def _require_int(name: str, value: Optional[int]) -> int:
    if value is None:
        raise SystemExit(f"[FAILED] Missing or invalid service config: {name}")
    return value


def _render_service_file(
    service_name: str,
    description: str,
    user: str,
    group: str,
    host: str,
    port: int,
    log_path: str,
    restart_sec: int,
    limit_nofile: int,
    extra_args: Sequence[str],
) -> str:
    exec_parts = [
        "/usr/bin/env",
        "uv",
        "run",
        "bubench",
        "server",
        "--host",
        host,
        "--port",
        str(port),
    ]
    exec_parts.extend(extra_args)
    exec_start = " ".join(shlex.quote(part) for part in exec_parts)

    template = f"""
    [Unit]
    Description={description}
    After=network.target

    [Service]
    Type=simple
    User={user}
    Group={group}
    WorkingDirectory={REPO_ROOT}
    Environment="PYTHONPATH={REPO_ROOT}"
    Environment="PYTHONUNBUFFERED=1"
    Environment="BROWSERUSE_BENCH_LOG_FORMAT=plain"
    ExecStart={exec_start}
    Restart=always
    RestartSec={restart_sec}
    StandardOutput=append:{log_path}
    StandardError=append:{log_path}

    # Security settings
    NoNewPrivileges=true
    PrivateTmp=true

    # Resource limits
    LimitNOFILE={limit_nofile}

    [Install]
    WantedBy=multi-user.target
    """
    return textwrap.dedent(template).strip() + "\n"


def _ensure_log_path(log_path: str, user: str, group: str) -> None:
    log_dir = Path(log_path).expanduser().resolve().parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        shutil.chown(log_dir, user=user, group=group)
    except (OSError, PermissionError) as exc:
        raise SystemExit(f"[FAILED] Unable to prepare log directory {log_dir}: {exc}") from exc


def _systemctl(cmd: List[str], stream: bool = False, check: bool = True) -> int:
    logger.info("   Command: %s", " ".join(cmd))
    if stream:
        result = subprocess.run(cmd, check=False)
        return result.returncode

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        logger.error("Command failed with code %s", result.returncode)
        if result.stdout:
            logger.error("stdout: %s", result.stdout.strip())
        if result.stderr:
            logger.error("stderr: %s", result.stderr.strip())
        raise SystemExit(result.returncode)
    return result.returncode


def _require_systemctl() -> None:
    if shutil.which("systemctl") is None:
        raise SystemExit("[FAILED] systemctl is required but not found in PATH")


def _require_root(action: str) -> None:
    if os.geteuid() != 0:
        raise SystemExit(f"[FAILED] Root privileges required for '{action}', please use sudo")


def service_command(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Entry point for the service subcommand."""
    if platform.system().lower() != "linux":
        raise SystemExit("[FAILED] bubench service is supported on Linux with systemd only")
    _require_systemctl()

    action = args.action
    service_config = _load_service_config()

    name = _get_config_value(service_config, "BU_SERVICE_NAME", "name")
    description = _get_config_value(service_config, "BU_SERVICE_DESCRIPTION", "description")
    user = _get_config_value(service_config, "BU_SERVICE_USER", "user")
    group = _get_config_value(service_config, "BU_SERVICE_GROUP", "group") or user
    host = _get_config_value(service_config, "BU_SERVICE_HOST", "host")
    port = _get_int_config_value(service_config, "BU_SERVICE_PORT", "port")
    log_path = _get_config_value(service_config, "BU_SERVICE_LOG_PATH", "log_path")
    restart_sec = _get_int_config_value(service_config, "BU_SERVICE_RESTART_SEC", "restart_sec")
    limit_nofile = _get_int_config_value(service_config, "BU_SERVICE_LIMIT_NOFILE", "limit_nofile")
    extra_args_raw = service_config.get("extra_args")
    extra_args: List[str] = []
    if isinstance(extra_args_raw, list):
        extra_args = [str(item) for item in extra_args_raw]
    elif isinstance(extra_args_raw, str):
        extra_args = extra_args_raw.split()

    service_name = _require_value("service.name", name)
    service_description = _require_value("service.description", description)
    service_user = _require_value("service.user", user)
    service_group = _require_value("service.group", group)
    service_host = _require_value("service.host", host)
    service_port = _require_int("service.port", port)
    service_log_path = _require_value("service.log_path", log_path)
    service_restart_sec = _require_int("service.restart_sec", restart_sec)
    service_limit_nofile = _require_int("service.limit_nofile", limit_nofile)

    service_path = Path("/etc/systemd/system") / f"{service_name}.service"

    logger.info("Running systemd service command...")

    if action == "install":
        _require_root(action)
        _ensure_log_path(service_log_path, service_user, service_group)
        unit_contents = _render_service_file(
            service_name=service_name,
            description=service_description,
            user=service_user,
            group=service_group,
            host=service_host,
            port=service_port,
            log_path=service_log_path,
            restart_sec=service_restart_sec,
            limit_nofile=service_limit_nofile,
            extra_args=extra_args,
        )
        try:
            service_path.write_text(unit_contents, encoding="utf-8")
        except (OSError, PermissionError) as exc:
            raise SystemExit(f"[FAILED] Unable to write service file {service_path}: {exc}") from exc

        _systemctl(["systemctl", "daemon-reload"])
        logger.info("[SUCCESS] Service installed: %s", service_path)
        return 0

    if action == "uninstall":
        _require_root(action)
        _systemctl(["systemctl", "stop", service_name], check=False)
        _systemctl(["systemctl", "disable", service_name], check=False)
        try:
            if service_path.exists():
                service_path.unlink()
        except (OSError, PermissionError) as exc:
            raise SystemExit(f"[FAILED] Unable to remove service file {service_path}: {exc}") from exc
        _systemctl(["systemctl", "daemon-reload"])
        logger.info("[SUCCESS] Service uninstalled")
        return 0

    if action in {"start", "stop", "restart", "enable", "disable"}:
        _require_root(action)
        return _systemctl(["systemctl", action, service_name])

    if action == "status":
        return _systemctl(["systemctl", "status", service_name, "--no-pager", "-l"], stream=True, check=False)

    if action == "logs":
        return _systemctl(["journalctl", "-u", service_name, "-f"], stream=True, check=False)

    raise SystemExit(f"[FAILED] Unsupported action: {action}")


@handle_cli_errors
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bubench service")
    configure_service_parser(parser)
    args, extra = parser.parse_known_args(argv)
    if extra:
        logger.info("Forwarding extra arguments: %s", " ".join(extra))
    setattr(args, "extra_args", extra)
    return service_command(args, {})


if __name__ == "__main__":
    raise SystemExit(main())
