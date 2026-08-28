import pandas as pd
from pathlib import Path

from accidents.normalizer import (
    normalize,
    validate,
)

from analysis.geography import (
    load_municipality,
    validate_coordinates,
)

from analysis.spatial import (
    cluster_points,
    assign_clusters_to_accidents,
)

from analysis.occurrences import (
    build_occurrence_points,
)

from analysis.criteria import (
    count_cluster_accidents,
    evaluate_criteria,
)

from analysis.results import (
    build_analysis_result,
)

from analysis.location import (
    build_location_summary,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_DIR = Path(
    __file__
).resolve().parent.parent

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


# ============================================================
# LEITURA
# ============================================================

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


# ============================================================
# NORMALIZAÇÃO
# ============================================================

normalized = normalize(df)

validate(normalized)


# ============================================================
# RIBEIRÃO PRETO
# ============================================================

ribeirao = normalized[
    normalized["city"]
    == "RIBEIRAO PRETO"
].copy()


# ============================================================
# MUNICÍPIO
# ============================================================

municipality = load_municipality(
    MUNICIPALITY_PATH
)


# ============================================================
# COORDENADAS
# ============================================================

ribeirao = validate_coordinates(
    ribeirao,
    municipality,
)

valid_ribeirao = ribeirao[
    ribeirao["coordinate_status"]
    == "VALID"
].copy()


# ============================================================
# PONTOS
# ============================================================

points = build_occurrence_points(
    valid_ribeirao
)


# ============================================================
# CLUSTERS
# ============================================================

clusters = cluster_points(
    points
)


clustered_accidents = (
    assign_clusters_to_accidents(
        valid_ribeirao,
        clusters,
    )
)


# ============================================================
# PERÍODOS
# ============================================================

end_date = (
    clustered_accidents["date"]
    .max()
)

start_1y = (
    end_date
    - pd.DateOffset(years=1)
)

start_3y = (
    end_date
    - pd.DateOffset(years=3)
)


# ============================================================
# CRITÉRIOS
# ============================================================

one_year = count_cluster_accidents(
    clustered_accidents,
    start_1y,
    end_date,
)

three_years = count_cluster_accidents(
    clustered_accidents,
    start_3y,
    end_date,
)

criteria = evaluate_criteria(
    one_year,
    three_years,
)


# ============================================================
# RESULTADO
# ============================================================

analysis_result = build_analysis_result(
    clusters,
    criteria,
)


# ============================================================
# LOCALIZAÇÃO
# ============================================================

result = build_location_summary(
    clustered_accidents,
    analysis_result,
)


# ============================================================
# RESULTADO
# ============================================================

print()
print(
    "=== CLUSTERS ELEGÍVEIS ==="
)

print(
    "Total:",
    len(result)
)

print()

print(
    result[
        [
            "cluster_id",
            "latitude",
            "longitude",
            "location",
            "location_type",
            "collisions_1y",
            "pedestrians_1y",
            "collisions_3y",
            "pedestrians_3y",
        ]
    ]
    .sort_values(
        "cluster_id"
    )
    .to_string(
        index=False
    )
)