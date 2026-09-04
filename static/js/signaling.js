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
    PEDESTRIAN_CROSSING: {
        label: "Travessia segura",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}pedestrians-crossing-icon.svg`,
    },
    MINI_ROUNDABOUT: {
        label: "Minirrotatória",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}rotatory-icon.svg`,
    },
    RIGHT_OF_WAY_REVERSAL: {
        label: "Inversão de Pref. Passagem",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}reversal-right-of-way-icon.svg`,
    },
    TRAFFIC_FLOW_CHANGE: {
        label: "Alteração de circulação",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}traffic-change-icon.svg`,
    },
    PEDESTRIAN_REFUGE: {
        label: "Refúgios para pedestres",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}pedestrian-refuges-icon.svg`,
    },
    NO_PARKING: {
        label: "Proibido estacionar",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}no-parking-icon.svg`,
    },
    GEOMETRY_ADJUSTMENT: {
        label: "Adequação na geometria",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}geometry-icon.svg`,
    },
    SPEED_REDUCTION: {
        label: "Redução de velocidade",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}speedometer-icon.svg`,
    },
    VERTICAL_HORIZONTAL_SIGNALING: {
        label: "Sinalizações verticais e horizontais",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}signaling-icon.svg`,
    },
    LOW_VISIBILITY: {
        label: "Visibilidade prejudicada",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}signal-low-vision.svg`,
    },
    R1: {
        label: "R-1",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}signal-stop-icon.svg`,
    },
    STREET_LIGHTING: {
        label: "Iluminação",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}street-ligth-icon.svg`,
    },
    SPEED_BUMP: {
        label: "Lombada",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}signal-speed-bump.svg`,
    },
    R5A: {
        label: "R-5a",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}R-5a-icon.svg`,
    },
    R5B: {
        label: "R-5b",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}R-5b-icon.svg`,
    },
    R4A: {
        label: "R-4a",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}R-4a-icon.svg`,
    },
    R24A: {
        label: "R-24a",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}R-24a-icon.svg`,
    },
    R6C: {
        label: "R-6c",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}R-6c-icon.svg`,
    },
    R6A: {
        label: "R-6a",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}R-6a-icon.svg`,
    },
    RAISED_CROSSWALK: {
        label: "Faixa elevada",
        iconUrl: `${signalingConfig.dataset.interventionIconBaseUrl}raised-crosswalk-icon.svg`,
    },
};


const signalingConditions = {
    OK: {
        label: "Adequada",
        iconUrl: signalingConfig.dataset.adequateIconUrl,
        buttonClass: "btn-outline-success",
    },
    ABSENT: {
        label: "Inadequada",
        iconUrl: signalingConfig.dataset.inadequateIconUrl,
        buttonClass: "btn-outline-warning",
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


function updateStatusUrl(pointId) {
    return signalingConfig.dataset.updateStatusUrlTemplate.replace(
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


function updateConditionUrl(pointId, interventionId) {
    return signalingConfig.dataset.updateConditionUrlTemplate
        .replace("/0/", `/${pointId}/`)
        .replace("/0/", `/${interventionId}/`);
}


function buildInterventionList(point) {
    if (point.interventions.length === 0) {
        return `
            <div class="signaling-interventions-panel">
                <p class="signaling-popup__empty">Nenhuma sinalização cadastrada.</p>
            </div>
        `;
    }

    const items = point.interventions.map((intervention) => {
        const type = signalingInterventionTypes[intervention.type];
        const condition = signalingConditions[intervention.condition];
        const nextCondition = intervention.condition === "OK" ? "ABSENT" : "OK";
        const toggleLabel = nextCondition === "OK"
            ? "Marcar como adequada"
            : "Marcar como inadequada";

        return `
            <li class="signaling-intervention">
                <span class="signaling-intervention__type">
                    <img
                        class="signaling-intervention__icon"
                        src="${type.iconUrl}"
                        alt=""
                    >
                    <span class="fw-semibold signaling-intervention__type-name">
                        ${type.label}
                    </span>
                </span>
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
                <span class="signaling-intervention__actions">
                    <button
                        class="signaling-intervention__toggle"
                        type="button"
                        data-toggle-intervention="${intervention.id}"
                        data-next-condition="${nextCondition}"
                        title="${toggleLabel}"
                        aria-label="${toggleLabel}"
                    >
                        <img
                            class="signaling-toggle-icon"
                            src="${signalingConfig.dataset.toggleIconUrl}"
                            alt=""
                        >
                    </button>
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
                    <button
                        class="signaling-intervention__notes"
                        type="button"
                        data-read-intervention-notes="${intervention.id}"
                        title="Ver observações"
                        aria-label="Ver observações da intervenção"
                    >
                        <img
                            class="signaling-notes-icon"
                            src="${signalingConfig.dataset.notesIconUrl}"
                            alt=""
                        >
                    </button>
                </span>
            </li>
        `;
    }).join("");

    return `
        <div class="signaling-interventions-panel">
            <ul class="signaling-interventions">${items}</ul>
        </div>
    `;
}


function buildExistingPointPopup(point) {
    const statusOptions = Object.entries(signalingStatuses)
        .map(([status, config]) => `
            <button
                class="btn ${config.buttonClass} btn-sm"
                type="button"
                data-point-status="${status}"
                ${status === point.status ? "disabled" : ""}
            >${config.label}</button>
        `).join("");

    return `
        <article class="signaling-popup" data-signaling-point-id="${point.id}">
            <header class="signaling-popup__header">
                <h2>${signalingStatuses[point.status].popupLabel}</h2>
                <button
                    class="btn btn-outline-secondary btn-sm"
                    type="button"
                    data-edit-point-status
                    aria-expanded="false"
                >Alterar</button>
            </header>
            <div class="signaling-status-editor" data-status-editor hidden>
                ${statusOptions}
            </div>
            <h3 class="signaling-popup__heading">Intervenções</h3>
            ${buildInterventionList(point)}
            <section class="signaling-notes-panel" data-notes-panel hidden>
                <header class="signaling-notes-panel__header">
                    <strong>Observações</strong>
                    <button
                        class="signaling-notes-panel__close"
                        type="button"
                        data-close-notes
                        title="Fechar observações"
                        aria-label="Fechar observações"
                    >&times;</button>
                </header>
                <p class="signaling-notes-panel__content" data-notes-content></p>
            </section>
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
    const catalogOptions = Object.entries(signalingInterventionTypes)
        .map(([value, config]) => `
            <button
                class="signaling-catalog__option"
                type="button"
                data-intervention-type="${value}"
                aria-pressed="false"
                title="${config.label}"
            >
                <img
                    class="signaling-catalog__icon"
                    src="${config.iconUrl}"
                    alt=""
                >
                <span class="signaling-catalog__label">${config.label}</span>
            </button>
        `).join("");
    const conditionOptions = Object.entries(signalingConditions)
        .map(([value, config]) => `
            <div>
                <input
                    class="btn-check"
                    type="radio"
                    name="intervention-condition"
                    id="intervention-condition-${point.id}-${value}"
                    value="${value}"
                    autocomplete="off"
                >
                <label
                    class="btn ${config.buttonClass} btn-sm signaling-condition-option w-100"
                    for="intervention-condition-${point.id}-${value}"
                >
                    <img
                        class="signaling-condition-icon"
                        src="${config.iconUrl}"
                        alt=""
                    >
                    ${config.label}
                </label>
            </div>
        `).join("");

    return `
        <form class="signaling-popup signaling-intervention-form">
            <div class="d-flex align-items-center justify-content-between gap-2 mb-2">
                <h2 class="mb-0">Dados 📈</h2>
                <button
                    class="btn btn-outline-secondary btn-sm"
                    type="button"
                    data-back-to-signaling
                >&larr; Voltar</button>
            </div>
            <p class="small text-secondary mb-2">Adicionar intervenção</p>
            <input type="hidden" name="type" value="">
            <div class="signaling-catalog">
                <button
                    class="btn btn-outline-secondary btn-sm signaling-catalog__arrow"
                    type="button"
                    data-catalog-direction="previous"
                    title="Intervenções anteriores"
                    aria-label="Intervenções anteriores"
                >&larr;</button>
                <div
                    class="signaling-catalog__viewport"
                    data-intervention-catalog
                    tabindex="0"
                    aria-label="Tipos de intervenção"
                >
                    ${catalogOptions}
                </div>
                <button
                    class="btn btn-outline-secondary btn-sm signaling-catalog__arrow"
                    type="button"
                    data-catalog-direction="next"
                    title="Próximas intervenções"
                    aria-label="Próximas intervenções"
                >&rarr;</button>
            </div>
            <p class="signaling-selection-summary text-secondary">
                Selecionada: <strong data-selected-intervention>Nenhuma</strong>
            </p>
            <div class="mb-3">
                <label
                    class="form-label small fw-semibold mb-1"
                    for="intervention-notes-${point.id}"
                >Observações</label>
                <textarea
                    class="form-control form-control-sm signaling-notes-input"
                    id="intervention-notes-${point.id}"
                    name="notes"
                    rows="3"
                    placeholder="Escreva observações se necessário..."
                ></textarea>
            </div>
            <fieldset class="mb-0">
                <legend class="fs-6 mb-2">Condição</legend>
                <div class="signaling-condition-options">
                    ${conditionOptions}
                </div>
            </fieldset>
            <div
                class="alert alert-success signaling-form-feedback"
                role="status"
                data-intervention-feedback
                hidden
            ></div>
            <div class="d-flex gap-2 mt-3">
                <button
                    class="btn btn-success btn-sm flex-fill"
                    type="submit"
                    disabled
                >
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
    L.DomEvent.disableScrollPropagation(popupElement);

    const statusEditor = popupElement.querySelector("[data-status-editor]");
    const editStatusButton = popupElement.querySelector(
        "[data-edit-point-status]"
    );
    editStatusButton.addEventListener("click", (event) => {
        L.DomEvent.stopPropagation(event);
        statusEditor.hidden = !statusEditor.hidden;
        editStatusButton.setAttribute(
            "aria-expanded",
            String(!statusEditor.hidden)
        );
    });

    popupElement.querySelectorAll("[data-point-status]").forEach((button) => {
        button.addEventListener("click", async (event) => {
            L.DomEvent.stopPropagation(event);
            button.disabled = true;
            try {
                const updatedPoint = await postJson(
                    updateStatusUrl(point.id),
                    {status: button.dataset.pointStatus}
                );
                point.status = updatedPoint.status;
                marker.setIcon(createSignalingIcon(point.status));
                marker.openPopup();
                showPointPopup(marker, point);
            } catch (error) {
                button.disabled = false;
                window.alert(error.message);
            }
        });
    });

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

    popupElement.querySelectorAll("[data-toggle-intervention]")
        .forEach((button) => {
            button.addEventListener("click", async (event) => {
                L.DomEvent.stopPropagation(event);
                button.disabled = true;
                const interventionId = Number(
                    button.dataset.toggleIntervention
                );
                try {
                    const updatedIntervention = await postJson(
                        updateConditionUrl(point.id, interventionId),
                        {condition: button.dataset.nextCondition}
                    );
                    const interventionIndex = point.interventions.findIndex(
                        (item) => item.id === interventionId
                    );
                    point.interventions[interventionIndex] = updatedIntervention;
                    showPointPopup(marker, point);
                } catch (error) {
                    button.disabled = false;
                    window.alert(error.message);
                }
            });
        });

    const notesPanel = popupElement.querySelector("[data-notes-panel]");
    const notesContent = popupElement.querySelector("[data-notes-content]");
    popupElement.querySelectorAll("[data-read-intervention-notes]")
        .forEach((button) => {
            button.addEventListener("click", (event) => {
                L.DomEvent.stopPropagation(event);
                const interventionId = Number(
                    button.dataset.readInterventionNotes
                );
                const intervention = point.interventions.find(
                    (item) => item.id === interventionId
                );
                const notes = intervention && typeof intervention.notes === "string"
                    ? intervention.notes
                    : "";
                notesContent.textContent = notes.trim()
                    ? notes
                    : "Nenhuma observação registrada";
                notesPanel.hidden = false;
            });
        });

    popupElement.querySelector("[data-close-notes]")
        .addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            notesPanel.hidden = true;
            notesContent.textContent = "";
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
    const typeInput = form.elements.type;
    const conditionInputs = Array.from(
        form.elements["intervention-condition"]
    );
    const submitButton = form.querySelector('[type="submit"]');
    const selectedIntervention = form.querySelector(
        "[data-selected-intervention]"
    );
    const feedback = form.querySelector("[data-intervention-feedback]");
    const catalog = form.querySelector("[data-intervention-catalog]");
    L.DomEvent.disableClickPropagation(popupElement);
    L.DomEvent.disableScrollPropagation(popupElement);
    form.addEventListener("click", (event) => {
        L.DomEvent.stopPropagation(event);
    });

    function updateSubmitState() {
        submitButton.disabled = !(
            typeInput.value && conditionInputs.some((input) => input.checked)
        );
    }

    function resetFormSelection() {
        typeInput.value = "";
        form.elements.notes.value = "";
        selectedIntervention.textContent = "Nenhuma";
        form.querySelectorAll("[data-intervention-type]").forEach((option) => {
            option.classList.remove("is-selected");
            option.setAttribute("aria-pressed", "false");
        });
        conditionInputs.forEach((input) => {
            input.checked = false;
        });
        updateSubmitState();
    }

    form.querySelectorAll("[data-intervention-type]").forEach((option) => {
        option.addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            form.querySelectorAll("[data-intervention-type]").forEach((item) => {
                const isSelected = item === option;
                item.classList.toggle("is-selected", isSelected);
                item.setAttribute("aria-pressed", String(isSelected));
            });
            typeInput.value = option.dataset.interventionType;
            selectedIntervention.textContent = (
                signalingInterventionTypes[typeInput.value].label
            );
            feedback.hidden = true;
            updateSubmitState();
        });
    });

    conditionInputs.forEach((input) => {
        input.addEventListener("change", () => {
            feedback.hidden = true;
            updateSubmitState();
        });
    });

    form.querySelectorAll("[data-catalog-direction]").forEach((button) => {
        button.addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            const direction = button.dataset.catalogDirection === "next" ? 1 : -1;
            catalog.scrollBy({left: direction * 260, behavior: "smooth"});
        });
    });

    catalog.addEventListener("wheel", (event) => {
        L.DomEvent.stopPropagation(event);
        if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
            event.preventDefault();
            catalog.scrollLeft += event.deltaY;
        }
    }, {passive: false});

    form.querySelector("[data-cancel-intervention]")
        .addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            showPointPopup(marker, point);
        });

    form.querySelector("[data-back-to-signaling]")
        .addEventListener("click", (event) => {
            L.DomEvent.stopPropagation(event);
            showPointPopup(marker, point);
        });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        L.DomEvent.stopPropagation(event);
        const formData = new FormData(form);
        const savedType = formData.get("type");
        const savedCondition = formData.get("intervention-condition");
        submitButton.disabled = true;

        try {
            const intervention = await postJson(
                interventionUrl(point.id),
                {
                    type: formData.get("type"),
                    condition: formData.get("intervention-condition"),
                    notes: formData.get("notes"),
                }
            );
            point.interventions.push(intervention);
            feedback.textContent = (
                `${signalingInterventionTypes[savedType].label} — ` +
                `${signalingConditions[savedCondition].label} adicionada.`
            );
            feedback.hidden = false;
            resetFormSelection();
        } catch (error) {
            updateSubmitState();
            window.alert(error.message);
        }
    });
}


function addSignalingMarker(point) {
    const marker = L.marker([point.latitude, point.longitude], {
        icon: createSignalingIcon(point.status),
    });

    point.interventions = point.interventions || [];
    marker.bindPopup(buildExistingPointPopup(point), {maxWidth: 390});
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
            <div class="signaling-study-actions">
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
