import subprocess
from pathlib import Path


def test_script_keeps_refresh_available_when_old_page_has_no_position_selector():
    script = Path(__file__).resolve().parents[1] / "static" / "dashboard.js"
    harness = r'''
const fs = require("fs");
const element = () => ({
  textContent: "null",
  hidden: false,
  className: "",
  disabled: false,
  options: [],
  classList: { add() {}, remove() {}, toggle() {} },
  querySelector() { return element(); },
  addEventListener() {},
  append() {},
  replaceChildren() {},
});
const elements = new Map();
global.document = {
  getElementById(id) {
    if (id === "position-selector") return null;
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  },
  querySelector() { return { replaceChildren() {}, insertRow() { return { insertCell() { return {}; } }; } }; },
  createElement() { return element(); },
};
global.window = {
  matchMedia() { return { matches: true }; },
  addEventListener() {},
  clearTimeout() {},
  setTimeout() { return 1; },
};
require(process.argv[1]);
'''

    result = subprocess.run(
        ["node", "-e", harness, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
