/* Inert client: no DOM handlers, timers, acquisition or automatic publication. */
(function (root, factory) {
    const api = factory(typeof module === "object" && module.exports
        ? require("./waypoint_reservations.js") : root.WaypointReservations);
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.ReportFinalization = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function (reservations) {
    "use strict";
    const states = new Set(["PROCESSING", "STORING", "FINALIZED", "FAILED", "INTERRUPTED"]);
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    function createIntent(options) {
        const { manager, pointId, expectedRevision, url, attemptUrl } = options;
        if (!Number.isSafeInteger(pointId) || pointId < 1 ||
            !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) throw new Error("invalid_intent");
        // URLs must be server-rendered local paths, never arbitrary origins.
        function local(path) {
            if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || /[\\#\r\n]/.test(path)) throw new Error("invalid_url");
            return path;
        }
        local(url);
        const key = options.idempotencyKey || reservations.uuidV4();
        if (!uuid.test(key)) throw new Error("invalid_idempotency_key");
        const photos = [...(options.photos || [])];
        if (options.attemptId && !uuid.test(options.attemptId)) throw new Error("invalid_attempt_id");
        let attempt = options.attemptId ? {attempt_id:options.attemptId, state:"UNKNOWN"} : null;
        let pending = null, last = null, keyConflict = false;
        const fetcher = options.fetch || globalThis.fetch;
        const recovery = () => ({ idempotencyKey: key, attemptId: attempt?.attempt_id || null });
        function remember(data) {
            const candidate = data?.attempt || data;
            if (candidate?.attempt_id && states.has(candidate.state)) {
                if (attempt && candidate.attempt_id !== attempt.attempt_id) throw new Error("attempt_mismatch");
                attempt = { ...candidate };
            }
        }
        function result(kind, extra = {}) {
            last = { kind, attempt: attempt ? { ...attempt } : null, ...extra, recovery: recovery() };
            return last;
        }
        function classify(status, data) {
            if (data?.code === "idempotency_key_conflict") keyConflict = true;
            else remember(data);
            if (status >= 200 && status < 300 && (!states.has(data?.state) ||
                !data.attempt_id || !data.report_id || !Number.isSafeInteger(data.version) ||
                data.version < 1 || typeof data.number !== "string" ||
                (data.state === "FINALIZED" && data.success !== true))) {
                return result("uncertain", { status, code: "invalid_response", ambiguous: true });
            }
            if (status >= 200 && status < 300 && states.has(data?.state)) {
                return result(data.state === "FINALIZED" ? "published" :
                    ["FAILED", "INTERRUPTED"].includes(data.state) ? "retry_required" : "processing", { status });
            }
            const code = data?.code || (status === 403 ? "permission_or_csrf_denied" : "request_failed");
            const kind = status === 401 || status === 403 ? "forbidden" :
                status === 409 || status === 428 ? "conflict" :
                status >= 500 ? "unavailable" : "error";
            return result(kind, { status, code, ambiguous: status >= 500 && !attempt, errors: data?.errors });
        }
        async function envelope(response) {
            if (response.redirected) return { status: 401, data: { code: "authentication_required" } };
            let data;
            try { data = await response.json(); }
            catch (_) { return { status: response.status, data: null }; }
            return { status: response.status, data };
        }
        function payload(retry) {
            if (photos.length) {
                const form = new FormData();
                if (!retry) { form.append("idempotency_key", key); form.append("expected_revision", String(expectedRevision)); }
                photos.forEach(photo => form.append("photos", photo));
                return { body: form, headers: {} };
            }
            return { body: JSON.stringify(retry ? {} : { idempotency_key: key, expected_revision: expectedRevision }),
                headers: { "Content-Type": "application/json" } };
        }
        function run(operation) {
            if (pending) return pending;
            pending = Promise.resolve().then(operation).catch(error => {
                const code = error.code || "network";
                return result(code === "authentication_required" ? "forbidden" : code.startsWith("reservation_") ? "reservation_error" :
                    code === "superseded" ? "superseded" : "uncertain", { code, ambiguous: true });
            }).finally(() => { pending = null; });
            return pending;
        }
        async function post(path, retry) {
            const output = await manager.perform(pointId, local(path), {
                method: "POST", ...payload(retry), credentials: "same-origin", cache: "no-store",
            }, async response => {
                const output = await envelope(response);
                if (output.data?.code !== "idempotency_key_conflict") remember(output.data);
                if (output.status === 401) throw new reservations.ReservationError("authentication_required", 401);
                if (output.data?.code?.startsWith("reservation_")) {
                    throw new reservations.ReservationError(output.data.code, output.status);
                }
                return output;
            }, { consumeErrors: true });
            if (!output.data && output.status < 500 && output.status !== 403) return result("uncertain", { code: "invalid_response", ambiguous: true });
            return classify(output.status, output.data);
        }
        return {
            recovery,
            snapshot: () => last ? { ...last, attempt: last.attempt ? { ...last.attempt } : null } : null,
            submit() {
                if (attempt?.state === "FINALIZED") return Promise.resolve(result("published"));
                // Explicit replay uses the frozen revision, photos, filters and same key.
                return run(() => post(url, false));
            },
            check() {
                if (!attempt) return Promise.resolve(result("unknown", { code: "attempt_id_unknown" }));
                return run(async () => {
                    const response = await fetcher(local(attemptUrl(attempt.attempt_id, false)), {
                        method: "GET", credentials: "same-origin", cache: "no-store",
                        signal: AbortSignal.timeout(options.statusTimeout || 20000),
                    });
                    const output = await envelope(response);
                    if (!output.data) return result("uncertain", { code: "invalid_response", ambiguous: true });
                    return classify(output.status, output.data);
                });
            },
            retry() {
                if (keyConflict || !attempt || !["FAILED", "INTERRUPTED"].includes(attempt.state)) {
                    return Promise.resolve(result("error", { code: "explicit_retry_not_available" }));
                }
                return run(() => post(attemptUrl(attempt.attempt_id, true), true));
            },
        };
    }
    return { createIntent };
}));
