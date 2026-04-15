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
import useRealtimeStore, { type ChatMessage } from "@/store/realtimeStore"
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

const LANG_LABELS: Record<string, string> = {
  en: "English",
  es: "Spanish (Español)",
  pt: "Portuguese (Português)",
}

// Per audio-state: { ring color, icon, label, sublabel, animate }
const STATE_CONFIG: Record<
  AudioState,
  { ring: string; icon: string; label: string; sublabel: string; pulse: boolean; spin: boolean }
> = {
  connecting:   { ring: "#475569", icon: "more_horiz",         label: "Connecting…",        sublabel: "Setting up your session", pulse: false, spin: true },
  waiting:      { ring: "#F59E0B", icon: "hourglass_top",      label: "Waiting",            sublabel: "Session will start shortly", pulse: true, spin: false },
  your_turn:    { ring: "#3B82F6", icon: "mic",                label: "You may speak",      sublabel: "Speak clearly into your microphone", pulse: true, spin: false },
  you_speaking: { ring: "#EF4444", icon: "mic",                label: "You're speaking",    sublabel: "Listening…", pulse: false, spin: false },
  translating:  { ring: "#A78BFA", icon: "translate",          label: "Translating",        sublabel: "Processing your speech", pulse: true, spin: false },
  ai_speaking:  { ring: "#22C55E", icon: "volume_up",          label: "Court is speaking",  sublabel: "Listen to the translation", pulse: true, spin: false },
  muted:        { ring: "#6B7280", icon: "mic_off",            label: "Microphone muted",   sublabel: "Tap the mic button to unmute", pulse: false, spin: false },
  ended:        { ring: "#475569", icon: "waving_hand",        label: "Session ended",      sublabel: "Thank you", pulse: false, spin: false },
}

// ── Guest message bubbles ─────────────────────────────────────────────────────

function GuestMessageBubble({
  msg,
  myName,
  partnerName,
}: {
  msg: ChatMessage
  myName: string
  partnerName: string
}) {
  const isSelf = msg.speaker === "self"
  const displayText = isSelf
    ? msg.text
    : (msg.verifiedTranslation ?? msg.translation ?? msg.text)
  const subText = isSelf ? msg.translation : msg.text
  const subLabel = isSelf ? "Sent as" : "Original"
  const speakerLabel = isSelf ? (myName || "You") : (partnerName || "Court Official")

  return (
    <div className={`flex flex-col ${isSelf ? "items-end" : "items-start"} gap-1`}>
      <div className="flex items-center gap-2 px-1">
        <span className="text-[11px] font-semibold text-white/50">
          {speakerLabel}
        </span>
        <span className="text-[10px] text-white/25">
          {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
      <div
        className={`max-w-xs px-3 py-2 text-sm leading-relaxed text-white/[0.92] ${
          isSelf
            ? "bg-indigo-500/[0.14] rounded-[14px_14px_4px_14px]"
            : "bg-green-500/10 rounded-[14px_14px_14px_4px]"
        }`}
      >
        {displayText}
      </div>
      {subText && (
        <div className="max-w-xs px-2 text-[11px] leading-relaxed text-white/35">
          <span className="text-white/20">{subLabel}: </span>
          {subText}
        </div>
      )}
      {/* Legal verification — shown for partner messages that have been verified */}
      {!isSelf && msg.verifiedTranslation && (
        <div className={`max-w-xs px-3 py-2 text-xs leading-relaxed border-l-2 pl-2.5 ${
          msg.usedFallback
            ? "bg-amber-500/[0.05] border-amber-500/30 text-white/55"
            : "bg-indigo-500/[0.07] border-indigo-500/40 text-white/70"
        }`}>
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-[10px] font-semibold flex items-center gap-1 ${
              msg.usedFallback ? "text-amber-400" : "text-indigo-300"
            }`}>
              <span className="material-symbols-outlined text-xs">gavel</span>
              {msg.usedFallback ? "Verification Unavailable" : "Legal Verified"}
            </span>
            {msg.accuracyScore != null && !msg.usedFallback && (
              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                msg.accuracyScore >= 0.9 ? "bg-green-900/30 text-green-400"
                : msg.accuracyScore >= 0.7 ? "bg-amber-900/30 text-amber-400"
                : "bg-red-900/30 text-red-400"
              }`}>
                {Math.round(msg.accuracyScore * 100)}%
              </span>
            )}
          </div>
          {msg.usedFallback ? (
            <span className="text-white/35">Showing machine translation.</span>
          ) : msg.verifiedTranslation === msg.translation ? (
            <span className="text-white/40">No changes — legally precise.</span>
          ) : (
            <span>{msg.verifiedTranslation}</span>
          )}
          {msg.accuracyNote && !msg.usedFallback && msg.verifiedTranslation !== msg.translation && (
            <div className="mt-1 text-[10px] text-white/40">{msg.accuracyNote}</div>
          )}
        </div>
      )}
    </div>
  )
}

function GuestPartialBubble({
  partial,
  myName,
  partnerName,
}: {
  partial: { speaker: "self" | "partner"; text: string; translation?: string }
  myName: string
  partnerName: string
}) {
  const isSelf = partial.speaker === "self"
  const speakerLabel = isSelf ? (myName || "You") : (partnerName || "Court Official")
  const displayText = isSelf ? partial.text : (partial.translation ?? partial.text)

  return (
    <div className={`flex flex-col ${isSelf ? "items-end" : "items-start"} gap-1`}>
      <div className="flex items-center gap-2 px-1">
        <span className="text-[11px] font-semibold text-white/40">
          {speakerLabel}
        </span>
        <span className="blink-dot" />
        <span className="text-[10px] text-white/30">speaking</span>
      </div>
      <div
        className={`max-w-xs px-3 py-2 text-sm leading-relaxed border border-dashed border-white/10 text-white/60 ${
          isSelf
            ? "bg-indigo-500/[0.07] rounded-[14px_14px_4px_14px]"
            : "bg-green-500/[0.05] rounded-[14px_14px_14px_4px]"
        }`}
      >
        {displayText}
      </div>
    </div>
  )
}

// ── Orb component ─────────────────────────────────────────────────────────────

function AudioOrb({ state, compact = false }: { state: AudioState; compact?: boolean }) {
  const cfg = STATE_CONFIG[state]
  const size = compact ? 90 : 200
  const midSize = compact ? 72 : 160
  const innerSize = compact ? 54 : 120

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size, transition: "width 0.3s ease, height 0.3s ease" }}
    >
      {/* Outer pulse ring */}
      {cfg.pulse && (
        <div
          className="absolute rounded-full"
          style={{
            width: size,
            height: size,
            border: `2px solid ${cfg.ring}`,
            opacity: 0.3,
            animation: "guestPulseOuter 2s ease-in-out infinite",
            transition: "width 0.3s ease, height 0.3s ease",
          }}
        />
      )}
      {/* Mid ring */}
      <div
        className="absolute rounded-full"
        style={{
          width: midSize,
          height: midSize,
          border: `2px solid ${cfg.ring}`,
          opacity: 0.5,
          animation: cfg.pulse
            ? "guestPulseMid 2s ease-in-out infinite 0.3s"
            : cfg.spin
              ? "guestSpin 1.4s linear infinite"
              : undefined,
          transition: "width 0.3s ease, height 0.3s ease",
        }}
      />
      {/* Inner orb */}
      <div
        className="relative flex items-center justify-center rounded-full"
        style={{
          width: innerSize,
          height: innerSize,
          background: `radial-gradient(circle at 35% 35%, ${cfg.ring}55, ${cfg.ring}22)`,
          border: `2.5px solid ${cfg.ring}88`,
          boxShadow: `0 0 ${cfg.pulse || state === "you_speaking" ? "40px" : "20px"} ${cfg.ring}44`,
          animation:
            state === "you_speaking"
              ? "guestSpeaking 0.5s ease-in-out infinite alternate"
              : undefined,
          transition: "width 0.3s ease, height 0.3s ease",
        }}
      >
        <span className={`material-symbols-outlined ${compact ? "text-2xl" : "text-4xl"} select-none`}
          style={{ color: cfg.ring }}>
          {cfg.icon}
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
  const myName        = useRealtimeStore((s) => s.myName)
  const partner       = useRealtimeStore((s) => s.partner)
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

    const state = useRealtimeStore.getState()
    const isReconnect = state.messages.length > 0 && state.roomCode === code.toUpperCase()

    if (!isReconnect) {
      // First connect — initialise store from scratch
      reset()
      setMyName(meta.partnerName)
      setMyLanguage(meta.targetLanguage)
      setCourtInfo(meta.courtDivision ?? "", meta.courtroom ?? "", "")
    }

    // Persist guest identity so the session survives a page refresh
    useRealtimeStore.getState().setIsGuest(true)
    useRealtimeStore.getState().setRoomToken(meta.roomToken)

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
    if (isPlayingTts)  return "ai_speaking"
    if (micLocked)     return "translating"
    if (isMuted)       return "muted"
    if (isSpeaking)    return "you_speaking"
    return "your_turn"
  }, [sessionPhase, isPlayingTts, micLocked, isSpeaking, isMuted])

  // ── Auto-scroll ────────────────────────────────────────────────────────────
  const chatEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, livePartial])

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleMicToggle = useCallback(() => {
    const currentIsMuted = useRealtimeStore.getState().isMuted
    toggleMute()
    sendMarker(currentIsMuted ? "MIC_UNMUTE" : "MIC_MUTE")
  }, [toggleMute, sendMarker])

  function handleLeave() {
    disconnect()
    reset()
    setLeft(true)
  }

  // ── Thank-you screen ───────────────────────────────────────────────────────
  if (left) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-5 bg-background text-on-surface">
        <span className="material-symbols-outlined text-5xl text-white/40">waving_hand</span>
        <h1 className="text-2xl font-headline text-white">Session Ended</h1>
        <p className="text-sm text-white/50">Thank you for using CourtAccess AI.</p>
        <p className="text-xs text-center max-w-xs text-white/30">
          If you need a record of this session, please ask the court official.
        </p>
      </div>
    )
  }

  // ── Session ended by host ──────────────────────────────────────────────────
  if (sessionPhase === "ended" && !left) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-5 bg-background text-on-surface">
        <span className="material-symbols-outlined text-5xl text-green-400">check_circle</span>
        <h1 className="text-2xl font-headline text-white">Session Complete</h1>
        <p className="text-sm text-white/50">The court official has ended the session.</p>
        <button
          onClick={() => setLeft(true)}
          className="mt-4 px-6 py-2.5 rounded-lg text-sm font-semibold bg-white/[0.08] text-white/80 border border-white/[0.12] cursor-pointer hover:bg-white/[0.12] transition-colors"
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
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
        .blink-dot { display:inline-block; width:6px; height:6px; border-radius:50%;
                     background:#ef4444; animation:blink 1s ease-in-out infinite; }
      `}</style>

      <div className="h-screen flex flex-col overflow-hidden bg-background text-on-surface">
        {/* ── Top bar ─────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-3 shrink-0 bg-[#0D1B2A] border-b border-white/[0.07] shadow-xl shadow-black/40">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[#FFD700] text-base">gavel</span>
            <span className="text-sm font-headline font-semibold text-white/85">
              CourtAccess AI
            </span>
          </div>
          <div className="flex items-center gap-3">
            {meta.courtDivision && (
              <span className="text-xs text-white/35">{meta.courtDivision}</span>
            )}
            {meta.courtroom && (
              <span className="text-xs text-white/35">{meta.courtroom}</span>
            )}
            <span
              className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                isActive
                  ? "bg-red-500/[0.12] text-red-400"
                  : "bg-white/[0.06] text-white/40"
              }`}
            >
              {isActive ? (
                <span className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400 inline-block" /> LIVE
                </span>
              ) : sessionPhase === "connecting" ? "Connecting" : "Waiting"}
            </span>
          </div>
        </div>

        {/* ── Language banner ─────────────────────────────────────────────── */}
        <div className="text-center py-2 text-xs text-white/30 border-b border-white/[0.04]">
          Your language: <strong className="text-white/55">
            {LANG_LABELS[meta.targetLanguage] ?? meta.targetLanguage}
          </strong>
        </div>

        {/* ── Main content: compact orb + message history ────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Orb area — compact when messages exist */}
          <div
            className={`flex flex-col items-center py-4 shrink-0 transition-all ${
              messages.length > 0 || livePartial ? "border-b border-white/[0.06]" : ""
            }`}
          >
            <AudioOrb state={audioState} compact={messages.length > 0 || !!livePartial} />
            <p className="text-sm font-semibold mt-3 transition-colors" style={{ color: cfg.ring }}>
              {cfg.label}
            </p>
            <p className="text-xs mt-0.5 text-white/35">
              {cfg.sublabel}
            </p>
          </div>

          {/* Message history — scrollable */}
          {messages.length > 0 || livePartial ? (
            <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
              {messages.map((msg) => (
                <GuestMessageBubble
                  key={msg.id}
                  msg={msg}
                  myName={myName || meta.partnerName}
                  partnerName={partner?.name ?? "Court Official"}
                />
              ))}
              {livePartial && (
                <GuestPartialBubble
                  partial={livePartial}
                  myName={myName || meta.partnerName}
                  partnerName={partner?.name ?? "Court Official"}
                />
              )}
              <div ref={chatEndRef} />
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <p className="text-sm text-center max-w-xs text-white/30">
                {sessionPhase === "waiting"
                  ? "Waiting for session to start…"
                  : "Conversation will appear here"}
              </p>
            </div>
          )}
        </div>

        {/* ── Bottom controls ──────────────────────────────────────────────── */}
        <div className="px-6 py-5 flex items-center justify-between shrink-0 border-t border-outline-variant/20 bg-surface-container-lowest/30">
          {/* Leave button */}
          <button
            onClick={handleLeave}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-red-950/50 text-red-300 border border-red-900/50 cursor-pointer hover:bg-red-950/70 transition-colors"
          >
            Leave Session
          </button>

          {/* Mic button — large, centered */}
          <button
            onClick={isActive && !micLocked ? handleMicToggle : undefined}
            disabled={!isActive || micLocked}
            className="w-16 h-16 rounded-full flex items-center justify-center"
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
            <span className="material-symbols-outlined text-2xl">
              {micLocked ? "lock" : isMuted ? "mic_off" : "mic"}
            </span>
          </button>

          {/* Spacer to keep mic centered */}
          <div style={{ width: 88 }} />
        </div>
      </div>
    </>
  )
}
