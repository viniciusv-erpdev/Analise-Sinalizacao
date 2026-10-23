/* Credentials stay in this document's memory. PostgreSQL remains authoritative. */
(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.WaypointReservations = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";
    const messages = {
        authentication_required: "Sua sessão terminou. Entre novamente; a operação não será reenviada.",
        permission_denied: "Você não tem permissão para esta operação.",
        csrf_failed: "O formulário expirou. Recarregue a página e confira sua sessão.",
        reservation_occupied: "Waypoint ocupado por outra interação, inclusive outra aba.",
        reservation_expired: "A reserva expirou. Inicie uma nova interação.",
        reservation_generation_stale: "Esta aquisição foi substituída. Inicie uma nova interação.",
        reservation_credentials_invalid: "A reserva não pertence a esta interação.",
        reservation_inactive: "A reserva foi encerrada.",
        reservation_required: "Adquira uma reserva antes de continuar.",
        secure_random_unavailable: "Este navegador não oferece geração segura de identificadores. Use um navegador atualizado ou acesse por HTTPS para editar waypoints.",
        network: "Sem confirmação do servidor. Edição suspensa até recuperar a conexão.",
        superseded: "Interação encerrada. O resultado anterior foi descartado.",
    };
    class ReservationError extends Error {
        constructor(code, status = 0, detail) {
            super(messages[code] || detail || "Não foi possível confirmar a reserva.");
            this.code = code; this.status = status;
        }
    }
    function uuidV4(cryptoSource = globalThis.crypto) {
        try {
            if (typeof cryptoSource?.randomUUID === "function") return cryptoSource.randomUUID();
            if (typeof cryptoSource?.getRandomValues === "function") {
                const bytes = new Uint8Array(16);
                cryptoSource.getRandomValues(bytes);
                bytes[6] = (bytes[6] & 0x0f) | 0x40;
                bytes[8] = (bytes[8] & 0x3f) | 0x80;
                const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0"));
                return [hex.slice(0,4), hex.slice(4,6), hex.slice(6,8),
                    hex.slice(8,10), hex.slice(10)].map(part => part.join("")).join("-");
            }
        } catch { /* API failure must also block acquisition safely. */ }
        throw new ReservationError("secure_random_unavailable");
    }
    function create(options) {
        const fetcher = options.fetch;
        const schedule = options.setTimeout || setTimeout;
        const cancel = options.clearTimeout || clearTimeout;
        const now = options.now || (() => performance.now());
        const interval = options.interval || 30000;
        const listeners = new Set();
        let active = null, intent = 0;
        const entries = new Set();
        const statusRequests = new Map();
        function snapshot(entry = active) {
            return entry ? {pointId: entry.id, state: entry.state, busy: entry.busy,
                expiresAt: entry.expiresAt, message: entry.message || "", code: entry.code, closing: entry.closing}
                : {pointId: null, state: "idle", busy: 0};
        }
        function emit(entry, state, error) {
            if (error || state !== entry.state) {
                entry.message = error?.message || ""; entry.code = error?.code;
            }
            entry.state = state;
            listeners.forEach(fn => fn(snapshot(entry)));
        }
        function proof(entry) {
            return {"X-Waypoint-Token": entry.token,
                "X-Waypoint-Interaction": entry.interaction,
                "X-Waypoint-Generation": String(entry.generation)};
        }
        function current(entry) {
            if (active !== entry || entry.closing) throw new ReservationError("superseded");
        }
        function fail(entry, error) {
            if (["network","invalid_response"].includes(error.code)) {
                entry.trusted = false; emit(entry, "uncertain", error);
            }
            else if (error.status === 401 || [403,409,428].includes(error.status)) {
                entry.trusted = false; emit(entry, "lost", error);
                cancel(entry.timer);
            }
        }
        async function response(url, init = {}, timeout = options.workTimeout || 300000) {
            try {
                const deadline = AbortSignal.timeout(timeout);
                const signal = init.signal ? AbortSignal.any([init.signal, deadline]) : deadline;
                return await fetcher(url, {...init, signal, credentials: "same-origin", cache: "no-store"});
            }
            catch (error) {
                if (error instanceof TypeError || ["AbortError","TimeoutError"].includes(error.name)) {
                    throw new ReservationError("network");
                }
                throw error;
            }
        }
        async function json(res) {
            let data;
            try { data = await res.json(); }
            catch { throw new ReservationError(res.status === 401 || res.redirected
                ? "authentication_required" : res.status === 403 ? "csrf_failed" : "invalid_response", res.status); }
            if (!data || typeof data !== "object" || Array.isArray(data)) {
                throw new ReservationError("invalid_response",res.status);
            }
            if (!res.ok || data.success === false) {
                const detail = data.error || (data.errors && Object.entries(data.errors)
                    .map(([field,errors]) => field + ": " + [].concat(errors).join(" ")).join(" "));
                throw new ReservationError(data.code || "request_failed", res.status, detail);
            }
            return data;
        }
        async function send(entry, operation, body, keepalive = false) {
            return json(await response(options.url(entry.id, operation), {
                method: "POST", keepalive,
                headers: {"Content-Type": "application/json", "X-CSRFToken": options.csrf(),
                    ...(operation === "acquire" ? {} : proof(entry))},
                body: JSON.stringify(body || {}),
            }, options.requestTimeout || 20000));
        }
        function heartbeat(entry) {
            cancel(entry.timer);
            if (!entry.token || entry.state === "lost") return;
            entry.timer = schedule(async () => {
                try { await renew(entry); } catch { /* fail() publishes the classified error. */ }
                if (!entry.releasing && (!entry.closing || entry.busy)) heartbeat(entry);
            }, interval);
        }
        async function renew(entry = active) {
            if (!entry?.token || entry.state === "lost") throw new ReservationError("reservation_required");
            if (entry.renewing) return entry.renewing;
            entry.renewing = (async () => {
                emit(entry, "renewing");
                try {
                    const data = await send(entry, "renew");
                    if (data.generation !== entry.generation) throw new ReservationError("reservation_generation_stale",409);
                    entry.confirmedAt = now(); entry.trusted = true; entry.expiresAt = data.expires_at;
                    entry.confirmation = (entry.confirmation || 0) + 1;
                    emit(entry, "active");
                    return data;
                } catch (error) { fail(entry, error); throw error; }
                finally { entry.renewing = null; }
            })();
            return entry.renewing;
        }
        function release(entry, keepalive = false) {
            if (!entry || entry.busy || entry.acquiring) return Promise.resolve();
            if (entry.releasePromise) return entry.releasePromise;
            entry.releasing = true;
            cancel(entry.timer);
            entry.releasePromise = Promise.resolve().then(async () => {
                entry.releaseError = null;
                try {
                    if (entry.renewing) await entry.renewing.catch(() => {});
                    if (entry.token) await send(entry, "release", {}, keepalive);
                    emit(entry, "available");
                } catch (error) {
                    // Retain proof ONLY to retry an authorized release, never to edit.
                    if (!error.status || error.status >= 500 || error.code === "csrf_failed") {
                        entry.releaseError = error;
                    }
                    emit(entry, "release_failed", error);
                } finally {
                    if (!entry.releaseError) { entry.token = null; entries.delete(entry); }
                    entry.releasing = false;
                    entry.releasePromise = null;
                }
            });
            return entry.releasePromise;
        }
        async function finishClosing(id) {
            for (const entry of [...entries]) {
                if (!entry.closing || (id !== undefined && entry.id !== id)) continue;
                if (entry.busy || entry.acquiring) {
                    if (id !== undefined) throw new ReservationError("operation_pending",409,
                        "Aguarde a operação anterior terminar antes de reabrir os detalhes.");
                    continue;
                }
                await release(entry);
                if (id !== undefined && entry.releaseError) throw entry.releaseError;
            }
        }
        async function close(internal = false) {
            if (!internal) intent++;
            const entry = active;
            active = null;
            if (!entry) return;
            entry.closing = true;
            emit(entry, "closing");
            await release(entry);
        }
        async function acquire(id) {
            if (active?.id === id && active.acquiring) return active.acquiring;
            if (active?.id === id && canOperate(id)) return snapshot();
            const request = ++intent;
            await close(true);
            await finishClosing(id);
            if (request !== intent) throw new ReservationError("superseded");
            const entry = {id, interaction: (options.uuid || uuidV4)(), generation: null, token: null,
                busy: 0, closing: false, state: "acquiring"};
            active = entry; entries.add(entry); emit(entry, "acquiring");
            entry.acquiring = (async () => {
                try {
                    const data = await send(entry, "acquire", {interaction_id: entry.interaction});
                    if (!data.token || !Number.isSafeInteger(data.generation) || data.generation < 1 ||
                            data.interaction_id !== entry.interaction || !data.expires_at) {
                        throw new ReservationError("invalid_response");
                    }
                    if (entry.invalidated) throw new ReservationError("superseded");
                    entry.token = data.token; entry.generation = data.generation;
                    entry.expiresAt = data.expires_at; entry.confirmedAt = now(); entry.trusted = true;
                    current(entry);
                    emit(entry, "active"); heartbeat(entry);
                    return snapshot(entry);
                } catch (error) {
                    if (!entry.closing) emit(entry, error.code === "reservation_occupied" ? "occupied"
                        : error.code === "network" ? "uncertain" : "lost", error);
                    throw error;
                } finally {
                    entry.acquiring = null;
                    if (entry.closing) await release(entry);
                }
            })();
            return entry.acquiring;
        }
        function canOperate(id) {
            return active?.id === id && !active.closing && !!active.token && active.trusted === true
                && ["active","renewing"].includes(active.state)
                // Conservative freshness guard after timer suspension; not an expiry decision.
                && now() - active.confirmedAt < interval * 2;
        }
        async function perform(id, url, init = {}, consume = json) {
            const entry = active;
            if (!entry || entry.id !== id || !canOperate(id)) throw new ReservationError("reservation_required");
            entry.busy++; emit(entry, entry.state);
            try {
                await renew(entry); current(entry);
                const res = await response(url, {...init, headers: {...init.headers, ...proof(entry),
                    ...((init.method || "GET") !== "GET" ? {"X-CSRFToken": options.csrf()} : {})}});
                if (res.redirected) throw new ReservationError("authentication_required",401);
                if (!res.ok && res.status !== 400) await json(res);
                const result = await consume(res); // keep lease through streamed body consumption
                current(entry);
                // Server already fences output; confirm again after slow network transfer.
                if ((init.method || "GET") === "GET" || /\/(report|pgts)\//.test(url)) await renew(entry);
                current(entry);
                return result;
            } catch (error) {
                if (error instanceof TypeError || error.name === "AbortError") error = new ReservationError("network");
                fail(entry, error); throw error;
            } finally {
                entry.busy--; emit(entry, entry.state);
                if (entry.closing) await release(entry);
            }
        }
        async function status(id) {
            const entry = active?.id === id ? active : null;
            // Bind this advisory read to the identity and confirmation at SEND time.
            const sentToken = entry?.token || null;
            const confirmation = entry?.confirmation;
            const requestIntent = intent;
            const sequence = (statusRequests.get(id) || 0) + 1;
            statusRequests.set(id,sequence);
            const stillCurrent = () => requestIntent === intent &&
                sequence === statusRequests.get(id) &&
                entry === (active?.id === id ? active : null) &&
                sentToken === (entry?.token || null) &&
                confirmation === entry?.confirmation && !entry?.closing && !entry?.renewing;
            try {
                const data = await json(await response(options.url(id,"status"), {
                    headers: sentToken ? proof(entry) : {},
                }, options.requestTimeout || 20000));
                if (!stillCurrent()) return {stale:true};
                if (sentToken && data.state !== "reserved_self") {
                    fail(entry, new ReservationError("reservation_expired",409));
                }
                return data;
            } catch (error) {
                if (!stillCurrent()) return {stale:true};
                if (entry) fail(entry,error);
                throw error;
            }
        }
        function suspend() {
            if (active?.token && active.state !== "lost") {
                active.trusted = false; emit(active, "uncertain",new ReservationError("network"));
            }
        }
        async function resume() {
            const entry = active;
            if (!entry) { await finishClosing(); return; }
            if (!entry.token || entry.state === "lost") return;
            entry.trusted = false;
            try {
                await renew(entry);
                if (active === entry && !entry.closing) heartbeat(entry);
            } catch { /* state notification; never reacquire automatically */ }
        }
        function invalidate(id) {
            const entry = active;
            if (!entry || entry.id !== id) return;
            intent++; active = null;
            entry.invalidated = true; entry.closing = true; entry.trusted = false; entry.token = null;
            cancel(entry.timer);
            emit(entry,"lost",new ReservationError("waypoint_not_found",404,"Este waypoint foi excluído."));
            if (!entry.busy && !entry.acquiring) entries.delete(entry);
        }
        function leave() {
            // Best effort only; do not release a lease while work is still outstanding.
            intent++;
            active = null;
            for (const entry of entries) {
                entry.closing = true; emit(entry,"closing");
                if (!entry.busy && !entry.acquiring && entry.token) {
                    release(entry,true);
                }
                // Busy work retains its heartbeat and drains through perform()'s finally.
            }
        }
        return {acquire, close, renew: () => renew(), perform, status, canOperate,
            snapshot: () => snapshot(), suspend, resume, leave, invalidate,
            subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }};
    }
    return {create, ReservationError, uuidV4};
}));
