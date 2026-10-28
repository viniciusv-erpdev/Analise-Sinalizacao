/* Progressive enhancement: the complete hash remains selectable without JS. */
"use strict";
document.querySelectorAll("[data-copy-hash]").forEach((button) => {
    if (!navigator.clipboard || !navigator.clipboard.writeText) return;
    button.hidden = false;
    button.addEventListener("click", async () => {
        const hash = document.getElementById(button.dataset.copyHash);
        const status = button.parentElement.querySelector('[role="status"]');
        if (!hash || !status) return;
        button.disabled = true;
        try {
            await navigator.clipboard.writeText(hash.textContent.trim());
            status.textContent = "SHA-256 copiado.";
        } catch (_) {
            status.textContent = "N\u00e3o foi poss\u00edvel copiar. Selecione o hash e copie manualmente.";
        } finally {
            button.disabled = false;
        }
    });
});
