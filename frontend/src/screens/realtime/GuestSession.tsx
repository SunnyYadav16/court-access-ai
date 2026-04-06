/**
 * GuestSession — LEP individual's live session view.
 *
 * Fullscreen audio-first interface. The guest does not need court metadata
 * or a bidirectional transcript — they need to:
 *   1. Know when the AI is speaking to them (TTS playing)
 *   2. Know when it is their turn to speak
 *   3. Read the translated text of what was just said to them
 *   4. Toggle their microphone
 *   5. Leave the session
 *
 * Authentication: room JWT (meta.roomToken) passed as WS query param.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import useRealtimeStore from "@/store/realtimeStore"
import { useRealtimeWebSocket } from "@/hooks/useRealtimeWebSocket"
import { useAudioCapture } from "@/hooks/useAudioCapture"
import { useTtsPlayback } from "@/hooks/useTtsPlayback"

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GuestMeta {
  roomToken: string
  partnerName: string    // the guest's own name
  targetLanguage: string // guest's spoken language
  courtDivision: string | null
  courtroom: string | null
}

type AudioState =
  | "connecting"  // WS not yet open
  | "waiting"     // phase=waiting — host hasn't started
  | "your_turn"   // active, mic open, idle
  | "you_speaking"// active, VAD detected speech from guest
  | "translating" // active, mic locked (server processing)
  | "ai_speaking" // active, TTS playing back to guest
  | "muted"       // active, guest muted their mic
  | "ended"       // session ended by host

// ── Constants ─────────────────────────────────────────────────────────────────

const BG = "#0D1B2A"

const LANG_LABELS: Record<string, string> = {
  en: "English",
  es: "Spanish (Español)",
  pt: "Portuguese (Português)",
}

// Per audio-state: { ring color, label, sublabel, animate }
const STATE_CONFIG: Record<
  AudioState,
  { ring: string; label: string; sublabel: string; pulse: boolean; spin: boolean }
> = {
  connecting:   { ring: "#475569", label: "Connecting…",        sublabel: "Setting up your session", pulse: false, spin: true },
  waiting:      { ring: "#F59E0B", label: "Waiting",            sublabel: "Session will start shortly", pulse: true, spin: false },
  your_turn:    { ring: "#3B82F6", label: "You may speak",      sublabel: "Speak clearly into your microphone", pulse: true, spin: false },
  you_speaking: { ring: "#EF4444", label: "You're speaking",    sublabel: "Listening…", pulse: false, spin: false },
  translating:  { ring: "#A78BFA", label: "Translating",        sublabel: "Processing your speech", pulse: true, spin: false },
  ai_speaking:  { ring: "#22C55E", label: "Court is speaking",  sublabel: "Listen to the translation", pulse: true, spin: false },
  muted:        { ring: "#6B7280", label: "Microphone muted",   sublabel: "Tap the mic button to unmute", pulse: false, spin: false },
  ended:        { ring: "#475569", label: "Session ended",      sublabel: "Thank you", pulse: false, spin: false },
}

// ── Orb component ─────────────────────────────────────────────────────────────

function AudioOrb({ state }: { state: AudioState }) {
  const cfg = STATE_CONFIG[state]

  return (
    <div className="relative flex items-center justify-center" style={{ width: 200, height: 200 }}>
      {/* Outer pulse ring */}
      {cfg.pulse && (
        <div
          className="absolute rounded-full"
          style={{
            width: 200,
            height: 200,
            border: `2px solid ${cfg.ring}`,
            opacity: 0.3,
            animation: "guestPulseOuter 2s ease-in-out infinite",
          }}
        />
      )}
      {/* Mid ring */}
      <div
        className="absolute rounded-full"
        style={{
          width: 160,
          height: 160,
          border: `2px solid ${cfg.ring}`,
          opacity: 0.5,
          animation: cfg.pulse
            ? "guestPulseMid 2s ease-in-out infinite 0.3s"
            : cfg.spin
              ? "guestSpin 1.4s linear infinite"
              : undefined,
        }}
      />
      {/* Inner orb */}
      <div
        className="relative flex items-center justify-center rounded-full"
        style={{
          width: 120,
          height: 120,
          background: `radial-gradient(circle at 35% 35%, ${cfg.ring}55, ${cfg.ring}22)`,
          border: `2.5px solid ${cfg.ring}88`,
          boxShadow: `0 0 ${cfg.pulse || state === "you_speaking" ? "40px" : "20px"} ${cfg.ring}44`,
          animation:
            state === "you_speaking"
              ? "guestSpeaking 0.5s ease-in-out infinite alternate"
              : undefined,
        }}
      >
        <span className="text-3xl select-none">
          {state === "connecting"   && "⋯"}
          {state === "waiting"      && "⏳"}
          {state === "your_turn"    && "🎙"}
          {state === "you_speaking" && "🎙"}
          {state === "translating"  && "✦"}
          {state === "ai_speaking"  && "🔊"}
          {state === "muted"        && "🔇"}
          {state === "ended"        && "👋"}
        </span>
      </div>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  meta: GuestMeta
  code: string
}

export default function GuestSession({ meta, code }: Props) {
  // ── Store ──────────────────────────────────────────────────────────────────
  const storePhase    = useRealtimeStore((s) => s.phase)
  const messages      = useRealtimeStore((s) => s.messages)
  const livePartial   = useRealtimeStore((s) => s.livePartial)
  const isMuted       = useRealtimeStore((s) => s.isMuted)
  const micLocked     = useRealtimeStore((s) => s.micLocked)
  const isSpeaking    = useRealtimeStore((s) => s.isSpeaking)
  const isPlayingTts  = useRealtimeStore((s) => s.isPlayingTts)
  const toggleMute    = useRealtimeStore((s) => s.toggleMute)
  const reset         = useRealtimeStore((s) => s.reset)
  const setMyName     = useRealtimeStore((s) => s.setMyName)
  const setMyLanguage = useRealtimeStore((s) => s.setMyLanguage)
  const setCourtInfo  = useRealtimeStore((s) => s.setCourtInfo)

  // ── Local state ────────────────────────────────────────────────────────────
  const [sessionPhase, setSessionPhase] = useState<"connecting" | "waiting" | "active" | "ended">("connecting")
  const [left, setLeft] = useState(false)
  const connectedRef   = useRef(false)

  // ── Audio hooks ────────────────────────────────────────────────────────────
  const { enqueue, clearQueue } = useTtsPlayback()
  const { startCapture, stopCapture } = useAudioCapture()
  const sendAudioRef = useRef<((data: Blob | ArrayBuffer) => void) | null>(null)

  const onStartCapture = useCallback(
    () => startCapture((data) => sendAudioRef.current?.(data)),
    [startCapture],
  )
  const onStopCapture = useCallback(() => {
    stopCapture()
    clearQueue()
  }, [stopCapture, clearQueue])

  const { connect, disconnect, sendMarker, sendAudio } = useRealtimeWebSocket({
    enqueueTts: enqueue,
    onStartCapture,
    onStopCapture,
  })

  useEffect(() => { sendAudioRef.current = sendAudio }, [sendAudio])

  // ── Connect on mount ───────────────────────────────────────────────────────
  useEffect(() => {
    if (connectedRef.current) return
    connectedRef.current = true
    reset()
    setMyName(meta.partnerName)
    setMyLanguage(meta.targetLanguage)
    setCourtInfo(meta.courtDivision ?? "", meta.courtroom ?? "", "")
    void connect({ roomId: code, name: meta.partnerName, token: meta.roomToken })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => disconnect(), [disconnect])

  // ── Sync phase ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (storePhase === "waiting") setSessionPhase("waiting")
    if (storePhase === "active")  setSessionPhase("active")
    if (storePhase === "ended")   setSessionPhase("ended")
  }, [storePhase])

  // ── Derived audio state ───────────────────────────────────────────────────
  const audioState = useMemo((): AudioState => {
    if (sessionPhase === "connecting") return "connecting"
    if (sessionPhase === "waiting")    return "waiting"
    if (sessionPhase === "ended")      return "ended"
    // active
    if (isPlayingTts)  return "ai_speaking"
    if (micLocked)     return "translating"
    if (isSpeaking)    return "you_speaking"
    if (isMuted)       return "muted"
    return "your_turn"
  }, [sessionPhase, isPlayingTts, micLocked, isSpeaking, isMuted])

  // ── Latest displayable content ────────────────────────────────────────────
  // Priority: live partial → last committed message
  const latestDisplay = useMemo((): { text: string; source: "partner" | "self" | "partial" } | null => {
    if (livePartial) {
      return {
        text: livePartial.translation ?? livePartial.text,
        source: "partial",
      }
    }
    if (messages.length === 0) return null
    const last = messages[messages.length - 1]
    if (last.speaker === "partner") {
      // Show the verified/translated version — this is what the guest should understand
      return {
        text: last.verifiedTranslation ?? last.translation ?? last.text,
        source: "partner",
      }
    }
    // self — show their own transcription as confirmation
    return { text: last.text, source: "self" }
  }, [messages, livePartial])

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleMicToggle = useCallback(() => {
    toggleMute()
    sendMarker(isMuted ? "MIC_UNMUTE" : "MIC_MUTE")
  }, [isMuted, toggleMute, sendMarker])

  function handleLeave() {
    disconnect()
    reset()
    setLeft(true)
  }

  // ── Thank-you screen ───────────────────────────────────────────────────────
  if (left) {
    return (
      <div
        className="min-h-screen flex flex-col items-center justify-center gap-5"
        style={{ background: BG, color: "#fff" }}
      >
        <div className="text-5xl">👋</div>
        <h1
          className="text-2xl font-bold"
          style={{ fontFamily: "Palatino, Georgia, serif" }}
        >
          Session Ended
        </h1>
        <p className="text-sm" style={{ color: "rgba(255,255,255,0.5)" }}>
          Thank you for using CourtAccess AI.
        </p>
        <p className="text-xs text-center max-w-xs" style={{ color: "rgba(255,255,255,0.3)" }}>
          If you need a record of this session, please ask the court official.
        </p>
      </div>
    )
  }

  // ── Session ended by host ──────────────────────────────────────────────────
  if (sessionPhase === "ended" && !left) {
    return (
      <div
        className="min-h-screen flex flex-col items-center justify-center gap-5"
        style={{ background: BG, color: "#fff" }}
      >
        <div className="text-5xl">✅</div>
        <h1
          className="text-2xl font-bold"
          style={{ fontFamily: "Palatino, Georgia, serif" }}
        >
          Session Complete
        </h1>
        <p className="text-sm" style={{ color: "rgba(255,255,255,0.5)" }}>
          The court official has ended the session.
        </p>
        <button
          onClick={() => setLeft(true)}
          className="mt-4 px-6 py-2.5 rounded-lg text-sm font-semibold"
          style={{ background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.8)", border: "1px solid rgba(255,255,255,0.12)" }}
        >
          Close
        </button>
      </div>
    )
  }

  const cfg = STATE_CONFIG[audioState]
  const isActive = sessionPhase === "active"

  // ── Main session UI ────────────────────────────────────────────────────────
  return (
    <>
      {/* Scoped keyframes */}
      <style>{`
        @keyframes guestPulseOuter {
          0%, 100% { transform: scale(1);   opacity: 0.3; }
          50%       { transform: scale(1.08); opacity: 0.1; }
        }
        @keyframes guestPulseMid {
          0%, 100% { transform: scale(1);   opacity: 0.5; }
          50%       { transform: scale(1.05); opacity: 0.25; }
        }
        @keyframes guestSpin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes guestSpeaking {
          from { transform: scale(1);    box-shadow: 0 0 30px #EF444444; }
          to   { transform: scale(1.06); box-shadow: 0 0 55px #EF444477; }
        }
        @keyframes guestFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <div
        className="min-h-screen flex flex-col"
        style={{ background: BG, color: "#fff" }}
      >
        {/* ── Top bar ─────────────────────────────────────────────────────── */}
        <div
          className="flex items-center justify-between px-5 py-3 shrink-0"
          style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2">
            <span className="text-base">⚖</span>
            <span
              className="text-sm font-semibold"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "rgba(255,255,255,0.85)" }}
            >
              CourtAccess AI
            </span>
          </div>
          <div className="flex items-center gap-3">
            {meta.courtDivision && (
              <span className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
                {meta.courtDivision}
              </span>
            )}
            {meta.courtroom && (
              <span className="text-xs" style={{ color: "rgba(255,255,255,0.35)" }}>
                {meta.courtroom}
              </span>
            )}
            <span
              className="text-[10px] font-semibold px-2 py-0.5 rounded"
              style={{
                background: isActive ? "rgba(239,68,68,0.12)" : "rgba(255,255,255,0.06)",
                color: isActive ? "#ef4444" : "rgba(255,255,255,0.4)",
              }}
            >
              {isActive ? "● LIVE" : sessionPhase === "connecting" ? "Connecting" : "Waiting"}
            </span>
          </div>
        </div>

        {/* ── Language banner ─────────────────────────────────────────────── */}
        <div
          className="text-center py-2 text-xs"
          style={{ color: "rgba(255,255,255,0.3)", borderBottom: "1px solid rgba(255,255,255,0.04)" }}
        >
          Your language: <strong style={{ color: "rgba(255,255,255,0.55)" }}>
            {LANG_LABELS[meta.targetLanguage] ?? meta.targetLanguage}
          </strong>
        </div>

        {/* ── Center: orb + status ─────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col items-center justify-center gap-6 px-6">
          <AudioOrb state={audioState} />

          {/* State label */}
          <div className="text-center">
            <p
              className="text-xl font-semibold mb-1"
              style={{ color: cfg.ring, transition: "color 0.4s ease" }}
            >
              {cfg.label}
            </p>
            <p className="text-sm" style={{ color: "rgba(255,255,255,0.35)" }}>
              {cfg.sublabel}
            </p>
          </div>

          {/* ── Latest translated content ──────────────────────────────────── */}
          {latestDisplay && (
            <div
              key={latestDisplay.text.slice(0, 20)} // re-animate on new content
              className="w-full max-w-md rounded-xl px-5 py-4 text-center"
              style={{
                background: latestDisplay.source === "partner"
                  ? "rgba(34,197,94,0.08)"
                  : latestDisplay.source === "self"
                    ? "rgba(99,102,241,0.09)"
                    : "rgba(255,255,255,0.04)",
                border: `1px solid ${
                  latestDisplay.source === "partner"
                    ? "rgba(34,197,94,0.2)"
                    : latestDisplay.source === "self"
                      ? "rgba(99,102,241,0.2)"
                      : "rgba(255,255,255,0.08)"
                }`,
                animation: "guestFadeIn 0.35s ease-out",
              }}
            >
              {/* Label */}
              <p
                className="text-[10px] font-semibold uppercase tracking-widest mb-2"
                style={{
                  color: latestDisplay.source === "partner"
                    ? "#22c55e"
                    : latestDisplay.source === "self"
                      ? "#a5b4fc"
                      : "rgba(255,255,255,0.3)",
                }}
              >
                {latestDisplay.source === "partner"
                  ? "Court Official (translated)"
                  : latestDisplay.source === "self"
                    ? "You said"
                    : "…"}
              </p>
              {/* Text */}
              <p
                className="text-base leading-relaxed"
                style={{
                  color: latestDisplay.source === "partial"
                    ? "rgba(255,255,255,0.5)"
                    : "rgba(255,255,255,0.9)",
                  fontStyle: latestDisplay.source === "partial" ? "italic" : "normal",
                }}
              >
                {latestDisplay.text}
              </p>
            </div>
          )}
        </div>

        {/* ── Bottom controls ──────────────────────────────────────────────── */}
        <div
          className="px-6 py-5 flex items-center justify-between shrink-0"
          style={{ borderTop: "1px solid rgba(255,255,255,0.07)" }}
        >
          {/* Leave button */}
          <button
            onClick={handleLeave}
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={{
              background: "rgba(127,29,29,0.35)",
              color: "#fca5a5",
              border: "1px solid rgba(127,29,29,0.5)",
            }}
          >
            Leave Session
          </button>

          {/* Mic button — large, centered */}
          <button
            onClick={isActive && !micLocked ? handleMicToggle : undefined}
            disabled={!isActive || micLocked}
            className="w-16 h-16 rounded-full flex items-center justify-center text-2xl"
            style={{
              background: isMuted
                ? "rgba(255,255,255,0.06)"
                : micLocked
                  ? "rgba(251,191,36,0.12)"
                  : "rgba(239,68,68,0.15)",
              border: `2.5px solid ${
                isMuted ? "rgba(255,255,255,0.18)" : micLocked ? "#fbbf24" : "#ef4444"
              }`,
              opacity: !isActive ? 0.4 : 1,
              cursor: !isActive || micLocked ? "not-allowed" : "pointer",
              boxShadow: !isMuted && isActive && !micLocked ? "0 0 20px rgba(239,68,68,0.25)" : "none",
            }}
          >
            {micLocked ? "🔒" : isMuted ? "🔇" : "🎙"}
          </button>

          {/* Spacer to keep mic centered */}
          <div style={{ width: 88 }} />
        </div>
      </div>
    </>
  )
}
