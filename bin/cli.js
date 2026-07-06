#!/usr/bin/env node
const { spawnSync } = require("child_process");
const path = require("path");

if (process.platform !== "darwin") {
  console.error("mac-os-debloat only runs on macOS.");
  process.exit(1);
}

const script = path.join(__dirname, "..", "debloat");
const result = spawnSync("python3", [script, ...process.argv.slice(2)], {
  stdio: "inherit",
});
if (result.error && result.error.code === "ENOENT") {
  console.error(
    "python3 not found. Install the Xcode Command Line Tools:\n" +
      "  xcode-select --install"
  );
  process.exit(1);
}
process.exit(result.status ?? 1);
