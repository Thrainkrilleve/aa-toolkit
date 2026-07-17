from django.urls import path
from . import views

app_name = "aa_admin_toolkit"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("log/<int:log_id>/", views.log_detail, name="log_detail"),
]
