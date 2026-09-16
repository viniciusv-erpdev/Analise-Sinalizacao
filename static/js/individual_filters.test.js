"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
    filterVisibleAccidents,
    hasFatalAccident,
} = require("./individual_filters.js");

const mixedGroup = [
    {id: "1", category: "collision", is_fatal: true},
    {id: "2", category: "collision", is_fatal: false},
    {id: "3", category: "pedestrian", is_fatal: false},
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
