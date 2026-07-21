from django.contrib import admin
from .models import CommandLog

@admin.register(CommandLog)
class CommandLogAdmin(admin.ModelAdmin):
    list_display = ("command_name", "action_type", "target", "executed_by", "executed_at", "status", "exit_code")
    list_filter = ("status", "command_name")
    readonly_fields = (
        "command_name",
        "action_type",
        "normalized_command",
        "target",
        "exit_code",
        "started_at",
        "finished_at",
        "executed_by",
        "executed_at",
        "output",
        "status",
    )
