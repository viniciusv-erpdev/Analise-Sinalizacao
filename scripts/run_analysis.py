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


# ============================================================
# CONFIGURAÇÃO
# ============================================================

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


# ============================================================
# LEITURA DOS DADOS
# ============================================================

print("=== LEITURA DOS DADOS ===")

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


print(
    "Total de registros:",
    len(df),
)


# ============================================================
# NORMALIZAÇÃO
# ============================================================

print()
print("=== NORMALIZAÇÃO ===")

normalized = normalize(df)

validate(normalized)

print(
    "Total de registros:",
    len(normalized),
)

print(
    "Colunas:",
    normalized.columns.tolist(),
)


# ============================================================
# RIBEIRÃO PRETO
# ============================================================

ribeirao = normalized[
    normalized["city"] == "RIBEIRAO PRETO"
].copy()


print()
print("=== RIBEIRÃO PRETO ===")

print(
    "Registros:",
    len(ribeirao),
)


# ============================================================
# CARREGAMENTO DO MUNICÍPIO
# ============================================================

municipality = load_municipality(
    MUNICIPALITY_PATH
)


print()
print("=== MUNICÍPIO ===")

print(
    "CRS:",
    municipality.crs,
)

print(
    "Bounds:",
    municipality.total_bounds,
)


# ============================================================
# VALIDAÇÃO DAS COORDENADAS
# ============================================================

ribeirao = validate_coordinates(
    ribeirao,
    municipality,
)


print()
print("=== VALIDAÇÃO DAS COORDENADAS ===")

print(
    ribeirao[
        "coordinate_status"
    ].value_counts()
)


# ============================================================
# COORDENADAS VÁLIDAS
# ============================================================

valid_coordinates = ribeirao[
    ribeirao["coordinate_status"] == "VALID"
].copy()


print()
print("=== COORDENADAS VÁLIDAS ===")

print(
    "Total:",
    len(valid_coordinates),
)


# ============================================================
# PONTOS DE OCORRÊNCIA
# ============================================================

points = build_occurrence_points(
    valid_coordinates
)


print()
print("=== PONTOS DE OCORRÊNCIA ===")

print(
    "Total de pontos:",
    len(points),
)


print()
print("=== MAIORES PONTOS ===")

print(
    points
    .sort_values(
        "accident_count",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)


# ============================================================
# CLUSTERS ESPACIAIS
# ============================================================

clusters = cluster_points(
    points,
    radius_meters=20,
    min_samples=1,
)


print()
print("=== CLUSTERS ESPACIAIS ===")

print(
    "Quantidade de clusters:",
    clusters["cluster_id"].nunique(),
)


print()
print("=== TAMANHO DOS CLUSTERS ===")

print(
    clusters[
        "cluster_id"
    ]
    .value_counts()
    .head(30)
)


# ============================================================
# ACIDENTES COM CLUSTER
# ============================================================

clustered_accidents = (
    assign_clusters_to_accidents(
        valid_coordinates,
        clusters,
    )
)


print()
print("=== ACIDENTES COM CLUSTER ===")

print(
    clustered_accidents[
        [
            "id",
            "date",
            "latitude",
            "longitude",
            "accident_type",
            "cluster_id",
        ]
    ]
    .head(20)
    .to_string(index=False)
)


# ============================================================
# ACIDENTES POR CLUSTER
# ============================================================

print()
print("=== ACIDENTES POR CLUSTER ===")

cluster_accidents = (
    clustered_accidents[
        [
            "id",
            "date",
            "cluster_id",
            "accident_type",
        ]
    ]
    .copy()
)


cluster_counts = (
    cluster_accidents
    .groupby("cluster_id")
    .size()
    .sort_values(
        ascending=False
    )
    .head(30)
)


print(cluster_counts)


# ============================================================
# TESTES DE CONSISTÊNCIA ESPACIAL
# ============================================================

print()
print("=== TESTES DE CONSISTÊNCIA ===")


assert (
    len(clustered_accidents)
    == len(valid_coordinates)
)

print(
    "Quantidade de acidentes preservada."
)


assert (
    clustered_accidents["cluster_id"]
    .notna()
    .all()
)

print(
    "Todos os acidentes receberam um cluster."
)


valid_cluster_ids = set(
    clusters["cluster_id"]
)

assert set(
    clustered_accidents["cluster_id"]
).issubset(
    valid_cluster_ids
)

print(
    "Todos os clusters dos acidentes são válidos."
)


calculated_counts = (
    clustered_accidents
    .groupby("cluster_id")
    .size()
    .sort_index()
)

cluster_point_counts = (
    points
    .merge(
        clusters[
            [
                "latitude",
                "longitude",
                "cluster_id",
            ]
        ],
        on=[
            "latitude",
            "longitude",
        ],
        how="inner",
    )
    .groupby("cluster_id")
    ["accident_count"]
    .sum()
    .sort_index()
)

assert (
    calculated_counts
    == cluster_point_counts
).all()

print(
    "Contagem de acidentes por cluster consistente."
)


assert (
    len(points)
    <= len(clusters)
)

print(
    "Quantidade de pontos preservada."
)


# ============================================================
# ANÁLISE TEMPORAL
# ============================================================

start_date = normalized["date"].min()
end_date = normalized["date"].max()

one_year_start = (
    end_date
    - pd.DateOffset(years=1)
)

three_years_start = (
    end_date
    - pd.DateOffset(years=3)
)


print()
print("=== ANÁLISE TEMPORAL ===")

print(
    "Data inicial:",
    start_date,
)

print(
    "Data final:",
    end_date,
)

print(
    "Início 1 ano:",
    one_year_start,
)

print(
    "Início 3 anos:",
    three_years_start,
)


# ============================================================
# CONTAGEM DE 1 ANO
# ============================================================

one_year = count_cluster_accidents(
    clustered_accidents,
    one_year_start,
    end_date,
)


# ============================================================
# CONTAGEM DE 3 ANOS
# ============================================================

three_years = count_cluster_accidents(
    clustered_accidents,
    three_years_start,
    end_date,
)


# ============================================================
# AVALIAÇÃO DOS CRITÉRIOS
# ============================================================

print()
print("=== AVALIAÇÃO DOS CRITÉRIOS ===")

criteria_result = evaluate_criteria(
    one_year,
    three_years,
)

criteria_result = add_criterion_classification(
    criteria_result
)

print(
    "COLUNAS APÓS CLASSIFICAÇÃO:",
    criteria_result.columns.tolist(),
)

print()
print("=== RESULTADO DOS CRITÉRIOS ===")

print(
    criteria_result
    .sort_values(
        "eligible",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)


# ============================================================
# RESULTADO FINAL
# ============================================================

analysis_result = build_analysis_result(
    clusters,
    criteria_result,
)

print(
    "COLUNAS APÓS BUILD RESULT:",
    analysis_result.columns.tolist(),
)

from analysis.location import (
    build_location_summary,
)

analysis_result = build_location_summary(
    clustered_accidents,
    analysis_result,
)

print(
    "COLUNAS ANTES DO MAPA:",
    analysis_result.columns.tolist(),
)

print()
print("=== PONTOS ELEGÍVEIS ===")

print(
    "Total de clusters elegíveis:",
    len(analysis_result),
)


print()

print(
    analysis_result
    .head(30)
    .to_string(index=False)
)


# ============================================================
# RESUMO
# ============================================================

print()
print("=== RESUMO DA ANÁLISE ===")

print(
    "Acidentes em Ribeirão Preto:",
    len(ribeirao),
)

print(
    "Coordenadas válidas:",
    len(valid_coordinates),
)

print(
    "Pontos de ocorrência:",
    len(points),
)

print(
    "Clusters:",
    clusters["cluster_id"].nunique(),
)

print(
    "Clusters elegíveis:",
    len(analysis_result),
)


print()
print("Análise concluída.")