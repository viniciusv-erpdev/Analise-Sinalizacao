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
const markersLayer = L.layerGroup().addTo(map);
const filterInputs = Array.from(
    document.querySelectorAll("[data-filter-field]")
);
const filterCounter = document.getElementById("filter-counter");
const clearFiltersButton = document.getElementById(
    "clear-filters-button"
);
const filterPanel = document.getElementById("filter-panel");
const minimizeFilterPanel = document.getElementById(
    "minimize-filter-panel"
);
const openFilterPanel = document.getElementById("open-filter-panel");


const markerRecords = mapData.map(point => {

    const marker = L.marker([
        point.latitude,
        point.longitude
    ]);

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

    return {point, marker};
});


function getActiveFilters() {
    return filterInputs.filter((input) => input.checked);
}


function pointMatchesFilters(point, activeFilters) {
    if (activeFilters.length === 0) {
        return true;
    }

    // Filtros simultâneos usam OR: basta uma condição selecionada.
    return activeFilters.some((input) => (
        point[input.dataset.filterField] === true
    ));
}


function applyMapFilters() {
    const activeFilters = getActiveFilters();
    let visibleCount = 0;

    markersLayer.clearLayers();

    markerRecords.forEach(({point, marker}) => {
        if (pointMatchesFilters(point, activeFilters)) {
            markersLayer.addLayer(marker);
            visibleCount += 1;
        }
    });

    filterCounter.textContent = (
        `${visibleCount} de ${markerRecords.length} locais exibidos`
    );
}


function clearMapFilters() {
    filterInputs.forEach((input) => {
        input.checked = false;
    });
    applyMapFilters();
}


function setFilterPanelExpanded(expanded) {
    filterPanel.hidden = !expanded;
    openFilterPanel.hidden = expanded;
    minimizeFilterPanel.setAttribute("aria-expanded", String(expanded));
    openFilterPanel.setAttribute("aria-expanded", String(expanded));
}


filterInputs.forEach((input) => {
    input.disabled = markerRecords.length === 0;
    input.addEventListener("change", applyMapFilters);
});
clearFiltersButton.disabled = markerRecords.length === 0;
clearFiltersButton.addEventListener("click", clearMapFilters);
minimizeFilterPanel.addEventListener("click", () => {
    setFilterPanelExpanded(false);
});
openFilterPanel.addEventListener("click", () => {
    setFilterPanelExpanded(true);
});

applyMapFilters();
