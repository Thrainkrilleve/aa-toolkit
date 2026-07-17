from celery import shared_task
from django.core.management import call_command
from .models import CommandLog
import sys
import io
import traceback
import subprocess

@shared_task
def run_django_command_task(log_id, command, *args, **kwargs):
    try:
        log = CommandLog.objects.get(id=log_id)
        log.status = "RUNNING"
        log.save()
        
        # Capture stdout and stderr
        out = io.StringIO()
        err = io.StringIO()
        
        try:
            call_command(command, *args, stdout=out, stderr=err, **kwargs)
            log.status = "SUCCESS"
            log.output = out.getvalue() + "\n" + err.getvalue()
        except Exception as e:
            log.status = "FAILED"
            log.output = out.getvalue() + "\n" + err.getvalue() + "\n" + traceback.format_exc()
        
        log.save()
    except Exception as e:
        pass # If we can't get the log, not much we can do.

@shared_task
def run_shell_command_task(log_id, command_str):
    try:
        log = CommandLog.objects.get(id=log_id)
        log.status = "RUNNING"
        log.save()
        
        try:
            from django.conf import settings
            import os
            env = os.environ.copy()
            env["LC_ALL"] = "C.UTF-8"
            env["LANG"] = "C.UTF-8"
            result = subprocess.run(
                command_str, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=300,
                cwd=settings.BASE_DIR,
                env=env
            )
            log.status = "SUCCESS" if result.returncode == 0 else "FAILED"
            log.output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        except Exception as e:
            log.status = "FAILED"
            log.output = traceback.format_exc()
            
        log.save()
    except Exception as e:
        pass
