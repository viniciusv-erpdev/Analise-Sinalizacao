"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const IndividualAccidentFilters = require("./individual_filters.js");
const source = fs.readFileSync(path.join(__dirname, "map.js"), "utf8");
const template = fs.readFileSync(path.join(__dirname, "../../templates/map.html"), "utf8");
const colors = Object.fromEntries([...template.matchAll(/(--marker-[\w-]+):\s*(#[\da-f]+);/g)]
    .map((match) => [match[1], match[2]]));

// Execute the complete map entry point with DOM/Leaflet contract doubles.
// This checks application wiring, not browser hit-testing or Canvas painting.
class Element {
    constructor(tag = "div", dataset = {}) {
        Object.assign(this, {tag, dataset, children: [], listeners: {}, style: {
            setProperty(name, value) { this[name] = value; },
        }, textContent: "", checked: false, value: ""});
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    dispatch(type, target = this) {
        (this.listeners[type] || []).forEach((listener) => listener({target}));
    }
    matches(selector) {
        if (selector.includes(",")) return selector.split(",").some((s) => this.matches(s.trim()));
        if (selector.startsWith(".")) return (this.className || "").split(" ").includes(selector.slice(1));
        const match = selector.match(/^\[data-([\w-]+)\](:checked)?$/);
        if (!match) return this.tag === selector;
        const key = match[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        return Object.hasOwn(this.dataset, key) && (!match[2] || this.checked);
    }
    querySelectorAll(selector) {
        return this.children.flatMap((child) => [
            ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector),
        ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const criteria = ["collision_1y_met", "collision_3y_met", "pedestrian_1y_met", "pedestrian_3y_met"];
function point(overrides = {}) {
    return {
        latitude: -21.177512345, longitude: -47.810312345, location: "Rua A <B>",
        collision_criterion: true, pedestrian_criterion: false,
        collision_1y_met: true, collision_3y_met: true,
        pedestrian_1y_met: false, pedestrian_3y_met: false,
        collisions_1y: 3, collisions_3y: 7, pedestrians_1y: 0, pedestrians_3y: 0,
        period_summary: {total_count: 7, counts: [
            {year: 2025, month: 1, count: 5}, {year: 2026, month: 3, count: 2},
        ]},
        ...overrides,
    };
}

function page(data = [point()], mode = "clusters", periods = [{year: 2025, months: [1]}, {year: 2026, months: [3]}]) {
    const document = new Element();
    document.documentElement = new Element("html");
    document.createElement = (tag) => new Element(tag);
    const ids = {};
    const add = (id, element = new Element()) => {
        ids[id] = element;
        document.append(element);
        return element;
    };
    document.getElementById = (id) => ids[id] || null;
    add("map").dataset.hasActiveAnalysis = "true";
    for (const [id, value] of Object.entries({
        "map-data": data, "view-mode": mode, "analysis-id": "analysis-test",
        "available-periods": periods,
    })) add(id).textContent = JSON.stringify(value);
    add("filter-counter");
    add("clear-filters-button");
    add("active-filter-categories");
    const years = add("period-year-filter");
    years.append(new Element("span", {periodSummary: ""}));
    years.append(new Element("input", {periodAllYears: ""}));
    for (const year of [2025, 2026]) {
        const input = new Element("input", {periodYear: ""});
        input.value = String(year);
        years.append(input);
    }
    const months = add("period-month-filter");
    months.append(new Element("span", {periodSummary: ""}), new Element("div", {periodMonthOptions: ""}));
    criteria.forEach((field) => document.append(new Element("input", {filterField: field})));
    for (const category of ["collision", "pedestrian"]) {
        document.append(new Element("input", {individualCategory: category, filterLabel: category}));
    }
    for (const gravity of ["all", "fatal", "non_fatal"]) {
        const input = new Element("input", {individualGravity: ""});
        input.value = gravity;
        input.checked = gravity === "all";
        document.append(input);
    }
    const circles = [], domMarkers = [], icons = [], renderers = [], groups = [];
    const map = {
        panes: {}, layers: new Set(),
        setView() { return this; },
        createPane(name) { this.panes[name] = {style: {}}; },
        getPane(name) { return this.panes[name]; },
    };
    function layer(coordinates, options) {
        return {
            coordinates: Array.from(coordinates), options, listeners: {},
            bindings: 0, builds: 0, open: false,
            bindPopup(content, popupOptions) {
                this.bindings++;
                this.content = content;
                this.popupOptions = popupOptions;
                return this;
            },
            on(type, listener) { (this.listeners[type] ||= []).push(listener); return this; },
            isPopupOpen() { return this.open; },
            closePopup() { this.open = false; return this; },
            openPopup() {
                if (!map.layers.has(this)) return this;
                this.open = true;
                this.builds++;
                this.html = typeof this.content === "function" ? this.content() : this.content;
                return this;
            },
            click() {
                if (!map.layers.has(this) || this.options.interactive === false) return;
                if (this.content) this.openPopup();
                (this.listeners.click || []).forEach((listener) => listener({}));
            },
            setStyle(style) { Object.assign(this.options, style); },
            setIcon(icon) { this.options.icon = icon; },
            bringToFront() {}, bringToBack() {},
        };
    }
    const L = {
        map: () => map,
        tileLayer: () => ({addTo() {}}),
        canvas(options) { const renderer = {options}; renderers.push(renderer); return renderer; },
        circleMarker(coordinates, options) {
            const marker = layer(coordinates, options); circles.push(marker); return marker;
        },
        marker(coordinates, options) {
            const marker = layer(coordinates, options); domMarkers.push(marker); return marker;
        },
        divIcon(options) { icons.push(options); return options; },
        layerGroup() {
            const group = {
                layers: new Set(), adds: 0, removes: 0,
                addTo() { return this; },
                hasLayer(marker) { return this.layers.has(marker); },
                addLayer(marker) { this.adds++; this.layers.add(marker); map.layers.add(marker); },
                removeLayer(marker) {
                    this.removes++; this.layers.delete(marker); map.layers.delete(marker); marker.closePopup();
                },
                clearLayers() { [...this.layers].forEach((marker) => this.removeLayer(marker)); },
            };
            groups.push(group);
            return group;
        },
        control: () => ({addTo() { this.onAdd(); }}),
        DomUtil: {create: (tag) => new Element(tag)},
        DomEvent: {disableClickPropagation() {}, stopPropagation() {}},
    };
    const context = vm.createContext({
        document, L, IndividualAccidentFilters, URLSearchParams,
        window: {localStorage: {getItem: () => null}},
        getComputedStyle: () => ({getPropertyValue: (name) => colors[name] || ""}),
    });
    vm.runInContext(source, context, {filename: "map.js"});
    return {
        circles, domMarkers, icons, renderers, groups, map, document,
        counter: () => ids["filter-counter"].textContent,
        visible: () => circles.filter((marker) => map.layers.has(marker) && marker.options.interactive !== false),
        filter(fields) {
            document.querySelectorAll("[data-filter-field]").forEach((input) => {
                input.checked = fields.includes(input.dataset.filterField);
            });
            document.querySelector("[data-filter-field]").dispatch("change");
        },
        period(selectedYears, selectedMonths) {
            const inputs = years.querySelectorAll("[data-period-year]");
            inputs.forEach((input) => { input.checked = selectedYears.includes(Number(input.value)); });
            years.dispatch("change", inputs[0]);
            const monthInputs = months.querySelectorAll("[data-period-month]");
            monthInputs.forEach((input) => { input.checked = selectedMonths.includes(Number(input.value)); });
            months.dispatch("change", monthInputs[0]);
        },
        clear() { ids["clear-filters-button"].dispatch("click"); },
    };
}

test("eligible points use one Canvas renderer and no DOM icons, retaining exact coordinates and styles", () => {
    const data = [point(), point({latitude: -21.177512346})];
    const p = page(data);
    assert.equal(p.renderers.length, 1);
    assert.equal(p.renderers[0].options.padding, 0.5);
    assert.equal(p.domMarkers.length, 0);
    assert.equal(p.icons.length, 0);
    assert.equal(p.circles.length, 2);
    p.circles.forEach((marker, index) => {
        assert.deepEqual(marker.coordinates, [data[index].latitude, data[index].longitude]);
        assert.equal(marker.options.renderer, p.renderers[0]);
        assert.equal(marker.options.radius, 7);
        assert.equal(marker.options.color, "#ffffff");
        assert.equal(marker.options.weight, 2);
        assert.equal(marker.options.opacity, 1);
        assert.equal(marker.options.fillOpacity, 0.9);
        assert.equal(marker.options.bubblingMouseEvents, false);
        assert.notEqual(marker.options.interactive, false);
    });
    assert.deepEqual(Object.keys(p.map.panes), []); // Default overlay pane; no new pane.
});

test("historical categories retain purple, red and orange, independent of individual colors", () => {
    const p = page([point(), point({collision_criterion: false, pedestrian_criterion: true}),
        point({pedestrian_criterion: true})]);
    assert.deepEqual(p.circles.map((m) => m.options.fillColor), ["#6f42c1", "#dc3545", "#fd7e14"]);
});

test("eligible popups are lazy, belong to the clicked point and keep escaped titles", () => {
    const p = page([point(), point({location: "Rua diferente"})]);
    p.circles.forEach((m) => { assert.equal(typeof m.content, "function"); assert.equal(m.builds, 0); });
    p.circles[1].click();
    assert.match(p.circles[1].html, /Rua diferente/);
    assert.equal(p.circles[0].builds, 0);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Rua A &lt;B&gt;/);
    assert.equal(p.circles[0].popupOptions.maxWidth, 320);
    // Former DivIcon anchor -10 plus Leaflet Popup default offset +7.
    assert.deepEqual(Array.from(p.circles[0].popupOptions.offset), [0, -3]);
});

test("popup separates historical maxima from SP 322 cluster 358's March count", () => {
    // Reference scenario supplied by the temporal audit, not a new CSV analysis.
    const data = point({cluster_id: 358, location: "SP 322", eligible: true,
        collisions_1y: 6, collisions_3y: 7,
        period_summary: {total_count: 7, counts: [
            {year: 2025, month: 1, count: 6}, {year: 2026, month: 3, count: 1},
        ]}});
    const before = JSON.stringify(data);
    const p = page([data]);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Todos os períodos disponíveis/);
    assert.match(p.circles[0].html, /<strong>7<\/strong>/);
    p.period([2026], [3]);
    assert.equal(p.circles[0].isPopupOpen(), false);
    assert.equal(p.visible().length, 1);
    p.circles[0].click();
    const html = p.circles[0].html;
    assert.match(html, /Critérios históricos atendidos/);
    assert.match(html, /3\+ em 1 ano/);
    assert.match(html, /7\+ em 3 anos/);
    assert.match(html, /Máximos históricos em janelas de 1 e 3 anos/);
    assert.match(html, /Janela histórica/);
    assert.match(html, /<td>1 ano<\/td>\s*<td>6<\/td>/);
    assert.match(html, /<td>3 anos<\/td>\s*<td>7<\/td>/);
    assert.match(html, /janelas históricas diferentes/);
    assert.match(html, /Período visualizado/);
    assert.match(html, /Março de 2026/);
    assert.match(html, /Sinistros associados no período/);
    assert.match(html, /<strong>1<\/strong>/);
    assert.match(html, /todos os tipos de sinistro associados ao local/);
    assert.match(html, /não recalcula sua elegibilidade histórica/);
    assert.equal(JSON.stringify(data), before);
    assert.equal(p.circles[0].options.fillColor, "#6f42c1");
    p.clear();
    p.circles[0].click();
    assert.match(p.circles[0].html, /<strong>7<\/strong>/);
});

test("multiple years/months describe only existing pairs, including month-only filtering", () => {
    const p = page();
    p.period([2025, 2026], [1, 3]);
    p.circles[0].click();
    assert.match(p.circles[0].html, /2025: Janeiro; 2026: Março/);
    assert.doesNotMatch(p.circles[0].html, /Março de 2025|Janeiro de 2026/);
    assert.match(p.circles[0].html, /<strong>7<\/strong>/);
    p.period([], [3]);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Março de 2026/);
    assert.match(p.circles[0].html, /<strong>2<\/strong>/);
    p.period([2025, 2026], []);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Todos os meses disponíveis de 2025 e 2026/);
});

test("several months of one year use readable names; long selections use abbreviations", () => {
    const p = page([point()], "clusters", [{year: 2026, months: [1, 2, 3, 4, 6, 10]}]);
    p.period([2026], [3, 4]);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Março e Abril de 2026/);
    p.period([2026], [1, 2, 3, 4, 6, 10]);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Jan, Fev, Mar, Abr, Jun e Out de 2026/);
    p.period([2026], []);
    p.circles[0].click();
    assert.match(p.circles[0].html, /Todos os meses disponíveis de 2026/);
});

test("aggregate occurrence from another type does not change collision eligibility presentation", () => {
    // The aggregate payload intentionally does not distinguish types. This one
    // March occurrence can be a CHOQUE; the UI must not call it a collision.
    const p = page([point({collisions_1y: 6, collisions_3y: 7,
        period_summary: {total_count: 8, counts: [
            {year: 2025, month: 1, count: 7}, {year: 2026, month: 3, count: 1},
        ]}})]);
    p.period([2026], [3]);
    assert.equal(p.visible().length, 1);
    p.circles[0].click();
    const html = p.circles[0].html;
    assert.match(html, /Sinistros associados no período/);
    assert.match(html, /<strong>1<\/strong>/);
    assert.match(html, /todos os tipos de sinistro/);
    assert.match(html, /7\+ em 3 anos/);
    assert.equal(p.circles[0].options.fillColor, "#6f42c1");
});

for (const field of criteria) {
    test("historical filter preserves visibility: " + field, () => {
        const flags = Object.fromEntries(criteria.map((key) => [key, false]));
        const p = page(criteria.map((key, i) => point({...flags, [key]: true, latitude: -21 - i})));
        p.filter([field]);
        assert.deepEqual(p.visible(), [p.circles[criteria.indexOf(field)]]);
        assert.equal(p.counter(), "1 de 4 locais exibidos");
    });
}

test("historical filters use OR, combined with temporal visibility by AND", () => {
    const p = page([
        point(), point({collision_1y_met: false, collision_3y_met: false, pedestrian_1y_met: true}),
        point({period_summary: {total_count: 7, counts: [{year: 2025, month: 1, count: 7}]}}),
    ]);
    p.filter(["collision_1y_met", "pedestrian_1y_met"]);
    assert.equal(p.visible().length, 3);
    p.period([2026], [3]);
    assert.deepEqual(p.visible(), p.circles.slice(0, 2));
    assert.equal(p.counter(), "2 de 3 locais exibidos");
});

test("unavailable months reset selection; hidden layers cannot open popup and are reused", () => {
    const p = page();
    const marker = p.circles[0];
    marker.click();
    p.period([2025], [3]); // March unavailable in 2025: UI falls back to all months.
    assert.equal(p.visible().length, 1);
    p.period([2025, 2026], [1, 3]);
    assert.equal(p.visible().length, 1);
    p.period([2026], []);
    assert.equal(p.visible().length, 1);
    p.filter(["pedestrian_1y_met"]);
    assert.equal(p.map.layers.has(marker), false);
    assert.equal(marker.open, false);
    const builds = marker.builds;
    marker.click();
    assert.equal(marker.builds, builds);
    p.clear();
    assert.deepEqual(p.visible(), [marker]);
    assert.equal(marker.bindings, 1);
});

test("point without selected-period occurrences is hidden even when historically eligible", () => {
    const p = page([point({period_summary: {total_count: 7, counts: [{year: 2025, month: 1, count: 7}]}})]);
    p.circles[0].click();
    p.period([2026], [3]);
    assert.equal(p.visible().length, 0);
    assert.equal(p.circles[0].isPopupOpen(), false);
    assert.equal(p.counter(), "0 de 1 locais exibidos");
    p.clear();
    assert.equal(p.visible().length, 1);
});

test("multi-year/month selections count visible locations, not their historical accidents", () => {
    const p = page([point(), point({period_summary: {total_count: 9, counts: [{year: 2025, month: 1, count: 9}]}})]);
    p.period([2026], [3]);
    assert.equal(p.counter(), "1 de 2 locais exibidos");
    p.period([2025, 2026], [1, 3]);
    assert.equal(p.counter(), "2 de 2 locais exibidos");
    p.period([], [1]);
    assert.equal(p.counter(), "2 de 2 locais exibidos");
});

test("unchanged filters do not re-add layers, recreate markers, render HTML or rebind popups", () => {
    const p = page();
    const group = p.groups[0];
    for (let i = 0; i < 20; i++) p.filter(["collision_1y_met"]);
    assert.equal(group.adds, 1);
    assert.equal(group.removes, 0);
    assert.equal(p.circles.length, 1);
    assert.equal(p.renderers.length, 1);
    assert.equal(p.circles[0].bindings, 1);
    assert.equal(p.circles[0].builds, 0);
    for (let i = 0; i < 20; i++) { p.filter(["pedestrian_1y_met"]); p.clear(); }
    assert.equal(group.layers.size, 1);
    assert.equal(p.circles.length, 1);
    assert.equal(p.circles[0].bindings, 1);
});

test("empty eligible payload initializes safely and disables criteria", () => {
    const p = page([]);
    assert.equal(p.circles.length, 0);
    assert.equal(p.map.layers.size, 0);
    assert.equal(p.counter(), "0 de 0 locais exibidos");
    assert.ok(p.document.querySelectorAll("[data-filter-field]").every((input) => input.disabled));
    p.clear();
});

const accident = (overrides = {}) => ({
    latitude: -21.1775, longitude: -47.8103, category: "collision",
    id: "a", is_fatal: false, year: 2026, month: 3, modes: [],
    date: "01/03/2026", accident_type: "COLISAO", record_type: "NAO FATAL", street: "Rua A",
    ...overrides,
});

test("individual mode retains grouping, halo, badge, colors, popup navigation and filtered counter", () => {
    const p = page([accident(), accident({id: "b", category: "pedestrian", is_fatal: true})], "individual");
    assert.equal(p.renderers.length, 1);
    assert.equal(p.circles.length, 2); // One group and its halo.
    assert.ok(p.circles.every((m) => m.options.renderer === p.renderers[0]));
    assert.equal(p.visible().length, 1);
    assert.equal(p.circles[0].options.fillColor, "#6c757d");
    assert.equal(p.circles[1].options.interactive, false);
    assert.equal(p.circles[1].options.radius, 13);
    assert.equal(p.domMarkers.length, 1);
    assert.match(p.domMarkers[0].options.icon.html, />2</);
    assert.equal(p.map.panes.individualCounterPane.style.zIndex, "450");
    p.circles[0].click();
    assert.equal(p.circles[0].html.querySelectorAll("button").length, 2);
    assert.equal(p.counter(), "2 de 2 sinistros exibidos");
    const category = p.document.querySelectorAll("[data-individual-category]")[0];
    category.checked = true;
    category.dispatch("change");
    assert.equal(p.counter(), "1 de 2 sinistros exibidos");
    assert.equal(p.circles[0].options.fillColor, "#0d6efd");
    assert.equal(p.map.layers.has(p.circles[1]), false);
    assert.equal(p.map.layers.has(p.domMarkers[0]), false);
    p.circles[0].click();
    assert.equal(p.circles[0].html.querySelectorAll("button").length, 0);
    p.period([2025], [1]);
    assert.equal(p.counter(), "0 de 2 sinistros exibidos");
});

test("mode changes and replacement uploads initialize isolated documents without stale layers", () => {
    // The upload form submits normally; each response executes map.js in a new document.
    assert.match(template, /id="upload-form"\s+method="post"/);
    const previousLayers = new Set();
    for (const mode of ["clusters", "individual", "clusters", "individual", "clusters"]) {
        const data = mode === "individual" ? [accident()] : [point({location: "Upload " + previousLayers.size})];
        const p = page(data, mode);
        assert.equal(p.renderers.length, 1);
        assert.equal(p.visible().length, 1);
        p.circles.forEach((marker) => {
            assert.equal(previousLayers.has(marker), false);
            previousLayers.add(marker);
        });
        p.circles[0].click();
        if (mode === "clusters") assert.ok(p.circles[0].html.includes(data[0].location));
    }
    assert.equal(page([]).visible().length, 0);
});
