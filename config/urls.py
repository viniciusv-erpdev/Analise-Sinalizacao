from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path


urlpatterns = [
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
