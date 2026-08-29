const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const fileSelectionSummary = document.getElementById(
    "file-selection-summary"
);
const selectedFiles = document.getElementById("selected-files");
const analyzeButton = document.getElementById("analyze-button");


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


fileInput.addEventListener("change", updateSelectedFiles);

uploadForm.addEventListener("submit", () => {
    analyzeButton.disabled = true;
    analyzeButton.textContent = "Processando...";
});
