from django.shortcuts import render, redirect
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from .models import CommandLog
from .tasks import run_django_command_task, run_shell_command_task

# Only allow superusers
def superuser_check(user):
    return user.is_superuser

@user_passes_test(superuser_check)
def dashboard(request):
    if request.method == "POST":
        command = request.POST.get("command")
        command_type = request.POST.get("type", "django")
        
        if command:
            log = CommandLog.objects.create(
                command_name=command,
                executed_by=request.user
            )
            
            if command_type == "django":
                # Split command and args loosely
                parts = command.split()
                cmd = parts[0]
                args = parts[1:]
                run_django_command_task.delay(log.id, cmd, *args)
                messages.success(request, f"Django command '{command}' started in background.")
            elif command_type == "shell":
                run_shell_command_task.delay(log.id, command)
                messages.success(request, f"Shell command '{command}' started in background.")
            elif command_type == "celery":
                if command.startswith("call "):
                    task_name = command.replace("call ", "").strip()
                    try:
                        from celery import current_app
                        current_app.send_task(task_name)
                        log.status = "SUCCESS"
                        log.output = f"Successfully dispatched background celery task: {task_name}\n\nNote: The task has been queued to the Celery workers. You can check the worker logs for the actual execution output."
                        log.save()
                        messages.success(request, f"Celery task '{task_name}' dispatched successfully.")
                    except Exception as e:
                        log.status = "FAILED"
                        log.output = str(e)
                        log.save()
                        messages.error(request, f"Failed to dispatch celery task: {e}")
                else:
                    # Fallback for celery shell commands like 'celery status'
                    run_shell_command_task.delay(log.id, command)
                    messages.success(request, f"Celery command '{command}' started in background.")
                
            return redirect("aa_admin_toolkit:dashboard")

    recent_logs = CommandLog.objects.all()[:10]
    
    return render(request, "aa_admin_toolkit/dashboard.html", {
        "recent_logs": recent_logs
    })

@user_passes_test(superuser_check)
def log_detail(request, log_id):
    log = CommandLog.objects.get(id=log_id)
    return render(request, "aa_admin_toolkit/log_detail.html", {
        "log": log
    })

from django.http import JsonResponse
from django.db import connection
from django.contrib.auth.models import User
from eveonline.models import EveCharacter
import time
import os

@user_passes_test(superuser_check)
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
