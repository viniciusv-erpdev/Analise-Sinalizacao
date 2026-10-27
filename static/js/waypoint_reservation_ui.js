/* Map/popup/report lifecycle. No credentials are rendered into HTML or persisted. */
(function (root) {
    "use strict";
    if (typeof module === "object" && module.exports) module.exports = {create};
    else root.WaypointReservationUI = {create};
    function create({manager, document, window, map, markers, canChange, canDelete, canReport, render}) {
        let current = null, report = null, pollCursor = 0;
        const bindings = new Map();
        const blocked = new WeakMap();
        const guarded = new WeakSet();
        const labels = {
            idle: "Somente leitura. Feche e reabra os detalhes para editar.",
            available: "Disponível — inicie uma nova interação.",
            acquiring: "Solicitando reserva…",
            active: "Reservado por esta interação.",
            renewing: "Confirmando reserva…",
            occupied: "Ocupado por outra interação. Informações em modo somente leitura.",
            uncertain: "Sem confirmação de conexão. Operações protegidas suspensas.",
            lost: "A edição foi interrompida. Tente novamente.",
            closing: "Encerrando interação…",
            release_failed: "Liberação não confirmada. A reserva expirará no servidor.",
        };
        const mutationSelector = "[data-edit-point-status], [data-point-status], [data-search-radius], " +
            "[data-add-intervention], [data-add-problems], [data-remove-intervention], " +
            "[data-toggle-intervention], [data-edit-notes], [data-generate-report], " +
            ".signaling-popup__delete, [data-notes-edit-form] button[type=submit], " +
            "[data-notes-edit-form] textarea, .signaling-intervention-form input, " +
            ".signaling-intervention-form textarea, .signaling-intervention-form button[type=submit], " +
            ".intersection-problems input, .intersection-problems button[type=submit], " +
            "[data-edit-problem], [data-delete-problem]";
        function notify(message) {
            let node = document.getElementById("waypoint-feedback");
            if (!node) {
                node = document.createElement("div"); node.id = "waypoint-feedback";
                node.className = "alert alert-warning position-fixed bottom-0 start-0 m-3";
                node.style.zIndex = "2000"; node.setAttribute("role","alert");
                document.body.append(node);
            }
            node.textContent = message;
        }
        function controls(rootNode, allowed, selector = mutationSelector) {
            rootNode.querySelectorAll(selector).forEach(node => {
                const permission = selector !== mutationSelector ? true
                    : node.matches("[data-generate-report]") ? canReport
                    : node.matches(".signaling-popup__delete") ? canDelete : canChange;
                if (!allowed || !permission) {
                    if (!blocked.has(node)) blocked.set(node, node.disabled);
                    if ("disabled" in node && !node.disabled) node.disabled = true;
                    if (node.getAttribute("aria-disabled") !== "true") node.setAttribute("aria-disabled","true");
                } else if (blocked.has(node)) {
                    if ("disabled" in node) node.disabled = !!blocked.get(node);
                    node.removeAttribute("aria-disabled"); blocked.delete(node);
                }
            });
        }
        function reportControls(doc, allowed) {
            controls(doc, allowed, "input[type=file], select, button:not([data-draft-retry])");
            doc.querySelectorAll("input:not([type=file]):not([type=hidden]), textarea").forEach(node => {
                node.readOnly = !allowed; // Preserve selection/copy after losing the lease.
            });
        }
        function badge(id, state) {
            const icon = markers.get(id)?.getElement();
            if (!icon) return;
            let node = icon.querySelector("[data-reservation-badge]");
            if (!node) {
                node = document.createElement("span"); node.dataset.reservationBadge = "";
                node.style.cssText = "position:absolute;right:-4px;top:0;border-radius:1rem;padding:1px 4px;font:12px sans-serif;color:white";
                icon.append(node);
            }
            const own = ["active","renewing"].includes(state);
            node.textContent = own ? "✓" : state === "available" ? "○" : "•";
            node.style.background = own ? "#087f5b" : state === "available" ? "#495057" : "#b45309";
            node.title = labels[state] || "Ocupado por outra interação.";
            node.setAttribute("aria-label", node.title);
        }
        function update(binding) {
            const state = manager.snapshot();
            const relevant = state.pointId === binding.point.id;
            const allowed = relevant && current?.ready === true && manager.canOperate(binding.point.id);
            binding.message.textContent = relevant ? (state.message || labels[state.state]) : labels.idle;
            binding.message.hidden = allowed || (relevant && state.state === "renewing");
            binding.retry.disabled = !!state.busy || state.state === "acquiring" || state.state === "closing";
            const endedHere = state.state === "idle" && current?.point.id === binding.point.id;
            binding.retry.hidden = allowed || (!endedHere &&
                (!relevant || !["lost","uncertain","occupied"].includes(state.state)));
            binding.panel.hidden = allowed;
            controls(binding.element, allowed);
        }
        manager.subscribe(state => {
            if (state.code === "authentication_required") {
                document.querySelectorAll("[data-signaling-auth-notice]").forEach(node => { node.hidden = false; });
            }
            badge(state.pointId, state.state);
            bindings.forEach(update);
            if (report) {
                if (state.pointId !== report.id || ["idle","lost","closing","release_failed","acquiring","occupied"].includes(state.state)) {
                    report.invalidated = true; report.draft?.stop();
                } else if (state.state === "uncertain") report.draft?.pause();
                else report.draft?.resume();
                const allowed = manager.canOperate(report.id) && !report.closing && !report.invalidated;
                report.message.textContent = state.message || labels[state.state] || "";
                const doc = report.frame.contentDocument;
                if (doc) reportControls(doc, allowed);
            }
        });
        function bind(marker, point) {
            const element = marker.getPopup().getElement();
            const previous = bindings.get(point.id);
            if (previous?.element === element && element.contains(previous.message)) {
                update(previous); return;
            }
            previous?.observer?.disconnect();
            const panel = document.createElement("div");
            panel.className = "small text-secondary mb-2";
            panel.dataset.waypointReservation = "";
            const message = document.createElement("p"); message.className = "mb-1"; message.setAttribute("role","status");
            const retry = document.createElement("button"); retry.type = "button";
            retry.className = "btn btn-link btn-sm p-0"; retry.textContent = "Tentar editar novamente";
            retry.addEventListener("click", () => begin(marker,point));
            panel.append(message,retry);
            (element.querySelector(".leaflet-popup-content") || element).prepend(panel);
            const binding = {element, panel, message, retry, marker, point};
            bindings.set(point.id,binding);
            // Guard event handlers too: async finally handlers must never reopen writes.
            const guard = event => {
                const target = event.target.closest(mutationSelector);
                const editorForm = event.target.closest(".intersection-problems, .signaling-intervention-form, [data-notes-edit-form]");
                if (!(current?.ready && manager.canOperate(point.id)) && (target || (event.type === "submit" && editorForm))) {
                    event.preventDefault(); event.stopImmediatePropagation();
                    message.textContent = labels.lost;
                }
            };
            if (!guarded.has(element)) {
                ["click","change","submit"].forEach(type => element.addEventListener(type,guard,true));
                guarded.add(element);
            }
            binding.observer = new MutationObserver(() => controls(element,!!current?.ready && manager.canOperate(point.id)));
            binding.observer.observe(element,{childList:true,subtree:true,attributes:true,attributeFilter:["disabled"]});
            update(binding);
        }
        async function begin(marker,point) {
            if (report) { notify("Encerre o relatório antes de trocar de waypoint."); return; }
            current = {marker,point,ready:false};
            try {
                await manager.acquire(point.id);
                if (current?.point !== point || !marker.isPopupOpen()) return;
                // Existing authorized map payload is the read contract; refresh after reacquisition.
                const data = await manager.perform(point.id, window.location.pathname, {}, async res => {
                    if (!res.ok) throw new Error("Não foi possível atualizar os dados do waypoint.");
                    const doc = new DOMParser().parseFromString(await res.text(),"text/html");
                    return JSON.parse(doc.getElementById("signaling-map-data").textContent);
                });
                const fresh = data.find(item => item.id === point.id);
                if (!fresh) throw new Error("Waypoint não encontrado. Recarregue o mapa.");
                Object.assign(point,fresh);
                current.ready = true;
                if (current?.point === point && marker.isPopupOpen()) render(marker,point);
            } catch (error) {
                if (error.code !== "superseded") {
                    const binding = bindings.get(point.id);
                    if (binding && current?.point === point) binding.message.textContent = error.message;
                }
                if (!error.code) { await manager.close(); notify(error.message); }
            }
        }
        function end(id) {
            const binding = bindings.get(id); binding?.observer?.disconnect(); bindings.delete(id);
            if (report?.id === id) return; // report owns the same interaction
            if (current?.point.id === id) { current = null; manager.close(); }
        }
        async function confirm(message) {
            const dialog = document.createElement("dialog"); dialog.className = "rounded border p-3";
            const text = document.createElement("p"); text.textContent = message;
            const yes = document.createElement("button"); yes.className = "btn btn-danger"; yes.textContent = "Confirmar";
            const no = document.createElement("button"); no.className = "btn btn-secondary ms-2"; no.textContent = "Cancelar";
            dialog.append(text,yes,no); document.body.append(dialog);
            return new Promise(resolve => {
                const done = value => { dialog.close(); dialog.remove(); resolve(value); };
                yes.onclick = () => done(true); no.onclick = () => done(false);
                dialog.addEventListener("cancel",event => { event.preventDefault(); done(false); });
                dialog.showModal();
            });
        }
        async function openReport(id,url) {
            if (report) return;
            const dialog = document.createElement("dialog");
            dialog.className = "waypoint-report-dialog";
            const closeButton = document.createElement("button");
            closeButton.className = "btn btn-outline-secondary btn-sm"; closeButton.textContent = "Encerrar relatório";
            const message = document.createElement("p"); message.className = "small"; message.setAttribute("role","status");
            const frame = document.createElement("iframe"); frame.title = "Relatório de sinalização";
            dialog.append(closeButton,message,frame); document.body.append(dialog);
            const flow = {id, dialog, frame, message, closing:false, url}; report = flow;
            const finish = async () => {
                if (flow.closing || flow.finishing) return false;
                flow.finishing = true;
                try {
                    if (flow.draft?.hasPending()) {
                        if (!flow.invalidated && manager.canOperate(id)) await flow.draft.flush();
                        if (flow.draft.hasPending() && !await confirm(
                            "Há alterações não salvas neste relatório. Deseja descartá-las e encerrar? Cancelar mantém os textos abertos.")) return false;
                    }
                } finally { flow.finishing = false; }
                flow.closing = true; report = null;
                flow.draft?.destroy();
                flow.observer?.disconnect();
                dialog.close(); dialog.remove();
                if (current?.point.id === id && current.marker.isPopupOpen()) {
                    // The report is a panel of the same map interaction, not its owner.
                    manager.resume();
                    bindings.forEach(update);
                } else {
                    manager.close(); // No remaining UI owner: drain work before release.
                }
            };
            closeButton.onclick = finish;
            dialog.addEventListener("cancel",event => { event.preventDefault(); finish(); });
            dialog.showModal();
            async function request(url,options = {}) {
                const data = await manager.perform(id,url,options);
                return {ok:true,status:200,json:async () => data};
            }
            function show(html) {
                if (flow.closing || flow.invalidated || report !== flow) return;
                frame.onload = () => {
                    if (flow.closing || flow.invalidated) return;
                    const doc = frame.contentDocument, win = frame.contentWindow;
                    win.waypointReservationRequest = request;
                    if (flow.draft) flow.draft.attach(doc);
                    else if (window.ReportDraft) flow.draft = window.ReportDraft.mount({manager,pointId:id,doc});
                    flow.observer?.disconnect();
                    flow.observer = new MutationObserver(() => reportControls(doc,
                        manager.canOperate(id) && !flow.closing && !flow.invalidated));
                    flow.observer.observe(doc,{subtree:true,childList:true,attributes:true,attributeFilter:["disabled"]});
                    reportControls(doc,manager.canOperate(id) && !flow.invalidated);
                    doc.addEventListener("submit",async event => {
                        event.preventDefault();
                        if (!event.target.matches("[data-waypoint-report-form]")) {
                            if (manager.snapshot().busy) { message.textContent = "Aguarde a operação em andamento antes de sair."; return; }
                            // Account logout: retain native POST + CSRF after release.
                            if (flow.draft?.hasPending()) {
                                message.textContent = "Encerre o relatório e resolva as alterações pendentes antes de sair."; return;
                            }
                            const form = event.target; await manager.close();
                            form.target = "_top"; win.HTMLFormElement.prototype.submit.call(form);
                            return;
                        }
                        const form = event.target;
                        if (form.dataset.sending === "true" || !manager.canOperate(id)) return;
                        form.dataset.sending = "true";
                        try {
                            if (flow.draft) await flow.draft.flush();
                            if (flow.closing || flow.invalidated || !manager.canOperate(id)) return;
                            const result = await manager.perform(id,flow.url,{method:"POST",body:new win.FormData(form)},
                                async res => {
                                    const type = res.headers.get("Content-Type") || "";
                                    if (type.includes("text/html")) return {html:await res.text()};
                                    if (!res.ok) throw new Error("Não foi possível gerar o relatório.");
                                    return {blob:await res.blob()};
                                });
                            if (flow.closing || flow.invalidated) return;
                            if (result.html) show(result.html);
                            else {
                                const objectUrl = URL.createObjectURL(result.blob);
                                const link = document.createElement("a"); link.href = objectUrl;
                                link.download = "relatorio-sinalizacao.docx"; link.click();
                                setTimeout(() => URL.revokeObjectURL(objectUrl),60000);
                            }
                        } catch (error) { if (!flow.closing) message.textContent = error.message; }
                        finally { form.dataset.sending = "false"; }
                    });
                    doc.addEventListener("click",event => {
                        const link = event.target.closest("a");
                        if (!link || link.target === "_blank") return;
                        event.preventDefault();
                        if (link.getAttribute("href") === "/") finish();
                        else message.textContent = "Encerre o relatório antes de navegar.";
                    });
                };
                // Set only a public base URL; proof remains in the parent manager's closure.
                const parsed = new DOMParser().parseFromString(html,"text/html");
                if (flow.draft?.hasPending() && parsed.querySelector && !parsed.querySelector("[data-waypoint-report-form]")) {
                    message.textContent = "Não foi possível atualizar o relatório. Seus textos foram mantidos; confira a análise e os filtros.";
                    return;
                }
                const base = parsed.createElement("base"); base.href = new URL(flow.url,window.location.href).href;
                // Embedded screen layout only; standalone/print styles stay unchanged.
                const embeddedStyle = parsed.createElement("style");
                embeddedStyle.textContent = "@media screen { html .report-accidents { max-height: none; } }";
                parsed.head.prepend(base,embeddedStyle); frame.srcdoc = "<!doctype html>" + parsed.documentElement.outerHTML;
            }
            try {
                const html = await manager.perform(id,url,{},async res => {
                    if (!res.ok) throw new Error("Não foi possível abrir o relatório.");
                    return res.text();
                });
                show(html);
            } catch (error) { message.textContent = error.message; }
        }
        // Bounded advisory polling, never acquisition. Hidden tabs do no status polling.
        let polling = false;
        window.setInterval(async () => {
            if (document.hidden || polling || manager.snapshot().busy) return;
            polling = true;
            try {
                const ids = [...markers.entries()].filter(([,marker]) =>
                    !map.getBounds || map.getBounds().contains(marker.getLatLng())).map(([id]) => id);
                const batch = ids.slice(pollCursor,pollCursor+4);
                pollCursor = pollCursor+4 >= ids.length ? 0 : pollCursor+4;
                if (current && !batch.includes(current.point.id)) batch.unshift(current.point.id);
                for (const id of batch) {
                    try {
                        const data = await manager.status(id);
                        if (data.stale || (manager.snapshot().pointId === id &&
                                manager.snapshot().state === "acquiring")) continue;
                        badge(id,data.state === "reserved_self" ? "active" : data.state === "reserved_other" ? "occupied" : "available");
                        const binding = bindings.get(id);
                        if (binding && !manager.canOperate(id) && data.state === "available") {
                            binding.message.textContent = "Disponível para edição.";
                            binding.message.hidden = false;
                            binding.retry.hidden = false;
                        }
                    } catch (error) { if (current?.point.id === id) notify(error.message); }
                }
            } finally { polling = false; }
        },3000);
        document.addEventListener("visibilitychange",() => {
            if (document.hidden) manager.suspend(); else manager.resume();
        });
        window.addEventListener("beforeunload",event => {
            if (report?.draft?.hasPending()) { event.preventDefault(); event.returnValue = ""; }
        });
        window.addEventListener("online",() => { if (report && !report.invalidated) void manager.resume(); });
        window.addEventListener("pagehide",() => manager.leave());
        window.addEventListener("pageshow",async () => {
            await manager.resume();
            if (report && manager.snapshot().pointId !== report.id) {
                // BFCache must not restore a form tied to an ended acquisition.
                if (report.draft?.hasPending()) {
                    report.invalidated = true; report.draft.stop();
                    reportControls(report.frame.contentDocument,false);
                } else {
                    report.closing = true; report.draft?.destroy(); report.observer?.disconnect();
                    report.dialog.close(); report.dialog.remove(); report = null;
                }
            }
            bindings.forEach(update);
        });
        // Navigation/logout are blocked while a server operation may still be running.
        document.addEventListener("submit",event => {
            if (event.target.closest(".leaflet-popup")) return;
            if (report?.draft?.hasPending() || manager.snapshot().busy) {
                event.preventDefault(); event.stopImmediatePropagation();
                notify("Conclua as operações ou encerre o relatório resolvendo as alterações pendentes antes de sair.");
            } else manager.leave();
        },true);
        document.addEventListener("click",event => {
            const link = event.target.closest("a");
            if (!link || link.closest(".leaflet-popup") || link.target === "_blank" || link.getAttribute("href")?.startsWith("#")) return;
            if (report?.draft?.hasPending() || manager.snapshot().busy) {
                event.preventDefault(); event.stopImmediatePropagation();
                notify("Conclua as operações ou encerre o relatório resolvendo as alterações pendentes antes de sair.");
            } else manager.leave();
        },true);
        function isOpen(id) {
            return current?.point.id === id || report?.id === id;
        }
        function invalidate(id) {
            manager.invalidate(id);
            if (report?.id === id) {
                if (report.draft?.hasPending()) {
                    report.invalidated = true; report.draft.stop();
                    reportControls(report.frame.contentDocument,false);
                } else {
                    report.closing = true; report.draft?.destroy(); report.observer?.disconnect();
                    report.dialog.close(); report.dialog.remove(); report = null;
                }
            }
            if (current?.point.id === id) current = null;
            notify("Este waypoint foi excluído. Os detalhes foram encerrados.");
        }
        return {bind,begin,end,openReport,notify,confirm,isOpen,invalidate};
    }
}(typeof globalThis !== "undefined" ? globalThis : this));
