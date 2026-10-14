export const REALTIME_CHANNELS = ["prices", "signals", "risk_events"] as const;

export type RealtimeChannel = (typeof REALTIME_CHANNELS)[number];

export interface RealtimeMessage {
  type: string;
  timestamp: string | null;
  data: Record<string, unknown>;
}

export interface PriceUpdate {
  symbol: string;
  timeframe: string;
  price: string;
  timestamp: string;
}

const DEFAULT_API_BASE_PATH = "/backend/api/v1";

function getApiBasePath() {
  return process.env.NEXT_PUBLIC_API_BASE_PATH ?? DEFAULT_API_BASE_PATH;
}

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function browserOrigin(origin?: string) {
  if (origin) {
    return origin;
  }

  if (typeof window !== "undefined" && window.location.origin) {
    return window.location.origin;
  }

  throw new Error("Browser origin is required for relative realtime websocket URLs.");
}

function websocketProtocol(protocol: string) {
  return protocol === "https:" || protocol === "wss:" ? "wss:" : "ws:";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function buildRealtimeWebSocketUrl(apiBasePath = getApiBasePath(), origin?: string) {
  const basePath = trimTrailingSlash(apiBasePath);
  const endpoint = `${basePath}/ws/stream`;
  const url = /^https?:\/\//i.test(basePath)
    ? new URL(endpoint)
    : new URL(endpoint.startsWith("/") ? endpoint : `/${endpoint}`, browserOrigin(origin));

  url.protocol = websocketProtocol(url.protocol);
  return url.toString();
}

export function buildRealtimeSubscribePayload(channels: readonly RealtimeChannel[] = REALTIME_CHANNELS) {
  return {
    type: "subscribe",
    channels: [...channels],
  };
}

export function parseRealtimeMessage(raw: string): RealtimeMessage | null {
  let payload: unknown;

  try {
    payload = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isRecord(payload) || typeof payload.type !== "string") {
    return null;
  }

  const data = isRecord(payload.data) ? payload.data : {};
  return {
    type: payload.type,
    timestamp: typeof payload.timestamp === "string" ? payload.timestamp : null,
    data,
  };
}

export function parsePriceUpdate(message: RealtimeMessage | null): PriceUpdate | null {
  if (!message || message.type !== "price.updated" || !message.timestamp) {
    return null;
  }

  const { data } = message;
  if (
    typeof data.symbol !== "string" ||
    typeof data.timeframe !== "string" ||
    typeof data.price !== "string"
  ) {
    return null;
  }

  return {
    symbol: data.symbol,
    timeframe: data.timeframe,
    price: data.price,
    timestamp: message.timestamp,
  };
}
