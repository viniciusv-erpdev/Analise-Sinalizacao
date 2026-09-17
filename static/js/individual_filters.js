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
        popupIndex
    ) {
        const visibleAccidents = filterVisibleAccidents(
            accidents,
            categories,
            gravity
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
        buildVisibleGroupState,
        filterVisibleAccidents,
        groupByExactCoordinate,
        hasFatalAccident,
        matchesGravity,
        movePopupIndex,
        normalizePopupIndex,
        openGroupPopupFromCounter,
        replaceOpenPopupContent,
    };
}));
