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
    evaluate_historical_criteria,
    add_criterion_classification,
)

from analysis.results import (
    build_analysis_result,
)

from analysis.location import (
    build_location_summary,
)


BASE_DIR = Path(__file__).resolve().parent.parent

MUNICIPALITY_PATH = (
    BASE_DIR
    / "data"
    / "geography"
    / "ribeirao-preto"
    / "municipio.json"
)


def process_accidents(df: pd.DataFrame) -> pd.DataFrame:

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
    # CRITÉRIOS
    # ========================================================

    criteria_result = evaluate_historical_criteria(
        clustered_accidents
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
