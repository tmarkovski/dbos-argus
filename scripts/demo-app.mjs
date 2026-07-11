#!/usr/bin/env node
// Sample-app demo workload: a one-shot `argus-runner prepare` (serializes DBOS
// schema migration so the long-running processes don't race CREATE TABLE on a
// fresh database), then the three long-running processes via `concurrently`.
//
// Runs standalone (`node scripts/demo-app.mjs`) or as the `demo` entry of the
// stack in scripts/dev.mjs. Expects ARGUS_DATABASE_URL /
// DBOS_SYSTEM_DATABASE_URL to already be set by the caller.

import { spawn, spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const prepare = spawnSync("uv", ["run", "argus-runner", "prepare"], {
  stdio: "inherit",
  cwd: repoRoot,
});
if (prepare.status !== 0) process.exit(prepare.status ?? 1);

const workers = ["argus-simulator", "argus-scheduler", "argus-metrics-runner"];
const args = [
  "exec",
  "concurrently",
  "--kill-others",
  "--prefix-colors",
  "auto",
  "--names",
  "simulator,scheduler,metrics",
  ...workers.map((w) => `uv run ${w}`),
];
const child = spawn("pnpm", args, { stdio: "inherit", cwd: repoRoot, shell: false });

const forward = (sig) => {
  try {
    child.kill(sig);
  } catch {
    // Already gone.
  }
};
process.on("SIGINT", () => forward("SIGINT"));
process.on("SIGTERM", () => forward("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 0);
});
