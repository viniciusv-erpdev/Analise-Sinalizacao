const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const fileSelectionSummary = document.getElementById(
    "file-selection-summary"
);
const selectedFiles = document.getElementById("selected-files");
const analyzeButton = document.getElementById("analyze-button");
const clearFilesButton = document.getElementById("clear-files-button");
const toolsPanel = document.getElementById("tools-panel");
const minimizeToolsPanel = document.getElementById(
    "minimize-tools-panel"
);
const openToolsPanel = document.getElementById("open-tools-panel");
const toolsTabs = Array.from(
    document.querySelectorAll("[data-tools-tab]")
);
const toolsTabPanels = Array.from(
    document.querySelectorAll("[data-tools-tab-panel]")
);


function formatFileSize(bytes) {
    if (bytes === 0) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    const unitIndex = Math.min(
        Math.floor(Math.log(bytes) / Math.log(1024)),
        units.length - 1
    );
    const value = bytes / (1024 ** unitIndex);

    return `${value.toLocaleString("pt-BR", {
        maximumFractionDigits: 1,
    })} ${units[unitIndex]}`;
}


function updateSelectedFiles() {
    const files = Array.from(fileInput.files);

    selectedFiles.replaceChildren();
    analyzeButton.disabled = files.length === 0;

    if (files.length === 0) {
        fileSelectionSummary.textContent = "Nenhum arquivo selecionado";
        return;
    }

    fileSelectionSummary.textContent = (
        `Arquivos selecionados (${files.length})`
    );

    files.forEach((file) => {
        const item = document.createElement("li");
        const name = document.createElement("span");
        const size = document.createElement("span");

        name.className = "selected-file-name";
        name.textContent = file.name;
        name.title = file.name;

        size.className = "selected-file-size";
        size.textContent = formatFileSize(file.size);

        item.append(name, size);
        selectedFiles.append(item);
    });
}


function clearFiles() {
    if (toolsPanel.dataset.hasServerState === "true") {
        window.location.assign("/");
        return;
    }

    fileInput.value = "";
    analyzeButton.textContent = "Analisar arquivos";
    updateSelectedFiles();
}


function setActiveToolsTab(tabName) {
    toolsTabs.forEach((tab) => {
        const isActive = tab.dataset.toolsTab === tabName;

        tab.classList.toggle("is-active", isActive);
        tab.setAttribute("aria-selected", String(isActive));
        tab.tabIndex = isActive ? 0 : -1;
    });

    toolsTabPanels.forEach((panel) => {
        panel.hidden = panel.dataset.toolsTabPanel !== tabName;
    });
}


function setToolsPanelExpanded(expanded) {
    toolsPanel.hidden = !expanded;
    openToolsPanel.hidden = expanded;
    minimizeToolsPanel.setAttribute("aria-expanded", String(expanded));
    openToolsPanel.setAttribute("aria-expanded", String(expanded));
}


fileInput.addEventListener("change", updateSelectedFiles);
clearFilesButton.addEventListener("click", clearFiles);
toolsTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
        setActiveToolsTab(tab.dataset.toolsTab);
    });
});
minimizeToolsPanel.addEventListener("click", () => {
    setToolsPanelExpanded(false);
});
openToolsPanel.addEventListener("click", () => {
    setToolsPanelExpanded(true);
});

uploadForm.addEventListener("submit", () => {
    analyzeButton.disabled = true;
    analyzeButton.textContent = "Processando...";
});

setActiveToolsTab(toolsPanel.dataset.initialTab);
