from django.contrib import admin
from .models import CommandLog

@admin.register(CommandLog)
class CommandLogAdmin(admin.ModelAdmin):
    list_display = ("command_name", "executed_by", "executed_at", "status")
    list_filter = ("status", "command_name")
    readonly_fields = ("command_name", "executed_by", "executed_at", "output", "status")
