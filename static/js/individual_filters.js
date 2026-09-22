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

    function matchesPeriod(accident, year, month) {
        if (year === null || year === undefined || year === "") {
            return true;
        }
        if (accident.year !== Number(year)) {
            return false;
        }
        return (
            month === null
            || month === undefined
            || month === ""
            || accident.month === Number(month)
        );
    }

    function monthsForYear(periods, year) {
        const selected = periods.find(
            (period) => Number(period.year) === Number(year)
        );
        return selected ? selected.months.map(Number) : [];
    }

    function countPeriodSummary(summary, year, month) {
        if (year === null || year === undefined || year === "") {
            return Number(summary.total_count) || 0;
        }
        return (summary.counts || []).reduce((total, period) => {
            const matches = (
                Number(period.year) === Number(year)
                && (
                    month === null
                    || month === undefined
                    || month === ""
                    || Number(period.month) === Number(month)
                )
            );
            return total + (matches ? Number(period.count) || 0 : 0);
        }, 0);
    }

    function buildReportFilterQuery({
        analysisId, year, month, categories, gravity,
    }) {
        const parameters = new URLSearchParams();
        if (analysisId) {
            parameters.set("analysis", analysisId);
        }
        if (year !== null && year !== undefined && year !== "") {
            parameters.set("year", String(year));
        }
        if (month !== null && month !== undefined && month !== "") {
            parameters.set("month", String(month));
        }
        categories.forEach((category) => {
            parameters.append("category", category);
        });
        if (gravity && gravity !== "all") {
            parameters.set("gravity", gravity);
        }
        return parameters.toString();
    }

    function filterVisibleAccidents(
        accidents,
        categories,
        gravity,
        year = null,
        month = null
    ) {
        const selectedCategories = new Set(categories);
        return accidents.filter((accident) => {
            const matchesCategory = (
                selectedCategories.size === 0
                || selectedCategories.has(accident.category)
            );
            return (
                matchesCategory
                && matchesGravity(accident, gravity)
                && matchesPeriod(accident, year, month)
            );
        });
    }

    function hasFatalAccident(accidents) {
        return accidents.some((accident) => accident.is_fatal === true);
    }

    function groupByExactCoordinate(accidents) {
        const groups = new Map();
        accidents.forEach((accident) => {
            const coordinateKey = `${accident.latitude},${accident.longitude}`;
            let group = groups.get(coordinateKey);
            if (!group) {
                group = {
                    latitude: accident.latitude,
                    longitude: accident.longitude,
                    accidents: [],
                };
                groups.set(coordinateKey, group);
            }
            group.accidents.push(accident);
        });
        return Array.from(groups.values());
    }

    function normalizePopupIndex(index, visibleCount) {
        if (visibleCount <= 0) {
            return 0;
        }
        return Math.min(Math.max(0, index), visibleCount - 1);
    }

    function movePopupIndex(index, visibleCount, direction) {
        if (visibleCount <= 0) {
            return 0;
        }
        return (index + direction + visibleCount) % visibleCount;
    }

    function replaceOpenPopupContent(popup, content) {
        const popupElement = popup && popup.getElement();
        const contentElement = popupElement && popupElement.querySelector(
            ".leaflet-popup-content"
        );
        if (!contentElement) {
            return false;
        }
        contentElement.replaceChildren(content);
        popup.update();
        return true;
    }

    function openGroupPopupFromCounter(marker, event, stopPropagation) {
        stopPropagation(event);
        marker.openPopup();
    }

    function buildVisibleGroupState(
        accidents,
        categories,
        gravity,
        popupIndex,
        year = null,
        month = null
    ) {
        const visibleAccidents = filterVisibleAccidents(
            accidents,
            categories,
            gravity,
            year,
            month
        );
        return {
            visibleAccidents,
            visibleCount: visibleAccidents.length,
            hasFatal: hasFatalAccident(visibleAccidents),
            popupIndex: normalizePopupIndex(
                popupIndex,
                visibleAccidents.length
            ),
        };
    }

    return {
        buildReportFilterQuery,
        buildVisibleGroupState,
        countPeriodSummary,
        filterVisibleAccidents,
        groupByExactCoordinate,
        hasFatalAccident,
        matchesGravity,
        matchesPeriod,
        monthsForYear,
        movePopupIndex,
        normalizePopupIndex,
        openGroupPopupFromCounter,
        replaceOpenPopupContent,
    };
}));
