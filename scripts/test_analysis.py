import pandas as pd
from pathlib import Path

from accidents.normalizer import normalize, validate

from analysis.spatial import (
    cluster_accidents,
    summarize_clusters,
)

BASE_DIR = Path(__file__).resolve().parent.parent

path = BASE_DIR / "data" / "raw" / "sinistros_2025-2026.csv"


# =========================
# CARREGAMENTO
# =========================

try:
    df = pd.read_csv(
        path,
        sep=";",
        encoding="utf-8"
    )
except UnicodeDecodeError:
    df = pd.read_csv(
        path,
        sep=";",
        encoding="latin-1"
    )


# =========================
# NORMALIZAÇÃO
# =========================

normalized = normalize(df)

validate(normalized)


# =========================
# MUNICÍPIOS
# =========================

print("=== CIDADES ===")

print(
    normalized["city"]
    .value_counts()
    .head(20)
)


# =========================
# FILTRO ESPACIAL
# =========================

ribeirao = normalized[
    (normalized["city"] == "RIBEIRAO PRETO")
    & normalized["latitude"].notna()
    & normalized["longitude"].notna()
].copy()


print("\n=== RIBEIRÃO PRETO ===")

print("Total de registros:", len(ribeirao))


# =========================
# DBSCAN
# =========================

print("\n=== TIPOS DAS COORDENADAS ===")

print(ribeirao[["latitude", "longitude"]].dtypes)

print("\nDtype do NumPy:")

print(
    ribeirao[
        ["latitude", "longitude"]
    ].to_numpy().dtype
)

clustered = cluster_accidents(
    ribeirao,
    radius_meters=20,
)


print("\n=== CLUSTERS ===")

print(
    clustered["cluster_id"]
    .value_counts()
    .head(20)
)

print("\n=== RESULTADO DBSCAN ===")

print(
    "Quantidade de registros:",
    len(clustered)
)

print(
    "Quantidade de clusters:",
    clustered["cluster_id"].nunique()
)

print("\nTamanho dos maiores clusters:")

print(
    clustered["cluster_id"]
    .value_counts()
    .head(30)
)

clustered = cluster_accidents(
    ribeirao,
    radius_meters=20,
)

clusters = summarize_clusters(clustered)

print("\n=== RESUMO DOS CLUSTERS ===")

print(
    clusters
    .sort_values(
        "accident_count",
        ascending=False
    )
    .head(30)
    .to_string(index=False)
)

print("\n=== PERÍODO ===")

print("Data inicial:", normalized["date"].min())
print("Data final:", normalized["date"].max())

print("\n=== COORDENADAS REPETIDAS ===")

coordinate_counts = (
    ribeirao
    .groupby(["latitude", "longitude"])
    .size()
    .sort_values(ascending=False)
)

print(coordinate_counts.head(30))

for radius in [10, 15, 20, 25, 30]:
    clustered = cluster_accidents(
        ribeirao,
        radius_meters=radius,
    )

    print(
        f"{radius}m → "
        f"{clustered['cluster_id'].nunique()} clusters"
    )
    
coordinate_groups = (
    ribeirao
    .groupby(["latitude", "longitude"])
    .agg(
        accident_count=("id", "count"),
        collisions=(
            "accident_type",
            lambda x: (x == "COLISAO").sum(),
        ),
        pedestrians=(
            "accident_type",
            lambda x: (x == "ATROPELAMENTO").sum(),
        ),
    )
    .reset_index()
)

print("\n=== PONTOS DE OCORRÊNCIA ===")

print(
    "Total de pontos:",
    len(coordinate_groups)
)

print("\n=== MAIORES PONTOS ===")

print(
    coordinate_groups
    .sort_values(
        "accident_count",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)

# ============================================================
# ANÁLISE DOS PONTOS DE OCORRÊNCIA
# ============================================================

coordinate_groups = (
    ribeirao
    .groupby(["latitude", "longitude"])
    .agg(
        accident_count=("id", "count"),
        collisions=(
            "accident_type",
            lambda x: (x == "COLISAO").sum(),
        ),
        pedestrians=(
            "accident_type",
            lambda x: (x == "ATROPELAMENTO").sum(),
        ),
    )
    .reset_index()
)

print("\n=== PONTOS DE OCORRÊNCIA ===")

print(
    "Total de pontos:",
    len(coordinate_groups),
)

print(
    "Total de acidentes:",
    len(ribeirao),
)

print("\n=== MAIORES PONTOS ===")

print(
    coordinate_groups
    .sort_values(
        "accident_count",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)


# ============================================================
# EXTREMOS DAS COORDENADAS
# ============================================================

print("\n=== EXTREMOS GEOGRÁFICOS ===")

print(
    "Latitude mínima:",
    ribeirao["latitude"].min(),
)

print(
    "Latitude máxima:",
    ribeirao["latitude"].max(),
)

print(
    "Longitude mínima:",
    ribeirao["longitude"].min(),
)

print(
    "Longitude máxima:",
    ribeirao["longitude"].max(),
)


# ============================================================
# PONTOS SUSPEITOS
# ============================================================

print("\n=== PONTOS MAIS DISTANTES DO CENTRO APROXIMADO ===")

CENTER_LAT = -21.1775
CENTER_LON = -47.8103

ribeirao["distance_approx"] = (
    (ribeirao["latitude"] - CENTER_LAT) ** 2
    + (ribeirao["longitude"] - CENTER_LON) ** 2
) ** 0.5

print(
    ribeirao[
        [
            "id",
            "latitude",
            "longitude",
            "city",
            "accident_type",
            "distance_approx",
        ]
    ]
    .sort_values(
        "distance_approx",
        ascending=False,
    )
    .head(30)
    .to_string(index=False)
)