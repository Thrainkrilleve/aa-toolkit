from django.urls import path
from . import views

app_name = "aa_admin_toolkit"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("operations/", views.operations, name="operations"),
    path("log/<int:log_id>/", views.log_detail, name="log_detail"),
    path("stats/", views.resource_stats, name="resource_stats"),
    path("docker-stats/", views.docker_stats, name="docker_stats"),
]
