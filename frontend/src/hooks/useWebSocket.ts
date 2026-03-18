/**
 * hooks/useWebSocket.ts
 *
 * WebSocket hook for real-time interpretation sessions.
 *
 * Manages the WebSocket lifecycle:
 *   - Connects to /sessions/{sessionId}/ws?token=<access_token>
 *   - Auto-reconnects up to MAX_RETRIES times on unexpected close
 *   - Dispatches parsed transcript segments and errors via callbacks
 *   - Provides send() to push audio_chunk or ping messages
 *
 * Usage:
 *   const { status, send, disconnect } = useWebSocket(sessionId, {
 *     onTranscript: (segment) => console.log(segment),
 *     onError: (err) => console.error(err),
 *   });
 */

import { useCallback, useEffect, useRef, useState } from "react";

const WS_BASE = import.meta.env.VITE_WS_BASE ?? `ws://${window.location.host}`;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 2000;

// ── Types ───────────────────────────────────────────────────────────────────

export type WSStatus = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected" | "error";

export interface TranscriptSegment {
  text: string;
  language: string;
  timestamp?: number;
  speaker?: string;
  is_final?: boolean;
  [key: string]: any;
}

export interface WSError {
  code: string;
  message: string;
  [key: string]: any;
}

export interface WSMessage {
  type: string;
  payload?: any;
  timestamp_ms?: number;
}

export interface UseWebSocketOptions {
  onTranscript?: (segment: TranscriptSegment) => void;
  onError?: (error: WSError) => void;
  onStatusChange?: (status: WSStatus) => void;
}

export interface UseWebSocketReturn {
  status: WSStatus;
  send: (type: string, payload?: any) => void;
  disconnect: () => void;
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useWebSocket(
  sessionId: string | null,
  { onTranscript, onError, onStatusChange }: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const [status, setStatus] = useState<WSStatus>("idle");
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const intentionalClose = useRef(false);

  const updateStatus = useCallback(
    (next: WSStatus) => {
      setStatus(next);
      onStatusChange?.(next);
    },
    [onStatusChange]
  );

  const connect = useCallback(() => {
    if (!sessionId) return;
    const token = localStorage.getItem("access_token") ?? "";
    const url = `${WS_BASE}/sessions/${sessionId}/ws?token=${token}`;
    updateStatus(retriesRef.current > 0 ? "reconnecting" : "connecting");

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      updateStatus("connected");
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        if (msg.type === "transcript") onTranscript?.(msg.payload as TranscriptSegment);
        else if (msg.type === "error") onError?.(msg.payload as WSError);
        // pong, session_ended etc. — silently ignored
      } catch {
        // Non-JSON frame — ignore
      }
    };

    ws.onerror = () => updateStatus("error");

    ws.onclose = () => {
      if (intentionalClose.current) {
        updateStatus("disconnected");
        return;
      }
      if (retriesRef.current < MAX_RETRIES) {
        retriesRef.current += 1;
        retryTimerRef.current = window.setTimeout(connect, RETRY_DELAY_MS);
      } else {
        updateStatus("error");
        onError?.({ code: "max_retries", message: "WebSocket connection lost after max retries" });
      }
    };
  }, [sessionId, onTranscript, onError, updateStatus]);

  // Connect when sessionId changes
  useEffect(() => {
    if (!sessionId) return;
    intentionalClose.current = false;
    connect();
    return () => {
      intentionalClose.current = true;
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
      }
      wsRef.current?.close();
    };
  }, [sessionId, connect]);

  /** Send a message over the WebSocket. */
  const send = useCallback((type: string, payload: any = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message: WSMessage = {
        type,
        payload,
        timestamp_ms: Date.now(),
      };
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  /** Intentionally disconnect. */
  const disconnect = useCallback(() => {
    intentionalClose.current = true;
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
    }
    wsRef.current?.close();
    updateStatus("disconnected");
  }, [updateStatus]);

  return { status, send, disconnect };
}

export default useWebSocket;
