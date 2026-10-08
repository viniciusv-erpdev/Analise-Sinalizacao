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

    function normalizeSelections(values) {
        if (!Array.isArray(values)) {
            return values === null || values === undefined || values === ""
                ? []
                : [Number(values)];
        }
        return values.map(Number);
    }

    function matchesPeriod(accident, years, months) {
        const selectedYears = normalizeSelections(years);
        const selectedMonths = normalizeSelections(months);
        if (
            selectedYears.length > 0
            && !selectedYears.includes(Number(accident.year))
        ) {
            return false;
        }
        return selectedMonths.length === 0
            || selectedMonths.includes(Number(accident.month));
    }

    function monthsForYears(periods, years) {
        const selectedYears = new Set(normalizeSelections(years));
        const months = new Set();
        periods.forEach((period) => {
            if (
                selectedYears.size === 0
                || selectedYears.has(Number(period.year))
            ) {
                period.months.map(Number).forEach((month) => months.add(month));
            }
        });
        return Array.from(months).sort((left, right) => left - right);
    }

    function countPeriodSummary(summary, years, months) {
        const selectedYears = normalizeSelections(years);
        const selectedMonths = normalizeSelections(months);
        if (selectedYears.length === 0 && selectedMonths.length === 0) {
            return Number(summary.total_count) || 0;
        }
        return (summary.counts || []).reduce((total, period) => {
            const matches = (
                (selectedYears.length === 0
                    || selectedYears.includes(Number(period.year)))
                && (selectedMonths.length === 0
                    || selectedMonths.includes(Number(period.month)))
            );
            return total + (matches ? Number(period.count) || 0 : 0);
        }, 0);
    }

    function buildReportFilterQuery({
        analysisId, years, months, categories, gravity,
    }) {
        const parameters = new URLSearchParams();
        if (analysisId) {
            parameters.set("analysis", analysisId);
        }
        normalizeSelections(years).forEach((year) => {
            parameters.append("year", String(year));
        });
        normalizeSelections(months).forEach((month) => {
            parameters.append("month", String(month));
        });
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
        years = [],
        months = []
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
                && matchesPeriod(accident, years, months)
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
        years = [],
        months = []
    ) {
        const visibleAccidents = filterVisibleAccidents(
            accidents,
            categories,
            gravity,
            years,
            months
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
        monthsForYears,
        movePopupIndex,
        normalizePopupIndex,
        openGroupPopupFromCounter,
        replaceOpenPopupContent,
    };
}));
