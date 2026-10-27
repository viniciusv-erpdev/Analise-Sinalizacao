from django.urls import path

from signaling import views, reservation_views, synchronization_views, report_draft_views


app_name = "signaling"

urlpatterns = [
    path("points/<int:point_id>/report-draft/", report_draft_views.report_draft, name="report-draft"),
    path("points/sync/", synchronization_views.synchronize, name="synchronize-points"),
    path("points/<int:point_id>/reservation/", reservation_views.status, name="reservation-status"),
    path("points/<int:point_id>/reservation/acquire/", reservation_views.acquire, name="acquire-reservation"),
    path("points/<int:point_id>/reservation/renew/", reservation_views.renew, name="renew-reservation"),
    path("points/<int:point_id>/reservation/release/", reservation_views.release, name="release-reservation"),
    path("points/<int:point_id>/problems/", views.point_problems, name="point-problems"),
    path(
        "points/<int:point_id>/problems/<int:problem_id>/solution/",
        views.update_problem_solution,
        name="update-problem-solution",
    ),
    path(
        "points/<int:point_id>/problems/<int:problem_id>/delete/",
        views.delete_point_problem,
        name="delete-point-problem",
    ),
    path(
        "points/<int:point_id>/pgts/",
        views.search_point_pgts,
        name="search-point-pgts",
    ),
    path(
        "points/<int:point_id>/report/",
        views.point_report,
        name="point-report",
    ),
    path("points/", views.create_point, name="create-point"),
    path(
        "points/<int:point_id>/delete/",
        views.delete_point,
        name="delete-point",
    ),
    path(
        "points/<int:point_id>/status/",
        views.update_point_status,
        name="update-point-status",
    ),
    path(
        "points/<int:point_id>/search-radius/",
        views.update_point_search_radius,
        name="update-point-search-radius",
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
    path(
        "points/<int:point_id>/interventions/<int:intervention_id>/condition/",
        views.update_intervention_condition,
        name="update-intervention-condition",
    ),
    path(
        "points/<int:point_id>/interventions/<int:intervention_id>/notes/",
        views.update_intervention_notes,
        name="update-intervention-notes",
    ),
]
