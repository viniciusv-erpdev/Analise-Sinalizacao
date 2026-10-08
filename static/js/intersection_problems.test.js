"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const {open} = require("./intersection_problems.js");
const signalingSource = fs.readFileSync(path.join(__dirname, "signaling.js"), "utf8");
const template = fs.readFileSync(path.join(__dirname, "../../templates/map.html"), "utf8");

// Minimal DOM/event double: tests run the real screen controller, not its logic copied here.
class Element {
    constructor(tag = "div", document = null) {
        Object.assign(this, {tag, ownerDocument: document, children: [], dataset: {},
            attributes: {}, listeners: {}, className: "", disabled: false, scrollTop: 0,
            style: {}, _text: ""});
    }
    set textContent(text) { this._text = String(text); this.children = []; }
    get textContent() { return this._text + this.children.map((n) => n.textContent).join(""); }
    append(...nodes) { nodes.forEach((node) => { node.parent = this; this.children.push(node); }); }
    replaceChildren(...nodes) { this._text = ""; this.children.forEach((n) => { n.parent = null; }); this.children = []; this.append(...nodes); }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key]; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async fire(type) {
        if (this.disabled) return;
        // DOM propagation follows a path captured BEFORE a handler detaches its target.
        const path = [];
        for (let node = this; node; node = node.parent) path.push(node);
        const event = {target: this, stopped: false, defaultPrevented: false,
            stopPropagation() { this.stopped = true; },
            preventDefault() { this.defaultPrevented = true; }};
        const pending = [];
        for (const node of path) {
            for (const handler of node.listeners[type] || []) pending.push(handler(event));
            if (event.stopped) break;
        }
        await Promise.all(pending);
        if (type === "click" && this.type === "submit" && !event.defaultPrevented) {
            const form = path.find((node) => node.tag === "form");
            if (form) await form.fire("submit");
        }
        return event;
    }
    contains(node) { return node === this || this.children.some((child) => child.contains(node)); }
    set innerHTML(html) {
        this._html = html;
        // Parse only the shell controls used by showPointPopup; dynamic problems use real controller nodes.
        this.replaceChildren();
        for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/gi)) {
            const node = new Element(match[1], this.ownerDocument);
            const cls = match[2].match(/class="([^"]*)"/);
            if (cls) node.className = cls[1];
            for (const attr of match[2].matchAll(/data-([a-z-]+)(?:="([^"]*)")?/g)) {
                node.dataset[attr[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = attr[2] || "";
            }
            if (node.tag === "form") node.elements = {notes: new Element("textarea")};
            this.append(node);
        }
    }
    get innerHTML() { return this._html || ""; }
    focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; }
    matches(selector) {
        if (selector.startsWith(".")) return this.className.split(" ").includes(selector.slice(1));
        if (selector.startsWith("[data-")) {
            const key = selector.slice(6, -1).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
            return Object.hasOwn(this.dataset, key);
        }
        return this.tag === selector;
    }
    querySelectorAll(selector) {
        return this.children.flatMap((node) => [
            ...(node.matches(selector) ? [node] : []), ...node.querySelectorAll(selector),
        ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
}
const catalog = [2, 2, 4, 5, 4].map((count, i) => ({
    code: `P${i + 1}`, text: `Problema recebido ${i + 1}`,
    solutions: Array.from({length: count}, (_, j) => ({
        code: `P${i + 1}${String.fromCharCode(65 + j)}`,
        text: `Solução recebida ${i + 1}-${j + 1}`,
    })),
}));
const record = (id = 15, problem = "P1", solution = "P1A") => ({
    success: true, id, problem_code: problem,
    problem_text: catalog.find((p) => p.code === problem).text,
    solutions: catalog.find((p) => p.code === problem).solutions.filter((s) => (Array.isArray(solution) ? solution : [solution]).includes(s.code)),
});
const urls = {
    collection: "/signaling/points/0/problems/",
    solution: "/signaling/points/0/problems/0/solution/",
    delete: "/signaling/points/0/problems/0/delete/",
};

function screen({saved = [], get, post, confirmation = true, id = 202, main = false} = {}) {
    let persisted = [...saved], nextId = 100, ready;
    const document = {createElement: (tag) => new Element(tag, document)};
    const outside = new Element(), escaped = [], calls = [];
    const popup = {content: null, getContent() { return this.content; },
        getElement() { return this.content; }, update() {}};
    const marker = {
        opened: true, getPopup: () => popup, isPopupOpen() { return this.opened; },
        setPopupContent(content) {
            popup.content = content;
            outside.replaceChildren(...(content instanceof Element ? [content] : []));
        },
    };
    outside.addEventListener("click", (event) => {
        for (let node = event.target; node; node = node.parent) {
            if (node._leaflet_disable_click) return;
        }
        escaped.push("click"); marker.opened = false;
    });
    outside.addEventListener("wheel", () => escaped.push("wheel"));
    const args = {
        document, marker, point: {id}, urls,
        leaflet: {DomEvent: {
            stopPropagation: (event) => event.stopPropagation(),
            disableClickPropagation: (node) => {
                node._leaflet_disable_click = true;
                for (const type of ["mousedown", "touchstart", "dblclick", "contextmenu"]) {
                    node.addEventListener(type, (event) => event.stopPropagation());
                }
            },
            disableScrollPropagation: (node) => node.addEventListener("wheel", (event) => event.stopPropagation()),
        }},
        confirm: () => confirmation,
        onBack: () => { mountMain(); },
        getJson: async (url) => {
            calls.push({method: "GET", url});
            return get ? get() : {success: true, point_id: id, catalog, problems: persisted};
        },
        postJson: async (url, body) => {
            calls.push({method: "POST", url, body});
            if (post) return post(url, body);
            const recordId = Number(url.split("/").at(-3));
            if (url.endsWith("/delete/")) {
                persisted = persisted.filter((item) => item.id !== recordId);
                return {success: true, deleted: true, id: recordId};
            }
            if (url.endsWith("/solution/")) {
                const old = persisted.find((item) => item.id === recordId);
                const updated = record(recordId, old.problem_code, body.solution_codes);
                persisted = persisted.map((item) => item.id === recordId ? updated : item);
                return updated;
            }
            const created = record(nextId++, body.problem_code, body.solution_codes);
            persisted.push(created); return created;
        },
    };
    function mountMain() {
        const article = new Element("article", document);
        const panel = new Element("section", document); panel.dataset.pointProblems = "";
        article.append(panel); marker.setPopupContent(article);
        ready = open({...args, container: panel});
        return ready;
    }
    function create() { ready = open(args); return ready; }
    if (main) mountMain(); else create();
    const root = () => popup.content;
    const choice = (code) => root().querySelectorAll("[data-choice]").find((n) => n.dataset.choice === code);
    const buttons = (text) => root().querySelectorAll("button").filter((n) => n.textContent === text);
    return {get ready() { return ready; }, get root() { return root(); }, args, marker, calls,
        choice, buttons, outside, escaped, create, mountMain,
        submit: () => root().querySelectorAll("button").find((n) => n.type === "submit"),
        click: (code) => choice(code).fire("click"),
        save: () => root().fire("submit"),
        rows: () => root().querySelectorAll("[data-record-id]"),
        writes: () => calls.filter((c) => c.method === "POST"),
        persisted: () => persisted,
    };
}

test("main loads only this waypoint, keeps heading and then shows empty state", async () => {
    const wait = deferred();
    const s = screen({main: true, get: () => wait.promise});
    assert.match(s.root.textContent, /PROBLEMAS E SOLUÇÕES.*Carregando/);
    assert.doesNotMatch(s.root.textContent, /Nenhum problema/);
    assert.deepEqual(s.calls, [{method: "GET", url: "/signaling/points/202/problems/"}]);
    wait.resolve({success: true, point_id: 202, catalog, problems: []}); await s.ready;
    assert.match(s.root.textContent, /Nenhum problema cadastrado/);
});

test("main groups multiple official solution texts under one problem with management actions", async () => {
    const s = screen({main: true, saved: [record(15, "P1", ["P1A", "P1B"]), record(16, "P3", "P3C")]});
    await s.ready;
    assert.equal(s.rows().length, 2);
    assert.equal(s.rows()[0].querySelectorAll("li").length, 2);
    assert.match(s.rows()[0].textContent, /Problema recebido 1/);
    assert.match(s.rows()[0].textContent, /Solução recebida 1-2/);
    assert.equal(s.buttons("Alterar").length, 2);
    assert.equal(s.buttons("Excluir").length, 2);
    assert.doesNotMatch(s.root.textContent, /P1A|P1B/);
    assert.equal(s.submit(), undefined);
});

test("creation has intervention-style back/cancel/save and no management records", async () => {
    const s = screen({saved: [record()]}); await s.ready;
    assert.equal(s.rows().length, 0);
    assert.equal(s.buttons("Alterar").length, 0);
    assert.equal(s.buttons("Excluir").length, 0);
    const back = s.buttons("← Voltar")[0];
    assert.equal(back.className, "btn btn-outline-secondary btn-sm");
    assert.equal(back.type, "button");
    assert.equal(back.dataset.backToSignaling, "");
    assert.equal(s.choice("P1").disabled, true);
    assert.match(s.choice("P1").textContent, /Adicionado/);
    assert.equal(s.choice("P3").disabled, false);
    assert.equal(s.root.querySelectorAll("[data-choice]").length, 5);
    assert.match(template, /\.intersection-problems__list\s*{\s*max-height: 150px/);
    assert.match(template, /\.signaling-interventions-panel\s*{[^}]*overflow-y: auto/s);
});

test("multiselect toggles independently and changing problem clears draft; clicks stay local", async () => {
    const s = screen(); await s.ready;
    await s.click("P1");
    assert.equal(s.submit().disabled, true);
    await s.click("P1A"); await s.click("P1B");
    assert.equal(s.choice("P1A").getAttribute("aria-pressed"), "true");
    assert.equal(s.choice("P1B").getAttribute("aria-pressed"), "true");
    assert.equal(s.submit().disabled, false);
    await s.click("P1A");
    assert.equal(s.choice("P1A").getAttribute("aria-pressed"), "false");
    assert.equal(s.choice("P1B").getAttribute("aria-pressed"), "true");
    await s.click("P3");
    assert.equal(s.choice("P1").getAttribute("aria-pressed"), "false");
    assert.equal(s.choice("P1B"), undefined);
    assert.ok(["P3A", "P3B", "P3C", "P3D"].every((code) => s.choice(code)));
    assert.equal(s.submit().disabled, true);
    assert.deepEqual(s.escaped, []);
    assert.equal(s.marker.opened, true);
});

test("create stays active, resets draft and blocks duplicate using confirmed record; back refetches", async () => {
    const s = screen(); await s.ready;
    const form = s.root;
    const getsBefore = s.calls.filter((call) => call.method === "GET").length;
    await s.click("P1"); await s.click("P1A"); await s.click("P1B");
    await s.submit().fire("click");
    assert.deepEqual(s.writes()[0].body, {problem_code: "P1", solution_codes: ["P1A", "P1B"]});
    assert.equal(s.root, form);
    assert.equal(s.calls.filter((call) => call.method === "GET").length, getsBefore);
    assert.equal(s.rows().length, 0);
    assert.equal(s.choice("P1").disabled, true);
    assert.match(s.choice("P1").textContent, /Adicionado/);
    assert.equal(s.choice("P1").getAttribute("aria-pressed"), "false");
    assert.equal(s.choice("P1A"), undefined);
    assert.equal(s.submit().disabled, true);
    assert.match(s.root.textContent, /Problema e soluções salvos/);
    for (const code of ["P2", "P3", "P4", "P5"]) assert.equal(s.choice(code).disabled, false);
    await s.buttons("← Voltar")[0].fire("click"); await s.ready;
    assert.notEqual(s.root, form);
    assert.equal(s.calls.filter((call) => call.method === "GET").length, getsBefore + 1);
    assert.equal(s.rows().length, 1);
    assert.equal(s.rows()[0].querySelectorAll("li").length, 2);
    assert.deepEqual(s.escaped, []);
});

test("sequential creation sends independent POSTs and stays open until back", async () => {
    const s = screen(); await s.ready;
    const form = s.root;
    for (const [problem, solutions] of [["P1", ["P1A", "P1B"]], ["P3", ["P3A", "P3C"]]]) {
        await s.click(problem);
        for (const code of solutions) await s.click(code);
        await s.save();
        assert.equal(s.root, form);
        assert.equal(s.choice(problem).disabled, true);
    }
    assert.deepEqual(s.writes().map((call) => call.body), [
        {problem_code: "P1", solution_codes: ["P1A", "P1B"]},
        {problem_code: "P3", solution_codes: ["P3A", "P3C"]},
    ]);
    await s.buttons("← Voltar")[0].fire("click"); await s.ready;
    assert.equal(s.rows().length, 2);
    assert.ok(s.rows().every((row) => row.querySelectorAll("li").length === 2));
});

test("all five P4 solutions may be saved at once", async () => {
    const s = screen(); await s.ready;
    await s.click("P4");
    for (const code of ["P4A", "P4B", "P4C", "P4D", "P4E"]) await s.click(code);
    await s.save();
    await s.buttons("← Voltar")[0].fire("click"); await s.ready;
    assert.equal(s.rows()[0].querySelectorAll("li").length, 5);
});

for (const label of ["← Voltar", "Cancelar"]) {
    test(label + " discards draft without POST and returns to same waypoint", async () => {
        const s = screen({saved: [record()]}); await s.ready;
        await s.click("P3"); await s.click("P3A"); await s.click("P3C");
        await s.buttons(label)[0].fire("click"); await s.ready;
        assert.equal(s.writes().length, 0);
        assert.equal(s.rows().length, 1);
        assert.equal(s.marker.opened, true);
        assert.deepEqual(s.escaped, []);
    });
}

test("edit fixes problem, selects persisted set, sends replacement and returns to main", async () => {
    const s = screen({main: true, saved: [record(15, "P1", ["P1A", "P1B"])]}); await s.ready;
    await s.buttons("Alterar")[0].fire("click");
    assert.match(s.root.textContent, /Alterar soluções/);
    assert.equal(s.choice("P1").disabled, true);
    assert.equal(s.choice("P3"), undefined);
    assert.equal(s.choice("P1A").getAttribute("aria-pressed"), "true");
    assert.equal(s.choice("P1B").getAttribute("aria-pressed"), "true");
    await s.click("P1A"); await s.click("P1B");
    assert.equal(s.submit().disabled, true);
    await s.click("P1B");
    await s.save(); await s.ready;
    assert.deepEqual(s.writes()[0], {method: "POST",
        url: "/signaling/points/202/problems/15/solution/", body: {solution_codes: ["P1B"]}});
    assert.equal(s.rows()[0].querySelectorAll("li").length, 1);
    assert.match(s.rows()[0].textContent, /Solução recebida 1-2/);
    assert.deepEqual(s.escaped, []);
});

test("cancel edit preserves confirmed solutions", async () => {
    const s = screen({main: true, saved: [record()]}); await s.ready;
    await s.buttons("Alterar")[0].fire("click");
    await s.click("P1B");
    await s.buttons("Cancelar")[0].fire("click"); await s.ready;
    assert.equal(s.writes().length, 0);
    assert.equal(s.rows()[0].querySelectorAll("li").length, 1);
});

test("delete waits for server, then removes only target and releases creation", async () => {
    const s = screen({main: true, saved: [record(), record(16, "P3", "P3C")]}); await s.ready;
    await s.buttons("Excluir")[0].fire("click");
    assert.equal(s.rows().length, 1);
    assert.equal(s.writes()[0].url, "/signaling/points/202/problems/15/delete/");
    await s.create();
    assert.equal(s.choice("P1").disabled, false);
    assert.deepEqual(s.escaped, []);
});

test("delete does not update optimistically; failure retains record", async () => {
    const wait = deferred();
    const s = screen({main: true, saved: [record()], post: () => wait.promise}); await s.ready;
    const pending = s.buttons("Excluir")[0].fire("click");
    assert.equal(s.rows().length, 1);
    assert.ok(s.root.querySelectorAll("button").every((button) => button.disabled));
    wait.reject(new Error("Falha")); await pending;
    assert.equal(s.rows().length, 1);
    assert.match(s.root.textContent, /Falha/);
});

test("declined deletion sends nothing", async () => {
    const s = screen({main: true, saved: [record()], confirmation: false}); await s.ready;
    await s.buttons("Excluir")[0].fire("click");
    assert.equal(s.writes().length, 0); assert.equal(s.rows().length, 1);
});

for (const editing of [false, true]) {
    test("failed save keeps draft and confirmed values; editing=" + editing, async () => {
        const s = screen({main: editing, saved: editing ? [record()] : [],
            post: async () => { throw new Error("Falha"); }});
        await s.ready;
        if (editing) await s.buttons("Alterar")[0].fire("click");
        else { await s.click("P1"); await s.click("P1A"); }
        await s.click("P1B"); await s.save();
        assert.match(s.root.textContent, /Falha/);
        assert.equal(s.submit().disabled, false);
        assert.equal(s.choice("P1B").getAttribute("aria-pressed"), "true");
        assert.equal(s.persisted().length, editing ? 1 : 0);
        if (editing) assert.equal(s.persisted()[0].solutions.length, 1);
    });
}

test("busy save prevents double submit and late success does not overwrite navigation", async () => {
    const wait = deferred();
    const s = screen({post: () => wait.promise}); await s.ready;
    await s.click("P1"); await s.click("P1A");
    const pending = s.save(); await s.save();
    assert.equal(s.writes().length, 1);
    assert.ok(s.root.querySelectorAll("button").every((button) => button.disabled));
    s.marker.setPopupContent(new Element("article"));
    const replacement = s.root;
    wait.resolve(record()); await pending;
    assert.equal(s.root, replacement);
});

test("main GET error remains local and retry can recover", async () => {
    let failed = true;
    const s = screen({main: true, get: () => {
        if (failed) throw new TypeError("offline");
        return {success: true, point_id: 202, catalog, problems: [record()]};
    }});
    await s.ready;
    assert.equal(s.root.tag, "article");
    assert.match(s.root.textContent, /Verifique a conexão/);
    failed = false;
    await s.buttons("Tentar novamente")[0].fire("click");
    assert.equal(s.rows().length, 1);
    assert.deepEqual(s.escaped, []);
});

test("late GET after another waypoint, reopening or close never updates detached panel", async () => {
    for (const closed of [false, true]) {
        const wait = deferred();
        const s = screen({main: true, get: () => wait.promise});
        const old = s.root, before = old.textContent;
        if (closed) s.marker.opened = false;
        else s.marker.setPopupContent(new Element("article"));
        wait.resolve({success: true, point_id: 202, catalog, problems: [record()]});
        await s.ready;
        assert.equal(old.textContent, before);
    }
});

test("wrong waypoint and malformed data rejected", async () => {
    for (const data of [{success: true, point_id: 999, catalog, problems: []},
        {success: true, point_id: 202, catalog: null, problems: []}]) {
        const s = screen({main: true, get: () => data}); await s.ready;
        assert.match(s.root.textContent, /dados inesperados/);
        assert.equal(s.rows().length, 0);
    }
});

test("scroll is isolated in main and form without preventing native scroll", async () => {
    for (const main of [true, false]) {
        const s = screen({main, saved: [record()]}); await s.ready;
        for (const list of s.root.querySelectorAll("[data-scroll]")) {
            const event = await list.fire("wheel"); assert.equal(event.defaultPrevented, false);
        }
        assert.deepEqual(s.escaped, []);
        await s.outside.fire("wheel"); await s.outside.fire("click");
        assert.deepEqual(s.escaped, ["wheel", "click"]);
    }
});

test("backend texts are text content, not injected HTML", async () => {
    const dangerous = {...record(), problem_text: "<img src=x onerror=bad()>"};
    const s = screen({main: true, saved: [dangerous]}); await s.ready;
    assert.match(s.rows()[0].textContent, /<img/);
    assert.equal(s.rows()[0].querySelectorAll("img").length, 0);
});

function signalingContext(fetch) {
    const config = {dataset: {
        problemsUrlTemplate: urls.collection, problemSolutionUrlTemplate: urls.solution,
        problemDeleteUrlTemplate: urls.delete, hasIndividualAnalysis: "false",
        minSearchRadiusMeters: "10", maxSearchRadiusMeters: "300",
        interventionUrlTemplate: "/signaling/points/0/interventions/",
    }};
    const document = {
        getElementById(id) {
            if (id === "signaling-map-data") return {textContent: "[]"};
            if (id === "signaling-config") return config;
            return null;
        },
        querySelector: () => ({value: "csrf-test"}),
        createElement: (tag) => new Element(tag),
    };
    const map = {createPane() {}, getPane: () => ({style: {}}), on() {}};
    const L = {layerGroup: () => ({addTo() { return this; }}),
        DomEvent: {disableClickPropagation() {}, disableScrollPropagation() {}, stopPropagation() {}}};
    const context = vm.createContext({
        document, map, L, fetch, Element, window: {},
        console: {error() {}}, escapeHtml: (text) => text,
    });
    vm.runInContext(signalingSource, context);
    return context;
}
test("shared request helper retains intervention POST JSON and CSRF; GET has no write", async () => {
    const calls = [];
    const context = signalingContext(async (url, options) => {
        calls.push({url, options});
        return {ok: true, headers: {get: () => "application/json"}, json: async () => ({success: true})};
    });
    await vm.runInContext('postJson("/interventions/", {type: "R1", condition: "OK", notes: "x"})', context);
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers["X-CSRFToken"], "csrf-test");
    assert.deepEqual(JSON.parse(calls[0].options.body), {type: "R1", condition: "OK", notes: "x"});
    await vm.runInContext('requestSignalingJson("/problems/")', context);
    assert.equal(calls[1].options.method, undefined);
    assert.equal(calls[1].options.body, undefined);
});
test("HTTP validation/404 and non-JSON errors retain readable messages", async () => {
    for (const [response, expected] of [
        [{ok: false, headers: {get: () => "application/json"}, json: async () => ({
            errors: {problem_code: ["Já cadastrado"]}})}, /Já cadastrado/],
        [{ok: false, headers: {get: () => "application/json"}, json: async () => ({
            error: "Ponto não encontrado"})}, /Ponto não encontrado/],
        [{ok: false, headers: {get: () => "text/html"}, text: async () => "<html>Erro</html>"}, /resposta inesperada/],
        [{ok: true, headers: {get: () => "application/json"}, json: async () => {
            throw new SyntaxError("invalid JSON");
        }}, /resposta inválida/],
    ]) {
        const context = signalingContext(async () => response);
        await assert.rejects(vm.runInContext('requestSignalingJson("/problems/")', context), expected);
    }
});
test("main button order and actual handlers open problems or the unchanged intervention form", async () => {
    const context = signalingContext(async () => {});
    const nodes = new Map();
    const popupElement = {querySelector(selector) {
        if (selector === "[data-generate-report]") return null;
        if (!nodes.has(selector)) {
            const node = new Element();
            node.elements = {notes: new Element()};
            nodes.set(selector, node);
        }
        return nodes.get(selector);
    }, querySelectorAll: () => []};
    const marker = {
        setPopupContent(html) { this.html = typeof html === "string" ? html : html.innerHTML; },
        getPopup: () => ({getElement: () => popupElement}),
    };
    context.marker = marker;
    context.point = {id: 202, status: "OK", search_radius_meters: 50, interventions: []};
    context.IntersectionProblems = {open(options) { context.opened = options; }};
    vm.runInContext("showPointPopup(marker, point)", context);
    assert.equal(context.opened.container, nodes.get("[data-point-problems]"));
    assert.ok(marker.html.indexOf("Intervenções") < marker.html.indexOf("data-point-problems"));
    assert.ok(marker.html.indexOf("data-point-problems") < marker.html.indexOf("data-add-intervention"));
    assert.ok(marker.html.indexOf("+ Adicionar sinalização")
        < marker.html.indexOf("+ Adicionar problemas e soluções"));
    assert.ok(marker.html.indexOf("+ Adicionar problemas e soluções") < marker.html.indexOf("Excluir ponto"));
    await nodes.get("[data-add-problems]").fire("click");
    assert.equal(context.opened.point.id, 202);
    assert.equal(context.opened.urls.collection, urls.collection);
    context.opened.onBack();
    assert.match(marker.html, /Adicionar sinalização/);
    vm.runInContext("wireInterventionForm = (marker, point) => { window.wiredPoint = point.id; }", context);
    await nodes.get("[data-add-intervention]").fire("click");
    assert.match(marker.html, /Dados 📈/);
    assert.match(marker.html, /data-back-to-signaling/);
    assert.equal(context.window.wiredPoint, 202);
});



test("late delete completion cannot replace another waypoint", async () => {
    const wait = deferred();
    const s = screen({main: true, saved: [record()], post: () => wait.promise}); await s.ready;
    const pending = s.buttons("Excluir")[0].fire("click");
    const other = new Element("article");
    s.marker.setPopupContent(other);
    wait.resolve({success: true, deleted: true, id: 15}); await pending;
    assert.equal(s.root, other);
    assert.equal(other.textContent, "");
});

test("successful edit refetches current server values when reopened", async () => {
    const s = screen({main: true, saved: [record()]}); await s.ready;
    await s.buttons("Alterar")[0].fire("click");
    await s.click("P1B");
    await s.save(); await s.ready;
    await s.buttons("Alterar")[0].fire("click");
    assert.equal(s.choice("P1A").getAttribute("aria-pressed"), "true");
    assert.equal(s.choice("P1B").getAttribute("aria-pressed"), "true");
    assert.equal(s.rows().length, 0);
});

test("showPointPopup survives Leaflet content updates through loading GET and subsequent reconstruction", async () => {
    const waits = [deferred(), deferred(), deferred()];
    let requests = 0;
    const context = signalingContext(async () => ({
        ok: true, headers: {get: () => "application/json"},
        json: () => waits[requests++].promise,
    }));
    context.IntersectionProblems = {open};
    const shell = new Element("div");
    const popup = {
        content: null,
        getContent() { return this.content; },
        getElement: () => shell,
        // Leaflet 1.9.4 DivOverlay.update calls _updateContent: strings reparse; elements reattach.
        update() {
            if (typeof this.content === "string") shell.innerHTML = this.content;
            else shell.replaceChildren(this.content);
        },
    };
    const marker = {
        opened: true, isPopupOpen() { return this.opened; },
        getPopup: () => popup,
        setPopupContent(content) { popup.content = content; popup.update(); },
    };
    context.marker = marker;
    context.point = {id: 202, status: "OK", search_radius_meters: 50, interventions: []};
    vm.runInContext("showPointPopup(marker, point)", context);
    const first = shell.querySelector("[data-point-problems]");
    assert.match(first.textContent, /PROBLEMAS E SOLUÇÕES.*Carregando/);
    popup.update();
    assert.equal(shell.querySelector("[data-point-problems]"), first);
    await new Promise((resolve) => setImmediate(resolve));
    waits[0].resolve({success: true, point_id: 202, catalog, problems: [record(15, "P1", ["P1A", "P1B"])]});
    await new Promise((resolve) => setImmediate(resolve));
    assert.ok(shell.contains(first));
    assert.equal(first.querySelectorAll("[data-record-id]").length, 1);
    assert.equal(first.querySelectorAll("li").length, 2);
    assert.equal(first.querySelectorAll("button").length, 2);
    assert.match(first.textContent, /Solução recebida 1-1/);
    assert.match(first.textContent, /Solução recebida 1-2/);
    popup.update();
    assert.equal(shell.querySelector("[data-point-problems]"), first);
    vm.runInContext("showPointPopup(marker, point)", context);
    await new Promise((resolve) => setImmediate(resolve));
    context.point = {...context.point, id: 203};
    vm.runInContext("showPointPopup(marker, point)", context);
    await new Promise((resolve) => setImmediate(resolve));
    waits[1].resolve({success: true, point_id: 202, catalog, problems: [record()]});
    waits[2].resolve({success: true, point_id: 203, catalog, problems: []});
    await new Promise((resolve) => setImmediate(resolve));
    const current = shell.querySelector("[data-point-problems]");
    assert.notEqual(current, first);
    assert.match(current.textContent, /Nenhum problema cadastrado/);
    assert.equal(current.querySelectorAll("[data-record-id]").length, 0);
});
