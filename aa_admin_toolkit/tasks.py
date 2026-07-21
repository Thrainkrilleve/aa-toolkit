from celery import shared_task
from .models import CommandLog
from django.utils import timezone

from .actions import execute_action, send_audit_webhook
import traceback

@shared_task
def run_action_task(log_id, action_key, payload=None):
    try:
        log = CommandLog.objects.get(id=log_id)
        log.status = "RUNNING"
        log.started_at = timezone.now()
        log.save()
        
        try:
            result = execute_action(action_key, payload or {})
            log.status = result.status
            log.output = result.output
            log.normalized_command = result.normalized_command
            log.exit_code = result.exit_code
            log.target = result.target
        except Exception:
            log.status = "FAILED"
            log.output = traceback.format_exc()
            log.exit_code = 1
        
        log.finished_at = timezone.now()
        log.save()

        disruptive_actions = {
            "db_backup",
            "docker_restart_service",
            "docker_up_service",
            "docker_pull_service",
            "docker_full_restart",
            "file_save",
            "file_revert",
            "auth_migrate",
            "auth_collectstatic",
            "pip_install",
            "pip_upgrade",
            "pip_uninstall",
        }
        if action_key in disruptive_actions:
            send_audit_webhook(
                action_type=action_key,
                target=log.target or "-",
                status=log.status,
                exit_code=log.exit_code,
                executor=str(log.executed_by) if log.executed_by else "unknown",
                started_at=log.started_at.isoformat() if log.started_at else None,
                finished_at=log.finished_at.isoformat() if log.finished_at else None,
            )
    except Exception as e:
        pass # If we can't get the log, not much we can do.
