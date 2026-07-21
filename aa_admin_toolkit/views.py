from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.utils import timezone
from .models import CommandLog
from .tasks import run_action_task
from .actions import (
    user_can_view,
    user_can_execute,
    docker_enabled,
    allowed_docker_services,
    allowed_editor_files,
    read_editor_file,
    save_editor_file,
    revert_editor_file,
    editor_backup_exists,
    docker_service_snapshot,
    maintenance_mode_enabled,
    enable_maintenance_mode,
    disable_maintenance_mode,
    is_supported_action,
    allowed_manage_commands,
    send_audit_webhook,
)


FULL_RESTART_CONFIRM_PHRASE = "RESTART STACK"
FULL_RECREATE_CONFIRM_PHRASE = "RECREATE STACK"

DOCKER_REQUIRED_ACTIONS = {
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
    "manage_command",
    "pip_list",
    "pip_show",
    "pip_install",
    "pip_upgrade",
    "pip_uninstall",
}


def toolkit_access_check(user):
    return user_can_view(user)

@user_passes_test(toolkit_access_check)
def dashboard(request):
    recent_logs = CommandLog.objects.all()[:10]
    
    return render(request, "aa_admin_toolkit/dashboard.html", {
        "recent_logs": recent_logs,
        "operations_url": "aa_admin_toolkit:operations",
    })

@user_passes_test(toolkit_access_check)
def operations(request):
    can_execute = user_can_execute(request.user)

    if request.method == "POST":
        if not can_execute:
            messages.error(request, "You are allowed to view this page, but not execute actions.")
            return redirect("aa_admin_toolkit:operations")

        action_key = request.POST.get("action", "").strip()
        if not action_key:
            messages.error(request, "No action was selected.")
            return redirect("aa_admin_toolkit:operations")

        if not is_supported_action(action_key):
            messages.error(request, "Unknown action requested.")
            return redirect("aa_admin_toolkit:operations")

        if action_key in DOCKER_REQUIRED_ACTIONS and not docker_enabled():
            messages.error(request, "Docker is disabled, so this action cannot run.")
            return redirect("aa_admin_toolkit:operations")

        if action_key == "docker_full_restart":
            if request.POST.get("confirm_full_restart") != "1":
                messages.error(request, "Full stack restart requires explicit confirmation.")
                return redirect("aa_admin_toolkit:operations")

            phrase = request.POST.get("confirm_full_restart_phrase", "").strip().upper()
            if phrase != FULL_RESTART_CONFIRM_PHRASE:
                messages.error(request, f"Type '{FULL_RESTART_CONFIRM_PHRASE}' to confirm full stack restart.")
                return redirect("aa_admin_toolkit:operations")

        if action_key in {"maintenance_enable", "maintenance_disable"}:
            log = CommandLog.objects.create(
                command_name=action_key,
                action_type=action_key,
                executed_by=request.user,
                status="RUNNING",
                started_at=timezone.now(),
            )

            try:
                if action_key == "maintenance_enable":
                    result = enable_maintenance_mode()
                    log.output = f"Maintenance mode enabled via {result['path']}"
                else:
                    result = disable_maintenance_mode()
                    log.output = f"Maintenance mode disabled via {result['path']}"

                log.status = "SUCCESS"
                log.exit_code = 0
                messages.success(request, log.output)
            except Exception as exc:
                log.status = "FAILED"
                log.exit_code = 1
                log.output = str(exc)
                messages.error(request, log.output)

            log.finished_at = timezone.now()
            log.save()
            send_audit_webhook(
                action_type=action_key,
                target=log.target or "-",
                status=log.status,
                exit_code=log.exit_code,
                executor=str(log.executed_by) if log.executed_by else "unknown",
                started_at=log.started_at.isoformat() if log.started_at else None,
                finished_at=log.finished_at.isoformat() if log.finished_at else None,
            )
            return redirect("aa_admin_toolkit:operations")

        if action_key in {"file_save", "file_revert"}:
            selected_file = request.POST.get("file", "").strip()
            if selected_file not in allowed_editor_files():
                messages.error(request, "Selected file is not allowlisted.")
                return redirect("aa_admin_toolkit:operations")

            log = CommandLog.objects.create(
                command_name=action_key,
                action_type=action_key,
                target=selected_file,
                executed_by=request.user,
                status="RUNNING",
                started_at=timezone.now(),
            )

            try:
                if action_key == "file_save":
                    content = request.POST.get("content", "")
                    result = save_editor_file(selected_file, content)
                    log.normalized_command = f"edit file {selected_file}"
                    log.output = f"Saved {selected_file}. Backup created at {result['backup_path']}"
                else:
                    result = revert_editor_file(selected_file)
                    log.normalized_command = f"revert file {selected_file}"
                    log.output = f"Restored {selected_file} from {result['backup_path']}"

                log.status = "SUCCESS"
                log.exit_code = 0
                messages.success(request, log.output)
            except Exception as exc:
                log.status = "FAILED"
                log.exit_code = 1
                log.output = str(exc)
                messages.error(request, log.output)

            log.finished_at = timezone.now()
            log.save()
            send_audit_webhook(
                action_type=action_key,
                target=log.target or "-",
                status=log.status,
                exit_code=log.exit_code,
                executor=str(log.executed_by) if log.executed_by else "unknown",
                started_at=log.started_at.isoformat() if log.started_at else None,
                finished_at=log.finished_at.isoformat() if log.finished_at else None,
            )
            return redirect(f"{request.path}?file={selected_file}")

        payload = {
            "service": request.POST.get("service", "").strip(),
            "package": request.POST.get("package", "").strip(),
            "version": request.POST.get("version", "").strip(),
            "tail": request.POST.get("tail", "100").strip(),
            "followup": request.POST.get("followup", "").strip(),
            "followup_service": request.POST.get("followup_service", "").strip(),
            "command": request.POST.get("command", "").strip(),
            "args": request.POST.getlist("args"),
        }

        if action_key in {"pip_install", "pip_upgrade", "pip_uninstall"} and request.POST.get("confirm_package_change") != "1":
            messages.error(request, "Package changes require explicit confirmation.")
            return redirect("aa_admin_toolkit:operations")

        if action_key in {"pip_install", "pip_upgrade", "pip_uninstall"} and payload.get("followup") == "full_stack_recreate":
            if request.POST.get("confirm_followup_recreate") != "1":
                messages.error(request, "Full stack down/up follow-up requires additional confirmation.")
                return redirect("aa_admin_toolkit:operations")

            recreate_phrase = request.POST.get("confirm_followup_recreate_phrase", "").strip().upper()
            if recreate_phrase != FULL_RECREATE_CONFIRM_PHRASE:
                messages.error(request, f"Type '{FULL_RECREATE_CONFIRM_PHRASE}' to confirm full stack down/up follow-up.")
                return redirect("aa_admin_toolkit:operations")

        log = CommandLog.objects.create(
            command_name=action_key,
            action_type=action_key,
            executed_by=request.user,
        )
        run_action_task.delay(log.id, action_key, payload)
        messages.success(request, f"Action '{action_key}' started in background.")
        return redirect("aa_admin_toolkit:operations")

    selected_file = request.GET.get("file", "").strip()
    if selected_file not in allowed_editor_files():
        selected_file = allowed_editor_files()[0] if allowed_editor_files() else ""

    file_content = read_editor_file(selected_file) if selected_file else ""

    recent_logs = CommandLog.objects.all()[:10]

    return render(request, "aa_admin_toolkit/operations.html", {
        "recent_logs": recent_logs,
        "docker_enabled": docker_enabled(),
        "docker_services": allowed_docker_services(),
        "editable_files": allowed_editor_files(),
        "selected_file": selected_file,
        "file_content": file_content,
        "backup_exists": editor_backup_exists(selected_file) if selected_file else False,
        "maintenance_enabled": maintenance_mode_enabled(),
        "manage_commands": allowed_manage_commands(),
        "can_execute": can_execute,
    })

@user_passes_test(toolkit_access_check)
def log_detail(request, log_id):
    log = get_object_or_404(CommandLog, id=log_id)
    return render(request, "aa_admin_toolkit/log_detail.html", {
        "log": log
    })

from django.http import JsonResponse
from django.db import connection
from django.contrib.auth.models import User
from allianceauth.eveonline.models import EveCharacter
import time
import os

@user_passes_test(toolkit_access_check)
def resource_stats(request):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_used = round(mem.used / (1024**3), 2)
        mem_total = round(mem.total / (1024**3), 2)
        
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used = round(disk.used / (1024**3), 2)
        disk_total = round(disk.total / (1024**3), 2)
        
        net = psutil.net_io_counters()
        net_sent = round(net.bytes_sent / (1024**2), 2)
        net_recv = round(net.bytes_recv / (1024**2), 2)
        
        uptime_seconds = time.time() - psutil.boot_time()
        uptime_hours = round(uptime_seconds / 3600, 1)
        
        try:
            load = os.getloadavg()
            load_str = f"{load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}"
        except AttributeError:
            load_str = "N/A"
            
    except ImportError:
        cpu = mem_percent = mem_used = mem_total = disk_percent = disk_used = disk_total = net_sent = net_recv = uptime_hours = 0
        load_str = "psutil not installed"

    # Alliance Auth Stats
    user_count = User.objects.count()
    char_count = EveCharacter.objects.count()
    
    # DB Size
    db_size_mb = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT SUM(data_length + index_length) / 1024 / 1024 FROM information_schema.tables WHERE table_schema = DATABASE();")
            row = cursor.fetchone()
            if row and row[0]:
                db_size_mb = round(float(row[0]), 2)
    except Exception:
        pass

    # Celery Queue Length
    queue_len = 0
    try:
        from celery import current_app
        with current_app.connection() as conn:
            queue_len = conn.default_channel.client.llen('celery')
    except Exception:
        pass

    return JsonResponse({
        "cpu": cpu,
        "mem_percent": mem_percent,
        "mem_used": mem_used,
        "mem_total": mem_total,
        "disk_percent": disk_percent,
        "disk_used": disk_used,
        "disk_total": disk_total,
        "net_sent": net_sent,
        "net_recv": net_recv,
        "uptime": uptime_hours,
        "load": load_str,
        "users": user_count,
        "characters": char_count,
        "db_size": db_size_mb,
        "queue": queue_len
    })


@user_passes_test(toolkit_access_check)
def docker_stats(request):
    return JsonResponse({
        "services": docker_service_snapshot(),
    })
