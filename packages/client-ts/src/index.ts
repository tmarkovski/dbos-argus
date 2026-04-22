import type {
  AppConnectMessage,
  ClientMessage,
  ServerMessage,
} from "./protocol.js";

export * from "./protocol.js";

export interface ConnectArgusOptions {
  url: string;
  apiKey: string;
  appName?: string;
  sdkVersion?: string;
  onMessage?: (message: ServerMessage) => void;
  onOpen?: () => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (error: Event) => void;
}

export interface ArgusConnection {
  close: () => void;
  send: (message: ClientMessage) => void;
}

/**
 * Stub: opens a WebSocket to the Argus backend and sends app.connect on open.
 *
 * This is not a production client. It exists so the surface area is stable
 * while the real implementation is developed.
 */
export function connectArgus(opts: ConnectArgusOptions): ArgusConnection {
  const wsUrl = new URL(opts.url);
  if (opts.apiKey) wsUrl.searchParams.set("api_key", opts.apiKey);

  const ws = new WebSocket(wsUrl.toString());

  ws.addEventListener("open", () => {
    const hello: AppConnectMessage = {
      type: "app.connect",
      app_name: opts.appName ?? "unknown",
      sdk: "typescript",
      sdk_version: opts.sdkVersion ?? "0.0.0",
    };
    ws.send(JSON.stringify(hello));
    opts.onOpen?.();
  });

  ws.addEventListener("message", (event) => {
    try {
      const parsed = JSON.parse(event.data) as ServerMessage;
      opts.onMessage?.(parsed);
    } catch {
      // Ignore non-JSON frames for now.
    }
  });

  if (opts.onClose) ws.addEventListener("close", opts.onClose);
  if (opts.onError) ws.addEventListener("error", opts.onError);

  return {
    close: () => ws.close(),
    send: (message: ClientMessage) => ws.send(JSON.stringify(message)),
  };
}
