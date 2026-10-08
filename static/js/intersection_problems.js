(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.IntersectionProblems = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    function open(options) {
        const {marker, point, urls, getJson, postJson, onBack,
            document, leaflet, confirm, container = null, editingProblemId = null} = options;
        const root = container || document.createElement("form");
        if (!container) root.className = "signaling-popup intersection-problems";
        let catalog = [], saved = [], problemCode = "", solutionCodes = [], editingId = editingProblemId;
        let loading = true, busy = false, loaded = false, message = "", error = false;
        let busyLabel = "Salvando...";
        const current = () => marker.isPopupOpen() && (container
            ? marker.getPopup().getElement()?.contains(root)
            : marker.getPopup().getContent() === root);
        const url = (template, id) => template.replace("/0/", `/${point.id}/`)
            .replace("/0/", `/${id}/`);
        const collectionUrl = url(urls.collection);
        const selectedProblem = () => catalog.find((item) => item.code === problemCode);
        const validSelection = () => solutionCodes.length > 0 && solutionCodes.every(
            (code) => selectedProblem()?.solutions.some((solution) => solution.code === code)
        );
        function element(tag, text = "", className = "") {
            const node = document.createElement(tag);
            node.className = className;
            node.textContent = text;
            return node;
        }
        function button(text, action, className = "btn btn-outline-secondary btn-sm") {
            const node = element("button", text, className);
            node.type = "button";
            node.disabled = busy;
            node.addEventListener("click", () => {
                if (!busy && current()) return action();
            });
            return node;
        }
        function resetSelection() {
            problemCode = "";
            solutionCodes = [];
            editingId = null;
        }
        function notify(text, failed = false) {
            message = text;
            error = failed;
        }
        function choice(text, selected, action, disabled, key) {
            const node = button(text, action, "intersection-problems__choice");
            node.dataset.choice = key;
            node.setAttribute("aria-pressed", String(selected));
            node.disabled = busy || disabled;
            return node;
        }
        function render() {
            if (!current()) return;
            const scroll = Array.from(root.querySelectorAll("[data-scroll]"))
                .map((node) => node.scrollTop);
            const focused = document.activeElement?.dataset.choice;
            root.replaceChildren();
            root.setAttribute("aria-busy", String(loading || busy));
            if (container) {
                root.append(element("h3", "PROBLEMAS E SOLUÇÕES", "signaling-popup__heading"));
            } else {
                const header = element("div", "", "d-flex align-items-center justify-content-between gap-2 mb-2");
                header.append(element("h2", editingId !== null ? "Alterar soluções" : "⚠️ Problemas na interseção", "mb-0"));
                const back = button("← Voltar", onBack);
                back.dataset.backToSignaling = "";
                header.append(back);
                root.append(header);
            }
            if (loading) {
                const status = element("p", "Carregando...", "small text-secondary");
                status.setAttribute("role", "status");
                root.append(status);
            }
            if (message) {
                const feedback = element("div", message,
                    `alert alert-${error ? "danger" : "success"} signaling-form-feedback`);
                feedback.setAttribute("role", error ? "alert" : "status");
                root.append(feedback);
            }
            if (!loading && !loaded) root.append(button("Tentar novamente", load));
            if (loaded && !container) {
                root.append(element("h3", editingId !== null ? "Problema" : "Problemas",
                    "signaling-popup__heading"));
                const problems = element("div", "",
                    "signaling-interventions-panel intersection-problems__list");
                problems.dataset.scroll = "problems";
                catalog.filter((problem) => editingId === null || problem.code === problemCode).forEach((problem, index) => {
                    const added = saved.some((record) => record.problem_code === problem.code);
                    problems.append(choice(
                        editingId !== null ? problem.text : `${index + 1}. ${problem.text}${added ? " — Adicionado" : ""}`,
                        problem.code === problemCode,
                        () => {
                            problemCode = problem.code;
                            solutionCodes = [];
                            notify("");
                            render();
                        },
                        editingId !== null || added, problem.code
                    ));
                });
                root.append(problems);
                root.append(element("h3", "Soluções recomendadas", "signaling-popup__heading"));
                const solutions = element("div", "",
                    "signaling-interventions-panel intersection-problems__list");
                solutions.dataset.scroll = "solutions";
                if (!selectedProblem()) {
                    solutions.append(element("p",
                        "Selecione um problema para visualizar as soluções recomendadas.",
                        "small text-secondary mb-0"));
                } else {
                    selectedProblem().solutions.forEach((solution, index) => {
                        solutions.append(choice(
                            `${String.fromCharCode(97 + index)}. ${solution.text}`,
                            solutionCodes.includes(solution.code),
                            () => {
                                solutionCodes = solutionCodes.includes(solution.code)
                                    ? solutionCodes.filter((code) => code !== solution.code)
                                    : [...solutionCodes, solution.code];
                                notify(""); render();
                            },
                            false, solution.code
                        ));
                    });
                }
                root.append(solutions);
            }
            if (!container) {
                const actions = element("div", "", "signaling-intervention-actions");
                if (loaded) {
                    const submit = element("button", busy ? busyLabel : "Salvar", "btn btn-success btn-sm w-100");
                    submit.type = "submit";
                    submit.disabled = busy || !validSelection();
                    actions.append(submit);
                }
                actions.append(button("Cancelar", onBack, "btn btn-outline-danger btn-sm w-100"));
                root.append(actions);
            }
            if (loaded && container) {
                const records = element("div", "",
                    "signaling-interventions-panel intersection-problems__list");
                records.dataset.scroll = "saved";
                if (!saved.length) records.append(element("p", "Nenhum problema cadastrado.",
                    "small text-secondary mb-0"));
                saved.forEach((record) => {
                    const row = element("section", "", "intersection-problems__record");
                    row.dataset.recordId = String(record.id);
                    row.append(element("p", record.problem_text, "fw-semibold mb-1"),
                        element("p", "Soluções:", "mb-1"));
                    const list = element("ul", "", "mb-2");
                    record.solutions.forEach((solution) => list.append(element("li", solution.text)));
                    row.append(list);
                    const controls = element("div", "", "d-flex gap-2");
                    controls.append(button("Alterar", () => open({
                        ...options, container: null, editingProblemId: record.id,
                    })));
                    controls.append(button("Excluir", () => remove(record),
                        "btn btn-outline-danger btn-sm"));
                    row.append(controls);
                    records.append(row);
                });
                root.append(records);
            }
            Array.from(root.querySelectorAll("[data-scroll]")).forEach(
                (node, index) => { node.scrollTop = scroll[index] || 0; }
            );
            if (focused) {
                Array.from(root.querySelectorAll("[data-choice]"))
                    .find((node) => node.dataset.choice === focused && !node.disabled)?.focus();
            }
            marker.getPopup().update();
        }
        async function load() {
            if (!current()) return;
            loading = true;
            notify("");
            render();
            try {
                const data = await getJson(collectionUrl);
                if (!current()) return;
                if (data.success !== true || data.point_id !== point.id
                    || !Array.isArray(data.catalog) || !Array.isArray(data.problems)
                    || !data.problems.every((item) => Number.isInteger(item.id)
                        && typeof item.problem_code === "string"
                        && Array.isArray(item.solutions) && item.solutions.length > 0
                        && item.solutions.every((solution) => typeof solution.code === "string"
                            && typeof solution.text === "string")
                        && typeof item.problem_text === "string")
                    || !data.catalog.every((item) => typeof item.code === "string"
                        && typeof item.text === "string" && Array.isArray(item.solutions)
                        && item.solutions.every((s) => typeof s.code === "string"
                            && typeof s.text === "string"))) {
                    throw new Error("O servidor retornou dados inesperados. Tente novamente.");
                }
                catalog = data.catalog;
                saved = data.problems;
                if (editingId !== null) {
                    const record = saved.find((item) => item.id === editingId);
                    if (!record) throw new Error("Problema não encontrado. Volte ao waypoint.");
                    problemCode = record.problem_code;
                    solutionCodes = record.solutions.map((solution) => solution.code);
                }
                loaded = true;
            } catch (failure) {
                notify(failure instanceof TypeError
                    ? "Não foi possível carregar os problemas. Verifique a conexão e tente novamente."
                    : failure.message, true);
            } finally {
                loading = false;
                render();
            }
        }
        async function save(event) {
            event.preventDefault();
            if (!current() || busy || !validSelection()) return;
            busy = true;
            busyLabel = "Salvando...";
            notify("");
            render();
            const targetId = editingId;
            try {
                const record = await postJson(
                    targetId === null ? collectionUrl : url(urls.solution, targetId),
                    targetId === null
                        ? {problem_code: problemCode, solution_codes: solutionCodes}
                        : {solution_codes: solutionCodes}
                );
                if (!current()) return;
                if (record.success !== true || !Number.isInteger(record.id)
                    || record.problem_code !== problemCode
                    || typeof record.problem_text !== "string" || !Array.isArray(record.solutions)
                    || record.solutions.length !== solutionCodes.length
                    || new Set(record.solutions.map((solution) => solution.code)).size !== solutionCodes.length
                    || !record.solutions.every((solution) => solutionCodes.includes(solution.code)
                        && typeof solution.text === "string")
                    || (targetId !== null && record.id !== targetId)) {
                    throw new Error("Resposta inesperada. Reabra a tela para conferir o registro.");
                }
                saved = targetId === null ? [...saved, record]
                    : saved.map((item) => item.id === targetId ? record : item);
                resetSelection();
                if (targetId === null) notify("Problema e soluções salvos.");
                else onBack();
            } catch (failure) {
                notify(failure instanceof TypeError
                    ? "Não foi possível salvar. Verifique a conexão e tente novamente."
                    : failure.message, true);
            } finally {
                busy = false;
                render();
            }
        }
        async function remove(record) {
            if (busy || !current() || !confirm("Excluir este problema e suas soluções selecionadas?")) return;
            busy = true;
            busyLabel = "Excluindo...";
            notify("");
            render();
            try {
                const response = await postJson(url(urls.delete, record.id));
                if (!current()) return;
                if (response.success !== true || response.deleted !== true || response.id !== record.id) {
                    throw new Error("Resposta inesperada. Reabra a tela para conferir a exclusão.");
                }
                saved = saved.filter((item) => item.id !== record.id);
                if (editingId === record.id) resetSelection();
                notify("Problema excluído.");
            } catch (failure) {
                notify(failure instanceof TypeError
                    ? "Não foi possível excluir. Verifique a conexão e tente novamente."
                    : failure.message, true);
            } finally {
                busy = false;
                render();
            }
        }
        // render() can detach the click target before Leaflet checks its ancestors.
        root.addEventListener("click", (event) => {
            leaflet.DomEvent.stopPropagation(event);
        });
        if (!container) {
            root.addEventListener("submit", save);
            marker.setPopupContent(root);
        }
        leaflet.DomEvent.disableClickPropagation(root);
        leaflet.DomEvent.disableScrollPropagation(root);
        return load();
    }
    return {open};
}));
