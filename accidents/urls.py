from django.urls import path

from . import views


urlpatterns = [
    path(
        "",
        views.analysis_view,
        name="analysis",
    ),
]