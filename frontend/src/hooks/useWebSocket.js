/**
 * hooks/useWebSocket.js
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

/**
 * @typedef {"idle"|"connecting"|"connected"|"reconnecting"|"disconnected"|"error"} WSStatus
 */

/**
 * @param {string|null} sessionId
 * @param {{ onTranscript?: Function, onError?: Function, onStatusChange?: Function }} options
 * @returns {{ status: WSStatus, send: Function, disconnect: Function }}
 */
export function useWebSocket(sessionId, { onTranscript, onError, onStatusChange } = {}) {
    const [status, setStatus] = useState("idle");
    const wsRef = useRef(null);
    const retriesRef = useRef(0);
    const retryTimerRef = useRef(null);
    const intentionalClose = useRef(false);

    const updateStatus = useCallback(
        (next) => {
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

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === "transcript") onTranscript?.(msg.payload);
                else if (msg.type === "error") onError?.(msg.payload);
                // pong, session_ended etc. — silently ignored
            } catch (_) {
                // Non-JSON frame — ignore
            }
        };

        ws.onerror = () => updateStatus("error");

        ws.onclose = (e) => {
            if (intentionalClose.current) {
                updateStatus("disconnected");
                return;
            }
            if (retriesRef.current < MAX_RETRIES) {
                retriesRef.current += 1;
                retryTimerRef.current = setTimeout(connect, RETRY_DELAY_MS);
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
            clearTimeout(retryTimerRef.current);
            wsRef.current?.close();
        };
    }, [sessionId, connect]);

    /** Send a message over the WebSocket. */
    const send = useCallback((type, payload = {}) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(
                JSON.stringify({ type, payload, timestamp_ms: Date.now() })
            );
        }
    }, []);

    /** Intentionally disconnect. */
    const disconnect = useCallback(() => {
        intentionalClose.current = true;
        clearTimeout(retryTimerRef.current);
        wsRef.current?.close();
        updateStatus("disconnected");
    }, [updateStatus]);

    return { status, send, disconnect };
}

export default useWebSocket;
