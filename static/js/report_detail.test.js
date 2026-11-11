const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "report_detail.js"), "utf8");
function mount(clipboard) {
    let click;
    const status = { textContent: "" };
    const button = { hidden: true, dataset: { copyHash: "hash-1" },
        parentElement: { querySelector: () => status },
        addEventListener: (_, handler) => { click = handler; } };
    vm.runInNewContext(source, {
        navigator: { clipboard },
        document: { querySelectorAll: () => [button], getElementById: () => ({ textContent: " aabb " }) }
    });
    return { button, status, click };
}
test("copies full hash and restores button", async () => {
    let copied;
    const ui = mount({ writeText: async (value) => { copied = value; } });
    assert.equal(ui.button.hidden, false);
    await ui.click();
    assert.equal(copied, "aabb");
    assert.equal(ui.status.textContent, "SHA-256 copiado.");
    assert.equal(ui.button.disabled, false);
});
test("clipboard rejection offers manual copying and permits retry", async () => {
    const ui = mount({ writeText: async () => { throw new Error("denied"); } });
    await ui.click();
    assert.match(ui.status.textContent, /manualmente/);
    assert.equal(ui.button.disabled, false);
});
test("without clipboard leaves hash available and copy control hidden", () => {
    const ui = mount(undefined);
    assert.equal(ui.button.hidden, true);
    assert.equal(ui.click, undefined);
});
