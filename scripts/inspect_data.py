from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
path = BASE_DIR / "data" / "raw" / "sinistros_2025-2026.csv"

# Adicionado sep=";" para indicar que as colunas são separadas por ponto e vírgula
try:
    df = pd.read_csv(path, sep=";", encoding="utf-8")
except UnicodeDecodeError:
    df = pd.read_csv(path, sep=";", encoding="latin-1")

print("Linhas:", len(df))
print("Colunas:", len(df.columns))

print("\nColunas:")
for column in df.columns:
    print("-", column)

print("\nTipos:")
print(df.dtypes)

print("\nPrimeiras linhas:")
print(df.head())

# Ver os 10 primeiros valores originais (sem conversão)
print("Amostra original de DATA:")
print(df["data_sinistro"].head(10))

# Ver o tipo de dado original (provavelmente 'object' / string)
print("\nTipo original:", df["data_sinistro"].dtype)

# Contar valores nulos/vazios originais
print("Nulos originais em DATA:", df["data_sinistro"].isna().sum())

# Ver valores únicos (útil se forem poucas variações de texto)
print("Tamanhos de texto nas datas:", df["data_sinistro"].dropna().astype(str).str.len().value_counts())

# Ver amostras brutas de latitude e longitude
print("Amostra original de Coordenadas:")
print(df[["latitude", "longitude"]].head(10))

# Verificar se existem vírgulas nos números
tem_virgula_lat = df["latitude"].astype(str).str.contains(",").sum()
tem_virgula_lon = df["longitude"].astype(str).str.contains(",").sum()

print(f"\nRegistros com vírgula em LATITUDE: {tem_virgula_lat}")
print(f"Registros com vírgula em LONGITUDE: {tem_virgula_lon}")

# Mostra todos os valores únicos e a quantidade (sem ocultar linhas no terminal)
with pd.option_context('display.max_rows', None):
    print(df["tp_sinistro_primario"].value_counts(dropna=False))

# Ver a porcentagem / proporção de cada tipo de sinistro
print("\nProporção (%) de cada tipo:")
print(df["tp_sinistro_primario"].value_counts(normalize=True, dropna=False) * 100)

cols = ["data_sinistro", "latitude", "longitude", "tp_sinistro_primario"]

print("=== AMOSTRA DOS DADOS BRUTOS ===")
print(df[cols].head())

print("\n=== VERIFICAÇÃO DE VÍRGULAS NAS COORDENADAS ===")
print("Latitude tem vírgula?", df["latitude"].astype(str).str.contains(",").any())
print("Longitude tem vírgula?", df["longitude"].astype(str).str.contains(",").any())

print("\n=== CONTAGEM DE NULOS BRUTOS ===")
print(df[cols].isna().sum())

print("\n=== TIPO DE REGISTRO ===")
print(df["tipo_registro"].value_counts(dropna=False))

print("\n=== IDS REPETIDOS ===")

duplicated_ids = df["id_sinistro"].duplicated(keep=False)

print("IDs repetidos:", duplicated_ids.sum())
print(
    "IDs únicos repetidos:",
    df.loc[duplicated_ids, "id_sinistro"].nunique()
)

print("\n=== COMBINAÇÃO ID + TIPO DE REGISTRO ===")

print(
    df.groupby(["id_sinistro", "tipo_registro"])
      .size()
      .sort_values(ascending=False)
      .head(20)
)

print("\n=== COORDENADAS ===")

valid_coords = (
    df["latitude"].notna()
    & df["longitude"].notna()
)

print("Com coordenadas:", valid_coords.sum())
print("Sem coordenadas:", (~valid_coords).sum())

print("\nLatitude:")
print(df.loc[valid_coords, "latitude"].describe())

print("\nLongitude:")
print(df.loc[valid_coords, "longitude"].describe())