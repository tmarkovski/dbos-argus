import type { SqlDiagnostics } from "$lib/connection-diagnostics";

// See https://svelte.dev/docs/kit/types#app.d.ts for details.
declare global {
  namespace App {
    // interface Error {}
    // interface Locals {}
    // interface PageData {}
    interface PageState {
      connectionDiagnostics?: SqlDiagnostics | null;
    }
    // interface Platform {}
  }
}

export {};
