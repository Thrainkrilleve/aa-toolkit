import os
import re
import shutil
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from datetime import datetime

from celery import current_app
from django.conf import settings
from django.core.management import call_command


PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
VERSION_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+\-!=<>~,:;\[\]\(\)\s]{0,127}$")
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SAFE_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MANAGE_COMMAND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class ActionResult:
    status: str
    output: str
    normalized_command: str = ""
    exit_code: int | None = None
    target: str = ""


SUPPORTED_ACTION_KEYS = {
    "django_check",
    "django_showmigrations",
    "django_clearsessions",
    "auth_check",
    "auth_showmigrations",
    "auth_migrate",
    "auth_collectstatic",
    "db_backup",
    "docker_status",
    "docker_restart_service",
    "docker_up_service",
    "docker_pull_service",
    "docker_logs_service",
    "docker_full_restart",
    "discord_sync_all",
    "discord_sync_groups",
    "discord_sync_nicknames",
    "pip_list",
    "pip_show",
    "pip_install",
    "pip_upgrade",
    "pip_uninstall",
    "celery_status",
    "maintenance_enable",
    "maintenance_disable",
    "file_save",
    "file_revert",
}


def is_supported_action(action_key: str) -> bool:
    return action_key in SUPPORTED_ACTION_KEYS


def setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def docker_enabled() -> bool:
    return bool(setting("AA_ADMIN_TOOLKIT_ENABLE_DOCKER", False))


def docker_full_restart_enabled() -> bool:
    return bool(setting("AA_ADMIN_TOOLKIT_ENABLE_FULL_STACK_RESTART", False))


def docker_service_snapshot() -> list[dict[str, str]]:
    if not docker_enabled():
        return []

    allowed_services = allowed_docker_services()
    inventory = _compose_service_inventory(allowed_services)

    services: list[dict[str, str]] = []
    for service_name, item in inventory.items():
        state = str(item.get("state") or "unknown").strip()
        health = str(item.get("health") or "unknown").strip()
        services.append({
            "service": service_name,
            "state": state,
            "health": health,
            "status": "Up" if state.lower() in {"running", "up"} else "Down",
        })

    if not services and allowed_services:
        for service_name in allowed_services:
            services.append({"service": service_name, "state": "unknown", "health": "unknown", "status": "Unknown"})

    stats_by_service = _docker_service_stats_by_name(inventory)
    for service in services:
        stats = stats_by_service.get(service["service"], {})
        service["cpu"] = stats.get("cpu", "-")
        service["memory"] = stats.get("memory", "-")

    return services


def _compose_service_inventory(allowed_services: list[str]) -> dict[str, dict[str, str]]:
    try:
        result = _run_subprocess(compose_base_command() + ["ps", "--format", "json"], cwd=compose_project_directory(), timeout=30)
    except Exception:
        return {}

    if result.returncode != 0 or not result.stdout.strip():
        return {}

    try:
        raw_items = json.loads(result.stdout)
    except Exception:
        return {}

    if isinstance(raw_items, dict):
        raw_items = [raw_items]

    services: dict[str, dict[str, str]] = {}
    for item in raw_items:
        service_name = str(item.get("Service") or item.get("service") or "").strip()
        if not service_name:
            service_name = _derive_service_name_from_container(str(item.get("Name") or item.get("name") or ""))
        if not service_name:
            continue
        if allowed_services and service_name not in allowed_services:
            continue

        state = str(item.get("State") or item.get("state") or "unknown").strip()
        health = str(item.get("Health") or item.get("health") or "unknown").strip()
        services[service_name] = {
            "state": state,
            "health": health,
            "container_id": _normalize_container_id(str(item.get("ID") or item.get("Id") or item.get("id") or "")),
            "container_name": _normalize_container_name(str(item.get("Name") or item.get("name") or "")),
        }

    return services


def _normalize_container_id(value: str) -> str:
    return value.strip().lower()


def _normalize_container_name(value: str) -> str:
    return value.strip().lstrip("/")


def _derive_service_name_from_container(container_name: str) -> str:
    normalized = _normalize_container_name(container_name)
    if not normalized:
        return ""

    # Compose names are typically project-service-index or project_service_index.
    for separator in ("-", "_"):
        parts = normalized.split(separator)
        if len(parts) >= 2:
            return parts[-2]

    return normalized


def _docker_service_stats_by_name(service_inventory: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    try:
        result = _run_subprocess(compose_base_command() + ["stats", "--no-stream", "--format", "json"], cwd=compose_project_directory(), timeout=60)
    except Exception:
        return {}

    if result.returncode != 0 or not result.stdout.strip():
        return {}

    stats_by_id: dict[str, dict[str, str]] = {}
    stats_by_name: dict[str, dict[str, str]] = {}
    stats_by_service: dict[str, dict[str, str]] = {}

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue

        stats = {
            "cpu": str(item.get("CPUPerc") or item.get("CPU") or "-").strip(),
            "memory": str(item.get("MemPerc") or item.get("MEM%") or item.get("MemUsage") or "-").strip(),
        }

        container_id = _normalize_container_id(str(item.get("ID") or item.get("Id") or item.get("id") or ""))
        container_name = _normalize_container_name(str(item.get("Name") or item.get("Container") or item.get("name") or ""))
        service_name = str(item.get("Service") or item.get("service") or "").strip()
        if not service_name:
            service_name = _derive_service_name_from_container(container_name)

        if container_id:
            stats_by_id[container_id] = stats
        if container_name:
            stats_by_name[container_name] = stats
        if service_name:
            stats_by_service[service_name] = stats

    resolved: dict[str, dict[str, str]] = {}
    for service_name, service_item in service_inventory.items():
        container_id = _normalize_container_id(str(service_item.get("container_id") or ""))
        container_name = _normalize_container_name(str(service_item.get("container_name") or ""))

        stats: dict[str, str] | None = None
        if container_id:
            if container_id in stats_by_id:
                stats = stats_by_id[container_id]
            else:
                short_id = container_id[:12]
                for known_id, known_stats in stats_by_id.items():
                    if known_id.startswith(short_id) or short_id.startswith(known_id):
                        stats = known_stats
                        break

        if stats is None and container_name:
            stats = stats_by_name.get(container_name)

        if stats is None:
            stats = stats_by_service.get(service_name)

        if stats is not None:
            resolved[service_name] = stats

    return resolved


def allow_non_superusers() -> bool:
    return bool(setting("AA_ADMIN_TOOLKIT_ALLOW_NON_SUPERUSERS", False))


def allow_view_non_superusers() -> bool:
    return bool(setting("AA_ADMIN_TOOLKIT_ALLOW_VIEW_NON_SUPERUSERS", allow_non_superusers()))


def allow_execute_non_superusers() -> bool:
    return bool(setting("AA_ADMIN_TOOLKIT_ALLOW_EXECUTE_NON_SUPERUSERS", allow_non_superusers()))


def allowed_users() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_ALLOWED_USERS", [])}


def allowed_view_users() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_VIEW_ALLOWED_USERS", list(allowed_users()))}


def allowed_execute_users() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_USERS", list(allowed_users()))}


def allowed_groups() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_ALLOWED_GROUPS", [])}


def allowed_view_groups() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_VIEW_ALLOWED_GROUPS", list(allowed_groups()))}


def allowed_execute_groups() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_GROUPS", list(allowed_groups()))}


def allowed_permissions() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_ALLOWED_PERMISSIONS", [])}


def allowed_view_permissions() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_VIEW_ALLOWED_PERMISSIONS", list(allowed_permissions()))}


def allowed_execute_permissions() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_PERMISSIONS", list(allowed_permissions()))}


def allowed_eve_character_ids() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_ALLOWED_EVE_CHARACTER_IDS", [])}


def allowed_view_eve_character_ids() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_VIEW_ALLOWED_EVE_CHARACTER_IDS", list(allowed_eve_character_ids()))}


def allowed_execute_eve_character_ids() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_EVE_CHARACTER_IDS", list(allowed_eve_character_ids()))}


def allowed_eve_character_names() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_ALLOWED_EVE_CHARACTER_NAMES", [])}


def allowed_view_eve_character_names() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_VIEW_ALLOWED_EVE_CHARACTER_NAMES", list(allowed_eve_character_names()))}


def allowed_execute_eve_character_names() -> set[str]:
    return {str(item) for item in setting("AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_EVE_CHARACTER_NAMES", list(allowed_eve_character_names()))}


def allowed_docker_services() -> list[str]:
    return list(setting("AA_ADMIN_TOOLKIT_ALLOWED_DOCKER_SERVICES", []))


def allowed_editor_files() -> list[str]:
    files = setting("AA_ADMIN_TOOLKIT_ALLOWED_EDITABLE_FILES", ["requirements.txt", "local.py"])
    return [str(item) for item in files]


def allowed_manage_commands() -> list[dict[str, Any]]:
    commands = setting("AA_ADMIN_TOOLKIT_ALLOWED_MANAGE_COMMANDS", [])
    normalized: list[dict[str, Any]] = []

    for item in commands:
        if isinstance(item, str):
            command = item.strip()
            if command:
                normalized.append({"label": command, "command": command, "args": []})
            continue

        if isinstance(item, dict):
            command = str(item.get("command", "")).strip()
            if not command:
                continue
            normalized.append({
                "label": str(item.get("label", command)).strip() or command,
                "command": command,
                "args": [str(arg) for arg in item.get("args", [])],
            })

    return normalized


def db_service_name() -> str:
    return str(setting("AA_ADMIN_TOOLKIT_DB_SERVICE", "db"))


def db_backup_command() -> list[str]:
    value = setting("AA_ADMIN_TOOLKIT_DB_BACKUP_COMMAND", ["mariadb-dump", "--all-databases"])
    if isinstance(value, str):
        return value.split()
    return list(value)


def db_backup_output_dir() -> Path:
    value = setting("AA_ADMIN_TOOLKIT_DB_BACKUP_OUTPUT_DIR", Path(settings.BASE_DIR) / "db_backups")
    return Path(value)


def db_backup_filename_prefix() -> str:
    return str(setting("AA_ADMIN_TOOLKIT_DB_BACKUP_FILENAME_PREFIX", "database-backup"))


def audit_webhook_url() -> str:
    return str(setting("AA_ADMIN_TOOLKIT_AUDIT_WEBHOOK_URL", "")).strip()


def maintenance_sentinel_path() -> Path:
    value = setting("AA_ADMIN_TOOLKIT_MAINTENANCE_SENTINEL_PATH", Path(settings.BASE_DIR) / ".maintenance-mode")
    return Path(value)


def maintenance_mode_enabled() -> bool:
    return maintenance_sentinel_path().exists()


def enable_maintenance_mode() -> dict[str, str]:
    path = maintenance_sentinel_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Maintenance mode enabled by Admin Toolkit at %s\n" % datetime.now().isoformat(),
        encoding="utf-8",
    )
    return {"path": str(path)}


def disable_maintenance_mode() -> dict[str, str]:
    path = maintenance_sentinel_path()
    if path.exists():
        path.unlink()
    return {"path": str(path)}


def compose_base_command() -> list[str]:
    value = setting("AA_ADMIN_TOOLKIT_COMPOSE_COMMAND", ["docker", "compose"])
    if isinstance(value, str):
        return value.split()
    return list(value)


def compose_project_directory() -> str:
    return str(setting("AA_ADMIN_TOOLKIT_COMPOSE_PROJECT_DIRECTORY", settings.BASE_DIR))


def app_service_name() -> str:
    return str(setting("AA_ADMIN_TOOLKIT_APP_SERVICE", "web"))


def app_python_command() -> list[str]:
    value = setting("AA_ADMIN_TOOLKIT_APP_PYTHON_COMMAND", ["python"])
    if isinstance(value, str):
        return value.split()
    return list(value)


def app_management_command() -> list[str]:
    value = setting("AA_ADMIN_TOOLKIT_APP_MANAGEMENT_COMMAND", ["python", "manage.py"])
    if isinstance(value, str):
        return value.split()
    return list(value)


def celery_app_name() -> str:
    return str(setting("AA_ADMIN_TOOLKIT_CELERY_APP", "myauth"))


def python_executable() -> str:
    return sys.executable


def user_can_view(user) -> bool:
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if not allow_view_non_superusers():
        return False

    if user.username in allowed_view_users():
        return True

    view_permissions = allowed_view_permissions()
    if view_permissions and any(user.has_perm(permission) for permission in view_permissions):
        return True

    view_groups = allowed_view_groups()
    if view_groups and user.groups.filter(name__in=view_groups).exists():
        return True

    if _user_matches_eve_character_allowlist(user, allowed_view_eve_character_ids(), allowed_view_eve_character_names()):
        return True

    return False


def user_can_execute(user) -> bool:
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if not allow_execute_non_superusers():
        return False

    if user.username in allowed_execute_users():
        return True

    execute_permissions = allowed_execute_permissions()
    if execute_permissions and any(user.has_perm(permission) for permission in execute_permissions):
        return True

    execute_groups = allowed_execute_groups()
    if execute_groups and user.groups.filter(name__in=execute_groups).exists():
        return True

    if _user_matches_eve_character_allowlist(user, allowed_execute_eve_character_ids(), allowed_execute_eve_character_names()):
        return True

    return False


def user_has_access(user) -> bool:
    # Backward-compatible alias used by existing imports.
    return user_can_view(user)


def _user_matches_eve_character_allowlist(user, allowed_ids: set[str], allowed_names: set[str]) -> bool:
    if not allowed_ids and not allowed_names:
        return False

    candidate_ids: set[str] = set()
    candidate_names: set[str] = set()

    try:
        ownerships = user.character_ownerships.select_related("character").all()
        for ownership in ownerships:
            character = getattr(ownership, "character", None)
            if character is None:
                continue
            candidate_ids.add(str(character.character_id))
            candidate_names.add(str(character.character_name))
    except Exception:
        pass

    try:
        main_character = user.profile.main_character
        if main_character is not None:
            candidate_ids.add(str(main_character.character_id))
            candidate_names.add(str(main_character.character_name))
    except Exception:
        pass

    return bool(candidate_ids.intersection(allowed_ids) or candidate_names.intersection(allowed_names))


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    return env


def _run_subprocess(argv: list[str], *, cwd: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or settings.BASE_DIR,
        env=_subprocess_env(),
    )


def _package_spec(package_name: str, version: str | None = None) -> str:
    if not PACKAGE_NAME_RE.fullmatch(package_name):
        raise ValueError("Package name contains invalid characters.")

    if version:
        if not VERSION_SPEC_RE.fullmatch(version):
            raise ValueError("Version specifier contains invalid characters.")
        return f"{package_name}=={version}"

    return package_name


def _service_name(service_name: str) -> str:
    if not SERVICE_NAME_RE.fullmatch(service_name):
        raise ValueError("Service name contains invalid characters.")

    allowed_services = allowed_docker_services()
    if allowed_services and service_name not in allowed_services:
        raise ValueError("Service is not allowlisted.")

    return service_name


def _editor_file_name(file_name: str) -> str:
    if not SAFE_FILE_NAME_RE.fullmatch(file_name):
        raise ValueError("File name contains invalid characters.")

    allowed_files = allowed_editor_files()
    if file_name not in allowed_files:
        raise ValueError("File is not allowlisted.")

    return file_name


def _manage_command_name(command_name: str) -> str:
    if not MANAGE_COMMAND_NAME_RE.fullmatch(command_name):
        raise ValueError("Management command contains invalid characters.")

    for item in allowed_manage_commands():
        if item["command"] == command_name:
            return command_name

    raise ValueError("Management command is not allowlisted.")


def editor_file_path(file_name: str) -> Path:
    return Path(settings.BASE_DIR) / _editor_file_name(file_name)


def editor_backup_path(file_name: str) -> Path:
    path = editor_file_path(file_name)
    return path.with_suffix(path.suffix + ".bak")


def editor_backup_exists(file_name: str) -> bool:
    return editor_backup_path(file_name).exists()


def read_editor_file(file_name: str) -> str:
    path = editor_file_path(file_name)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_editor_file(file_name: str, content: str) -> dict[str, str]:
    path = editor_file_path(file_name)
    backup_path = editor_backup_path(file_name)
    if path.exists():
        shutil.copy2(path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "backup_path": str(backup_path)}


def revert_editor_file(file_name: str) -> dict[str, str]:
    path = editor_file_path(file_name)
    backup_path = editor_backup_path(file_name)
    if not backup_path.exists():
        raise ValueError("No backup exists for this file.")
    shutil.copy2(backup_path, path)
    return {"path": str(path), "backup_path": str(backup_path)}


def _join_command(argv: list[str]) -> str:
    return " ".join(argv)


def _app_exec_command(argv: list[str]) -> list[str]:
    if not docker_enabled():
        raise ValueError("Docker actions are disabled.")

    service_name = app_service_name().strip()
    if not service_name:
        raise ValueError("App service is not configured.")

    allowed_services = allowed_docker_services()
    if allowed_services and service_name not in allowed_services:
        raise ValueError("App service is not allowlisted.")

    return compose_base_command() + ["exec", "-T", service_name] + argv


def _compose_exec_command(service_name: str, argv: list[str]) -> list[str]:
    if not docker_enabled():
        raise ValueError("Docker actions are disabled.")

    service_name = _service_name(service_name.strip())
    return compose_base_command() + ["exec", "-T", service_name] + argv


def _run_subprocess_binary(argv: list[str], *, cwd: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=False,
        timeout=timeout,
        cwd=cwd or settings.BASE_DIR,
        env=_subprocess_env(),
    )


def _database_backup_path() -> Path:
    backup_dir = db_backup_output_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return backup_dir / f"{db_backup_filename_prefix()}-{timestamp}.sql"


def _run_compose_action(argv: list[str], *, timeout: int = 300) -> ActionResult:
    completed = _run_subprocess_binary(argv, cwd=compose_project_directory(), timeout=timeout)
    stderr_text = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
    stdout_text = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
    output = f"STDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}".strip()
    return ActionResult(
        status="SUCCESS" if completed.returncode == 0 else "FAILED",
        output=output,
        normalized_command=_join_command(argv),
        exit_code=completed.returncode,
    )


def send_audit_webhook(*, action_type: str, target: str, status: str, exit_code: int | None, executor: str, started_at: str | None = None, finished_at: str | None = None) -> None:
    webhook = audit_webhook_url()
    if not webhook:
        return

    payload = {
        "content": None,
        "embeds": [
            {
                "title": "Admin Toolkit Action",
                "color": 15105570 if status != "SUCCESS" else 5763719,
                "fields": [
                    {"name": "Action", "value": action_type or "unknown", "inline": True},
                    {"name": "Target", "value": target or "-", "inline": True},
                    {"name": "Status", "value": status or "unknown", "inline": True},
                    {"name": "Exit Code", "value": str(exit_code) if exit_code is not None else "-", "inline": True},
                    {"name": "Executor", "value": executor or "unknown", "inline": True},
                    {"name": "Started", "value": started_at or "-", "inline": False},
                    {"name": "Finished", "value": finished_at or "-", "inline": False},
                ],
            }
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(request, timeout=5)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return


def _app_manage_command(command_name: str) -> list[str]:
    return _app_exec_command(app_management_command() + [command_name])


def execute_action(action_key: str, params: dict[str, Any]) -> ActionResult:
    if action_key == "django_check":
        return _run_django_command("check")
    if action_key == "django_showmigrations":
        return _run_django_command("showmigrations")
    if action_key == "django_clearsessions":
        return _run_django_command("clearsessions")

    if action_key == "auth_check":
        return _run_subprocess_action(_app_manage_command("check"), label="docker compose exec auth check", cwd=compose_project_directory())
    if action_key == "auth_showmigrations":
        return _run_subprocess_action(_app_manage_command("showmigrations"), label="docker compose exec auth showmigrations", cwd=compose_project_directory())
    if action_key == "auth_migrate":
        return _run_subprocess_action(_app_manage_command("migrate"), label="docker compose exec auth migrate", cwd=compose_project_directory())
    if action_key == "auth_collectstatic":
        return _run_subprocess_action(_app_manage_command("collectstatic") + ["--noinput"], label="docker compose exec auth collectstatic --noinput", cwd=compose_project_directory())

    if action_key == "manage_command":
        command_name = str(params.get("command", "")).strip()
        if not command_name:
            raise ValueError("Management command is required.")
        command_name = _manage_command_name(command_name)
        args = [str(arg).strip() for arg in params.get("args", []) if str(arg).strip()]
        command = _app_manage_command(command_name) + args
        return _run_subprocess_action(command, label=f"docker compose exec manage.py {command_name}", cwd=compose_project_directory(), target=command_name)

    if action_key == "db_backup":
        database_service = db_service_name().strip()
        if not database_service:
            raise ValueError("Database service is not configured.")

        backup_path = _database_backup_path()
        command = _compose_exec_command(database_service, db_backup_command())
        completed = _run_subprocess_binary(command, cwd=compose_project_directory(), timeout=900)
        stderr_text = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
        if completed.returncode == 0:
            backup_path.write_bytes(completed.stdout or b"")
            output = f"Database backup written to {backup_path}"
            if stderr_text.strip():
                output = f"{output}\n\nSTDERR:\n{stderr_text.strip()}"
            return ActionResult(
                status="SUCCESS",
                output=output,
                normalized_command=_join_command(command),
                exit_code=0,
                target=database_service,
            )

        stdout_text = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
        return ActionResult(
            status="FAILED",
            output=f"STDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}".strip(),
            normalized_command=_join_command(command),
            exit_code=completed.returncode,
            target=database_service,
        )

    if action_key == "docker_full_restart":
        if not docker_enabled():
            raise ValueError("Docker actions are disabled.")
        if not docker_full_restart_enabled():
            raise ValueError("Full stack restart is disabled.")

        down_result = _run_compose_action(compose_base_command() + ["down"], timeout=900)
        if down_result.status != "SUCCESS":
            return ActionResult(
                status=down_result.status,
                output=down_result.output,
                normalized_command=down_result.normalized_command,
                exit_code=down_result.exit_code,
                target="compose-stack",
            )

        up_result = _run_compose_action(compose_base_command() + ["up", "-d"], timeout=900)
        combined_output = f"Compose down:\n{down_result.output}\n\nCompose up:\n{up_result.output}".strip()
        return ActionResult(
            status="SUCCESS" if up_result.status == "SUCCESS" else "FAILED",
            output=combined_output,
            normalized_command=f"{_join_command(compose_base_command() + ['down'])} && {_join_command(compose_base_command() + ['up', '-d'])}",
            exit_code=up_result.exit_code,
            target="compose-stack",
        )

    if action_key == "discord_sync_all":
        return _dispatch_celery_task("discord.update_all", "Dispatched Discord sync task: discord.update_all")
    if action_key == "discord_sync_groups":
        return _dispatch_celery_task("discord.update_all_groups", "Dispatched Discord sync task: discord.update_all_groups")
    if action_key == "discord_sync_nicknames":
        return _dispatch_celery_task("discord.update_all_nicknames", "Dispatched Discord sync task: discord.update_all_nicknames")

    if action_key == "pip_list":
        return _run_subprocess_action(_app_exec_command(app_python_command() + ["-m", "pip", "list"]), label="docker compose exec pip list", cwd=compose_project_directory())
    if action_key == "pip_show":
        package_name = str(params.get("package", "")).strip()
        if not package_name:
            raise ValueError("Package name is required.")
        _package_spec(package_name)
        return _run_subprocess_action(_app_exec_command(app_python_command() + ["-m", "pip", "show", package_name]), label=f"docker compose exec pip show {package_name}", cwd=compose_project_directory(), target=package_name)
    if action_key == "pip_install":
        package_name = str(params.get("package", "")).strip()
        version = str(params.get("version", "")).strip() or None
        if not package_name:
            raise ValueError("Package name is required.")
        package_spec = _package_spec(package_name, version)
        result = _run_subprocess_action(_app_exec_command(app_python_command() + ["-m", "pip", "install", package_spec]), label=f"docker compose exec pip install {package_spec}", cwd=compose_project_directory(), target=package_name)
        return _apply_package_followup(result, params)
    if action_key == "pip_upgrade":
        package_name = str(params.get("package", "")).strip()
        version = str(params.get("version", "")).strip() or None
        if not package_name:
            raise ValueError("Package name is required.")
        package_spec = _package_spec(package_name, version)
        result = _run_subprocess_action(_app_exec_command(app_python_command() + ["-m", "pip", "install", "--upgrade", package_spec]), label=f"docker compose exec pip install --upgrade {package_spec}", cwd=compose_project_directory(), target=package_name)
        return _apply_package_followup(result, params)
    if action_key == "pip_uninstall":
        package_name = str(params.get("package", "")).strip()
        if not package_name:
            raise ValueError("Package name is required.")
        _package_spec(package_name)
        result = _run_subprocess_action(_app_exec_command(app_python_command() + ["-m", "pip", "uninstall", "-y", package_name]), label=f"docker compose exec pip uninstall -y {package_name}", cwd=compose_project_directory(), target=package_name)
        return _apply_package_followup(result, params)

    if action_key == "celery_status":
        return _run_subprocess_action([python_executable(), "-m", "celery", "-A", celery_app_name(), "status"], label=f"celery -A {celery_app_name()} status")

    if action_key == "docker_status":
        if not docker_enabled():
            raise ValueError("Docker actions are disabled.")
        return _run_subprocess_action(compose_base_command() + ["ps"], label="docker compose ps", cwd=compose_project_directory())
    if action_key == "docker_restart_service":
        service_name = _service_name(str(params.get("service", "")).strip())
        return _run_subprocess_action(compose_base_command() + ["restart", service_name], label=f"docker compose restart {service_name}", cwd=compose_project_directory(), target=service_name)
    if action_key == "docker_up_service":
        service_name = _service_name(str(params.get("service", "")).strip())
        return _run_subprocess_action(
            compose_base_command() + ["up", "-d", service_name],
            label=f"docker compose up -d {service_name}",
            cwd=compose_project_directory(),
            target=service_name,
            timeout=900,
        )
    if action_key == "docker_pull_service":
        service_name = _service_name(str(params.get("service", "")).strip())
        pull_result = _run_subprocess_action(compose_base_command() + ["pull", service_name], label=f"docker compose pull {service_name}", cwd=compose_project_directory(), target=service_name)
        if pull_result.status != "SUCCESS":
            return pull_result

        recreate_result = _run_subprocess_action(
            compose_base_command() + ["up", "-d", "--force-recreate", service_name],
            label=f"docker compose up -d --force-recreate {service_name}",
            cwd=compose_project_directory(),
            target=service_name,
            timeout=900,
        )

        return ActionResult(
            status="SUCCESS" if recreate_result.status == "SUCCESS" else "FAILED",
            output=f"Pull result:\n{pull_result.output}\n\nRecreate result:\n{recreate_result.output}".strip(),
            normalized_command=f"{pull_result.normalized_command} && {recreate_result.normalized_command}",
            exit_code=recreate_result.exit_code,
            target=service_name,
        )
    if action_key == "docker_logs_service":
        service_name = _service_name(str(params.get("service", "")).strip())
        tail = str(params.get("tail", "100")).strip()
        if not tail.isdigit():
            raise ValueError("Tail must be a positive integer.")
        tail_count = max(1, min(int(tail), 1000))
        return _run_subprocess_action(compose_base_command() + ["logs", "--tail", str(tail_count), service_name], label=f"docker compose logs --tail {tail_count} {service_name}", cwd=compose_project_directory(), target=service_name)

    raise ValueError(f"Unknown action: {action_key}")


def _run_django_command(command_name: str) -> ActionResult:
    from io import StringIO

    stdout = StringIO()
    stderr = StringIO()

    try:
        call_command(command_name, stdout=stdout, stderr=stderr)
        return ActionResult(
            status="SUCCESS",
            output=f"{stdout.getvalue()}\n{stderr.getvalue()}".strip(),
            normalized_command=f"python manage.py {command_name}",
            exit_code=0,
        )
    except Exception as exc:
        return ActionResult(
            status="FAILED",
            output=f"{stdout.getvalue()}\n{stderr.getvalue()}\n{exc}".strip(),
            normalized_command=f"python manage.py {command_name}",
            exit_code=1,
        )


def _dispatch_celery_task(task_name: str, message: str) -> ActionResult:
    current_app.send_task(task_name)
    return ActionResult(status="SUCCESS", output=message, normalized_command=f"celery task {task_name}", exit_code=0)


def _run_subprocess_action(argv: list[str], *, label: str, cwd: str | None = None, target: str = "", timeout: int = 300) -> ActionResult:
    completed = _run_subprocess(argv, cwd=cwd, timeout=timeout)
    output = f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}".strip()
    return ActionResult(
        status="SUCCESS" if completed.returncode == 0 else "FAILED",
        output=output,
        normalized_command=_join_command(argv),
        exit_code=completed.returncode,
        target=target,
    )


def _apply_package_followup(result: ActionResult, params: dict[str, Any]) -> ActionResult:
    followup = str(params.get("followup", "")).strip()
    if result.status != "SUCCESS" or not followup:
        return result

    if followup == "restart_app":
        restart_result = _run_subprocess_action(
            compose_base_command() + ["restart", app_service_name()],
            label=f"docker compose restart {app_service_name()}",
            cwd=compose_project_directory(),
            target=app_service_name(),
            timeout=600,
        )

        combined_output = f"Package action:\n{result.output}\n\nFollow-up restart:\n{restart_result.output}".strip()
        return ActionResult(
            status="SUCCESS" if restart_result.status == "SUCCESS" else "FAILED",
            output=combined_output,
            normalized_command=f"{result.normalized_command} && docker compose restart {app_service_name()}",
            exit_code=restart_result.exit_code,
            target=app_service_name(),
        )

    if followup == "restart_selected_service":
        service_name = str(params.get("followup_service", "")).strip()
        if not service_name:
            raise ValueError("A service must be selected for this follow-up.")
        service_name = _service_name(service_name)
        restart_result = _run_subprocess_action(
            compose_base_command() + ["restart", service_name],
            label=f"docker compose restart {service_name}",
            cwd=compose_project_directory(),
            target=service_name,
            timeout=600,
        )
        combined_output = f"Package action:\n{result.output}\n\nFollow-up restart:\n{restart_result.output}".strip()
        return ActionResult(
            status="SUCCESS" if restart_result.status == "SUCCESS" else "FAILED",
            output=combined_output,
            normalized_command=f"{result.normalized_command} && docker compose restart {service_name}",
            exit_code=restart_result.exit_code,
            target=service_name,
        )

    if followup == "restart_celery_workers":
        restart_result = _run_subprocess_action(
            compose_base_command() + ["restart", "worker"],
            label="docker compose restart worker",
            cwd=compose_project_directory(),
            target="worker",
            timeout=600,
        )
        combined_output = f"Package action:\n{result.output}\n\nFollow-up restart:\n{restart_result.output}".strip()
        return ActionResult(
            status="SUCCESS" if restart_result.status == "SUCCESS" else "FAILED",
            output=combined_output,
            normalized_command=f"{result.normalized_command} && docker compose restart worker",
            exit_code=restart_result.exit_code,
            target="worker",
        )

    if followup == "full_stack_recreate":
        down_result = _run_subprocess_action(compose_base_command() + ["down"], label="docker compose down", cwd=compose_project_directory(), timeout=900)
        if down_result.status != "SUCCESS":
            return down_result
        up_result = _run_subprocess_action(compose_base_command() + ["up", "-d"], label="docker compose up -d", cwd=compose_project_directory(), timeout=900)
        combined_output = f"Package action:\n{result.output}\n\nFollow-up down/up:\n{down_result.output}\n\n{up_result.output}".strip()
        return ActionResult(
            status="SUCCESS" if up_result.status == "SUCCESS" else "FAILED",
            output=combined_output,
            normalized_command=f"{result.normalized_command} && docker compose down && docker compose up -d",
            exit_code=up_result.exit_code,
            target="compose-stack",
        )

    return result
