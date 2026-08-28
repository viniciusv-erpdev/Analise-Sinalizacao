import pandas as pd

from analysis.results import build_analysis_result


# ============================================================
# DADOS DE TESTE DOS CLUSTERS
# ============================================================

clusters = pd.DataFrame(
    [
        {
            "cluster_id": 1,
            "latitude": -21.20,
            "longitude": -47.80,
        },
        {
            "cluster_id": 2,
            "latitude": -21.21,
            "longitude": -47.81,
        },
        {
            "cluster_id": 3,
            "latitude": -21.22,
            "longitude": -47.82,
        },
    ]
)


# ============================================================
# DADOS DE TESTE DOS CRITÉRIOS
# ============================================================

criteria_result = pd.DataFrame(
    [
        {
            "cluster_id": 1,
            "accident_count_1y": 3,
            "collisions_1y": 3,
            "pedestrians_1y": 0,
            "accident_count_3y": 4,
            "collisions_3y": 4,
            "pedestrians_3y": 0,
            "collision_criterion": True,
            "pedestrian_criterion": False,
            "eligible": True,
        },
        {
            "cluster_id": 2,
            "accident_count_1y": 2,
            "collisions_1y": 0,
            "pedestrians_1y": 2,
            "accident_count_3y": 2,
            "collisions_3y": 0,
            "pedestrians_3y": 2,
            "collision_criterion": False,
            "pedestrian_criterion": True,
            "eligible": True,
        },
        {
            "cluster_id": 3,
            "accident_count_1y": 1,
            "collisions_1y": 1,
            "pedestrians_1y": 0,
            "accident_count_3y": 2,
            "collisions_3y": 2,
            "pedestrians_3y": 0,
            "collision_criterion": False,
            "pedestrian_criterion": False,
            "eligible": False,
        },
    ]
)


# ============================================================
# EXECUÇÃO
# ============================================================

print("=== TESTE build_analysis_result ===")

result = build_analysis_result(
    clusters,
    criteria_result,
)

print(
    result.to_string(index=False)
)


# ============================================================
# TESTES DE CONSISTÊNCIA
# ============================================================

print()
print("=== TESTES DE CONSISTÊNCIA ===")


# ------------------------------------------------------------
# Quantidade de resultados
# ------------------------------------------------------------

assert len(result) == 2

print(
    "Quantidade de clusters elegíveis correta."
)


# ------------------------------------------------------------
# Apenas clusters elegíveis
# ------------------------------------------------------------

assert set(
    result["cluster_id"]
) == {1, 2}

print(
    "Somente clusters elegíveis foram mantidos."
)


# ------------------------------------------------------------
# Cluster 3 não deve aparecer
# ------------------------------------------------------------

assert 3 not in set(
    result["cluster_id"]
)

print(
    "Clusters não elegíveis foram excluídos."
)


# ------------------------------------------------------------
# Coordenadas preservadas
# ------------------------------------------------------------

cluster_1 = result[
    result["cluster_id"] == 1
].iloc[0]

assert cluster_1["latitude"] == -21.20
assert cluster_1["longitude"] == -47.80

print(
    "Coordenadas dos clusters preservadas."
)


# ------------------------------------------------------------
# Critério de colisão
# ------------------------------------------------------------

assert bool(
    cluster_1["collision_criterion"]
) is True

print(
    "Critério de colisão preservado."
)


# ------------------------------------------------------------
# Critério de atropelamento
# ------------------------------------------------------------

cluster_2 = result[
    result["cluster_id"] == 2
].iloc[0]

assert bool(
    cluster_2["pedestrian_criterion"]
) is True

print(
    "Critério de atropelamento preservado."
)


# ------------------------------------------------------------
# Estatísticas preservadas
# ------------------------------------------------------------

assert cluster_1[
    "collisions_1y"
] == 3

assert cluster_2[
    "pedestrians_1y"
] == 2

print(
    "Estatísticas temporais preservadas."
)


# ------------------------------------------------------------
# Todos os resultados são elegíveis
# ------------------------------------------------------------

assert (
    result["eligible"]
    == True
).all()

print(
    "Todos os resultados são elegíveis."
)


print()
print("Todos os testes passaram.")