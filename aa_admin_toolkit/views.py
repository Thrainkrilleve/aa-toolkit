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
                # For celery, it's really a shell command
                run_shell_command_task.delay(log.id, f"celery -A myauth {command}")
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
