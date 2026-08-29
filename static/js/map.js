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


const markerCategories = {
    collision: "Colisões",
    pedestrian: "Atropelamentos",
    both: "Colisões + Atropelamentos",
};


function getMarkerCategory(point) {
    if (point.collision_criterion && point.pedestrian_criterion) {
        return "both";
    }

    if (point.pedestrian_criterion) {
        return "pedestrian";
    }

    return "collision";
}


function createMarkerIcon(category) {
    return L.divIcon({
        className: `map-marker map-marker--${category}`,
        html: '<span class="map-marker__dot" aria-hidden="true"></span>',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -10],
    });
}


function escapeHtml(value) {
    const characters = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    };

    return String(value).replace(
        /[&<>"']/g,
        (character) => characters[character]
    );
}


function buildCriteriaGroup(title, criteria) {
    if (criteria.length === 0) {
        return "";
    }

    const items = criteria
        .map((criterion) => `<li>${criterion}</li>`)
        .join("");

    return `
        <h4 class="map-popup__criteria-title">${title}</h4>
        <ul class="map-popup__criteria">${items}</ul>
    `;
}


function buildCriteriaList(point) {
    const collisionCriteria = [];
    const pedestrianCriteria = [];

    if (point.collision_1y_met) {
        collisionCriteria.push("3+ em 1 ano");
    }
    if (point.collision_3y_met) {
        collisionCriteria.push("7+ em 3 anos");
    }
    if (point.pedestrian_1y_met) {
        pedestrianCriteria.push("2+ em 1 ano");
    }
    if (point.pedestrian_3y_met) {
        pedestrianCriteria.push("4+ em 3 anos");
    }

    return `
        <div class="map-popup__section">
            <h3 class="map-popup__section-title">Critérios atendidos</h3>
            ${buildCriteriaGroup("Colisões", collisionCriteria)}
            ${buildCriteriaGroup("Atropelamentos", pedestrianCriteria)}
        </div>
    `;
}


function buildMarkerPopup(point, category) {
    return `
        <article class="map-popup">
            <h2 class="map-popup__title">${escapeHtml(point.location)}</h2>
            <span class="map-popup__category map-popup__category--${category}">
                ${markerCategories[category]}
            </span>

            ${buildCriteriaList(point)}

            <div class="map-popup__section">
                <h3 class="map-popup__section-title">Ocorrências</h3>
                <table class="map-popup__stats">
                    <thead>
                        <tr>
                            <th>Período</th>
                            <th>Colisões</th>
                            <th>Atropelamentos</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>1 ano</td>
                            <td>${point.collisions_1y}</td>
                            <td>${point.pedestrians_1y}</td>
                        </tr>
                        <tr>
                            <td>3 anos</td>
                            <td>${point.collisions_3y}</td>
                            <td>${point.pedestrians_3y}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </article>
    `;
}


const markerRecords = mapData.map(point => {
    const category = getMarkerCategory(point);

    const marker = L.marker([
        point.latitude,
        point.longitude
    ], {
        icon: createMarkerIcon(category),
    });

    marker.bindPopup(
        buildMarkerPopup(point, category),
        {maxWidth: 320}
    );

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


function createMapLegend() {
    const legend = L.control({position: "bottomleft"});

    legend.onAdd = () => {
        const container = L.DomUtil.create("div", "map-legend");

        container.innerHTML = `
            <strong>Legenda</strong>
            <div class="map-legend__item">
                <span class="map-legend__dot map-legend__dot--collision"></span>
                Colisões
            </div>
            <div class="map-legend__item">
                <span class="map-legend__dot map-legend__dot--pedestrian"></span>
                Atropelamentos
            </div>
            <div class="map-legend__item">
                <span class="map-legend__dot map-legend__dot--both"></span>
                Ambos
            </div>
        `;

        L.DomEvent.disableClickPropagation(container);
        return container;
    };

    legend.addTo(map);
}


filterInputs.forEach((input) => {
    input.disabled = markerRecords.length === 0;
    input.addEventListener("change", applyMapFilters);
});
clearFiltersButton.disabled = markerRecords.length === 0;
clearFiltersButton.addEventListener("click", clearMapFilters);

createMapLegend();
applyMapFilters();
