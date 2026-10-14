import { describe, expect, it } from "vitest";
import {
  buildRealtimeSubscribePayload,
  buildRealtimeWebSocketUrl,
  parsePriceUpdate,
  parseRealtimeMessage,
} from "../lib/websocket";

describe("websocket helpers", () => {
  it("builds a same-origin websocket url from the default API proxy path", () => {
    expect(buildRealtimeWebSocketUrl("/backend/api/v1", "http://localhost:3000")).toBe(
      "ws://localhost:3000/backend/api/v1/ws/stream",
    );
  });

  it("builds a websocket url from an absolute API base path", () => {
    expect(buildRealtimeWebSocketUrl("https://api.example.com/api/v1", "http://localhost:3000")).toBe(
      "wss://api.example.com/api/v1/ws/stream",
    );
  });

  it("preserves subscribed realtime channels in the subscribe payload", () => {
    expect(buildRealtimeSubscribePayload()).toEqual({
      type: "subscribe",
      channels: ["prices", "signals", "risk_events"],
    });
  });

  it("parses price updates without coercing Decimal string prices to numbers", () => {
    const message = parseRealtimeMessage(
      JSON.stringify({
        type: "price.updated",
        timestamp: "2026-04-30T01:15:00+00:00",
        data: {
          symbol: "XAUUSD",
          timeframe: "15m",
          price: "2321.12345678",
        },
      }),
    );

    expect(parsePriceUpdate(message)).toEqual({
      symbol: "XAUUSD",
      timeframe: "15m",
      price: "2321.12345678",
      timestamp: "2026-04-30T01:15:00+00:00",
    });
  });

  it("ignores malformed realtime payloads", () => {
    expect(parseRealtimeMessage("not json")).toBeNull();
    expect(parseRealtimeMessage(JSON.stringify({ timestamp: "2026-04-30T01:15:00Z" }))).toBeNull();
    expect(parsePriceUpdate(parseRealtimeMessage(JSON.stringify({ type: "pong", data: {} })))).toBeNull();
  });
});
