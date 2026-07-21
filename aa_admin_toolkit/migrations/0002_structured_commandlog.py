from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aa_admin_toolkit", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="commandlog",
            name="action_type",
            field=models.CharField(default="manual", max_length=64),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="normalized_command",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="target",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="exit_code",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="commandlog",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]