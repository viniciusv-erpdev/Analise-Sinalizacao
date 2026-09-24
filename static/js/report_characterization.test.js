"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {init, newSuggestions} = require("./report_characterization.js");

// DOM mínimo apenas para exercitar eventos e valores do formulário, sem dependências.
class Element {
    constructor(tag, dataset = {}) {
        this.tag = tag;
        this.dataset = dataset;
        this.children = [];
        this.listeners = {};
        this.attributes = {};
        this.value = "";
        this.textContent = "";
        this.disabled = false;
    }
    append(...children) {
        children.forEach((child) => {
            child.parent = this;
            child.ownerDocument = this.ownerDocument;
            this.children.push(child);
        });
    }
    matches(selector) {
        if (selector === "textarea" || selector === "form") return this.tag === selector;
        if (selector === "[name=csrfmiddlewaretoken]") return this.name === "csrfmiddlewaretoken";
        const key = selector.slice(6, -1).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        return Object.hasOwn(this.dataset, key);
    }
    querySelectorAll(selector) {
        return this.children.flatMap((child) => [
            ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector),
        ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) {
        if (this.matches(selector)) return this;
        return this.parent ? this.parent.closest(selector) : null;
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    focus() { this.focused = true; }
    remove() { this.parent.children = this.parent.children.filter((child) => child !== this); }
    click() { return this.listeners.click({target: this}); }
}

function page() {
    const document = {createElement: (tag) => new Element(tag)};
    const form = new Element("form");
    form.ownerDocument = document;
    const csrf = new Element("input");
    csrf.name = "csrfmiddlewaretoken";
    csrf.value = "test-csrf";
    const section = new Element("section", {characterization: "", pgtSearchUrl: "/signaling/points/7/pgts/"});
    form.append(csrf, section);
    const editor = new Element("div", {pgtEditor: "", maxItems: "50", maxLength: "300"});
    const search = new Element("button", {pgtSearch: ""});
    search.textContent = "Buscar locais automaticamente";
    const notice = new Element("div", {pgtNotice: ""});
    section.append(editor, search, notice);
    const rows = new Element("div", {pgtRows: ""});
    const add = new Element("button", {pgtAdd: ""});
    editor.append(rows, add);
    init(section);
    return {
        form, section, editor, rows, add, search, notice,
        inputs: () => rows.querySelectorAll("textarea"),
        values: () => rows.querySelectorAll("textarea").map((input) => input.value),
        remove: (index) => {
            const button = rows.children[index].querySelector("[data-pgt-remove]");
            rows.listeners.click({target: button});
        },
    };
}

function mockSearch(t, results) {
    return t.mock.method(globalThis, "fetch", async () => ({
        ok: true, json: async () => ({success: true, results}),
    }));
}

test("deduplica categoria e texto normalizados sem aproximar nomes distintos", () => {
    assert.deepEqual(newSuggestions(
        ["Shopping Manual", "🏥 Unidade de Saúde: Hospital X"],
        ["🏥 Unidade de Saúde: HOSPITAL  X", "Shopping Manual", "Escola Y", "Escola Y", "Escola Z"],
    ), ["Escola Y", "Escola Z"]);
});

test("abrir, adicionar, editar e remover itens manuais não consulta a rede", (t) => {
    const fetch = mockSearch(t, []);
    const ui = page();
    ui.add.click();
    ui.inputs()[0].value = "Shopping Center";
    ui.add.click();
    ui.inputs()[1].value = "Outro local";
    ui.inputs()[0].value = "Shopping revisado";
    ui.remove(1);
    assert.deepEqual(ui.values(), ["Shopping revisado"]);
    assert.equal(ui.inputs()[0].name, "pgts");
    assert.equal(fetch.mock.callCount(), 0);
});

test("busca explícita preserva manual, permite editar/remover e envia CSRF", async (t) => {
    const fetch = mockSearch(t, ["🎓 Unidade escolar: Escola Y", "🏥 Unidade de Saúde: Hospital X"]);
    const ui = page();
    ui.add.click();
    ui.inputs()[0].value = "Shopping Center Exemplo";
    await ui.search.click();
    assert.equal(fetch.mock.callCount(), 1);
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, "/signaling/points/7/pgts/");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["X-CSRFToken"], "test-csrf");
    assert.equal(options.body, undefined);
    ui.inputs()[1].value = "🎓 Unidade escolar: Escola revisada";
    ui.remove(2);
    assert.deepEqual(ui.values(), ["Shopping Center Exemplo", "🎓 Unidade escolar: Escola revisada"]);
    assert.equal(ui.search.disabled, false);
});

test("busca repetida não duplica resultados nem apaga itens manuais", async (t) => {
    mockSearch(t, ["🎓 Unidade escolar: Escola Y"]);
    const ui = page();
    ui.add.click();
    ui.inputs()[0].value = "Manual";
    await ui.search.click();
    await ui.search.click();
    assert.deepEqual(ui.values(), ["Manual", "🎓 Unidade escolar: Escola Y"]);
    assert.match(ui.notice.textContent, /já estão/);
});

test("erro de rede mantém toda a lista editável e restaura botão", async (t) => {
    t.mock.method(globalThis, "fetch", async () => { throw new TypeError("offline"); });
    const ui = page();
    ui.add.click();
    ui.inputs()[0].value = "🏥 Unidade de Saúde: Resultado anterior editado";
    await ui.search.click();
    assert.equal(ui.search.disabled, false);
    assert.match(ui.notice.textContent, /adicionar.*manualmente/);
    ui.add.click();
    ui.inputs()[1].value = "Manual após erro";
    assert.deepEqual(ui.values(), ["🏥 Unidade de Saúde: Resultado anterior editado", "Manual após erro"]);
});

test("erro HTTP, JSON inválido e payload inesperado não alteram a lista", async (t) => {
    const fetch = mockSearch(t, []);
    const ui = page();
    ui.add.click();
    ui.inputs()[0].value = "Manual preservado";
    for (const response of [
        {ok: false, json: async () => ({success: false})},
        {ok: true, json: async () => { throw new SyntaxError("bad JSON"); }},
        {ok: true, json: async () => ({success: true, results: [null]})},
    ]) {
        fetch.mock.mockImplementation(async () => response);
        await ui.search.click();
        assert.deepEqual(ui.values(), ["Manual preservado"]);
        assert.equal(ui.search.disabled, false);
        assert.match(ui.notice.textContent, /Não foi possível/);
    }
});

test("durante busca somente o botão fica ocupado e edições são preservadas", async (t) => {
    let resolve;
    const fetch = t.mock.method(globalThis, "fetch", () => new Promise((done) => { resolve = done; }));
    const ui = page();
    const pending = ui.search.click();
    assert.equal(ui.search.disabled, true);
    assert.equal(ui.add.disabled, false);
    await ui.search.click();
    assert.equal(fetch.mock.callCount(), 1);
    ui.add.click();
    ui.inputs()[0].value = "Escola inserida durante a busca";
    resolve({ok: true, json: async () => ({success: true, results: ["Escola inserida durante a busca"]})});
    await pending;
    assert.deepEqual(ui.values(), ["Escola inserida durante a busca"]);
    assert.equal(ui.search.disabled, false);
});

test("ausência de resultados informa alternativa manual", async (t) => {
    mockSearch(t, []);
    const ui = page();
    await ui.search.click();
    assert.match(ui.notice.textContent, /Nenhum local.*manualmente/);
    ui.add.click();
    assert.equal(ui.inputs().length, 1);
});

test("respeita limite e trata texto HTML como valor editável", async (t) => {
    mockSearch(t, ["<img src=x onerror=alert(1)>", "Segundo", "Terceiro"]);
    const ui = page();
    // O limite configurado para a página é 50.
    for (let index = 0; index < 49; index += 1) {
        ui.add.click();
        ui.inputs()[index].value = "Manual " + index;
    }
    await ui.search.click();
    assert.equal(ui.inputs().length, 50);
    assert.equal(ui.inputs()[49].value, "<img src=x onerror=alert(1)>");
    assert.match(ui.notice.textContent, /Algumas sugestões não foram adicionadas/);
    assert.equal(ui.rows.querySelectorAll("img").length, 0);
});

test("sugestão com emoji no limite de caracteres continua sendo aceita", async (t) => {
    const label = "🏥" + "x".repeat(299);
    mockSearch(t, [label]);
    const ui = page();
    await ui.search.click();
    assert.deepEqual(ui.values(), [label]);
});

test("timeout do navegador restaura botão e preserva preenchimento", async (t) => {
    t.mock.timers.enable({apis: ["setTimeout"]});
    t.mock.method(globalThis, "fetch", (url, options) => new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new DOMException("Timeout", "AbortError")));
    }));
    const ui = page();
    ui.add.click();
    ui.inputs()[0].value = "Manual preservado";
    const pending = ui.search.click();
    t.mock.timers.tick(20000);
    await pending;
    assert.equal(ui.search.disabled, false);
    assert.deepEqual(ui.values(), ["Manual preservado"]);
    assert.match(ui.notice.textContent, /adicionar.*manualmente/);
});
