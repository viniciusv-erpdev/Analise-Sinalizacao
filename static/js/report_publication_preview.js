/* Confirmation UI. Only explicit confirm/recovery actions call the publication flow. */
(function(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.ReportPublicationPreview = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function() {
    "use strict";
    const labels = {loading:"Carregando rascunho", saved:"Salvo", pending:"Altera\u00e7\u00f5es pendentes",
        saving:"Salvando", error:"Falha no salvamento", conflict:"Conflito de revis\u00e3o", stopped:"Salvamento interrompido"};
    function evaluate({authorized, reserved, draft, photos, enabled}) {
        const warnings = [];
        if (!authorized) warnings.push("Autoriza\u00e7\u00e3o de finaliza\u00e7\u00e3o n\u00e3o confirmada.");
        if (!reserved) warnings.push("Reserva ausente, expirada ou ainda n\u00e3o confirmada.");
        const confirmed = draft?.confirmed === true && Number.isSafeInteger(draft.revision) && draft.revision >= 0;
        if (!confirmed) warnings.push("Revis\u00e3o persistida ainda n\u00e3o confirmada pelo backend.");
        if (draft?.pending || draft?.state !== "saved" || draft?.paused || draft?.stopped || draft?.conflict) {
            warnings.push("Aguarde ou resolva o autosave; dados locais n\u00e3o salvos n\u00e3o podem ser publicados.");
        }
        const total = photos.reduce((sum, file) => sum + file.size, 0);
        if (photos.length > 10 || total > 24 * 1024 * 1024 || photos.some(file =>
            !["image/jpeg", "image/png"].includes(file.type) || file.size <= 0 || file.size > 10 * 1024 * 1024)) {
            warnings.push("Confira as fotos: JPEG/PNG, at\u00e9 10 arquivos, 10 MiB por foto e 24 MiB no total.");
        }
        if (!enabled) warnings.push("Finaliza\u00e7\u00e3o desabilitada na configura\u00e7\u00e3o do ambiente.");
        return {ready: warnings.length === 0, warnings, revision:confirmed ? draft.revision : null,
            autosave:labels[draft?.state] || "Estado n\u00e3o confirmado", count:photos.length,
            saveState:draft?.state === "saving" ? "saving" :
                confirmed && draft.state === "saved" && !draft.pending && !draft.paused && !draft.stopped && !draft.conflict ? "saved" : "unsaved"};
    }
    function mount({doc, pointId, manager, draft, flowFactory, environment, onBusy = () => {}}) {
        const open = doc.querySelector("[data-publication-open]");
        const dialog = doc.querySelector("[data-publication-dialog]");
        const form = doc.querySelector("[data-waypoint-report-form]");
        if (!open || !dialog || !form) return null;
        const field = name => dialog.querySelector(`[data-publication-${name}]`);
        let flow = null, destroyed = false, confirmationKey = null;
        const files = () => Array.from(form.querySelector('[name="photos"]')?.files || []);
        function readiness() {
            const state = evaluate({authorized:true, reserved:manager.canOperate(pointId),
                draft:draft?.snapshot(), enabled:dialog.dataset.enabled === "true",photos:files()});
            if (form.checkValidity && !form.checkValidity()) {
                state.ready = false; state.warnings.push("Preencha os campos obrigat\u00f3rios e confira as datas.");
            }
            return state;
        }
        const messages = {
            published:"Publica\u00e7\u00e3o conclu\u00edda", processing:"Publica\u00e7\u00e3o em andamento. Consulte o estado antes de retomar.",
            uncertain:"Resultado n\u00e3o confirmado. Recupere a mesma tentativa; n\u00e3o crie outra publica\u00e7\u00e3o.",
            unavailable:"Falha recuper\u00e1vel ou servi\u00e7o indispon\u00edvel. Consulte a tentativa.",
            retry_required:"Falha recuper\u00e1vel. Confira os dados e retome explicitamente.",
            forbidden:"Permiss\u00e3o insuficiente, sess\u00e3o ou CSRF inv\u00e1lido. Confira sua autentica\u00e7\u00e3o.",
            reservation_error:"Reserva perdida ou expirada. Recupere a reserva pelo fluxo normal antes de retomar.",
            superseded:"Intera\u00e7\u00e3o encerrada. Consulte a tentativa para confirmar o resultado.",
            conflict:"Conflito: confira revis\u00e3o, origem e reserva. A mesma tentativa foi preservada.",
            error:"Falha definitiva da solicita\u00e7\u00e3o. Revise os dados; a tentativa foi preservada.",
        };
        const faults = {
            browser_protection_unavailable:"Este navegador n\u00e3o oferece a prote\u00e7\u00e3o necess\u00e1ria entre abas. Use navegador compat\u00edvel em localhost ou HTTPS.",
            journal_unavailable:"N\u00e3o foi poss\u00edvel preservar a tentativa neste navegador. Publica\u00e7\u00e3o bloqueada; n\u00e3o limpe os dados locais de uma tentativa incerta.",
            other_tab_busy:"H\u00e1 uma publica\u00e7\u00e3o em outra aba. Aguarde e recupere a tentativa existente.",
            preconditions_pending:"Pr\u00e9-condi\u00e7\u00f5es pendentes. Confira reserva, autosave, revis\u00e3o e fotos.",
            original_photos_unavailable:"N\u00e3o foi poss\u00edvel ler ou verificar as fotos. Selecione os arquivos originais novamente.",
            original_photos_required:"Selecione novamente as mesmas fotos originais, na mesma ordem, para recuperar esta tentativa.",
            source_changed:"Os dados mudaram durante a prepara\u00e7\u00e3o. Confira revis\u00e3o e fotos antes de confirmar novamente.",
            reservation_required:"Reserva ausente ou expirada. Use o fluxo normal do waypoint antes de retomar.",
            unresolved_intent:"A tentativa ainda n\u00e3o permite uma nova inten\u00e7\u00e3o. Consulte seu estado antes de continuar.",
            journal_invalid:"O registro local da tentativa est\u00e1 inconsistente. Solicite revis\u00e3o sem apagar uma chave incerta.",
            report_deleted:"Este relat\u00f3rio foi exclu\u00eddo. A inten\u00e7\u00e3o anterior foi preservada; solicite orienta\u00e7\u00e3o antes de iniciar outra.",
            finalization_not_found:"A tentativa n\u00e3o foi encontrada ou est\u00e1 inacess\u00edvel. O resultado anterior continua sem confirma\u00e7\u00e3o; preserve a inten\u00e7\u00e3o e confira seu acesso.",
            autosave_failed:"O autosave n\u00e3o foi conclu\u00eddo. Nenhuma nova publica\u00e7\u00e3o foi solicitada.",
        };
        function eligible(progress) {
            const record = progress?.record, last = record?.last;
            return !!progress?.canStartNew && (last?.kind === "published" || record?.safeToReplace === true ||
                (!record?.attemptId && last?.code === "draft_revision_conflict") ||
                ["report_source_changed","snapshot_integrity_failed","waypoint_not_found"].includes(last?.attempt?.error_code || last?.code));
        }
        function update() {
            if (destroyed) return;
            const state = readiness(), progress = flow?.snapshot();
            field("point").textContent = String(pointId);
            const badge = field("save-status");
            badge.textContent = {saved:"Salvo", unsaved:"N\u00e3o salvo", saving:"Salvando..."}[state.saveState];
            badge.className = `report-save-status report-save-status--${state.saveState}`;
            field("warnings").textContent = state.warnings.join(" ");
            if (!field("confirm")) return; // Graceful preview if the activation module is unavailable.
            const busy = !!progress?.busy, record = progress?.record, outcome = progress?.outcome;
            const replacing = !!confirmationKey && record?.key === confirmationKey && eligible(progress);
            field("confirm").textContent = replacing ? "Confirmar nova publica\u00e7\u00e3o" : "Confirmar publica\u00e7\u00e3o";
            field("confirm").disabled = !state.ready || !progress?.supported || busy || (!!record && !replacing) || ["journal_unavailable","journal_invalid"].includes(outcome?.code) || !!manager.snapshot?.().busy;
            field("cancel").disabled = busy;
            const published = outcome?.kind === "published";
            const errorCode = outcome?.attempt?.error_code || outcome?.code;
            const definitive = ["report_source_changed", "snapshot_integrity_failed", "waypoint_not_found", "idempotency_key_conflict"].includes(errorCode);
            field("confirm").hidden = busy || (!!record && !replacing);
            field("recover").hidden = busy || !record || published || definitive || record?.last?.code === "report_deleted";

            field("recover").disabled = busy || dialog.dataset.enabled !== "true" || (!record?.attemptId && !state.ready);
            field("retry").hidden = busy || published || definitive || !["FAILED","INTERRUPTED"].includes(record?.last?.attempt?.state);
            field("retry").disabled = busy || !state.ready || record?.last?.code === "idempotency_key_conflict";
            const result = field("result");
            const previousFault = ["report_deleted","finalization_not_found"].includes(record?.last?.code) ? faults[record.last.code] :
                record?.last?.kind === "forbidden" ? messages.forbidden : null;
            result.textContent = busy ? "Publica\u00e7\u00e3o em andamento. Aguarde a confirma\u00e7\u00e3o do servidor." :
                outcome ? (previousFault || faults[outcome.code] || messages[outcome.kind] || "Tentativa preservada. Consulte o estado antes de continuar.") :
                !progress?.supported ? faults.browser_protection_unavailable :
                state.ready ? "Pronto para publicar. Confirme para criar o relat\u00f3rio oficial." : "A publica\u00e7\u00e3o ainda n\u00e3o est\u00e1 pronta.";
            if (!busy && ["report_source_changed","snapshot_integrity_failed","waypoint_not_found"].includes(errorCode)) {
                result.textContent = "Falha definitiva desta tentativa: a origem mudou ou n\u00e3o est\u00e1 dispon\u00edvel. O snapshot anterior foi preservado. Revise os dados antes de preparar outro relat\u00f3rio.";
            }
            const link = field("report-link"); link.hidden = true; link.removeAttribute("href");
            if (outcome?.kind === "published" && outcome.attempt?.report_id) {
                result.textContent += ` ${outcome.attempt.number}.`;
                if (dialog.dataset.reportUrl) {
                    link.href = dialog.dataset.reportUrl.replace("00000000-0000-0000-0000-000000000000",outcome.attempt.report_id);
                    link.hidden = false;
                }
            }
            if (replacing && !busy) {
                const previous = record.last?.attempt?.number;
                result.textContent += previous ? ` J\u00e1 existe a publica\u00e7\u00e3o ${previous}.` : " A tentativa anterior pode ser substitu\u00edda ap\u00f3s revalida\u00e7\u00e3o.";
                result.textContent += " Ao confirmar, ser\u00e1 criado outro relat\u00f3rio independente, com novo n\u00famero oficial. A publica\u00e7\u00e3o anterior n\u00e3o ser\u00e1 alterada.";
            }
        }
        const buttonBindings = [];
        if (flowFactory && field("confirm")) {
            let storage;
            try { storage = environment.localStorage; } catch (_) { storage = null; }
            flow = flowFactory.create({manager,draft,pointId,userId:String(dialog.dataset.userId),
                url:dialog.dataset.url,storage,locks:environment.navigator?.locks,crypto:environment.crypto,
                fetch:environment.fetch.bind(environment),photos:files,readiness,
                attemptUrl:(id,retry) => (retry ? dialog.dataset.retryUrl : dialog.dataset.statusUrl)
                    .replace("00000000-0000-0000-0000-000000000000",id),
                notify(progress) { if (!destroyed && flow) { onBusy(progress.busy); update(); } },
            });
            for (const [name,method] of [["confirm","publish"],["recover","recover"],["retry","retry"]]) {
                const button = field(name), handler = async () => {
                    if (button.disabled || button.hidden) return;
                    if (name === "confirm" && confirmationKey) await flow.publishAnother(confirmationKey);
                    else await flow[method]();
                };
                button.addEventListener("click",handler); buttonBindings.push([button,handler]);
            }
        }
        update(); // create() has returned: first render can read the restored journal.
        const storageChanged = () => { if (!flow?.snapshot().busy) flow?.refresh(); };
        environment?.addEventListener("storage",storageChanged);
        let previousOverflow;
        function restoreScroll() {
            if (previousOverflow !== undefined && doc.body?.style) doc.body.style.overflow = previousOverflow;
            previousOverflow = undefined;
        }
        function show() {
            flow?.refresh();
            const progress = flow?.snapshot();
            confirmationKey = eligible(progress) ? progress.record.key : null;
            update();
            if (!dialog.open) {
                if (doc.body?.style) { previousOverflow = doc.body.style.overflow; doc.body.style.overflow = "hidden"; }
                dialog.showModal();
            }
        }
        function close() { if (flow?.snapshot().busy) return; if (dialog.open) dialog.close(); restoreScroll(); open.focus(); }
        function refresh() { if (dialog.open) update(); }
        function cancel(event) { event.preventDefault(); close(); }
        open.addEventListener("click",show);
        field("cancel").addEventListener("click",close);
        dialog.addEventListener("cancel",cancel);
        form.addEventListener("input",refresh); form.addEventListener("change",refresh);
        const unsubscribe = manager.subscribe(refresh);
        const observer = new doc.defaultView.MutationObserver(refresh);
        const status = form.querySelector("[data-draft-status]");
        if (status) observer.observe(status,{childList:true,subtree:true,characterData:true});
        return {busy:() => !!flow?.snapshot().busy, destroy() {
            destroyed = true;
            environment?.removeEventListener("storage",storageChanged);
            buttonBindings.forEach(([button,handler]) => button.removeEventListener("click",handler));
            unsubscribe(); observer.disconnect();
            open.removeEventListener("click",show); field("cancel").removeEventListener("click",close);
            dialog.removeEventListener("cancel",cancel);
            form.removeEventListener("input",refresh); form.removeEventListener("change",refresh);
            if (dialog.open) dialog.close();
            restoreScroll();
        }};
    }
    return {evaluate, mount};
}));
