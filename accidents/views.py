from django.shortcuts import render

from accidents.services import (
    AccidentImportError,
    import_accident_files,
)
from analysis.map_data import build_map_data
from analysis.pipeline import process_accidents
from signaling.services import get_signaling_map_data


def analysis_view(request):
    results = []
    map_data = []
    import_error = None
    import_summary = None

    if request.method == "POST":
        uploaded_files = request.FILES.getlist(
            "files"
        )

        try:
            consolidated = import_accident_files(
                uploaded_files
            )
            results = process_accidents(
                consolidated
            )
            map_data = build_map_data(
                results
            )
            import_summary = {
                "file_count": len(uploaded_files),
                "accident_count": len(consolidated),
                "eligible_count": len(results),
            }
        except AccidentImportError as error:
            import_error = str(error)

    context = {
        "results": results,
        "map_data": map_data,
        "signaling_map_data": get_signaling_map_data(),
        "import_error": import_error,
        "import_summary": import_summary,
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
