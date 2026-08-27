import pandas as pd
from pathlib import Path

from accidents.normalizer import normalize, validate

from analysis.geography import (
    load_municipality,
    validate_coordinates,
)

from analysis.spatial import (
    cluster_points,
    assign_clusters_to_accidents,
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


print("=== DADOS ORIGINAIS ===")
print("Total:", len(df))


# ============================================================
# NORMALIZAÇÃO
# ============================================================

normalized = normalize(df)

validate(normalized)


print()
print("=== DADOS NORMALIZADOS ===")
print("Total:", len(normalized))

print()
print("Colunas:")
print(normalized.columns.tolist())


# ============================================================
# RIBEIRÃO PRETO
# ============================================================

ribeirao = normalized[
    normalized["city"] == "RIBEIRAO PRETO"
].copy()


print()
print("=== RIBEIRÃO PRETO ===")
print("Registros:", len(ribeirao))


# ============================================================
# CARREGAMENTO DO MUNICÍPIO
# ============================================================

municipality = load_municipality(
    MUNICIPALITY_PATH
)


print()
print("=== MUNICÍPIO ===")
print("CRS:", municipality.crs)
print("Bounds:", municipality.total_bounds)


# ============================================================
# VALIDAÇÃO DAS COORDENADAS
# ============================================================

ribeirao = validate_coordinates(
    ribeirao,
    municipality,
)


print()
print("=== STATUS DAS COORDENADAS ===")

print(
    ribeirao["coordinate_status"]
    .value_counts()
)


# ============================================================
# COORDENADAS VÁLIDAS
# ============================================================

valid_coordinates = ribeirao[
    ribeirao["coordinate_status"] == "VALID"
].copy()


print()
print("=== COORDENADAS VÁLIDAS ===")
print("Total:", len(valid_coordinates))


# ============================================================
# PONTOS DE OCORRÊNCIA
# ============================================================

points = (
    valid_coordinates
    .groupby(
        ["latitude", "longitude"],
        dropna=False,
    )
    .agg(
        accident_count=("id", "count"),

        collisions=(
            "accident_type",
            lambda x: (
                x == "COLISAO"
            ).sum(),
        ),

        pedestrians=(
            "accident_type",
            lambda x: (
                x == "ATROPELAMENTO"
            ).sum(),
        ),
    )
    .reset_index()
)


print()
print("=== PONTOS DE OCORRÊNCIA ===")
print("Total:", len(points))


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
# CLUSTERIZAÇÃO
# ============================================================

clusters = cluster_points(
    points,
    radius_meters=20,
    min_samples=1,
)


print()
print("=== CLUSTERS ===")

print(
    "Quantidade de clusters:",
    clusters["cluster_id"].nunique(),
)


print()
print("=== TAMANHO DOS CLUSTERS ===")

print(
    clusters[
        clusters["cluster_id"] >= 0
    ]
    .groupby("cluster_id")
    .size()
    .sort_values(
        ascending=False
    )
    .head(30)
)


# ============================================================
# ASSOCIAÇÃO DOS ACIDENTES AOS CLUSTERS
# ============================================================

clustered_accidents = assign_clusters_to_accidents(
    valid_coordinates,
    clusters,
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
# DISTRIBUIÇÃO DOS ACIDENTES POR CLUSTER
# ============================================================

print()
print("=== ACIDENTES POR CLUSTER ===")

print(
    clustered_accidents[
        "cluster_id"
    ]
    .value_counts()
    .head(30)
)


# ============================================================
# TESTES DE CONSISTÊNCIA
# ============================================================

print()
print("=== TESTES DE CONSISTÊNCIA ===")


# ------------------------------------------------------------
# Teste 1 — quantidade de acidentes preservada
# ------------------------------------------------------------

assert len(clustered_accidents) == len(
    valid_coordinates
)

print(
    "Quantidade de acidentes preservada."
)


# ------------------------------------------------------------
# Teste 2 — todos os acidentes receberam cluster
# ------------------------------------------------------------

assert (
    clustered_accidents["cluster_id"]
    .notna()
    .all()
)

print(
    "Todos os acidentes receberam um cluster."
)


# ------------------------------------------------------------
# Teste 3 — todos os clusters existem
# ------------------------------------------------------------

accident_clusters = set(
    clustered_accidents[
        "cluster_id"
    ].unique()
)

available_clusters = set(
    clusters[
        "cluster_id"
    ].unique()
)

assert accident_clusters.issubset(
    available_clusters
)

print(
    "Todos os clusters dos acidentes são válidos."
)


# ------------------------------------------------------------
# Teste 4 — quantidade de acidentes por cluster
# ------------------------------------------------------------

accident_counts = (
    clustered_accidents
    .groupby("cluster_id")
    .size()
    .sort_index()
)

point_counts = (
    clusters
    .groupby("cluster_id")[
        "accident_count"
    ]
    .sum()
    .sort_index()
)


pd.testing.assert_series_equal(
    accident_counts,
    point_counts,
    check_names=False,
)

print(
    "Contagem de acidentes por cluster consistente."
)


# ------------------------------------------------------------
# Teste 5 — quantidade de pontos preservada
# ------------------------------------------------------------

assert (
    clusters["cluster_id"].nunique()
    <= len(points)
)

print(
    "Quantidade de pontos preservada."
)


# ============================================================
# RESUMO DOS CLUSTERS
# ============================================================

cluster_summary = (
    clustered_accidents
    .groupby("cluster_id")
    .agg(
        latitude=(
            "latitude",
            "mean",
        ),

        longitude=(
            "longitude",
            "mean",
        ),

        point_count=(
            "id",
            lambda x: (
                clustered_accidents
                .loc[x.index, "latitude"]
                .astype(str)
                + "_"
                + clustered_accidents
                .loc[x.index, "longitude"]
                .astype(str)
            ).nunique(),
        ),

        accident_count=(
            "id",
            "count",
        ),

        collisions=(
            "accident_type",
            lambda x: (
                x == "COLISAO"
            ).sum(),
        ),

        pedestrians=(
            "accident_type",
            lambda x: (
                x == "ATROPELAMENTO"
            ).sum(),
        ),
    )
    .reset_index()
)


print()
print("=== RESUMO DOS CLUSTERS ===")

print(
    "Total de clusters:",
    len(cluster_summary),
)


print()

print(
    cluster_summary
    .sort_values(
        "accident_count",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)


# ============================================================
# RESULTADO FINAL
# ============================================================

print()
print("=== RESULTADO ===")
print("Todos os testes passaram.")