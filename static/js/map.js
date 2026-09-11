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
const individualMixedGroupColor = "#6c757d";
const markersLayer = L.layerGroup().addTo(map);
let individualCounterLayer = null;
if (viewMode === "individual") {
    map.createPane("individualCounterPane");
    map.getPane("individualCounterPane").style.zIndex = "450";
    individualCounterLayer = L.layerGroup().addTo(map);
}
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


function groupIndividualAccidentsByCoordinate(accidents) {
    const groups = new Map();

    accidents.forEach((accident) => {
        const coordinateKey = `${accident.latitude},${accident.longitude}`;
        let group = groups.get(coordinateKey);
        if (!group) {
            group = {
                latitude: accident.latitude,
                longitude: accident.longitude,
                accidents: [],
            };
            groups.set(coordinateKey, group);
        }
        group.accidents.push(accident);
    });

    return Array.from(groups.values());
}


function getVisibleGroupColor(accidents) {
    const categories = new Set(accidents.map((accident) => accident.category));
    if (categories.size !== 1) {
        return individualMixedGroupColor;
    }
    const category = categories.values().next().value;
    return individualCategoryColors[category] || individualCategoryColors.other;
}


function createIndividualCounterIcon(count) {
    return L.divIcon({
        className: "individual-marker-counter",
        html: `<span class="individual-marker-counter__badge">${count}</span>`,
        iconSize: [26, 20],
        iconAnchor: [2, 24],
    });
}


function buildIndividualGroupPopup(record) {
    const accidents = record.visibleAccidents;
    const activeIndex = Math.min(record.popupIndex, accidents.length - 1);
    record.popupIndex = Math.max(0, activeIndex);
    const popupContent = buildIndividualMarkerPopup(accidents[record.popupIndex]);

    if (accidents.length === 1) {
        return popupContent;
    }

    const navigation = document.createElement("div");
    navigation.className = "map-popup__navigation";
    const position = document.createElement("span");
    position.textContent = `${record.popupIndex + 1} / ${accidents.length}`;

    const controls = document.createElement("div");
    controls.className = "map-popup__navigation-controls";
    [
        {label: "Sinistro anterior", direction: -1, text: "◀"},
        {label: "Próximo sinistro", direction: 1, text: "▶"},
    ].forEach((control) => {
        const button = document.createElement("button");
        button.className = "btn btn-outline-secondary btn-sm";
        button.type = "button";
        button.textContent = control.text;
        button.title = control.label;
        button.setAttribute("aria-label", control.label);
        button.addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            record.popupIndex = (
                record.popupIndex + control.direction + accidents.length
            ) % accidents.length;
            record.marker.setPopupContent(buildIndividualGroupPopup(record));
        });
        controls.append(button);
    });

    navigation.append(position, controls);
    popupContent.append(navigation);
    L.DomEvent.disableClickPropagation(popupContent);
    return popupContent;
}


function createClusterMarkerRecord(point) {
    const category = getMarkerCategory(point);

    const coordinates = [
        point.latitude,
        point.longitude
    ];
    const marker = L.marker(coordinates, {icon: createMarkerIcon(category)});
    marker.bindPopup(buildMarkerPopup(point, category), {maxWidth: 320});

    return {point, marker};
}


function createIndividualMarkerRecord(group) {
    const coordinates = [group.latitude, group.longitude];
    const marker = createIndividualMarker(
        coordinates,
        group.accidents[0].category
    );
    const record = {
        marker,
        accidents: group.accidents,
        visibleAccidents: group.accidents,
        counterMarker: null,
        popupIndex: 0,
        coordinates,
    };
    marker.bindPopup(() => buildIndividualGroupPopup(record), {maxWidth: 320});
    return record;
}


const markerRecords = viewMode === "individual"
    ? groupIndividualAccidentsByCoordinate(mapData).map(createIndividualMarkerRecord)
    : mapData.map(createClusterMarkerRecord);


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


function updateIndividualCounter(record) {
    const visibleCount = record.visibleAccidents.length;
    if (visibleCount < 2) {
        if (
            record.counterMarker
            && individualCounterLayer.hasLayer(record.counterMarker)
        ) {
            individualCounterLayer.removeLayer(record.counterMarker);
        }
        return;
    }

    if (!record.counterMarker) {
        record.counterMarker = L.marker(record.coordinates, {
            icon: createIndividualCounterIcon(visibleCount),
            interactive: false,
            keyboard: false,
            pane: "individualCounterPane",
        });
    } else {
        record.counterMarker.setIcon(
            createIndividualCounterIcon(visibleCount)
        );
    }

    if (!individualCounterLayer.hasLayer(record.counterMarker)) {
        individualCounterLayer.addLayer(record.counterMarker);
    }
}


function applyMapFilters() {
    const activeFilters = getActiveFilters();
    let visibleCount = 0;

    if (viewMode === "individual") {
        markerRecords.forEach((record) => {
            if (record.marker.isPopupOpen()) {
                record.marker.closePopup();
            }

            record.visibleAccidents = record.accidents.filter((accident) => (
                pointMatchesFilters(accident, activeFilters)
            ));
            record.popupIndex = 0;
            const shouldBeVisible = record.visibleAccidents.length > 0;
            const isVisible = markersLayer.hasLayer(record.marker);

            if (shouldBeVisible && !isVisible) {
                markersLayer.addLayer(record.marker);
            } else if (!shouldBeVisible && isVisible) {
                markersLayer.removeLayer(record.marker);
            }

            if (shouldBeVisible) {
                record.marker.setStyle({
                    fillColor: getVisibleGroupColor(record.visibleAccidents),
                });
            }
            updateIndividualCounter(record);
            visibleCount += record.visibleAccidents.length;
        });
    } else {
        markersLayer.clearLayers();
        markerRecords.forEach(({point, marker}) => {
            const shouldBeVisible = pointMatchesFilters(point, activeFilters);
            if (shouldBeVisible) {
                markersLayer.addLayer(marker);
                visibleCount += 1;
            }
        });
    }

    filterCounter.textContent = viewMode === "individual"
        ? `${visibleCount} de ${mapData.length} sinistros exibidos`
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
