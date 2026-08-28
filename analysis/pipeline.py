import pandas as pd
from pathlib import Path

from accidents.normalizer import normalize, validate

from analysis.geography import (
    load_municipality,
    validate_coordinates,
)

from analysis.occurrences import (
    build_occurrence_points,
)

from analysis.spatial import (
    cluster_points,
    assign_clusters_to_accidents,
)

from analysis.criteria import (
    count_cluster_accidents,
    evaluate_criteria,
    add_criterion_classification,
)

from analysis.results import (
    build_analysis_result,
)

from analysis.location import (
    build_location_summary,
)


BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_PATH = (
    BASE_DIR
    / "data"
    / "raw"
    / "sinistros_2025-2026.csv"
)

MUNICIPALITY_PATH = (
    BASE_DIR
    / "data"
    / "geography"
    / "ribeirao-preto"
    / "municipio.json"
)


def run_analysis():

    # ========================================================
    # LEITURA
    # ========================================================

    try:
        df = pd.read_csv(
            INPUT_PATH,
            sep=";",
            encoding="utf-8",
        )

    except UnicodeDecodeError:
        df = pd.read_csv(
            INPUT_PATH,
            sep=";",
            encoding="latin-1",
        )

    # ========================================================
    # NORMALIZAÇÃO
    # ========================================================

    normalized = normalize(df)

    validate(normalized)

    # ========================================================
    # RIBEIRÃO PRETO
    # ========================================================

    ribeirao = normalized[
        normalized["city"] == "RIBEIRAO PRETO"
    ].copy()

    # ========================================================
    # MUNICÍPIO
    # ========================================================

    municipality = load_municipality(
        MUNICIPALITY_PATH
    )

    # ========================================================
    # VALIDAÇÃO DAS COORDENADAS
    # ========================================================

    ribeirao = validate_coordinates(
        ribeirao,
        municipality,
    )

    # ========================================================
    # COORDENADAS VÁLIDAS
    # ========================================================

    valid_coordinates = ribeirao[
        ribeirao["coordinate_status"] == "VALID"
    ].copy()

    # ========================================================
    # PONTOS DE OCORRÊNCIA
    # ========================================================

    points = build_occurrence_points(
        valid_coordinates
    )

    # ========================================================
    # CLUSTERS
    # ========================================================

    clusters = cluster_points(
        points,
        radius_meters=20,
        min_samples=1,
    )

    # ========================================================
    # ACIDENTES COM CLUSTER
    # ========================================================

    clustered_accidents = (
        assign_clusters_to_accidents(
            valid_coordinates,
            clusters,
        )
    )

    # ========================================================
    # PERÍODO DA ANÁLISE
    # ========================================================

    end_date = normalized["date"].max()

    one_year_start = (
        end_date
        - pd.DateOffset(years=1)
    )

    three_years_start = (
        end_date
        - pd.DateOffset(years=3)
    )

    # ========================================================
    # CONTAGEM 1 ANO
    # ========================================================

    one_year = count_cluster_accidents(
        clustered_accidents,
        one_year_start,
        end_date,
    )

    # ========================================================
    # CONTAGEM 3 ANOS
    # ========================================================

    three_years = count_cluster_accidents(
        clustered_accidents,
        three_years_start,
        end_date,
    )

    # ========================================================
    # CRITÉRIOS
    # ========================================================

    criteria_result = evaluate_criteria(
        one_year,
        three_years,
    )

    criteria_result = add_criterion_classification(
        criteria_result
    )
    # ========================================================
    # RESULTADO
    # ========================================================

    analysis_result = build_analysis_result(
        clusters,
        criteria_result,
    )

    # ========================================================
    # LOCALIZAÇÃO
    # ========================================================

    print(
    "PIPELINE - ANTES LOCATION:",
    analysis_result.columns.tolist(),
    )

    analysis_result = build_location_summary(
        clustered_accidents,
        analysis_result,
    )

    print(
    "PIPELINE - RETORNO:",
    analysis_result.columns.tolist(),
    )

    return analysis_result