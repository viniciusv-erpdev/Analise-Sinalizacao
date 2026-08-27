import pandas as pd
from pathlib import Path

from accidents.normalizer import normalize
from analysis.spatial import (
    cluster_accidents,
    summarize_clusters,
)


BASE_DIR = Path(__file__).resolve().parent.parent
path = BASE_DIR / "data" / "raw" / "sinistros_2025-2026.csv"
INPUT_PATH = "data/raw/sinistros_2025-2026.csv"

try:
    df = pd.read_csv(path, sep=";", encoding="utf-8")
except UnicodeDecodeError:
    df = pd.read_csv(path, sep=";", encoding="latin-1")

df = normalize(df)

df = df[
    (df["city"] == "RIBEIRAO PRETO")
    & df["latitude"].notna()
    & df["longitude"].notna()
].copy()

print("Acidentes analisáveis:", len(df))

clustered = cluster_accidents(
    df,
    radius_meters=20,
)

clusters = summarize_clusters(clustered)

print("\nClusters:")
print(clusters.head(20))