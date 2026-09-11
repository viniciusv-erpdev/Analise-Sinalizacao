from django.shortcuts import redirect, render

from accidents.services import (
    AccidentImportError,
    import_accident_files,
)
from analysis.map_data import (
    INDIVIDUAL_FILTER_CATEGORIES,
    build_individual_map_data,
    build_map_data,
)
from analysis.pipeline import process_accidents, process_individual_accidents
from signaling.services import get_signaling_map_data
from signaling.surveys import ANALYSIS_SESSION_KEY, SIGNALING_SURVEY_RADIUS_METERS


def analysis_view(request):
    results = []
    map_data = []
    import_error = None
    import_summary = None
    view_mode = "clusters"
    has_individual_analysis = False

    if request.method == "POST":
        view_mode = request.POST.get("view_mode", "clusters")
        uploaded_files = request.FILES.getlist(
            "files"
        )

        try:
            if view_mode not in {"clusters", "individual"}:
                raise AccidentImportError("Modo de visualização inválido.")
            consolidated = import_accident_files(
                uploaded_files
            )
            if view_mode == "individual":
                results = process_individual_accidents(consolidated)
                map_data = build_individual_map_data(results)
                has_individual_analysis = True
                individual_metrics = results.attrs.get("individual_metrics", {})
                import_summary = {
                    "file_count": len(uploaded_files),
                    "accident_count": len(consolidated),
                    "valid_coordinate_count": individual_metrics.get(
                        "valid_coordinate_count",
                        len(results),
                    ),
                    "internal_filter_count": individual_metrics.get(
                        "internal_filter_count",
                        len(results),
                    ),
                    "displayed_count": len(map_data),
                }
            else:
                results = process_accidents(consolidated)
                map_data = build_map_data(results)
                import_summary = {
                    "file_count": len(uploaded_files),
                    "accident_count": len(consolidated),
                    "eligible_count": len(results),
                }
            request.session[ANALYSIS_SESSION_KEY] = {
                "view_mode": view_mode,
                "map_data": map_data,
                "import_summary": import_summary,
            }
            return redirect("analysis")
        except AccidentImportError as error:
            request.session.pop(ANALYSIS_SESSION_KEY, None)
            import_error = str(error)

    if request.GET.get("clear") == "1":
        request.session.pop(ANALYSIS_SESSION_KEY, None)
    elif request.method == "GET":
        analysis_state = request.session.get(ANALYSIS_SESSION_KEY)
        if isinstance(analysis_state, dict):
            view_mode = analysis_state.get("view_mode", "clusters")
            map_data = analysis_state.get("map_data", [])
            import_summary = analysis_state.get("import_summary")
            has_individual_analysis = view_mode == "individual"

    context = {
        "results": results,
        "map_data": map_data,
        "signaling_map_data": get_signaling_map_data(),
        "import_error": import_error,
        "import_summary": import_summary,
        "view_mode": view_mode,
        "has_individual_analysis": has_individual_analysis,
        "individual_filter_categories": INDIVIDUAL_FILTER_CATEGORIES,
        "signaling_survey_radius_meters": SIGNALING_SURVEY_RADIUS_METERS,
        "initial_tool_tab": (
            "filters"
            if import_summary
            else "data"
        ),
    }

    return render(
        request,
        "map.html",
        context,
    )
