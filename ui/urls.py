"""URL routes for the Freelance Agent monitoring UI."""

from django.contrib.auth import views as auth_views
from django.urls import path

from ui.views import ApplicationsView, DashboardView, JobsView, ResumeUploadView

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
    path("upload-resume", ResumeUploadView.as_view(), name="upload-resume"),
]
