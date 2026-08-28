from django.shortcuts import render

from analysis.pipeline import run_analysis
from analysis.map_data import build_map_data


def analysis_view(request):

    results = run_analysis()

    print(
        "VIEW - COLUNAS ENVIADAS PARA O MAPA:",
        results.columns.tolist(),
    )

    print(
        results.head()
    )

    map_data = build_map_data(
        results
    )

    print(
    "VIEW - TOTAL DE PONTOS DO MAPA:",
    len(map_data),
    )

    print(
    "VIEW - PRIMEIRO PONTO:",
    map_data[0] if map_data else None,
    )

    context = {
        "results": results,
        "map_data": map_data,
    }

    return render(
        request,
        "map.html",
        context,
    )