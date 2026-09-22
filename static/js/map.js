const mapElement = document.getElementById("map");
const map = L.map(mapElement).setView(
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
const availablePeriods = JSON.parse(
    document.getElementById("available-periods").textContent
);
const analysisId = JSON.parse(
    document.getElementById("analysis-id").textContent
);
const hasActiveAnalysis = (
    mapElement.dataset.hasActiveAnalysis === "true"
);
const individualPopupArrowIcons = {
    previous: mapElement.dataset.leftArrowIconUrl,
    next: mapElement.dataset.rightArrowIconUrl,
};
const DEBUG_INDIVIDUAL_POPUPS = (
    window.localStorage.getItem("debugIndividualPopups") === "1"
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
const individualFatalHaloColor = "#dc2626";
let individualHaloLayer = null;
if (viewMode === "individual") {
    individualHaloLayer = L.layerGroup().addTo(map);
}
const markersLayer = L.layerGroup().addTo(map);
let individualCounterLayer = null;
if (viewMode === "individual") {
    map.createPane("individualCounterPane");
    map.getPane("individualCounterPane").style.zIndex = "450";
    individualCounterLayer = L.layerGroup().addTo(map);
}
const filterInputs = Array.from(
    document.querySelectorAll(
        "[data-filter-field], [data-individual-category], [data-individual-gravity]"
    )
);
const individualCategoryFilterInputs = Array.from(
    document.querySelectorAll("[data-individual-category]")
);
const individualGravityFilterInputs = Array.from(
    document.querySelectorAll("[data-individual-gravity]")
);
const clusterFilterInputs = Array.from(
    document.querySelectorAll("[data-filter-field]")
);
const filterCounter = document.getElementById("filter-counter");
const clearFiltersButton = document.getElementById(
    "clear-filters-button"
);
const activeFilterCategories = document.getElementById(
    "active-filter-categories"
);
const periodYearFilter = document.getElementById("period-year-filter");
const periodMonthFilter = document.getElementById("period-month-filter");
const periodYearInputs = Array.from(
    document.querySelectorAll("[data-period-year]")
);
const allYearsInput = document.querySelector("[data-period-all-years]");
const monthLabels = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];


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


function createIndividualFatalHalo(coordinates) {
    return L.circleMarker(coordinates, {
        renderer: individualRenderer,
        radius: 13,
        color: individualFatalHaloColor,
        weight: 1,
        opacity: 0.8,
        fillColor: individualFatalHaloColor,
        fillOpacity: 0.24,
        interactive: false,
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


function buildMarkerPopup(point, category, periodState = null) {
    const hasPeriodFilter = periodState && (
        periodState.years.length > 0 || periodState.months.length > 0
    );
    const periodSection = hasPeriodFilter ? `
        <div class="map-popup__section">
            <h3 class="map-popup__section-title">Ocorrências no período</h3>
            <p class="mb-0">
                <strong>${periodState.visibleCount}</strong>
                ${periodState.label}
            </p>
        </div>
    ` : "";
    return `
        <article class="map-popup">
            <h2 class="map-popup__title">${escapeHtml(point.location)}</h2>
            <span class="map-popup__category map-popup__category--${category}">
                ${markerCategories[category]}
            </span>

            ${buildCriteriaList(point)}

            ${periodSection}

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
    return IndividualAccidentFilters.groupByExactCoordinate(accidents);
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


function getIndividualPopupDebugState(record, phase, extra = {}) {
    const popup = record.marker.getPopup();
    const popupElement = popup && popup.getElement();
    const navigation = popupElement && popupElement.querySelector(
        ".map-popup__navigation"
    );
    const navigationStyle = navigation
        ? window.getComputedStyle(navigation)
        : null;
    const counterElement = record.counterMarker
        ? record.counterMarker.getElement()
        : null;
    return {
        phase,
        coordinateKey: record.coordinateKey,
        coordinates: record.coordinates,
        originalIds: record.accidents.map((accident) => accident.id),
        originalCount: record.accidents.length,
        visibleIds: record.visibleAccidents.map((accident) => accident.id),
        visibleAccidentsLength: record.visibleAccidents.length,
        visibleCount: record.visibleAccidents.length,
        counterText: counterElement ? counterElement.textContent.trim() : null,
        counterIsOnMap: Boolean(
            record.counterMarker
            && individualCounterLayer.hasLayer(record.counterMarker)
        ),
        popupReceivedCount: record.visibleAccidents.length,
        shouldCreateNavigation: record.visibleAccidents.length > 1,
        navigationControlsGenerated: navigation
            ? navigation.querySelectorAll("button").length
            : 0,
        navigationInDom: Boolean(navigation && navigation.isConnected),
        navigationVisible: Boolean(
            navigation
            && navigation.isConnected
            && navigationStyle.display !== "none"
            && navigationStyle.visibility !== "hidden"
            && navigation.getClientRects().length > 0
        ),
        activeIndex: record.popupIndex,
        activeCategories: getActiveFilters().map(
            (input) => input.dataset.individualCategory
        ),
        activeGravity: getActiveGravityFilter(),
        ...extra,
    };
}


function logIndividualPopupDebug(record, phase, extra = {}) {
    if (!DEBUG_INDIVIDUAL_POPUPS || !record.debugClicked) {
        return;
    }
    console.info(
        "[IndividualPopupDebug]",
        JSON.stringify(
            getIndividualPopupDebugState(record, phase, extra),
            null,
            2
        )
    );
}


function buildIndividualGroupPopup(record) {
    const accidents = record.visibleAccidents;
    record.popupIndex = IndividualAccidentFilters.normalizePopupIndex(
        record.popupIndex,
        accidents.length
    );
    const popupContent = buildIndividualMarkerPopup(accidents[record.popupIndex]);

    if (accidents.length === 1) {
        logIndividualPopupDebug(record, "popup-built", {
            navigationControlsCreated: 0,
        });
        return popupContent;
    }

    const navigation = document.createElement("div");
    navigation.className = "map-popup__navigation";
    const position = document.createElement("span");
    position.textContent = `${record.popupIndex + 1} / ${accidents.length}`;

    const controls = document.createElement("div");
    controls.className = "map-popup__navigation-controls";
    [
        {
            label: "Sinistro anterior",
            direction: -1,
            iconUrl: individualPopupArrowIcons.previous,
        },
        {
            label: "Próximo sinistro",
            direction: 1,
            iconUrl: individualPopupArrowIcons.next,
        },
    ].forEach((control) => {
        const button = document.createElement("button");
        const icon = document.createElement("span");
        button.className = "map-popup__navigation-button";
        button.type = "button";
        button.title = control.label;
        button.setAttribute("aria-label", control.label);
        icon.className = "map-popup__navigation-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.style.setProperty(
            "--navigation-icon",
            `url("${control.iconUrl}")`
        );
        button.append(icon);
        button.addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            record.popupIndex = IndividualAccidentFilters.movePopupIndex(
                record.popupIndex,
                accidents.length,
                control.direction
            );
            IndividualAccidentFilters.replaceOpenPopupContent(
                record.marker.getPopup(),
                buildIndividualGroupPopup(record)
            );
        });
        controls.append(button);
    });

    navigation.append(position, controls);
    popupContent.append(navigation);
    record.debugNavigationElement = navigation;
    L.DomEvent.disableClickPropagation(popupContent);
    logIndividualPopupDebug(record, "popup-built", {
        navigationControlsCreated: controls.children.length,
    });
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
        haloMarker: IndividualAccidentFilters.hasFatalAccident(group.accidents)
            ? createIndividualFatalHalo(coordinates)
            : null,
        accidents: group.accidents,
        visibleAccidents: group.accidents,
        counterMarker: null,
        popupIndex: 0,
        coordinates,
        coordinateKey: `${group.latitude},${group.longitude}`,
        debugClicked: false,
    };
    if (DEBUG_INDIVIDUAL_POPUPS) {
        marker.on("click", () => {
            record.debugClicked = true;
            logIndividualPopupDebug(record, "marker-clicked");
        });
    }
    marker.bindPopup(() => buildIndividualGroupPopup(record), {maxWidth: 320});
    if (DEBUG_INDIVIDUAL_POPUPS) {
        marker.on("popupopen", () => {
            window.setTimeout(() => {
                logIndividualPopupDebug(record, "popup-opened");
            }, 0);
        });
        marker.on("popupclose", () => {
            logIndividualPopupDebug(record, "popup-closed", {
                previousNavigationStillInDom: Boolean(
                    record.debugNavigationElement
                    && record.debugNavigationElement.isConnected
                ),
            });
            record.debugClicked = false;
            record.debugNavigationElement = null;
        });
    }
    return record;
}


const markerRecords = viewMode === "individual"
    ? groupIndividualAccidentsByCoordinate(mapData).map(createIndividualMarkerRecord)
    : mapData.map(createClusterMarkerRecord);


function getActiveFilters() {
    const relevantInputs = viewMode === "individual"
        ? individualCategoryFilterInputs
        : clusterFilterInputs;
    return relevantInputs.filter((input) => input.checked);
}


function getActiveGravityFilter() {
    const selected = individualGravityFilterInputs.find((input) => input.checked);
    return selected ? selected.value : "all";
}


function getActivePeriod() {
    return {
        years: periodYearInputs
            .filter((input) => input.checked)
            .map((input) => Number(input.value)),
        months: Array.from(
            document.querySelectorAll("[data-period-month]:checked")
        ).map((input) => Number(input.value)),
    };
}


function getIndividualReportFilterQuery() {
    const {years, months} = getActivePeriod();
    return IndividualAccidentFilters.buildReportFilterQuery({
        analysisId,
        years,
        months,
        categories: getActiveFilters().map(
            (input) => input.dataset.individualCategory
        ),
        gravity: getActiveGravityFilter(),
    });
}


window.getIndividualReportFilterQuery = getIndividualReportFilterQuery;


function updatePeriodSummary(container, values, allLabel, itemLabel) {
    if (!container) {
        return;
    }
    const summary = container.querySelector("[data-period-summary]");
    summary.textContent = values.length === 0
        ? allLabel
        : itemLabel(values);
}


function updateMonthOptions() {
    if (!periodMonthFilter) {
        return;
    }
    const monthOptions = periodMonthFilter.querySelector(
        "[data-period-month-options]"
    );
    const selectedMonths = new Set(getActivePeriod().months);
    const availableMonths = IndividualAccidentFilters.monthsForYears(
        availablePeriods,
        getActivePeriod().years
    );
    monthOptions.replaceChildren();
    const allLabel = document.createElement("label");
    const allInput = document.createElement("input");
    const allText = document.createElement("span");
    allInput.type = "checkbox";
    allInput.dataset.periodAllMonths = "";
    allInput.checked = !availableMonths.some((month) => selectedMonths.has(month));
    allText.textContent = "Todos os meses disponíveis";
    allLabel.append(allInput, allText);
    monthOptions.append(allLabel);
    availableMonths.forEach((month) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        const text = document.createElement("span");
        input.type = "checkbox";
        input.value = String(month);
        input.dataset.periodMonth = "";
        input.checked = selectedMonths.has(month);
        text.textContent = monthLabels[month - 1];
        label.append(input, text);
        monthOptions.append(label);
    });
    updatePeriodSummaries();
}


function updatePeriodSummaries() {
    const {years, months} = getActivePeriod();
    updatePeriodSummary(
        periodYearFilter,
        years,
        "Todos os anos",
        (values) => values.length <= 3
            ? values.join(", ")
            : `${values.length} anos selecionados`
    );
    updatePeriodSummary(
        periodMonthFilter,
        months,
        "Todos os meses disponíveis",
        (values) => values.length <= 4
            ? values.map((month) => monthLabels[month - 1].slice(0, 3)).join(", ")
            : `${values.length} meses selecionados`
    );
}


function countClusterAccidentsInPeriod(point, years, months) {
    const summary = point.period_summary || {total_count: 0, counts: []};
    return IndividualAccidentFilters.countPeriodSummary(summary, years, months);
}


function describeActivePeriod(years, months) {
    if (years.length === 0 && months.length === 0) {
        return "";
    }
    return "sinistros no período selecionado";
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
            interactive: true,
            keyboard: false,
            pane: "individualCounterPane",
            bubblingMouseEvents: false,
        });
        record.counterMarker.on("click", (event) => {
            if (DEBUG_INDIVIDUAL_POPUPS) {
                record.debugClicked = true;
                logIndividualPopupDebug(record, "counter-clicked");
            }
            IndividualAccidentFilters.openGroupPopupFromCounter(
                record.marker,
                event.originalEvent || event,
                L.DomEvent.stopPropagation
            );
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
    const activeCategories = activeFilters.map(
        (input) => input.dataset.individualCategory
    );
    const activeGravity = getActiveGravityFilter();
    const activePeriod = getActivePeriod();
    let visibleCount = 0;

    if (viewMode === "individual") {
        markerRecords.forEach((record) => {
            if (record.marker.isPopupOpen()) {
                record.marker.closePopup();
            }

            const groupState = IndividualAccidentFilters.buildVisibleGroupState(
                record.accidents,
                activeCategories,
                activeGravity,
                0,
                activePeriod.years,
                activePeriod.months
            );
            record.visibleAccidents = groupState.visibleAccidents;
            record.popupIndex = groupState.popupIndex;
            const shouldBeVisible = groupState.visibleCount > 0;
            const isVisible = markersLayer.hasLayer(record.marker);
            const shouldShowHalo = (
                shouldBeVisible
                && record.haloMarker
                && groupState.hasFatal
            );

            if (record.haloMarker) {
                const haloIsVisible = individualHaloLayer.hasLayer(
                    record.haloMarker
                );
                if (shouldShowHalo && !haloIsVisible) {
                    individualHaloLayer.addLayer(record.haloMarker);
                    record.haloMarker.bringToBack();
                } else if (!shouldShowHalo && haloIsVisible) {
                    individualHaloLayer.removeLayer(record.haloMarker);
                }
            }

            if (shouldBeVisible && !isVisible) {
                markersLayer.addLayer(record.marker);
            } else if (!shouldBeVisible && isVisible) {
                markersLayer.removeLayer(record.marker);
            }

            if (shouldBeVisible) {
                record.marker.setStyle({
                    fillColor: getVisibleGroupColor(record.visibleAccidents),
                });
                record.marker.bringToFront();
            }
            updateIndividualCounter(record);
            visibleCount += groupState.visibleCount;
        });
    } else {
        markersLayer.clearLayers();
        markerRecords.forEach(({point, marker}) => {
            const visiblePeriodCount = countClusterAccidentsInPeriod(
                point,
                activePeriod.years,
                activePeriod.months
            );
            const matchesPeriod = (
                (
                    activePeriod.years.length === 0
                    && activePeriod.months.length === 0
                )
                || visiblePeriodCount > 0
            );
            const shouldBeVisible = (
                pointMatchesFilters(point, activeFilters)
                && matchesPeriod
            );
            marker.setPopupContent(buildMarkerPopup(
                point,
                getMarkerCategory(point),
                {
                    ...activePeriod,
                    visibleCount: visiblePeriodCount,
                    label: describeActivePeriod(
                        activePeriod.years,
                        activePeriod.months
                    ),
                }
            ));
            if (shouldBeVisible) {
                markersLayer.addLayer(marker);
                visibleCount += 1;
            }
        });
    }

    if (filterCounter) {
        filterCounter.textContent = viewMode === "individual"
            ? `${visibleCount} de ${mapData.length} sinistros exibidos`
            : `${visibleCount} de ${markerRecords.length} locais exibidos`;
    }

    if (viewMode === "individual" && activeFilterCategories) {
        activeFilterCategories.textContent = activeFilters.length === 0
            ? "Todas as categorias"
            : activeFilters
                .map((input) => input.dataset.filterLabel)
                .join(" · ");
    }
}


function clearMapFilters() {
    [...individualCategoryFilterInputs, ...clusterFilterInputs].forEach((input) => {
        input.checked = false;
    });
    const allGravityInput = individualGravityFilterInputs.find(
        (input) => input.value === "all"
    );
    if (allGravityInput) {
        allGravityInput.checked = true;
    }
    periodYearInputs.forEach((input) => {
        input.checked = false;
    });
    if (allYearsInput) {
        allYearsInput.checked = true;
    }
    if (periodMonthFilter) {
        periodMonthFilter.querySelectorAll("[data-period-month]").forEach(
            (input) => { input.checked = false; }
        );
    }
    updateMonthOptions();
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
            <div class="map-legend__item"><span class="map-legend__common-marker"></span>Sem halo: sinistro não fatal</div>
            <div class="map-legend__item"><span class="map-legend__fatal-halo"></span>Halo vermelho: há fatal entre os sinistros visíveis</div>
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
if (periodYearFilter) {
    periodYearFilter.addEventListener("change", (event) => {
        if (event.target.matches("[data-period-all-years]")) {
            periodYearInputs.forEach((input) => {
                input.checked = false;
            });
            event.target.checked = true;
        } else if (event.target.matches("[data-period-year]")) {
            allYearsInput.checked = !periodYearInputs.some(
                (input) => input.checked
            );
        } else {
            return;
        }
        updateMonthOptions();
        applyMapFilters();
    });
}
if (periodMonthFilter) {
    periodMonthFilter.addEventListener("change", (event) => {
        if (event.target.matches("[data-period-all-months]")) {
            periodMonthFilter.querySelectorAll("[data-period-month]").forEach(
                (input) => { input.checked = false; }
            );
            event.target.checked = true;
        } else if (event.target.matches("[data-period-month]")) {
            const allMonths = periodMonthFilter.querySelector(
                "[data-period-all-months]"
            );
            allMonths.checked = !periodMonthFilter.querySelector(
                "[data-period-month]:checked"
            );
        } else {
            return;
        }
        updatePeriodSummaries();
        applyMapFilters();
    });
}
if (clearFiltersButton) {
    clearFiltersButton.disabled = markerRecords.length === 0;
    clearFiltersButton.addEventListener("click", clearMapFilters);
}

if (hasActiveAnalysis) {
    createMapLegend();
}
updateMonthOptions();
applyMapFilters();
