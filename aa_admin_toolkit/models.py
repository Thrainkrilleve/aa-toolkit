from django.db import models
from django.contrib.auth.models import User

class CommandLog(models.Model):
    command_name = models.CharField(max_length=255)
    action_type = models.CharField(max_length=64, default="manual")
    normalized_command = models.CharField(max_length=512, blank=True)
    target = models.CharField(max_length=255, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    executed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    executed_at = models.DateTimeField(auto_now_add=True)
    output = models.TextField(blank=True)
    status = models.CharField(max_length=50, default="PENDING")
    
    class Meta:
        ordering = ["-executed_at"]

    def __str__(self):
        return f"{self.command_name} run by {self.executed_by} at {self.executed_at}"
