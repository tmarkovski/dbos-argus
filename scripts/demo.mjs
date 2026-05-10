#!/usr/bin/env node
// Cross-platform entrypoint for `pnpm demo`.
//
// Computes an absolute path to argus-demo.sqlite, sets the two DB URL env vars
// (so they propagate to every subprocess via process.env, not via POSIX inline
// `VAR=val cmd` syntax which is shell-specific), and then runs the same Turbo
// pipeline the previous bash one-liner did.
//
// Signal forwarding: SIGINT/SIGTERM go to the Turbo child, which in turn signals
// its workspace scripts (including `concurrently` in tests/sample-app), so a
// single Ctrl+C tears the whole stack down on macOS, Linux, and Windows.

import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// SQLAlchemy/aiosqlite URLs use forward slashes even on Windows.
const sqlitePath = resolve(repoRoot, "argus-demo.sqlite").replace(/\\/g, "/");

const env = {
  ...process.env,
  ARGUS_DATABASE_URL: `sqlite+aiosqlite:///${sqlitePath}`,
  DBOS_SYSTEM_DATABASE_URL: `sqlite:///${sqlitePath}`,
};

const args = ["exec", "turbo", "run", "dev", "demo", "--filter=*"];
// `detached: true` puts the child in its own process group so we can signal the
// whole subtree (otherwise simulator-spawned `argus-runner` workers can outlive
// their parent and become orphans).
const child = spawn("pnpm", args, {
  stdio: "inherit",
  env,
  cwd: repoRoot,
  shell: false,
  detached: process.platform !== "win32",
});

const killTree = (sig) => {
  try {
    if (process.platform === "win32") {
      // Win32 has no process groups; use taskkill /T to walk the child tree.
      spawn("taskkill", ["/pid", String(child.pid), "/f", "/t"], { stdio: "ignore" });
    } else {
      // Negative PID signals the entire process group.
      process.kill(-child.pid, sig);
    }
  } catch {
    // Already gone.
  }
};

process.on("SIGINT", () => killTree("SIGINT"));
process.on("SIGTERM", () => killTree("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 0);
});
