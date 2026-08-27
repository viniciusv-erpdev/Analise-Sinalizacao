from pathlib import Path

import geopandas as gpd


BASE_DIR = Path(__file__).resolve().parent.parent

path = (
    BASE_DIR
    / "data"
    / "geography"
    / "ribeirao-preto"
    / "Municipio.json"
)

print("Caminho procurado:")
print(path)

print()
print("Arquivo existe?")
print(path.exists())

municipality = gpd.read_file(path)

print("=== GEOMETRIA ===")
print(municipality)

print()
print("=== CRS ===")
print(municipality.crs)

print()
print("=== BOUNDS ===")
print(municipality.total_bounds)

print()
print("=== COLUNAS ===")
print(municipality.columns)

print()
print("=== TESTE DE TRANSFORMAÇÃO ===")

test = municipality.copy()

test = test.set_crs(
    "EPSG:31983",
    allow_override=True,
)

test = test.to_crs("EPSG:4326")

print(test.total_bounds)