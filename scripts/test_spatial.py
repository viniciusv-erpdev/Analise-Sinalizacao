import pandas as pd
from pathlib import Path

from analysis.clusters import (
    summarize_clusters,
)

from accidents.normalizer import normalize, validate
from analysis.geography import (
    load_municipality,
    validate_coordinates,
)
from analysis.occurrences import (
    create_occurrence_points,
)
from analysis.spatial import (
    cluster_points,
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
    normalized["city"] == "RIBEIRAO PRETO"
].copy()


# ============================================================
# GEOGRAFIA
# ============================================================

municipality = load_municipality(
    MUNICIPALITY_PATH
)

ribeirao = validate_coordinates(
    ribeirao,
    municipality,
)


# ============================================================
# COORDENADAS VÁLIDAS
# ============================================================

valid = ribeirao[
    ribeirao["coordinate_status"] == "VALID"
].copy()


# ============================================================
# PONTOS DE OCORRÊNCIA
# ============================================================

points = create_occurrence_points(
    valid
)


# ============================================================
# DBSCAN
# ============================================================

clustered = cluster_points(
    points,
    radius_meters=20,
    min_samples=1,
)

print()

print("=== COLUNAS DOS CLUSTERS ===")

print(
    clustered.columns.tolist()
)

print()

print("=== AMOSTRA DOS CLUSTERS ===")

print(
    clustered.head(10).to_string(
        index=False
    )
)

summary = summarize_clusters(
    clustered
)

# ============================================================
# RESULTADOS
# ============================================================

print("=== PONTOS ===")
print(
    "Total de pontos:",
    len(points),
)

print()

print("=== CLUSTERS ===")

print(
    "Quantidade de clusters:",
    clustered["cluster_id"].nunique(),
)


print()

print("=== TAMANHO DOS CLUSTERS ===")

cluster_sizes = (
    clustered
    .groupby("cluster_id")
    .size()
    .sort_values(
        ascending=False
    )
)

print(
    cluster_sizes.head(30)
)


# ============================================================
# TESTES
# ============================================================

print()

print("=== TESTES ===")


assert (
    len(clustered)
    == len(points)
), (
    "O DBSCAN alterou a quantidade "
    "de pontos."
)


assert (
    clustered["cluster_id"].notna().all()
), (
    "Existem clusters sem identificação."
)


assert (
    clustered["accident_count"].sum()
    == points["accident_count"].sum()
), (
    "A quantidade de acidentes "
    "foi alterada."
)


print("Quantidade de pontos preservada.")

print("Quantidade de acidentes preservada.")

print("Todos os testes passaram.")

print()

print("=== RESUMO DOS CLUSTERS ===")

print(
    "Total de clusters:",
    len(summary),
)

print()

print(
    summary
    .sort_values(
        "accident_count",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)

assert (
    summary["accident_count"].sum()
    == points["accident_count"].sum()
), (
    "A soma de acidentes dos clusters "
    "não corresponde aos pontos."
)


assert (
    summary["collisions"].sum()
    == points["collisions"].sum()
), (
    "A soma de colisões dos clusters "
    "não corresponde aos pontos."
)


assert (
    summary["pedestrians"].sum()
    == points["pedestrians"].sum()
), (
    "A soma de atropelamentos dos clusters "
    "não corresponde aos pontos."
)


assert (
    len(summary)
    == clustered["cluster_id"].nunique()
), (
    "Quantidade de clusters inconsistente."
)


print()
print("Resumo dos clusters consistente.")
print("Todos os testes passaram.")