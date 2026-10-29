/* Explicit publication controller. Journal contains no reservation proof or file bytes. */
(function(root, factory) {
    const api = factory(typeof module === "object" && module.exports ? require("./report_finalization.js") : root.ReportFinalization,
        typeof module === "object" && module.exports ? require("./waypoint_reservations.js") : root.WaypointReservations);
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.ReportPublicationFlow = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function(finalization, reservations) {
    "use strict";
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    const copy = value => value == null ? null : JSON.parse(JSON.stringify(value));
    function fault(code) { const error = new Error(code); error.code = code; return error; }
    function create(options) {
        const {storage, locks, crypto, userId, pointId, draft, readiness, photos, manager, notify = () => {}} = options;
        const journalKey = `rtsv.publication.v1.u${userId}.p${pointId}`;
        const supported = !!(storage && locks?.request && crypto?.subtle?.digest && /^\d+$/.test(String(userId)) && Number.isSafeInteger(pointId) && pointId > 0);
        let record = null, pending = null, outcome = null;
        function read() {
            const raw = storage?.getItem(journalKey);
            if (!raw) return null;
            const value = JSON.parse(raw);
            if (value.schema !== 1 || !uuid.test(value.key) || value.pointId !== pointId || value.userId !== userId ||
                !Number.isSafeInteger(value.revision) || value.revision < 0 || !Array.isArray(value.photos) ||
                typeof value.url !== "string" || typeof value.last?.kind !== "string" || (value.attemptId && !uuid.test(value.attemptId))) throw fault("journal_invalid");
            return value;
        }
        function write(value) {
            // Persist before ANY side effect; a failed write blocks the POST.
            const serialized = JSON.stringify(value);
            storage.setItem(journalKey, serialized);
            if (storage.getItem(journalKey) !== serialized) throw fault("journal_unavailable");
            record = value;
        }
        function refresh() {
            try { record = read(); outcome = record?.last || null; }
            catch (_) { outcome = {kind:"blocked",code:"journal_unavailable"}; }
            notify(snapshot());
        }
        function canStartNew() {
            return record?.safeToReplace === true || record?.last?.kind === "published" ||
                ["FAILED","INTERRUPTED"].includes(record?.last?.attempt?.state) ||
                (!record?.attemptId && record?.last?.kind === "conflict" && record?.last?.code === "draft_revision_conflict");
        }
        function snapshot() { return {supported, busy:!!pending, canStartNew:canStartNew(), record:copy(record), outcome:copy(outcome)}; }
        function requireReady() {
            const state = readiness();
            if (!state.ready) throw fault("preconditions_pending");
            if (!manager.canOperate(pointId)) throw fault("reservation_required");
            return state;
        }
        async function fingerprints(files) {
            try {
                return await Promise.all(files.map(async file => ({size:file.size, type:file.type,
                    sha256:Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer())),
                        byte => byte.toString(16).padStart(2,"0")).join("")})));
            } catch (_) { throw fault("original_photos_unavailable"); }
        }
        function client(value, files) {
            return finalization.createIntent({manager,pointId,expectedRevision:value.revision,
                idempotencyKey:value.key,attemptId:value.attemptId || undefined,
                url:value.url,photos:files,attemptUrl:options.attemptUrl,fetch:options.fetch});
        }
        function saveResult(result, initial = false) {
            const last = {kind:result.kind,code:result.code || result.attempt?.error_code || "",attempt:result.attempt || null};
            const next = {...record,last,attemptId:result.recovery?.attemptId || record.attemptId,
                // Only a definitive 400 on the FIRST send proves a rejected payload
                // has no prior unknown publication under this newly generated key.
                safeToReplace:initial && result.status === 400 && result.kind === "error" &&
                    result.code === "invalid_finalization_payload" && !result.attempt};
            write(next); outcome = last;
            return result;
        }
        async function originals() {
            const files = [...photos()];
            if (JSON.stringify(await fingerprints(files)) !== JSON.stringify(record.photos)) throw fault("original_photos_required");
            return files;
        }
        function run(operation) {
            if (pending) return pending;
            pending = Promise.resolve().then(async () => {
                if (!supported) throw fault("browser_protection_unavailable");
                return locks.request(journalKey,{mode:"exclusive",ifAvailable:true},async lock => {
                    if (!lock) throw fault("other_tab_busy");
                    record = read();
                    return operation();
                });
            }).catch(error => {
                outcome = {kind:"blocked",code:error.code || "journal_unavailable"};
                return outcome;
            }).finally(() => { pending = null; notify(snapshot()); });
            notify(snapshot());
            return pending;
        }
        refresh();
        return {
            snapshot, refresh,
            publish() { return run(async () => {
                if (record) { outcome = record.last; return {kind:"existing_intent"}; }
                requireReady();
                if (!await draft.flush()) throw fault("autosave_failed");
                const state = requireReady(), files = [...photos()];
                const hashes = await fingerprints(files);
                if (requireReady().revision !== state.revision || files.some((file,index) => file !== photos()[index]) || files.length !== photos().length) throw fault("source_changed");
                const value = {schema:1,userId,pointId,key:reservations.uuidV4(crypto),revision:state.revision,
                    url:options.url,photos:hashes,attemptId:null,last:{kind:"uncertain",code:"confirmation_pending"}};
                write(value);
                return saveResult(await client(value,files).submit(), true);
            }); },
            recover() { return run(async () => {
                if (!record) throw fault("intent_missing");
                if (record.attemptId) return saveResult(await client(record,[]).check());
                // No lookup-by-key endpoint exists: explicit replay is the only recovery.
                requireReady();
                const files = await originals(); requireReady();
                return saveResult(await client(record,files).submit());
            }); },
            retry() { return run(async () => {
                if (!record?.attemptId || record.last?.code === "idempotency_key_conflict") throw fault("retry_unavailable");
                const files = await originals(), intent = client(record,files);
                const current = await intent.check(); saveResult(current);
                if (!["FAILED","INTERRUPTED"].includes(current.attempt?.state)) return current;
                requireReady();
                return saveResult(await intent.retry());
            }); },
            newReport() { return run(async () => {
                if (!canStartNew()) throw fault("unresolved_intent");
                if (record.attemptId) {
                    const wasPublished = record.last.kind === "published";
                    const current = await client(record,[]).check(); saveResult(current);
                    if (current.kind === "published" && !wasPublished) return current;
                    if (current.kind !== "published" && !["FAILED","INTERRUPTED"].includes(current.attempt?.state)) throw fault("unresolved_intent");
                }
                // A pre-capture draft_revision_conflict without an attempt is definitive:
                // the server checks existing keys before validating that revision.
                storage.removeItem(journalKey); record = null; outcome = null;
                // A new UUID is created only by a subsequent explicit publish().
                return {kind:"ready"};
            }); },
        };
    }
    return {create};
}));
