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
const viewMode = JSON.parse(
    document.getElementById("view-mode").textContent
);
const hasActiveAnalysis = (
    document.getElementById("map").dataset.hasActiveAnalysis === "true"
);
const individualRenderer = viewMode === "individual"
    ? L.canvas({padding: 0.5})
    : null;
const documentStyles = getComputedStyle(document.documentElement);
const individualCategoryColors = {
    pedestrian: documentStyles.getPropertyValue("--marker-pedestrian").trim(),
    crash: documentStyles.getPropertyValue("--marker-individual-crash").trim(),
    collision: documentStyles.getPropertyValue("--marker-individual-collision").trim(),
    unavailable: documentStyles.getPropertyValue("--marker-individual-unavailable").trim(),
    other: documentStyles.getPropertyValue("--marker-individual-other").trim(),
};
const markersLayer = L.layerGroup().addTo(map);
const filterInputs = Array.from(
    document.querySelectorAll(
        "[data-filter-field], [data-individual-category]"
    )
);
const filterCounter = document.getElementById("filter-counter");
const clearFiltersButton = document.getElementById(
    "clear-filters-button"
);
const activeFilterCategories = document.getElementById(
    "active-filter-categories"
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


function createIndividualMarker(coordinates, category) {
    return L.circleMarker(coordinates, {
        renderer: individualRenderer,
        radius: 7,
        color: "#ffffff",
        weight: 2,
        opacity: 1,
        fillColor: individualCategoryColors[category]
            || individualCategoryColors.other,
        fillOpacity: 0.9,
        bubblingMouseEvents: false,
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


function appendDetail(list, label, value) {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value;
    list.append(term, description);
}


function buildIndividualMarkerPopup(point) {
    const article = document.createElement("article");
    article.className = "map-popup";

    const title = document.createElement("h2");
    title.className = "map-popup__title";
    title.textContent = "Sinistro";

    const category = document.createElement("span");
    category.className = (
        `map-popup__category map-popup__category--individual-${point.category}`
    );
    category.textContent = point.accident_type;

    const details = document.createElement("dl");
    details.className = "map-popup__details";
    appendDetail(details, "Data", point.date);
    appendDetail(details, "Tipo", point.accident_type);
    appendDetail(details, "Gravidade", point.record_type);
    appendDetail(details, "Local", point.street);

    const modesSection = document.createElement("section");
    modesSection.className = "map-popup__section";
    const modesTitle = document.createElement("h3");
    modesTitle.className = "map-popup__section-title";
    modesTitle.textContent = "Modais envolvidos";
    modesSection.append(modesTitle);

    if (point.modes.length === 0) {
        const empty = document.createElement("p");
        empty.className = "small text-secondary mb-0";
        empty.textContent = "Não disponível";
        modesSection.append(empty);
    } else {
        const table = document.createElement("table");
        table.className = "map-popup__modes";
        const body = document.createElement("tbody");
        point.modes.forEach((mode) => {
            const row = document.createElement("tr");
            const name = document.createElement("td");
            const quantity = document.createElement("td");
            name.textContent = mode.name;
            quantity.textContent = String(mode.quantity);
            row.append(name, quantity);
            body.append(row);
        });
        table.append(body);
        modesSection.append(table);
    }

    article.append(title, category, details, modesSection);
    return article;
}


const markerRecords = mapData.map(point => {
    const category = viewMode === "individual"
        ? point.category
        : getMarkerCategory(point);

    const coordinates = [
        point.latitude,
        point.longitude
    ];
    const marker = viewMode === "individual"
        ? createIndividualMarker(coordinates, category)
        : L.marker(coordinates, {icon: createMarkerIcon(category)});

    if (viewMode === "individual") {
        let popupContent = null;
        marker.bindPopup(
            () => {
                if (!popupContent) {
                    popupContent = buildIndividualMarkerPopup(point);
                }
                return popupContent;
            },
            {maxWidth: 320}
        );
    } else {
        marker.bindPopup(
            buildMarkerPopup(point, category),
            {maxWidth: 320}
        );
    }

    return {point, marker};
});


function getActiveFilters() {
    return filterInputs.filter((input) => input.checked);
}


function pointMatchesFilters(point, activeFilters) {
    if (viewMode === "individual") {
        return activeFilters.length === 0 || activeFilters.some(
            (input) => point.category === input.dataset.individualCategory
        );
    }
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

    if (viewMode !== "individual") {
        markersLayer.clearLayers();
    }

    markerRecords.forEach(({point, marker}) => {
        const shouldBeVisible = pointMatchesFilters(point, activeFilters);
        if (viewMode === "individual") {
            const isVisible = markersLayer.hasLayer(marker);

            if (shouldBeVisible && !isVisible) {
                markersLayer.addLayer(marker);
            } else if (!shouldBeVisible && isVisible) {
                markersLayer.removeLayer(marker);
            }
        } else if (shouldBeVisible) {
            markersLayer.addLayer(marker);
        }

        if (shouldBeVisible) {
            visibleCount += 1;
        }
    });

    filterCounter.textContent = viewMode === "individual"
        ? `${visibleCount} de ${markerRecords.length} sinistros exibidos`
        : `${visibleCount} de ${markerRecords.length} locais exibidos`;

    if (viewMode === "individual" && activeFilterCategories) {
        activeFilterCategories.textContent = activeFilters.length === 0
            ? "Todas as categorias"
            : activeFilters
                .map((input) => input.dataset.filterLabel)
                .join(" · ");
    }
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

        container.innerHTML = viewMode === "individual" ? `
            <strong>Sinistros</strong>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--individual-pedestrian"></span>Atropelamento</div>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--individual-crash"></span>Choque</div>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--individual-collision"></span>Colisão</div>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--individual-unavailable"></span>Não disponível</div>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--individual-other"></span>Outros</div>
        ` : `
            <strong>Legenda</strong>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--collision"></span>Colisões</div>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--pedestrian"></span>Atropelamentos</div>
            <div class="map-legend__item"><span class="map-legend__dot map-legend__dot--both"></span>Ambos</div>
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

if (hasActiveAnalysis) {
    createMapLegend();
}
applyMapFilters();
