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

print("Total de registros:", len(df))


# ============================================================
# NORMALIZAÇÃO
# ============================================================

print()
print("=== NORMALIZAÇÃO ===")

normalized = normalize(df)

validate(normalized)

print("Total de registros:", len(normalized))
print("Colunas:", normalized.columns.tolist())


# ============================================================
# FILTRO DE RIBEIRÃO PRETO
# ============================================================

print()
print("=== RIBEIRÃO PRETO ===")

ribeirao = normalized[
    normalized["city"] == "RIBEIRAO PRETO"
].copy()

print("Registros:", len(ribeirao))


# ============================================================
# CARREGAMENTO DO MUNICÍPIO
# ============================================================

print()
print("=== MUNICÍPIO ===")

municipality = load_municipality(
    MUNICIPALITY_PATH
)

print("CRS:", municipality.crs)
print("Bounds:", municipality.total_bounds)


# ============================================================
# VALIDAÇÃO DAS COORDENADAS
# ============================================================

print()
print("=== VALIDAÇÃO DAS COORDENADAS ===")

ribeirao = validate_coordinates(
    ribeirao,
    municipality,
)

print(
    ribeirao["coordinate_status"]
    .value_counts()
)


# ============================================================
# COORDENADAS VÁLIDAS
# ============================================================

valid_ribeirao = ribeirao[
    ribeirao["coordinate_status"] == "VALID"
].copy()

print()
print("=== COORDENADAS VÁLIDAS ===")
print("Total:", len(valid_ribeirao))


# ============================================================
# PONTOS DE OCORRÊNCIA
# ============================================================

print()
print("=== PONTOS DE OCORRÊNCIA ===")

points = build_occurrence_points(
    valid_ribeirao
)

print("Total de pontos:", len(points))

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

print()
print("=== CLUSTERS ESPACIAIS ===")

clusters = cluster_points(
    points,
    radius_meters=20,
    min_samples=1,
)

print(
    "Quantidade de clusters:",
    clusters["cluster_id"].nunique(),
)

print()
print("=== TAMANHO DOS CLUSTERS ===")

print(
    clusters["cluster_id"]
    .value_counts()
    .head(30)
)


# ============================================================
# ASSOCIAR ACIDENTES AOS CLUSTERS
# ============================================================

print()
print("=== ACIDENTES COM CLUSTER ===")

clustered_accidents = assign_clusters_to_accidents(
    valid_ribeirao,
    clusters,
)

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
# ANÁLISE TEMPORAL
# ============================================================

print()
print("=== ANÁLISE TEMPORAL ===")

clustered_accidents["date"] = pd.to_datetime(
    clustered_accidents["date"]
)


# ------------------------------------------------------------
# Período disponível
# ------------------------------------------------------------

min_date = clustered_accidents["date"].min()
max_date = clustered_accidents["date"].max()

print("Data inicial:", min_date)
print("Data final:", max_date)


# ------------------------------------------------------------
# Último ano disponível
# ------------------------------------------------------------

one_year_start = (
    max_date
    - pd.DateOffset(years=1)
)

one_year_end = max_date


one_year = count_cluster_accidents(
    clustered_accidents,
    one_year_start,
    one_year_end,
)


# ------------------------------------------------------------
# Três anos disponíveis
# ------------------------------------------------------------

three_year_start = (
    max_date
    - pd.DateOffset(years=3)
)

three_year_end = max_date


three_years = count_cluster_accidents(
    clustered_accidents,
    three_year_start,
    three_year_end,
)


# ============================================================
# CRITÉRIOS
# ============================================================

print()
print("=== AVALIAÇÃO DOS CRITÉRIOS ===")

criteria = evaluate_criteria(
    one_year,
    three_years,
)


# ============================================================
# RESULTADOS
# ============================================================

print()
print("=== RESULTADO DOS CRITÉRIOS ===")

print(
    criteria
    .sort_values(
        "eligible",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)


# ============================================================
# PONTOS ELEGÍVEIS
# ============================================================

eligible = criteria[
    criteria["eligible"]
].copy()


print()
print("=== PONTOS ELEGÍVEIS ===")

print(
    "Total de clusters elegíveis:",
    len(eligible),
)


print()
print(
    eligible
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
    len(valid_ribeirao),
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
    len(eligible),
)

print()
print("Análise concluída.")