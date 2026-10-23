from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from accounts.views import register


urlpatterns = [
    path("accounts/register/", register, name="register"),
    path("accounts/login/", LoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path(
        "admin/",
        admin.site.urls,
    ),

    path(
        "signaling/",
        include("signaling.urls"),
    ),

    path(
        "",
        include("accidents.urls"),
    ),
]
