const signalingData = JSON.parse(
    document.getElementById("signaling-map-data").textContent
);
const signalingConfig = document.getElementById("signaling-config");
const signalingLayer = L.layerGroup().addTo(map);
const signalingMarkers = new Map();


const signalingStatuses = {
    OK: {
        label: "Completa",
        popupLabel: "Sinalização completa",
        iconUrl: signalingConfig.dataset.adequateIconUrl,
        cssClass: "ok",
        buttonClass: "btn-outline-success",
    },
    INCOMPLETE: {
        label: "Incompleta",
        popupLabel: "Sinalização incompleta",
        iconUrl: signalingConfig.dataset.inadequateIconUrl,
        cssClass: "incomplete",
        buttonClass: "btn-outline-warning",
    },
    ABSENT: {
        label: "Ausente",
        popupLabel: "Sinalização ausente",
        iconUrl: signalingConfig.dataset.removeIconUrl,
        cssClass: "absent",
        buttonClass: "btn-outline-danger",
    },
};


const signalingInterventionTypes = {
    TRAFFIC_LIGHT: {
        label: "Semáforo",
        iconUrl: signalingConfig.dataset.trafficLightIconUrl,
    },
};


const signalingConditions = {
    OK: {
        label: "Adequada",
        iconUrl: signalingConfig.dataset.adequateIconUrl,
    },
    ABSENT: {
        label: "Inadequada",
        iconUrl: signalingConfig.dataset.inadequateIconUrl,
    },
};


function getCsrfToken() {
    const tokenInput = document.querySelector(
        "[name=csrfmiddlewaretoken]"
    );
    return tokenInput ? tokenInput.value : "";
}


async function postJson(url, body = {}) {
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify(body),
    });

    const data = await response.json();
    if (!response.ok) {
        const validationMessage = data.errors
            ? Object.entries(data.errors)
                .map(([field, messages]) => (
                    `${field}: ${messages.join(" ")}`
                ))
                .join("\n")
            : null;

        throw new Error(
            data.error ||
            validationMessage ||
            "Não foi possível concluir a operação."
        );
    }
    return data;
}


function createSignalingIcon(status) {
    const statusConfig = signalingStatuses[status];

    return L.divIcon({
        className: `signaling-marker signaling-marker--${statusConfig.cssClass}`,
        html: `
            <span class="signaling-marker__pin" aria-hidden="true">
                <span class="signaling-marker__inner">
                    <span class="signaling-marker__symbol"></span>
                </span>
            </span>
        `,
        iconSize: [46, 46],
        iconAnchor: [23, 44],
        popupAnchor: [0, -42],
    });
}


function deleteUrl(pointId) {
    return signalingConfig.dataset.deleteUrlTemplate.replace(
        "/0/",
        `/${pointId}/`
    );
}


function interventionUrl(pointId) {
    return signalingConfig.dataset.interventionUrlTemplate.replace(
        "/0/",
        `/${pointId}/`
    );
}


function deleteInterventionUrl(pointId, interventionId) {
    return signalingConfig.dataset.deleteInterventionUrlTemplate
        .replace("/0/", `/${pointId}/`)
        .replace("/0/", `/${interventionId}/`);
}


function buildInterventionList(point) {
    if (point.interventions.length === 0) {
        return '<p class="signaling-popup__empty">Nenhuma sinalização cadastrada.</p>';
    }

    const items = point.interventions.map((intervention) => {
        const type = signalingInterventionTypes[intervention.type];
        const condition = signalingConditions[intervention.condition];

        return `
            <li class="signaling-intervention">
                <img
                    class="signaling-intervention__icon"
                    src="${type.iconUrl}"
                    alt=""
                >
                <span class="fw-semibold">${type.label}</span>
                <span
                    class="signaling-intervention__condition small"
                >
                    <img
                        class="signaling-condition-icon"
                        src="${condition.iconUrl}"
                        alt=""
                    >
                    ${condition.label}
                </span>
                <button
                    class="signaling-intervention__remove"
                    type="button"
                    data-remove-intervention="${intervention.id}"
                    title="Remover sinalização"
                    aria-label="Remover sinalização"
                >
                    <img
                        class="signaling-delete-icon"
                        src="${signalingConfig.dataset.deleteIconUrl}"
                        alt=""
                    >
                </button>
            </li>
        `;
    }).join("");

    return `<ul class="signaling-interventions">${items}</ul>`;
}


function buildExistingPointPopup(point) {
    return `
        <article class="signaling-popup" data-signaling-point-id="${point.id}">
            <h2>${signalingStatuses[point.status].popupLabel}</h2>
            <h3 class="signaling-popup__heading">Intervenções</h3>
            ${buildInterventionList(point)}
            <div class="d-grid gap-2 mt-2">
                <button
                    class="btn btn-primary btn-sm"
                    type="button"
                    data-add-intervention
                >
                    + Adicionar sinalização
                </button>
            </div>
            <button
                class="btn btn-danger btn-sm w-100 mt-2 signaling-popup__delete"
                type="button"
            >
                Excluir ponto
            </button>
        </article>
    `;
}


function buildInterventionForm(point) {
    const existingIntervention = point.interventions[0] || null;
    const selectedType = existingIntervention
        ? existingIntervention.type
        : Object.keys(signalingInterventionTypes)[0];
    const typeConfig = signalingInterventionTypes[selectedType];
    const selectedCondition = existingIntervention
        ? existingIntervention.condition
        : "OK";
    const conditionOptions = Object.entries(signalingConditions)
        .map(([value, config]) => `
            <div class="form-check mb-1">
                <input
                    class="form-check-input"
                    type="radio"
                    name="intervention-condition"
                    id="intervention-condition-${point.id}-${value}"
                    value="${value}"
                    ${value === selectedCondition ? "checked" : ""}
                >
                <label
                    class="form-check-label"
                    for="intervention-condition-${point.id}-${value}"
                >${config.label}</label>
            </div>
        `).join("");

    return `
        <form class="signaling-popup signaling-intervention-form">
            <h2>Dados 📈</h2>
            <input type="hidden" name="type" value="${selectedType}">
            <div class="signaling-intervention mb-2">
                <img
                    class="signaling-intervention__icon"
                    src="${typeConfig.iconUrl}"
                    alt=""
                >
                <strong>${typeConfig.label}</strong>
            </div>
            <fieldset class="mb-0">
                <legend class="fs-6 mb-2">Condição</legend>
                ${conditionOptions}
            </fieldset>
            <div class="d-flex gap-2 mt-3">
                <button class="btn btn-success btn-sm flex-fill" type="submit">
                    Salvar
                </button>
                <button
                    class="btn btn-outline-danger btn-sm flex-fill"
                    type="button"
                    data-cancel-intervention
                >Cancelar</button>
            </div>
        </form>
    `;
}


function showPointPopup(marker, point) {
    marker.setPopupContent(buildExistingPointPopup(point));
    const popupElement = marker.getPopup().getElement();
    L.DomEvent.disableClickPropagation(popupElement);

    popupElement.querySelector("[data-add-intervention]")
        .addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            marker.setPopupContent(buildInterventionForm(point));
            wireInterventionForm(marker, point);
        });

    popupElement.querySelectorAll("[data-remove-intervention]")
        .forEach((button) => {
            button.addEventListener("click", async (event) => {
                L.DomEvent.stopPropagation(event);
                button.disabled = true;
                try {
                    await postJson(deleteInterventionUrl(
                        point.id,
                        Number(button.dataset.removeIntervention)
                    ));
                    point.interventions = point.interventions.filter(
                        (item) => item.id !== Number(button.dataset.removeIntervention)
                    );
                    showPointPopup(marker, point);
                } catch (error) {
                    button.disabled = false;
                    window.alert(error.message);
                }
            });
        });

    const deleteButton = popupElement.querySelector(
        ".signaling-popup__delete"
    );
    deleteButton.addEventListener("click", async (event) => {
        L.DomEvent.stopPropagation(event);
        const confirmed = window.confirm(
            "Excluir este ponto?\n\n" +
            "Todas as sinalizações cadastradas neste local " +
            "também serão removidas."
        );
        if (!confirmed) {
            return;
        }

        deleteButton.disabled = true;
        try {
            await postJson(deleteUrl(point.id));
            signalingLayer.removeLayer(marker);
            signalingMarkers.delete(point.id);
            map.closePopup();
        } catch (error) {
            deleteButton.disabled = false;
            window.alert(error.message);
        }
    });
}


function wireInterventionForm(marker, point) {
    const popupElement = marker.getPopup().getElement();
    const form = popupElement.querySelector(".signaling-intervention-form");
    L.DomEvent.disableClickPropagation(popupElement);
    form.addEventListener("click", (event) => {
        L.DomEvent.stopPropagation(event);
    });

    form.querySelector("[data-cancel-intervention]")
        .addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            showPointPopup(marker, point);
        });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        L.DomEvent.stopPropagation(event);
        const submitButton = form.querySelector('[type="submit"]');
        const formData = new FormData(form);
        submitButton.disabled = true;

        try {
            const intervention = await postJson(
                interventionUrl(point.id),
                {
                    type: formData.get("type"),
                    condition: formData.get("intervention-condition"),
                }
            );
            const existingIndex = point.interventions.findIndex(
                (item) => item.type === intervention.type
            );
            if (existingIndex === -1) {
                point.interventions.push(intervention);
            } else {
                point.interventions[existingIndex] = intervention;
            }
            showPointPopup(marker, point);
        } catch (error) {
            submitButton.disabled = false;
            window.alert(error.message);
        }
    });
}


function addSignalingMarker(point) {
    const marker = L.marker([point.latitude, point.longitude], {
        icon: createSignalingIcon(point.status),
    });

    point.interventions = point.interventions || [];
    marker.bindPopup(buildExistingPointPopup(point));
    marker.on("popupopen", () => showPointPopup(marker, point));

    marker.addTo(signalingLayer);
    signalingMarkers.set(point.id, marker);
}


function buildCreationPopup() {
    const buttons = Object.entries(signalingStatuses)
        .map(([status, config]) => `
            <button
                class="btn ${config.buttonClass} btn-sm d-flex align-items-center gap-2"
                type="button"
                data-signaling-status="${status}"
            >
                <img
                    class="signaling-option-icon"
                    src="${config.iconUrl}"
                    alt=""
                >
                ${config.label}
            </button>
        `)
        .join("");

    return `
        <section class="signaling-popup signaling-create-popup">
            <h2>Estudo 📝</h2>
            <div class="d-grid gap-2">
                ${buttons}
                <button
                    class="btn btn-outline-secondary btn-sm"
                    type="button"
                    data-signaling-cancel
                >Cancelar</button>
            </div>
        </section>
    `;
}


function openCreationPopup(latitude, longitude) {
    const popup = L.popup()
        .setLatLng([latitude, longitude])
        .setContent(buildCreationPopup())
        .openOn(map);

    const popupElement = popup.getElement();
    L.DomEvent.disableClickPropagation(popupElement);

    popupElement.querySelector("[data-signaling-cancel]")
        .addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            map.closePopup();
        });

    popupElement.querySelectorAll("[data-signaling-status]")
        .forEach((button) => {
            button.addEventListener("click", async (event) => {
                L.DomEvent.stopPropagation(event);
                const buttons = popupElement.querySelectorAll("button");
                buttons.forEach((item) => {
                    item.disabled = true;
                });

                try {
                    const point = await postJson(
                        signalingConfig.dataset.createUrl,
                        {
                            latitude,
                            longitude,
                            status: button.dataset.signalingStatus,
                        }
                    );
                    map.closePopup();
                    addSignalingMarker(point);
                } catch (error) {
                    buttons.forEach((item) => {
                        item.disabled = false;
                    });
                    window.alert(error.message);
                }
            }, {once: true});
        });
}


signalingData.forEach(addSignalingMarker);

const toolsPanelElement = document.getElementById("tools-panel");
const openToolsButton = document.getElementById("open-tools-panel");
L.DomEvent.disableClickPropagation(toolsPanelElement);
L.DomEvent.disableClickPropagation(openToolsButton);

map.on("click", (event) => {
    const sourceElement = event.originalEvent?.target;
    if (
        sourceElement instanceof Element &&
        sourceElement.closest(
            ".leaflet-popup, .leaflet-marker-icon, .leaflet-control, " +
            "#tools-panel, #open-tools-panel"
        )
    ) {
        return;
    }

    openCreationPopup(event.latlng.lat, event.latlng.lng);
});
