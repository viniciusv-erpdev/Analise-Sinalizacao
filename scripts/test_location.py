import pandas as pd

from analysis.location import (
    build_location_summary,
)


# ============================================================
# DADOS DE TESTE
# ============================================================

accidents = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5],
        "cluster_id": [1, 1, 2, 2, 3],
        "street": [
            "AVENIDA A",
            "AVENIDA A",
            "RUA B",
            "RUA B",
            None,
        ],
        "street_number": [
            "100",
            "100",
            "200",
            "200",
            None,
        ],
    }
)


eligible_clusters = pd.DataFrame(
    {
        "cluster_id": [1, 2, 3],
        "latitude": [
            -21.20,
            -21.21,
            -21.22,
        ],
        "longitude": [
            -47.80,
            -47.81,
            -47.82,
        ],
        "eligible": [
            True,
            True,
            True,
        ],
    }
)


# ============================================================
# TESTE
# ============================================================

print("=== TESTE build_location_summary ===")

result = build_location_summary(
    accidents,
    eligible_clusters,
)

print(
    result.to_string(
        index=False
    )
)


# ============================================================
# TESTES DE CONSISTÊNCIA
# ============================================================

print()
print("=== TESTES DE CONSISTÊNCIA ===")


# Quantidade de clusters preservada
assert len(result) == len(
    eligible_clusters
)

print(
    "Quantidade de clusters preservada."
)


# Cluster 1
cluster_1 = result[
    result["cluster_id"] == 1
].iloc[0]

assert cluster_1["street"] == "AVENIDA A"
assert cluster_1["street_number"] == "100"
assert cluster_1["location"] == "AVENIDA A, 100"

print(
    "Cluster 1: localização completa funcionando."
)


# Cluster 2
cluster_2 = result[
    result["cluster_id"] == 2
].iloc[0]

assert cluster_2["street"] == "RUA B"
assert cluster_2["street_number"] == "200"
assert cluster_2["location"] == "RUA B, 200"

print(
    "Cluster 2: localização completa funcionando."
)


# Cluster 3
cluster_3 = result[
    result["cluster_id"] == 3
].iloc[0]

assert cluster_3["location"] == (
    "Localização não identificada"
)

print(
    "Cluster 3: localização ausente tratada corretamente."
)


print()
print("Todos os testes passaram.")