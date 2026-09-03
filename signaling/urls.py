from django.urls import path

from signaling import views


app_name = "signaling"

urlpatterns = [
    path("points/", views.create_point, name="create-point"),
    path(
        "points/<int:point_id>/delete/",
        views.delete_point,
        name="delete-point",
    ),
    path(
        "points/<int:point_id>/interventions/",
        views.save_intervention,
        name="save-intervention",
    ),
    path(
        "points/<int:point_id>/interventions/<int:intervention_id>/delete/",
        views.delete_intervention,
        name="delete-intervention",
    ),
]
