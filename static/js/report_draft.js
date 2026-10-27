/* Text-only shared drafts. Reservation ownership stays in the map manager. */
(function(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.ReportDraft = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function() {
    "use strict";
    const fields = ["functional_classification", "geometric_configuration", "regulated_speed",
        "inspection_address", "occurrence_date", "inspection_date", "study_reason",
        "study_objective", "inspector_name", "pgts"];
    const dates = new Set(["occurrence_date", "inspection_date"]);
    const copy = value => JSON.parse(JSON.stringify(value));
    const equal = (a,b) => JSON.stringify(a) === JSON.stringify(b);
    function normalize(values) {
        return Object.fromEntries(fields.map(name => [name, name === "pgts"
            ? (values[name] || []).map(item => item.trim()).filter(Boolean)
            : dates.has(name) ? values[name] || null : values[name] || ""]));
    }
    function create({pointId, initial, request, apply = () => {}, notify = () => {},
        canSave = () => true, schedule = setTimeout, cancel = clearTimeout, delay = 2000}) {
        let local = normalize(initial), base = null, revision = 0, timer = null;
        let posting = false;
        let task = null, stopped = false, paused = false, conflict = false, epoch = 0;
        let recover = false, sent = {}, state = "loading";
        const touched = new Set();
        const dirty = () => fields.filter(name => base
            ? !equal(local[name],base[name]) || (Object.hasOwn(sent,name) && !equal(local[name],sent[name]))
            : touched.has(name));
        function publish(next, detail = "") { state = next; notify({state:next, detail}); }
        function plan() {
            cancel(timer);
            if (!stopped && !paused && !conflict && dirty().length) {
                timer = schedule(() => { timer = null; void save(); },delay);
            }
        }
        function valid(data) {
            if (!data || data.success !== true || data.point_id !== pointId ||
                !Number.isSafeInteger(data.revision) || data.revision < 0 ||
                !data.fields || fields.some(name => name === "pgts"
                    ? !Array.isArray(data.fields[name]) || data.fields[name].some(item => typeof item !== "string")
                    : dates.has(name) ? data.fields[name] !== null && typeof data.fields[name] !== "string"
                    : typeof data.fields[name] !== "string")) {
                throw new Error("Resposta de rascunho inválida.");
            }
            return normalize(data.fields);
        }
        function failed(error) {
            if (error.code === "draft_revision_conflict") {
                conflict = true; publish("conflict");
            } else if (["reservation_expired", "reservation_inactive", "reservation_generation_stale",
                "reservation_credentials_invalid", "authentication_required", "permission_denied",
                "superseded", "reservation_required"].includes(error.code)) {
                stop();
            } else {
                recover = true;
                publish("error", error.message || "Não foi possível confirmar o salvamento.");
            }
        }
        function load() {
            if (task || stopped || paused || conflict) return task || Promise.resolve(false);
            if (!canSave()) { paused = true; return Promise.resolve(false); }
            const version = epoch;
            publish("loading");
            task = (async () => {
                try {
                    const data = await request("GET");
                    if (stopped || version !== epoch) return false;
                    const remote = valid(data), patch = {}, changed = new Set(dirty());
                    // A failed POST may have committed. Reconcile before any retry.
                    if (base && [...changed].some(name => !equal(remote[name],base[name]) &&
                        !equal(remote[name],local[name]) && !equal(remote[name],sent[name]))) {
                        conflict = true; publish("conflict"); return false;
                    }
                    for (const name of fields) {
                        if (!changed.has(name)) {
                            local[name] = copy(remote[name]); patch[name] = copy(remote[name]);
                        }
                    }
                    base = remote; revision = data.revision; recover = false; sent = {};
                    apply(patch); publish(dirty().length ? "pending" : "saved");
                    return true;
                } catch (error) {
                    if (!stopped && version === epoch) failed(error);
                    return false;
                } finally {
                    task = null;
                    if (!recover) plan();
                }
            })();
            return task;
        }
        function save() {
            cancel(timer); timer = null;
            if (task || stopped || paused || conflict) return task || Promise.resolve(false);
            if (!canSave()) { paused = true; return Promise.resolve(false); }
            if (!base || recover) return load();
            const names = dirty();
            if (!names.length) { publish("saved"); return Promise.resolve(true); }
            const patch = Object.fromEntries(names.map(name => [name,copy(local[name])]));
            sent = copy(patch);
            const version = epoch;
            posting = true; publish("saving");
            task = (async () => {
                try {
                    const data = await request("POST", {expected_revision:revision, fields:patch});
                    if (stopped || version !== epoch) return false;
                    const remote = valid(data);
                    if (data.revision !== revision + 1) throw new Error("Revisão de rascunho inválida.");
                    base = remote; revision = data.revision; sent = {}; recover = false;
                    // Never repaint a form from a POST: edits may have happened in flight.
                    publish(dirty().length ? "pending" : "saved");
                    return true;
                } catch (error) {
                    if (!stopped && version === epoch) failed(error);
                    return false;
                } finally {
                    posting = false; task = null;
                    if (!recover) plan();
                }
            })();
            return task;
        }
        async function flush() {
            cancel(timer); timer = null;
            if (task) await task;
            while (!stopped && !paused && !conflict && canSave() && (dirty().length || !base || recover)) {
                const ok = await save();
                if (!ok) break;
            }
            return !dirty().length && !task;
        }
        function stop() {
            stopped = true; epoch++; cancel(timer); timer = null;
            publish("stopped");
        }
        return {
            load, flush, stop,
            edit(values) {
                const next = normalize(values);
                fields.forEach(name => { if (!equal(next[name],local[name])) touched.add(name); });
                local = next;
                if (!stopped && !conflict) { publish(dirty().length ? "pending" : "saved"); plan(); }
            },
            pause() { paused = true; cancel(timer); },
            resume() {
                if (stopped || conflict || !paused) return;
                paused = false;
                if (!base || recover) void load(); else plan();
            },
            retry() { if (stopped || conflict) return Promise.resolve(false); recover = true; return load(); },
            hasPending: () => dirty().length > 0 || posting,
            values: () => copy(local),
            snapshot: () => ({state, revision, stopped, conflict}),
            destroy() { stopped = true; epoch++; cancel(timer); },
        };
    }
    function mount({manager, pointId, doc}) {
        let form, status, retry, attached, controller;
        const labels = {
            loading:"Carregando rascunho…", saving:"Salvando…", saved:"Rascunho salvo.",
            pending:"Alterações pendentes.",
            conflict:"Conflito: o rascunho compartilhado mudou. Seus textos foram mantidos. Copie as alterações antes de encerrar; o salvamento está suspenso.",
            error:"Não foi possível confirmar o salvamento. Seus textos foram mantidos.",
            stopped:"Reserva encerrada. Seus textos foram mantidos para consulta e cópia; o salvamento está suspenso.",
        };
        function read() {
            return Object.fromEntries(fields.map(name => [name, name === "pgts"
                ? Array.from(form.querySelectorAll('[name="pgts"]'),node => node.value)
                : form.querySelector('[name="'+name+'"]')?.value || ""]));
        }
        function write(patch) {
            for (const [name,value] of Object.entries(patch)) {
                if (name !== "pgts") {
                    const input = form.querySelector('[name="'+name+'"]');
                    if (input) input.value = value || "";
                } else {
                    const rows = form.querySelector("[data-pgt-rows]");
                    if (!rows) continue;
                    rows.replaceChildren();
                    for (const text of value.length ? value : [""]) {
                        const row = doc.createElement("div"); row.className = "input-group"; row.dataset.pgtRow = "";
                        const input = doc.createElement("textarea");
                        input.className = "form-control"; input.rows = 1; input.name = "pgts";
                        input.maxLength = 300; input.value = text; input.setAttribute("aria-label","Polo Gerador de Tráfego");
                        const remove = doc.createElement("button"); remove.type = "button";
                        remove.className = "btn btn-outline-danger"; remove.dataset.pgtRemove = "";
                        remove.textContent = "Remover"; remove.setAttribute("aria-label","Remover local");
                        row.append(input,remove); rows.append(row);
                    }
                }
            }
        }
        function display({state,detail}) {
            if (status) status.textContent = labels[state] + (state === "error" && detail ? " " + detail : "");
            if (retry) retry.hidden = state !== "error";
        }
        function attach(nextDoc) {
            const nextForm = nextDoc.querySelector("[data-waypoint-report-form]");
            if (!nextForm) return false;
            if (attached) attached.defaultView.waypointDraftChanged = undefined;
            doc = nextDoc; attached = doc; form = nextForm;
            status = form.querySelector("[data-draft-status]");
            retry = form.querySelector("[data-draft-retry]");
            if (!controller) {
                controller = create({pointId, initial:read(), apply:write, notify:display,
                    canSave:() => manager.canOperate(pointId),
                    request:(method,body) => manager.perform(pointId, form.dataset.draftUrl, {
                        method, ...(body ? {headers:{"Content-Type":"application/json"},body:JSON.stringify(body)} : {}),
                    }),
                });
            } else { write(controller.values()); display(controller.snapshot()); }
            const changed = () => { if (attached === nextDoc) controller.edit(read()); };
            form.addEventListener("input",changed); form.addEventListener("change",changed);
            doc.defaultView.waypointDraftChanged = changed;
            retry?.addEventListener("click",async event => {
                event.preventDefault();
                await manager.resume();
                if (manager.canOperate(pointId)) await controller.retry();
            });
            return true;
        }
        if (!attach(doc)) return null;
        void controller.load();
        return {
            attach, flush:controller.flush, hasPending:controller.hasPending,
            pause:controller.pause, resume:controller.resume, stop:controller.stop,
            destroy() { controller.destroy(); attached.defaultView.waypointDraftChanged = undefined; },
        };
    }
    return {create, mount, fields};
}));
