#!/usr/bin/env node
// Cross-platform orchestrator for the root `dev` / `dev:sqlite` / `demo` scripts.
//
// Usage: node scripts/dev.mjs (--pg | --sqlite=<file>) [--demo]
//
//   --pg             point the stack at the docker-compose Postgres
//   --sqlite=<file>  point the stack at <repo-root>/<file>
//   --demo           also run the sample-app workload (scripts/demo-app.mjs)
//
// Always starts the FastAPI backend (uvicorn on :8090) and the SvelteKit dev
// server (:5000) through a single `concurrently` child. DB URLs are set via
// process.env so they propagate to every subprocess without POSIX inline
// `VAR=val cmd` syntax, which is shell-specific.
//
// Signal forwarding: SIGINT/SIGTERM go to the concurrently child, which in
// turn signals its commands, so a single Ctrl+C tears the whole stack down on
// macOS, Linux, and Windows.

import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

let pg = false;
let sqliteFile = null;
let demo = false;
for (const arg of process.argv.slice(2)) {
  if (arg === "--pg") pg = true;
  else if (arg.startsWith("--sqlite=")) sqliteFile = arg.slice("--sqlite=".length);
  else if (arg === "--demo") demo = true;
  else {
    console.error(`dev.mjs: unknown argument ${arg}`);
    process.exit(2);
  }
}
if (pg === Boolean(sqliteFile)) {
  console.error("dev.mjs: pass exactly one of --pg or --sqlite=<file>");
  process.exit(2);
}

const env = { ...process.env };
if (pg) {
  env.ARGUS_DATABASE_URL = "postgresql+asyncpg://argus:argus@localhost:5432/argus";
  env.DBOS_SYSTEM_DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus";
} else {
  // SQLAlchemy/aiosqlite URLs use forward slashes even on Windows.
  const sqlitePath = resolve(repoRoot, sqliteFile).replace(/\\/g, "/");
  env.ARGUS_DATABASE_URL = `sqlite+aiosqlite:///${sqlitePath}`;
  env.DBOS_SYSTEM_DATABASE_URL = `sqlite:///${sqlitePath}`;
}

const procs = [
  { name: "server", cmd: "pnpm dev:server" },
  { name: "console", cmd: "pnpm --filter console dev" },
];
if (demo) procs.push({ name: "demo", cmd: "node scripts/demo-app.mjs" });

const args = [
  "exec",
  "concurrently",
  "--kill-others",
  "--prefix-colors",
  "auto",
  "--names",
  procs.map((p) => p.name).join(","),
  ...procs.map((p) => p.cmd),
];
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
