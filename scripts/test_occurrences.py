import pandas as pd
from pathlib import Path

from accidents.normalizer import normalize, validate
from analysis.geography import (
    load_municipality,
    validate_coordinates,
)
from analysis.occurrences import create_occurrence_points


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


print("=== DADOS ORIGINAIS ===")
print("Total:", len(df))


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


print()
print("=== RIBEIRÃO PRETO ===")
print("Registros:", len(ribeirao))


# ============================================================
# VALIDAÇÃO GEOGRÁFICA
# ============================================================

municipality = load_municipality(
    MUNICIPALITY_PATH
)

ribeirao = validate_coordinates(
    ribeirao,
    municipality,
)


# ============================================================
# SOMENTE COORDENADAS VÁLIDAS
# ============================================================

valid = ribeirao[
    ribeirao["coordinate_status"] == "VALID"
].copy()


print()
print("=== COORDENADAS VÁLIDAS ===")
print("Total:", len(valid))


# ============================================================
# CRIAÇÃO DOS PONTOS DE OCORRÊNCIA
# ============================================================

points = create_occurrence_points(valid)


# ============================================================
# RESULTADOS
# ============================================================

print()
print("=== PONTOS DE OCORRÊNCIA ===")
print("Total:", len(points))

print()
print("=== COLUNAS ===")
print(points.columns.tolist())

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
# TESTES DE CONSISTÊNCIA
# ============================================================

print()
print("=== TESTES DE CONSISTÊNCIA ===")

print(
    "Acidentes originais:",
    len(valid),
)

print(
    "Acidentes contabilizados nos pontos:",
    points["accident_count"].sum(),
)

print(
    "Pontos distintos:",
    len(points),
)

print(
    "Coordenadas únicas:",
    valid[
        ["latitude", "longitude"]
    ].drop_duplicates().shape[0],
)


# ============================================================
# VALIDAÇÕES
# ============================================================

assert (
    points["accident_count"].sum()
    == len(valid)
), (
    "A quantidade de acidentes nos pontos "
    "não corresponde à quantidade de acidentes válidos."
)

assert (
    len(points)
    == valid[
        ["latitude", "longitude"]
    ].drop_duplicates().shape[0]
), (
    "A quantidade de pontos não corresponde "
    "à quantidade de coordenadas únicas."
)

assert (
    points["collisions"].sum()
    == (
        valid["accident_type"] == "COLISAO"
    ).sum()
), (
    "A quantidade de colisões foi alterada "
    "durante a agregação."
)

assert (
    points["pedestrians"].sum()
    == (
        valid["accident_type"]
        == "ATROPELAMENTO"
    ).sum()
), (
    "A quantidade de atropelamentos foi alterada "
    "durante a agregação."
)

print()
print("Todos os testes passaram.")