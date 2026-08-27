import pandas as pd

from analysis.criteria import (
    count_accidents,
    count_cluster_accidents,
    evaluate_criteria,
)


# ============================================================
# DADOS DE TESTE
# ============================================================

data = [
    # Cluster 1
    {
        "id": 1,
        "date": "2025-01-10",
        "cluster_id": 1,
        "accident_type": "COLISAO",
    },
    {
        "id": 2,
        "date": "2025-03-15",
        "cluster_id": 1,
        "accident_type": "COLISAO",
    },
    {
        "id": 3,
        "date": "2025-05-20",
        "cluster_id": 1,
        "accident_type": "COLISAO",
    },

    # Cluster 2
    {
        "id": 4,
        "date": "2025-02-10",
        "cluster_id": 2,
        "accident_type": "ATROPELAMENTO",
    },
    {
        "id": 5,
        "date": "2025-04-10",
        "cluster_id": 2,
        "accident_type": "ATROPELAMENTO",
    },

    # Cluster 3
    {
        "id": 6,
        "date": "2023-06-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },
    {
        "id": 7,
        "date": "2023-07-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },
    {
        "id": 8,
        "date": "2023-08-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },
    {
        "id": 9,
        "date": "2023-09-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },
    {
        "id": 10,
        "date": "2023-10-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },
    {
        "id": 11,
        "date": "2023-11-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },
    {
        "id": 12,
        "date": "2023-12-10",
        "cluster_id": 3,
        "accident_type": "COLISAO",
    },

    # Cluster 4
    {
        "id": 13,
        "date": "2023-06-10",
        "cluster_id": 4,
        "accident_type": "ATROPELAMENTO",
    },
    {
        "id": 14,
        "date": "2023-07-10",
        "cluster_id": 4,
        "accident_type": "ATROPELAMENTO",
    },
    {
        "id": 15,
        "date": "2023-08-10",
        "cluster_id": 4,
        "accident_type": "ATROPELAMENTO",
    },
    {
        "id": 16,
        "date": "2023-09-10",
        "cluster_id": 4,
        "accident_type": "ATROPELAMENTO",
    },

    # Cluster 5
    {
        "id": 17,
        "date": "2025-01-10",
        "cluster_id": 5,
        "accident_type": "CHOQUE",
    },
]


df = pd.DataFrame(data)

df["date"] = pd.to_datetime(df["date"])


# ============================================================
# PERÍODOS
# ============================================================

start_1y = pd.Timestamp("2025-01-01")
end_1y = pd.Timestamp("2025-12-31")

start_3y = pd.Timestamp("2023-01-01")
end_3y = pd.Timestamp("2025-12-31")


# ============================================================
# TESTE 1 — count_accidents
# ============================================================

print("=== TESTE count_accidents ===")

result = count_accidents(
    df,
    start_1y,
    end_1y,
)

print(result)


# ============================================================
# TESTE 2 — count_cluster_accidents
# ============================================================

print()
print("=== TESTE count_cluster_accidents ===")

result_cluster = count_cluster_accidents(
    df,
    start_1y,
    end_1y,
)

print(result_cluster)


# ============================================================
# TESTE 3 — evaluate_criteria
# ============================================================

print()
print("=== TESTE evaluate_criteria ===")

one_year = count_cluster_accidents(
    df,
    start_1y,
    end_1y,
)

three_years = count_cluster_accidents(
    df,
    start_3y,
    end_3y,
)

evaluation = evaluate_criteria(
    one_year,
    three_years,
)

print(evaluation)


# ============================================================
# TESTES DE CONSISTÊNCIA
# ============================================================

print()
print("=== TESTES DE CONSISTÊNCIA ===")


# ------------------------------------------------------------
# Cluster 1
# 3 colisões em 1 ano
# ------------------------------------------------------------

cluster_1 = evaluation[
    evaluation["cluster_id"] == 1
].iloc[0]

assert cluster_1["collisions_1y"] == 3
assert cluster_1["collision_criterion"]
assert cluster_1["eligible"]

print(
    "Cluster 1: critério de 3 colisões em 1 ano funcionando."
)


# ------------------------------------------------------------
# Cluster 2
# 2 atropelamentos em 1 ano
# ------------------------------------------------------------

cluster_2 = evaluation[
    evaluation["cluster_id"] == 2
].iloc[0]

assert cluster_2["pedestrians_1y"] == 2
assert cluster_2["pedestrian_criterion"]
assert cluster_2["eligible"]

print(
    "Cluster 2: critério de 2 atropelamentos em 1 ano funcionando."
)


# ------------------------------------------------------------
# Cluster 3
# 7 colisões em 3 anos
# ------------------------------------------------------------

cluster_3 = evaluation[
    evaluation["cluster_id"] == 3
].iloc[0]

assert cluster_3["collisions_3y"] == 7
assert cluster_3["collision_criterion"]
assert cluster_3["eligible"]

print(
    "Cluster 3: critério de 7 colisões em 3 anos funcionando."
)


# ------------------------------------------------------------
# Cluster 4
# 4 atropelamentos em 3 anos
# ------------------------------------------------------------

cluster_4 = evaluation[
    evaluation["cluster_id"] == 4
].iloc[0]

assert cluster_4["pedestrians_3y"] == 4
assert cluster_4["pedestrian_criterion"]
assert cluster_4["eligible"]

print(
    "Cluster 4: critério de 4 atropelamentos em 3 anos funcionando."
)


# ------------------------------------------------------------
# Cluster 5
# Apenas CHOQUE
# ------------------------------------------------------------

cluster_5 = evaluation[
    evaluation["cluster_id"] == 5
].iloc[0]

assert cluster_5["collisions_1y"] == 0
assert cluster_5["pedestrians_1y"] == 0

assert not cluster_5["collision_criterion"]
assert not cluster_5["pedestrian_criterion"]
assert not cluster_5["eligible"]

print(
    "Cluster 5: exclusão de ocorrências não relacionadas funcionando."
)


print()
print("Todos os testes passaram.")