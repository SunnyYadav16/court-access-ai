/**
 * hooks/useRealtimeWebSocket.ts
 *
 * WebSocket hook for the real-time speech interpretation pipeline.
 *
 * Handles both JSON control frames and raw binary audio frames:
 *   - JSON → dispatched to realtimeStore (phase transitions, transcript, etc.)
 *   - ArrayBuffer → forwarded to enqueueTts (TTS playback queue)
 *
 * Binary control markers (4-byte Uint8Arrays) are used for session lifecycle
 * signals instead of JSON so they are always < 10 bytes and never ambiguous
 * with audio data.
 *
 * Usage:
 *   const { connect, disconnect, sendMarker, sendAudio, wsRef } =
 *     useRealtimeWebSocket({ enqueueTts });
 *
 *   // Lobby: create a new room
 *   connect({ name: 'Judge Smith', myLang: 'en', partnerLang: 'es' });
 *
 *   // Lobby: join an existing room
 *   connect({ name: 'Maria', roomId: 'ABC123' });
 *
 *   // Inside MediaRecorder.ondataavailable:
 *   sendAudio(event.data);
 */

import { useCallback, useRef } from "react";
import useRealtimeStore from "@/store/realtimeStore";

// ── Constants ─────────────────────────────────────────────────────────────────

const WS_BASE =
  (import.meta.env.VITE_WS_BASE as string | undefined) ??
  `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

// 4-byte binary control markers (match backend constants in api/routes/realtime.py)
const MARKERS = {
  SESSION_START: new Uint8Array([0x53, 0x54, 0x52, 0x54]), // STRT
  SESSION_END: new Uint8Array([0x45, 0x4e, 0x44, 0x53]), // ENDS
  MIC_MUTE: new Uint8Array([0x4d, 0x55, 0x54, 0x45]), // MUTE
  MIC_UNMUTE: new Uint8Array([0x55, 0x4e, 0x4d, 0x54]), // UNMT
} as const;

export type MarkerType = keyof typeof MARKERS;

// ── Hook options ──────────────────────────────────────────────────────────────

export interface UseRealtimeWebSocketOptions {
  /** Callback to enqueue TTS audio buffers for playback. */
  enqueueTts: (buffer: ArrayBuffer) => void;
  /** Called when session_status becomes 'active' — start mic capture. */
  onStartCapture?: () => void;
  /** Called when session_status becomes 'ready' or 'ended', on error, or on
   *  manual disconnect — stop mic capture and flush the audio pipeline. */
  onStopCapture?: () => void;
  /** Called when the connection opens (optional). */
  onOpen?: () => void;
  /** Called when the connection closes (optional). */
  onClose?: () => void;
}

export interface ConnectOptions {
  /** Existing room code to join. If omitted, a new room is created. */
  roomId?: string;
  /** Display name for this participant. */
  name: string;
  /** My language (ISO 639-1). Only used when creating a room. */
  myLang?: string;
  /** Partner's language (ISO 639-1). Only used when creating a room. */
  partnerLang?: string;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useRealtimeWebSocket({
  enqueueTts,
  onStartCapture,
  onStopCapture,
  onOpen,
  onClose,
}: UseRealtimeWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);

  // Pull store actions (stable references from Zustand)
  const setPhase = useRealtimeStore((s) => s.setPhase);
  const setRoomCode = useRealtimeStore((s) => s.setRoomCode);
  const setMyLanguage = useRealtimeStore((s) => s.setMyLanguage);
  const setIsCreator = useRealtimeStore((s) => s.setIsCreator);
  const setPartner = useRealtimeStore((s) => s.setPartner);
  const setPartnerMuted = useRealtimeStore((s) => s.setPartnerMuted);
  const setMicLocked = useRealtimeStore((s) => s.setMicLocked);
  const addMessage = useRealtimeStore((s) => s.addMessage);
  const setLivePartial = useRealtimeStore((s) => s.setLivePartial);
  const setError = useRealtimeStore((s) => s.setError);

  // ── Internal helpers ─────────────────────────────────────────────────────

  const _close = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    onStopCapture?.();
  }, [onStopCapture]);

  // ── Message dispatcher ───────────────────────────────────────────────────

  const _handleMessage = useCallback(
    (event: MessageEvent) => {
      // Binary frame → TTS audio
      if (event.data instanceof ArrayBuffer) {
        enqueueTts(event.data);
        return;
      }

      if (typeof event.data !== "string") return;

      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        return; // ignore malformed JSON
      }

      switch (msg.type) {
        case "room_created":
          setRoomCode(String(msg.room_id ?? ""));
          setMyLanguage(String(msg.language ?? "en"));
          setIsCreator(true);
          break;

        case "room_joined":
          setRoomCode(String(msg.room_id ?? ""));
          setMyLanguage(String(msg.language ?? "en"));
          if (msg.partner_name) {
            setPartner({
              name: String(msg.partner_name),
              language: String(msg.partner_language ?? ""),
            });
          }
          break;

        case "partner_joined":
          setPartner({
            name: String(msg.name ?? ""),
            language: String(msg.language ?? ""),
          });
          setPartnerMuted(false);
          break;

        case "partner_left":
          setPartner(null);
          setPartnerMuted(false);
          break;

        case "session_status": {
          const status = msg.status as string;
          switch (status) {
            case "waiting":
              setPhase("waiting");
              break;
            case "ready":
              onStopCapture?.();
              setPhase("ready");
              break;
            case "active":
              setPhase("active");
              onStartCapture?.();
              break;
            case "ended":
              onStopCapture?.();
              setPhase("ended");
              break;
          }
          break;
        }

        case "partner_muted":
          setPartnerMuted(true);
          break;

        case "partner_unmuted":
          setPartnerMuted(false);
          break;

        case "transcript":
          if (typeof msg.text === "string") {
            setLivePartial(null);
            addMessage({
              speaker: (msg.speaker as "self" | "partner") ?? "self",
              speakerName: msg.speaker_name as string | undefined,
              text: msg.text,
              language: (msg.language as string) ?? "unknown",
              translation: msg.translation as string | undefined,
              targetLanguage: msg.target_language as string | undefined,
              verifiedTranslation: msg.verified_translation as string | undefined,
              accuracyScore: msg.accuracy_score as number | undefined,
              accuracyNote: msg.accuracy_note as string | undefined,
              usedFallback: msg.used_fallback as boolean | undefined,
              duration: msg.duration as number | undefined,
              timestamp: new Date(),
            });
          }
          break;

        case "transcript_partial":
          if (typeof msg.text === "string") {
            setLivePartial({
              speaker: (msg.speaker as "self" | "partner") ?? "self",
              text: msg.text,
              translation: msg.translation as string | undefined,
            });
          }
          break;

        case "mic_locked": {
          setMicLocked(true);
          const durationMs = (msg.duration_ms as number | undefined) ?? 2000;
          setTimeout(() => setMicLocked(false), durationMs);
          break;
        }

        case "error":
          setError((msg.message as string) ?? "Unknown error");
          setPhase("lobby");
          _close();
          break;
      }
    },
    [
      enqueueTts,
      onStartCapture,
      onStopCapture,
      addMessage,
      setLivePartial,
      setMicLocked,
      setError,
      setIsCreator,
      setMyLanguage,
      setPartner,
      setPartnerMuted,
      setPhase,
      setRoomCode,
      _close,
    ]
  );

  // ── Public API ────────────────────────────────────────────────────────────

  const connect = useCallback(
    (opts: ConnectOptions) => {
      // Close any existing connection before opening a new one
      _close();

      setError(null);

      const params = new URLSearchParams();
      if (opts.roomId) {
        // Joining an existing room — no language params, server assigns
        params.set("room_id", opts.roomId);
        setIsCreator(false);
      } else {
        // Creating a new room — send both languages
        params.set("my_lang", opts.myLang ?? "en");
        params.set("partner_lang", opts.partnerLang ?? "es");
        setIsCreator(true);
      }
      params.set("name", opts.name || "User");

      // Attach Firebase token for server-side authentication (C2 fix)
      const token = localStorage.getItem("access_token") ?? "";
      if (token) {
        params.set("token", token);
      }

      const url = `${WS_BASE}/api/sessions/ws?${params.toString()}`;
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        onOpen?.();
      };

      ws.onmessage = _handleMessage;

      ws.onerror = () => {
        setError("Connection failed. Is the server running?");
        setPhase("lobby");
        _close();
      };

      ws.onclose = () => {
        wsRef.current = null;
        onClose?.();
      };
    },
    [_close, _handleMessage, onClose, onOpen, setError, setIsCreator, setPhase]
  );

  // _close() already calls onStopCapture, so audio capture is always stopped
  // on manual disconnect, connection error, and session end.
  const disconnect = useCallback(() => {
    _close();
  }, [_close]);

  /** Send a 4-byte binary control marker. */
  const sendMarker = useCallback((type: MarkerType) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(MARKERS[type]);
    }
  }, []);

  /** Send a raw audio chunk (Blob from MediaRecorder or ArrayBuffer). */
  const sendAudio = useCallback((data: Blob | ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { connect, disconnect, sendMarker, sendAudio, wsRef };
}

export default useRealtimeWebSocket;
