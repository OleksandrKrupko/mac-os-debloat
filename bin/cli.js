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
process.exit(result.status ?? 1);
