from django import template

register = template.Library()

ACTION_LABELS = {
    "django_check": "System check",
    "django_showmigrations": "Show migrations",
    "django_clearsessions": "Clear expired sessions",
    "auth_check": "Container system check",
    "auth_showmigrations": "Container show migrations",
    "auth_migrate": "Run migrations",
    "auth_collectstatic": "Collect static files",
    "manage_command": "Management command",
    "db_backup": "Database backup",
    "docker_status": "Compose status",
    "docker_restart_service": "Restart service",
    "docker_up_service": "Start service",
    "docker_pull_service": "Pull and recreate service",
    "docker_logs_service": "Service logs",
    "docker_full_restart": "Full stack restart",
    "discord_sync_all": "Discord sync: everything",
    "discord_sync_groups": "Discord sync: groups",
    "discord_sync_nicknames": "Discord sync: nicknames",
    "pip_list": "List packages",
    "pip_show": "Package details",
    "pip_install": "Install package",
    "pip_upgrade": "Upgrade package",
    "pip_uninstall": "Uninstall package",
    "celery_status": "Celery worker status",
    "maintenance_enable": "Enable maintenance mode",
    "maintenance_disable": "Disable maintenance mode",
    "file_save": "Save file",
    "file_revert": "Revert file",
}


@register.filter
def action_label(action_key):
    return ACTION_LABELS.get(action_key, action_key)


@register.filter
def duration(seconds):
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"
