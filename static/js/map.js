const map = L.map("map").setView(
    [-21.1775, -47.8103],
    12
);


L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
        attribution:
            '&copy; OpenStreetMap contributors',
            referrerPolicy: 'origin'
    }
).addTo(map);


const mapData = JSON.parse(
    document.getElementById("map-data").textContent
);


mapData.forEach(point => {

    const marker = L.marker([
        point.latitude,
        point.longitude
    ]).addTo(map);

    marker.bindPopup(`
        <strong>
            ${point.location}
        </strong>

        <br><br>

        <strong>Cluster:</strong>
        ${point.cluster_id}

        <br>

        <strong>Critério:</strong>
        ${point.criterion}

        <br><br>

        <strong>Colisões — 1 ano:</strong>
        ${point.collisions_1y}

        <br>

        <strong>Atropelamentos — 1 ano:</strong>
        ${point.pedestrians_1y}

        <br><br>

        <strong>Colisões — 3 anos:</strong>
        ${point.collisions_3y}

        <br>

        <strong>Atropelamentos — 3 anos:</strong>
        ${point.pedestrians_3y}
    `);

});