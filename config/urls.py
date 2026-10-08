from django.contrib import admin
from django.urls import include, path


urlpatterns = [
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
