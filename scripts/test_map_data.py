import pandas as pd

from analysis.map_data import build_map_data


def main():

    data = pd.DataFrame(
        [
            {
                "cluster_id": 1,
                "latitude": -21.20,
                "longitude": -47.80,
                "location": "AVENIDA A × RUA B",
                "location_type": "INTERSECTION",
                "collisions_1y": 3,
                "pedestrians_1y": 0,
                "collisions_3y": 4,
                "pedestrians_3y": 0,
                "collision_criterion": True,
                "pedestrian_criterion": False,
                "eligible": True,
            },
            {
                "cluster_id": 2,
                "latitude": -21.21,
                "longitude": -47.81,
                "location": "RUA C",
                "location_type": "STREET",
                "collisions_1y": 0,
                "pedestrians_1y": 2,
                "collisions_3y": 0,
                "pedestrians_3y": 2,
                "collision_criterion": False,
                "pedestrian_criterion": True,
                "eligible": True,
            },
            {
                "cluster_id": 3,
                "latitude": -21.22,
                "longitude": -47.82,
                "location": "RUA D",
                "location_type": "STREET",
                "collisions_1y": 1,
                "pedestrians_1y": 0,
                "collisions_3y": 2,
                "pedestrians_3y": 0,
                "collision_criterion": False,
                "pedestrian_criterion": False,
                "eligible": False,
            },
        ]
    )

    print("=== TESTE build_map_data ===")

    result = build_map_data(data)

    for item in result:
        print(item)

    print()
    print("=== TESTES DE CONSISTÊNCIA ===")

    assert len(result) == 2

    print("Somente clusters elegíveis foram mantidos.")

    assert result[0]["cluster_id"] == 1

    print("Cluster 1 preservado.")

    assert result[0]["latitude"] == -21.20
    assert result[0]["longitude"] == -47.80

    print("Coordenadas preservadas.")

    assert result[0]["collision_criterion"] is True
    assert result[0]["pedestrian_criterion"] is False

    print("Critérios preservados.")

    assert isinstance(result[0]["cluster_id"], int)
    assert isinstance(result[0]["latitude"], float)

    print("Tipos convertidos corretamente.")

    print()
    print("Todos os testes passaram.")


if __name__ == "__main__":
    main()