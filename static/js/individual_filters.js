(function exposeIndividualFilterLogic(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.IndividualAccidentFilters = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function createApi() {
    "use strict";

    function matchesGravity(accident, gravity) {
        if (gravity === "fatal") {
            return accident.is_fatal === true;
        }
        if (gravity === "non_fatal") {
            return accident.is_fatal !== true;
        }
        return true;
    }

    function filterVisibleAccidents(accidents, categories, gravity) {
        const selectedCategories = new Set(categories);
        return accidents.filter((accident) => {
            const matchesCategory = (
                selectedCategories.size === 0
                || selectedCategories.has(accident.category)
            );
            return matchesCategory && matchesGravity(accident, gravity);
        });
    }

    function hasFatalAccident(accidents) {
        return accidents.some((accident) => accident.is_fatal === true);
    }

    return {
        filterVisibleAccidents,
        hasFatalAccident,
        matchesGravity,
    };
}));
