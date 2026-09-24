(function exposeReportCharacterization(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    if (root.document) {
        const section = root.document.querySelector("[data-characterization]");
        if (section) api.init(section);
    }
}(typeof globalThis !== "undefined" ? globalThis : this, function createApi() {
    "use strict";

    const searchError = "Não foi possível consultar automaticamente os locais próximos. "
        + "Você ainda pode adicionar os Polos Geradores de Tráfego manualmente.";

    function normalizedLabel(value) {
        return value.trim().replace(/\s+/gu, " ").toLowerCase();
    }

    function newSuggestions(existing, suggestions) {
        const seen = new Set(existing.map(normalizedLabel));
        return suggestions.filter((value) => {
            const key = normalizedLabel(value);
            if (!key || seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }

    function init(section) {
        const document = section.ownerDocument;
        const editor = section.querySelector("[data-pgt-editor]");
        const rows = editor.querySelector("[data-pgt-rows]");
        const addButton = editor.querySelector("[data-pgt-add]");
        const searchButton = section.querySelector("[data-pgt-search]");
        const notice = section.querySelector("[data-pgt-notice]");
        const maxItems = Number(editor.dataset.maxItems);
        const maxLength = Number(editor.dataset.maxLength);
        const inputs = () => Array.from(rows.querySelectorAll("textarea"));
        let searching = false;

        function notify(message, warning = false) {
            notice.textContent = message;
            notice.className = "alert mt-3 mb-0 " + (warning ? "alert-warning" : "alert-info");
            notice.hidden = false;
        }

        function addRow(value = "") {
            if (inputs().length >= maxItems) {
                notify("Limite de " + maxItems + " locais atingido. Edite ou remova um item.", true);
                return false;
            }
            const row = document.createElement("div");
            row.className = "input-group";
            row.dataset.pgtRow = "";
            const input = document.createElement("textarea");
            input.className = "form-control";
            input.rows = 1;
            input.name = "pgts";
            input.maxLength = maxLength;
            input.setAttribute("aria-label", "Polo Gerador de Tráfego");
            input.value = value;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "btn btn-outline-danger";
            remove.dataset.pgtRemove = "";
            remove.setAttribute("aria-label", "Remover local");
            remove.textContent = "Remover";
            row.append(input, remove);
            rows.append(row);
            if (!value) input.focus();
            return true;
        }

        addButton.addEventListener("click", () => addRow());
        rows.addEventListener("click", (event) => {
            const button = event.target.closest("[data-pgt-remove]");
            if (button) button.closest("[data-pgt-row]").remove();
        });
        searchButton.addEventListener("click", async () => {
            if (searching) return;
            searching = true;
            searchButton.disabled = true;
            const originalLabel = searchButton.textContent;
            searchButton.textContent = "Buscando locais…";
            searchButton.setAttribute("aria-busy", "true");
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 20000);
            try {
                const response = await fetch(section.dataset.pgtSearchUrl, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": section.closest("form")
                            .querySelector("[name=csrfmiddlewaretoken]").value,
                    },
                    signal: controller.signal,
                });
                const data = await response.json();
                if (!response.ok || data.success !== true || !Array.isArray(data.results)
                    || !data.results.every((value) => typeof value === "string"
                        && Array.from(value).length <= maxLength)) {
                    throw new Error(searchError);
                }
                // Ler o DOM depois da resposta preserva edições feitas durante a busca.
                const additions = newSuggestions(inputs().map((input) => input.value), data.results);
                let added = 0;
                additions.forEach((value) => {
                    const emptyInput = inputs().find((input) => !input.value.trim());
                    if (emptyInput) {
                        emptyInput.value = value;
                        added += 1;
                    } else if (addRow(value)) {
                        added += 1;
                    }
                });
                if (added < additions.length) {
                    notify("Limite de " + maxItems + " locais atingido. Algumas sugestões não foram adicionadas.", true);
                } else if (!data.results.length) {
                    notify("Nenhum local foi encontrado automaticamente neste raio. "
                        + "Você ainda pode adicionar locais manualmente.");
                } else {
                    notify(added ? added + " local(is) adicionado(s). Revise as sugestões."
                        : "Os locais encontrados já estão na lista.");
                }
            } catch (error) {
                notify(searchError, true);
            } finally {
                clearTimeout(timeout);
                searching = false;
                searchButton.disabled = false;
                searchButton.textContent = originalLabel;
                searchButton.removeAttribute("aria-busy");
            }
        });
    }
    return {init, newSuggestions};
}));
