"""URL routes for the Freelance Agent monitoring UI."""

from django.contrib.auth import views as auth_views
from django.urls import path

from ui.views import (
    ApplicationsView,
    ConnectTelegramConfirmView,
    ConnectTelegramView,
    DashboardView,
    JobsView,
    ProfileView,
    ResumeUploadView,
)

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", DashboardView.as_view(), name="dashboard"),
    path("dashboard", DashboardView.as_view(), name="dashboard-alt"),
    path("jobs", JobsView.as_view(), name="jobs"),
    path("applications", ApplicationsView.as_view(), name="applications"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("upload-resume", ResumeUploadView.as_view(), name="upload-resume"),
    path("connect-telegram", ConnectTelegramView.as_view(), name="connect-telegram"),
    path(
        "connect-telegram/confirm/<str:token>",
        ConnectTelegramConfirmView.as_view(),
        name="connect-telegram-confirm",
    ),
]
