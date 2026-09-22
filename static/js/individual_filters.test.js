"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
    buildReportFilterQuery,
    buildVisibleGroupState,
    countPeriodSummary,
    filterVisibleAccidents,
    groupByExactCoordinate,
    hasFatalAccident,
    movePopupIndex,
    monthsForYear,
    normalizePopupIndex,
    openGroupPopupFromCounter,
    replaceOpenPopupContent,
} = require("./individual_filters.js");

test("serializa o snapshot dos filtros para o link do relatório", () => {
    const query = buildReportFilterQuery({
        analysisId: "analysis-current",
        year: 2025,
        month: 2,
        categories: ["collision", "pedestrian"],
        gravity: "fatal",
    });
    const parameters = new URLSearchParams(query);

    assert.equal(parameters.get("analysis"), "analysis-current");
    assert.equal(parameters.get("year"), "2025");
    assert.equal(parameters.get("month"), "2");
    assert.deepEqual(
        parameters.getAll("category"),
        ["collision", "pedestrian"]
    );
    assert.equal(parameters.get("gravity"), "fatal");
    assert.equal(buildReportFilterQuery({
        year: null, month: null, categories: [], gravity: "all",
    }), "");
});

const mixedGroup = [
    {id: "1", category: "collision", is_fatal: true, year: 2025, month: 1},
    {id: "2", category: "collision", is_fatal: false, year: 2025, month: 2},
    {id: "3", category: "pedestrian", is_fatal: false, year: 2025, month: 2},
];

test("Todos preserva fatais e não fatais", () => {
    assert.deepEqual(
        filterVisibleAccidents(mixedGroup, [], "all").map(({id}) => id),
        ["1", "2", "3"]
    );
});

test("filtros exclusivos de gravidade", () => {
    assert.deepEqual(
        filterVisibleAccidents(mixedGroup, [], "fatal").map(({id}) => id),
        ["1"]
    );
    assert.deepEqual(
        filterVisibleAccidents(mixedGroup, [], "non_fatal").map(({id}) => id),
        ["2", "3"]
    );
});

test("categorias usam OR e combinam com gravidade por AND", () => {
    assert.deepEqual(
        filterVisibleAccidents(
            mixedGroup,
            ["collision", "pedestrian"],
            "fatal"
        ).map(({id}) => id),
        ["1"]
    );
    assert.deepEqual(
        filterVisibleAccidents(mixedGroup, ["collision"], "non_fatal")
            .map(({id}) => id),
        ["2"]
    );
});

test("halo deriva somente dos registros atualmente visíveis", () => {
    const all = filterVisibleAccidents(mixedGroup, [], "all");
    const fatal = filterVisibleAccidents(mixedGroup, [], "fatal");
    const nonFatal = filterVisibleAccidents(mixedGroup, [], "non_fatal");
    const empty = filterVisibleAccidents(mixedGroup, ["crash"], "all");

    assert.equal(hasFatalAccident(all), true);
    assert.equal(hasFatalAccident(fatal), true);
    assert.equal(hasFatalAccident(nonFatal), false);
    assert.equal(hasFatalAccident(empty), false);
    assert.equal(nonFatal.length, 2);
    assert.equal(fatal.length, 1);
    assert.equal(empty.length, 0);
});

test("índice permanece válido ao reduzir grupos de três para dois ou um", () => {
    assert.equal(normalizePopupIndex(2, 3), 2);
    assert.equal(normalizePopupIndex(2, 2), 1);
    assert.equal(normalizePopupIndex(2, 1), 0);
    assert.equal(normalizePopupIndex(2, 0), 0);
});

test("navegação circular alcança todos os registros do grupo", () => {
    assert.equal(movePopupIndex(0, 3, 1), 1);
    assert.equal(movePopupIndex(1, 3, 1), 2);
    assert.equal(movePopupIndex(2, 3, 1), 0);
    assert.equal(movePopupIndex(0, 3, -1), 2);
});

test("atualiza o DOM aberto sem substituir o callback lazy do Leaflet", () => {
    const insertedContent = {id: "novo-conteudo"};
    let receivedContent = null;
    let updateCount = 0;
    const contentElement = {
        replaceChildren(content) {
            receivedContent = content;
        },
    };
    const popup = {
        getElement() {
            return {
                querySelector(selector) {
                    assert.equal(selector, ".leaflet-popup-content");
                    return contentElement;
                },
            };
        },
        update() {
            updateCount += 1;
        },
        setContent() {
            assert.fail("o callback lazy não deve ser substituído");
        },
    };

    assert.equal(replaceOpenPopupContent(popup, insertedContent), true);
    assert.equal(receivedContent, insertedContent);
    assert.equal(updateCount, 1);
});

test("clique no contador abre o popup do grupo associado", () => {
    const event = {type: "click"};
    let stoppedEvent = null;
    let openCount = 0;
    const marker = {
        openPopup() {
            openCount += 1;
        },
    };

    openGroupPopupFromCounter(
        marker,
        event,
        (receivedEvent) => {
            stoppedEvent = receivedEvent;
        }
    );

    assert.equal(stoppedEvent, event);
    assert.equal(openCount, 1);
});

test("grupos preservam IDs diferentes mesmo com os demais campos iguais", () => {
    const sameFields = [
        {id: "10", category: "collision", is_fatal: false},
        {id: "11", category: "collision", is_fatal: false},
    ];

    assert.deepEqual(
        filterVisibleAccidents(sameFields, [], "all").map(({id}) => id),
        ["10", "11"]
    );
});

test("agrupa somente coordenadas numericamente idênticas", () => {
    const groups = groupByExactCoordinate([
        {id: "1", latitude: -21.123456, longitude: -47.123456},
        {id: "2", latitude: -21.123456, longitude: -47.123456},
        {id: "3", latitude: -21.123457, longitude: -47.123456},
    ]);

    assert.equal(groups.length, 2);
    assert.deepEqual(groups[0].accidents.map(({id}) => id), ["1", "2"]);
    assert.deepEqual(groups[1].accidents.map(({id}) => id), ["3"]);
});

test("estado único alimenta contador, popup, índice e halo", () => {
    const all = buildVisibleGroupState(mixedGroup, [], "all", 2);
    const nonFatal = buildVisibleGroupState(
        mixedGroup,
        [],
        "non_fatal",
        all.popupIndex
    );
    const collisionNonFatal = buildVisibleGroupState(
        mixedGroup,
        ["collision"],
        "non_fatal",
        nonFatal.popupIndex
    );
    const empty = buildVisibleGroupState(
        mixedGroup,
        ["crash"],
        "all",
        collisionNonFatal.popupIndex
    );

    assert.deepEqual(all.visibleAccidents.map(({id}) => id), ["1", "2", "3"]);
    assert.equal(all.visibleCount, 3);
    assert.equal(all.hasFatal, true);
    assert.equal(all.popupIndex, 2);

    assert.deepEqual(nonFatal.visibleAccidents.map(({id}) => id), ["2", "3"]);
    assert.equal(nonFatal.visibleCount, 2);
    assert.equal(nonFatal.hasFatal, false);
    assert.equal(nonFatal.popupIndex, 1);

    assert.deepEqual(collisionNonFatal.visibleAccidents.map(({id}) => id), ["2"]);
    assert.equal(collisionNonFatal.visibleCount, 1);
    assert.equal(collisionNonFatal.popupIndex, 0);

    assert.equal(empty.visibleCount, 0);
    assert.equal(empty.hasFatal, false);
    assert.equal(empty.popupIndex, 0);
});

test("período combina com categoria e gravidade e exclui datas inválidas", () => {
    const invalidPeriod = {
        id: "4", category: "collision", is_fatal: false, year: null, month: null,
    };
    const accidents = [...mixedGroup, invalidPeriod];

    assert.deepEqual(
        filterVisibleAccidents(accidents, [], "all", 2025, null)
            .map(({id}) => id),
        ["1", "2", "3"]
    );
    assert.deepEqual(
        filterVisibleAccidents(accidents, [], "all", 2025, 2)
            .map(({id}) => id),
        ["2", "3"]
    );
    assert.deepEqual(
        filterVisibleAccidents(accidents, ["collision"], "non_fatal", 2025, 2)
            .map(({id}) => id),
        ["2"]
    );
    assert.deepEqual(
        filterVisibleAccidents(accidents, [], "all").map(({id}) => id),
        ["1", "2", "3", "4"]
    );
});

test("meses dependem do ano e contagens compactas restauram o total", () => {
    const periods = [
        {year: 2024, months: [12]},
        {year: 2025, months: [1, 2]},
    ];
    const summary = {
        total_count: 4,
        unperiodized_count: 1,
        counts: [
            {year: 2025, month: 1, count: 1},
            {year: 2025, month: 2, count: 2},
        ],
    };

    assert.deepEqual(monthsForYear(periods, 2025), [1, 2]);
    assert.deepEqual(monthsForYear(periods, 2024), [12]);
    assert.equal(countPeriodSummary(summary, null, null), 4);
    assert.equal(countPeriodSummary(summary, 2025, null), 3);
    assert.equal(countPeriodSummary(summary, 2025, 2), 2);
    assert.equal(countPeriodSummary(summary, 2024, null), 0);
});

test("estado do grupo usa período antes de contador, popup e halo", () => {
    const january = buildVisibleGroupState(
        mixedGroup, [], "all", 2, 2025, 1
    );
    const february = buildVisibleGroupState(
        mixedGroup, [], "all", january.popupIndex, 2025, 2
    );

    assert.deepEqual(january.visibleAccidents.map(({id}) => id), ["1"]);
    assert.equal(january.visibleCount, 1);
    assert.equal(january.hasFatal, true);
    assert.equal(january.popupIndex, 0);
    assert.deepEqual(february.visibleAccidents.map(({id}) => id), ["2", "3"]);
    assert.equal(february.visibleCount, 2);
    assert.equal(february.hasFatal, false);
    assert.equal(february.popupIndex, 0);
});
