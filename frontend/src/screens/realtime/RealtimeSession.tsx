import { useCallback, useEffect, useRef, useMemo } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import ScreenLabel from "@/components/shared/ScreenLabel"
import useRealtimeStore, { type ChatMessage } from "@/store/realtimeStore"
import { useRealtimeWebSocket, _wsRef } from "@/hooks/useRealtimeWebSocket"
import { useAudioCapture } from "@/hooks/useAudioCapture"
import { useTtsPlayback } from "@/hooks/useTtsPlayback"
import { realtimeApi } from "@/services/api"

const TOAST_SESSION_ENDED = "Session ended. Transcript saved."

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDuration(s: number): string {
  return `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`
}

const LANG_LABELS: Record<string, string> = {
  en: "English",
  es: "Spanish",
  pt: "Portuguese",
}

const LANG_FLAGS: Record<string, string> = {
  en: "🇺🇸 EN",
  es: "🇪🇸 ES",
  pt: "🇧🇷 PT",
}

// ── Sub-components ────────────────────────────────────────────────────────────

function VerificationChip({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  if (score >= 0.9) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold"
        style={{ background: "rgba(22,163,74,0.18)", color: "#4ade80" }}
      >
        ✔ {pct}%
      </span>
    )
  }
  if (score >= 0.7) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold"
        style={{ background: "rgba(217,119,6,0.18)", color: "#fbbf24" }}
      >
        ▲ {pct}%
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold"
      style={{ background: "rgba(239,68,68,0.18)", color: "#f87171" }}
    >
      ⚠ {pct}%
    </span>
  )
}

function MessageBubble({
  msg,
  myName,
  partnerName,
}: {
  msg: ChatMessage
  myName: string
  partnerName: string
}) {
  const isSelf = msg.speaker === "self"
  const speakerLabel = isSelf ? myName || "You" : msg.speakerName || partnerName || "Partner"
  const timeLabel = msg.timestamp.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })

  return (
    <div className={`flex flex-col ${isSelf ? "items-end" : "items-start"} gap-1`}>
      {/* Speaker + timestamp */}
      <div className="flex items-center gap-2 px-1">
        <span className="text-[11px] font-semibold" style={{ color: "rgba(255,255,255,0.5)" }}>
          {speakerLabel}
        </span>
        <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.25)" }}>
          {timeLabel}
        </span>
      </div>

      {/* Original text bubble */}
      <div
        className="max-w-xs px-3 py-2 text-sm leading-relaxed"
        style={{
          background: isSelf ? "rgba(99,102,241,0.14)" : "rgba(34,211,238,0.08)",
          borderRadius: isSelf ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
          color: "rgba(255,255,255,0.9)",
        }}
      >
        {msg.text}
      </div>

      {/* AI translation block */}
      {msg.translation && (
        <div
          className="max-w-xs px-3 py-2 text-xs leading-relaxed"
          style={{
            borderLeft: "2px solid #C8963E",
            paddingLeft: 10,
            color: "rgba(255,255,255,0.75)",
          }}
        >
          <div className="text-[10px] font-semibold mb-0.5" style={{ color: "#C8963E" }}>
            {msg.targetLanguage ? LANG_FLAGS[msg.targetLanguage] ?? msg.targetLanguage.toUpperCase() : "Translation"}
          </div>
          {msg.translation}
        </div>
      )}

      {/* Legal verification block */}
      {msg.verifiedTranslation && !msg.usedFallback && (
        <div
          className="max-w-xs px-3 py-2 text-xs leading-relaxed"
          style={{
            background: "rgba(99,102,241,0.07)",
            borderLeft: "2px solid rgba(99,102,241,0.4)",
            paddingLeft: 10,
            color: "rgba(255,255,255,0.7)",
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold" style={{ color: "#a5b4fc" }}>
              ✦ Legal Verified
            </span>
            {msg.accuracyScore != null && <VerificationChip score={msg.accuracyScore} />}
          </div>
          {msg.verifiedTranslation === msg.translation ? (
            <span style={{ color: "rgba(255,255,255,0.4)" }}>No changes — legally precise.</span>
          ) : (
            msg.verifiedTranslation
          )}
          {msg.accuracyNote && msg.verifiedTranslation !== msg.translation && (
            <div className="mt-1 text-[10px]" style={{ color: "rgba(255,255,255,0.4)" }}>
              {msg.accuracyNote}
            </div>
          )}
        </div>
      )}

      {/* Duration */}
      {msg.duration != null && (
        <div className="text-[10px] px-1" style={{ color: "rgba(255,255,255,0.25)" }}>
          {msg.duration}s
        </div>
      )}
    </div>
  )
}

function LivePartialBubble({
  speaker,
  text,
  translation,
  myName,
  partnerName,
}: {
  speaker: "self" | "partner"
  text: string
  translation?: string
  myName: string
  partnerName: string
}) {
  const isSelf = speaker === "self"
  const speakerLabel = isSelf ? myName || "You" : partnerName || "Partner"

  return (
    <div className={`flex flex-col ${isSelf ? "items-end" : "items-start"} gap-1`}>
      <div className="flex items-center gap-2 px-1">
        <span className="text-[11px] font-semibold" style={{ color: "rgba(255,255,255,0.4)" }}>
          {speakerLabel}
        </span>
        <span className="blink-dot" />
        <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.3)" }}>
          speaking
        </span>
      </div>
      <div
        className="max-w-xs px-3 py-2 text-sm leading-relaxed"
        style={{
          background: isSelf ? "rgba(99,102,241,0.07)" : "rgba(34,211,238,0.04)",
          borderRadius: isSelf ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
          border: "1px dashed rgba(255,255,255,0.1)",
          color: "rgba(255,255,255,0.6)",
        }}
      >
        {text}
        {translation && (
          <div className="mt-1 text-xs" style={{ color: "rgba(255,255,255,0.4)" }}>
            {translation}
          </div>
        )}
      </div>
    </div>
  )
}

function SidebarSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        className="text-[10px] uppercase tracking-widest mb-2"
        style={{ color: "rgba(255,255,255,0.35)" }}
      >
        {title}
      </div>
      {children}
    </div>
  )
}

function SidebarRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      className="flex justify-between items-center py-1"
      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
    >
      <span style={{ color: "rgba(255,255,255,0.38)" }}>{label}</span>
      <span className="font-medium text-right" style={{ color: "rgba(255,255,255,0.8)" }}>
        {value}
      </span>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function RealtimeSession({ onNav }: Props) {
  // ── Store ──────────────────────────────────────────────────────────────────
  const phase = useRealtimeStore((s) => s.phase)
  const roomCode = useRealtimeStore((s) => s.roomCode)
  const myName = useRealtimeStore((s) => s.myName)
  const myLanguage = useRealtimeStore((s) => s.myLanguage)
  const isCreator = useRealtimeStore((s) => s.isCreator)
  const partner = useRealtimeStore((s) => s.partner)
  const partnerMuted = useRealtimeStore((s) => s.partnerMuted)
  const isMuted = useRealtimeStore((s) => s.isMuted)
  const micLocked = useRealtimeStore((s) => s.micLocked)
  const isRecording = useRealtimeStore((s) => s.isRecording)
  const isSpeaking = useRealtimeStore((s) => s.isSpeaking)
  const isPlayingTts = useRealtimeStore((s) => s.isPlayingTts)
  const duration = useRealtimeStore((s) => s.duration)
  const messages = useRealtimeStore((s) => s.messages)
  const livePartial = useRealtimeStore((s) => s.livePartial)
  const courtDivision = useRealtimeStore((s) => s.courtDivision)
  const courtroom = useRealtimeStore((s) => s.courtroom)
  const caseDocket = useRealtimeStore((s) => s.caseDocket)
  const sessionId  = useRealtimeStore((s) => s.sessionId)
  const toggleMute = useRealtimeStore((s) => s.toggleMute)
  const resetStore = useRealtimeStore((s) => s.reset)

  // ── Hooks ──────────────────────────────────────────────────────────────────
  const { enqueue, clearQueue } = useTtsPlayback()
  const { startCapture, stopCapture } = useAudioCapture()

  // Stable callbacks — prevents cascading identity changes in WS hook
  const sendAudioRef = useRef<((data: Blob | ArrayBuffer) => void) | null>(null)
  const onStartCapture = useCallback(
    () => startCapture((data) => sendAudioRef.current?.(data)),
    [startCapture]
  )
  const onStopCapture = useCallback(
    () => { stopCapture(); clearQueue() },
    [stopCapture, clearQueue]
  )

  const { connect, disconnect, sendMarker, sendAudio } = useRealtimeWebSocket({
    enqueueTts: enqueue,
    onStartCapture,
    onStopCapture,
  })

  // Keep sendAudioRef current — avoids stale closure in startCapture callback
  useEffect(() => { sendAudioRef.current = sendAudio }, [sendAudio])

  // ── Auto-scroll ────────────────────────────────────────────────────────────
  const chatEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, livePartial])

  // ── Reconnect on mount ─────────────────────────────────────────────────────
  // If RealtimeSetup navigated here with the WebSocket still open (normal flow),
  // wsRef.current is already OPEN — do NOT reconnect or the server will delete the
  // existing room and create a new one.
  // Only reconnect when wsRef is null (e.g. after a hard page refresh).
  const savedIsCreator = useRef(isCreator)
  useEffect(() => {
    if (_wsRef.current && _wsRef.current.readyState === WebSocket.OPEN) {
      // Connection is live — just update the onmessage handler so TTS audio
      // from this point on is routed to this session's enqueue callback.
      // The handler is already wired by the hook; nothing else to do.
      return
    }
    // Fallback: reconnect (page refresh or hard navigation)
    if (roomCode && phase !== "idle" && phase !== "ended") {
      connect({ name: myName, roomId: roomCode })
      if (savedIsCreator.current) {
        useRealtimeStore.getState().setIsCreator(true)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // mount only

  // ── Session timer ──────────────────────────────────────────────────────────
  // Duration is incremented by useAudioCapture while recording. We also
  // need a timer when waiting/ready (before audio capture starts).
  const sessionStart = useRef<number | null>(null)
  useEffect(() => {
    if (phase === "active" && sessionStart.current === null) {
      sessionStart.current = Date.now()
    }
  }, [phase])

  // ── Computed sidebar stats ─────────────────────────────────────────────────
  const stats = useMemo(() => {
    const scored = messages.filter((m) => m.accuracyScore != null)
    const avgAsr = scored.length
      ? (scored.reduce((s, m) => s + (m.accuracyScore ?? 0), 0) / scored.length).toFixed(2)
      : "—"
    // NMT confidence: only count messages that have BOTH a translation AND a legal score
    const nmtScored = messages.filter((m) => m.translation != null && m.accuracyScore != null)
    const avgNmt = nmtScored.length
      ? (nmtScored.reduce((s, m) => s + (m.accuracyScore ?? 0), 0) / nmtScored.length).toFixed(2)
      : "—"
    const corrections = scored.filter((m) => (m.accuracyScore ?? 1) < 0.9).length
    const ttsSegments = messages.filter((m) => m.translation != null).length
    return { avgAsr, avgNmt, corrections, ttsSegments }
  }, [messages])

  // ── Action handlers ────────────────────────────────────────────────────────
  function handleToggleMute() {
    // Read live store value so the marker is never stale between renders.
    const currentIsMuted = useRealtimeStore.getState().isMuted
    sendMarker(currentIsMuted ? "MIC_UNMUTE" : "MIC_MUTE")
    toggleMute()
  }

  function handleStartSession() {
    sendMarker("SESSION_START")
  }

  async function handleEndSession() {
    // Send WS marker so the backend finalises the audio/transcript pipeline
    sendMarker("SESSION_END")

    // Call the REST endpoint (idempotent — safe to call even if WS marker fires first)
    if (sessionId) {
      realtimeApi.endRoom(sessionId).catch((err) => {
        console.warn("[RealtimeSession] endRoom REST call failed (non-blocking):", err)
      })
    }

    // Disconnect WS, reset store, queue toast for HomeCourtOfficial
    disconnect()
    resetStore()
    sessionStorage.setItem("pending_toast", TOAST_SESSION_ENDED)
    onNav(SCREENS.HOME_OFFICIAL)
  }

  function handleLeave() {
    disconnect()
    resetStore()
    onNav(SCREENS.HOME_OFFICIAL)
  }

  // ── Transcript area content (phase-aware) ─────────────────────────────────
  const sessionActive = phase === "active"
  const langPairLabel = `${LANG_LABELS[myLanguage] ?? myLanguage} ↔ ${partner ? (LANG_LABELS[partner.language] ?? partner.language) : "…"
    }`

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      {/* Scoped animation styles */}
      <style>{`
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
        .blink-dot { display:inline-block; width:6px; height:6px; border-radius:50%;
                     background:#ef4444; animation:blink 1s ease-in-out infinite; }
        @keyframes waveBar { 0%,100%{transform:scaleY(0.4)} 50%{transform:scaleY(1)} }
      `}</style>

      <div className="min-h-screen flex flex-col" style={{ background: "#0D1B2A", color: "#fff" }}>

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div
          className="px-6 py-2.5 flex items-center justify-between flex-shrink-0"
          style={{ background: "rgba(0,0,0,0.35)", borderBottom: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-3">
            <span className="font-bold tracking-wide text-sm" style={{ fontFamily: "Palatino, Georgia, serif" }}>
              ⚖ CourtAccess AI
            </span>
            {sessionActive && (
              <span
                className="text-[10px] font-semibold px-2 py-0.5 rounded"
                style={{ background: "rgba(239,68,68,0.15)", color: "#ef4444" }}
              >
                ● LIVE
              </span>
            )}
          </div>

          <div className="flex items-center gap-4 text-xs">
            {roomCode && (
              <span style={{ color: "rgba(255,255,255,0.45)" }}>
                Session {roomCode}
                {sessionActive && ` · ${formatDuration(duration)} elapsed`}
              </span>
            )}
            <button
              onClick={() => {
                if (isCreator && phase !== "ended") {
                  void handleEndSession();
                } else {
                  handleLeave();
                }
              }}
              className="px-3 py-1.5 rounded text-xs font-semibold cursor-pointer"
              style={{
                background: phase === "ended" ? "rgba(255,255,255,0.06)" : "#7f1d1d",
                color: phase === "ended" ? "rgba(255,255,255,0.6)" : "#fca5a5",
                border: "none"
              }}
            >
              {phase === "ended" ? "Exit Room" : isCreator ? "End Session" : "Leave Room"}
            </button>
          </div>
        </div>

        {/* ── Body ────────────────────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">

          {/* ── Left: Transcript ──────────────────────────────────────────── */}
          <div className="flex-1 flex flex-col overflow-hidden">

            {/* Sub-header */}
            <div
              className="px-5 py-2.5 flex justify-between items-center text-xs flex-shrink-0"
              style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
            >
              <span className="font-semibold">Live transcript</span>
              <span style={{ color: "rgba(255,255,255,0.38)" }}>{langPairLabel}</span>
            </div>

            {/* Scroll area */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {messages.length === 0 && !livePartial ? (
                /* Empty state — phase-aware */
                <div className="flex flex-col items-center justify-center h-full gap-3">
                  <div className="text-3xl">
                    {phase === "waiting" ? "⏳" : phase === "ready" ? "✋" : phase === "ended" ? "👋" : "💬"}
                  </div>
                  <p className="text-sm text-center max-w-xs" style={{ color: "rgba(255,255,255,0.45)" }}>
                    {phase === "waiting"
                      ? `Waiting for partner to join. Share room code `
                      : phase === "ready"
                        ? isCreator
                          ? "Partner joined. Click Start Session to begin."
                          : "Waiting for host to start session…"
                        : phase === "ended"
                          ? "Session ended. Transcript is preserved above."
                          : "Start speaking — your conversation will appear here in real time."}
                  </p>
                  {phase === "waiting" && roomCode && (
                    <div
                      className="font-mono text-2xl font-bold tracking-widest px-5 py-3 rounded-lg"
                      style={{ background: "rgba(255,255,255,0.06)", color: "#a5b4fc", letterSpacing: "0.25em" }}
                    >
                      {roomCode}
                    </div>
                  )}
                  {phase === "ready" && isCreator && (
                    <button
                      onClick={handleStartSession}
                      className="mt-2 px-6 py-2 rounded-lg text-sm font-semibold cursor-pointer"
                      style={{ background: "#166534", color: "#86efac", border: "none" }}
                    >
                      ▶ Start Session
                    </button>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  {messages.map((msg) => (
                    <MessageBubble
                      key={msg.id}
                      msg={msg}
                      myName={myName}
                      partnerName={partner?.name ?? "Partner"}
                    />
                  ))}
                  {livePartial && (
                    <LivePartialBubble
                      speaker={livePartial.speaker}
                      text={livePartial.text}
                      translation={livePartial.translation}
                      myName={myName}
                      partnerName={partner?.name ?? "Partner"}
                    />
                  )}
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* ── Bottom bar ──────────────────────────────────────────────── */}
            <div
              className="px-5 py-3 flex items-center gap-4 flex-shrink-0"
              style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
            >
              {/* Mic button */}
              <button
                onClick={sessionActive ? handleToggleMute : undefined}
                disabled={!sessionActive || micLocked}
                className="w-10 h-10 rounded-full flex items-center justify-center text-base flex-shrink-0 cursor-pointer"
                style={{
                  background: isMuted
                    ? "rgba(255,255,255,0.06)"
                    : micLocked
                      ? "rgba(251,191,36,0.12)"
                      : "rgba(239,68,68,0.15)",
                  border: `2px solid ${isMuted ? "rgba(255,255,255,0.15)" : micLocked ? "#fbbf24" : "#ef4444"}`,
                  opacity: !sessionActive ? 0.4 : 1,
                  cursor: !sessionActive || micLocked ? "not-allowed" : "pointer",
                }}
              >
                {isMuted ? "🔇" : micLocked ? "🔒" : "🎙"}
              </button>

              {/* Waveform + label */}
              <div className="flex-1 overflow-hidden">
                <div className="flex gap-px h-5 items-end mb-1">
                  {Array.from({ length: 44 }, (_, i) => {
                    const active = sessionActive && isRecording && !isMuted
                    const height = active && isSpeaking
                      ? `${12 + Math.abs(Math.sin(i * 0.8)) * 14}px`
                      : active
                        ? `${4 + Math.abs(Math.sin(i * 0.5)) * 6}px`
                        : "3px"
                    return (
                      <div
                        key={i}
                        className="w-1 rounded-sm flex-shrink-0"
                        style={{
                          height,
                          background: active
                            ? i % 3 === 0 ? "#ef4444" : "rgba(255,255,255,0.2)"
                            : "rgba(255,255,255,0.08)",
                          transition: "height 0.1s ease",
                        }}
                      />
                    )
                  })}
                </div>
                <div className="text-[10px]" style={{ color: "rgba(255,255,255,0.35)" }}>
                  {isMuted
                    ? "Muted"
                    : micLocked
                      ? "Mic paused — listening to translation"
                      : isPlayingTts
                        ? "Partner speaking…"
                        : sessionActive
                          ? "Listening · Silero VAD active · Faster-Whisper processing"
                          : phase === "ready" && !isCreator
                            ? "Waiting for host to start…"
                            : "Inactive"}
                </div>
              </div>

              {/* Confidence */}
              <div className="text-right flex-shrink-0">
                <div className="text-[10px]" style={{ color: "rgba(255,255,255,0.4)" }}>
                  Confidence
                </div>
                <div
                  className="text-lg font-bold"
                  style={{
                    color: stats.avgAsr !== "—" && parseFloat(stats.avgAsr) >= 0.9
                      ? "#4ade80"
                      : stats.avgAsr !== "—" && parseFloat(stats.avgAsr) >= 0.7
                        ? "#fbbf24"
                        : "rgba(255,255,255,0.4)",
                  }}
                >
                  {stats.avgAsr !== "—" ? `${Math.round(parseFloat(stats.avgAsr) * 100)}%` : "—"}
                </div>
              </div>
            </div>
          </div>

          {/* ── Right sidebar ──────────────────────────────────────────────── */}
          <div
            className="w-52 flex flex-col gap-5 p-4 text-xs overflow-y-auto flex-shrink-0"
            style={{ borderLeft: "1px solid rgba(255,255,255,0.06)" }}
          >

            {/* Session Info */}
            <SidebarSection title="Session Info">
              {roomCode && <SidebarRow label="Room" value={<span className="font-mono tracking-wider">{roomCode}</span>} />}
              {caseDocket && <SidebarRow label="Docket" value={caseDocket} />}
              {courtDivision && <SidebarRow label="Court" value={courtDivision.replace(" Court", "")} />}
              {courtroom && <SidebarRow label="Courtroom" value={courtroom} />}
              <SidebarRow label="Language" value={langPairLabel} />
              <SidebarRow
                label="Partner"
                value={
                  partner ? (
                    <span className="flex items-center gap-1">
                      <span
                        className="w-2 h-2 rounded-full inline-block"
                        style={{ background: partnerMuted ? "#f59e0b" : "#22c55e" }}
                      />
                      {partner.name}
                    </span>
                  ) : (
                    <span style={{ color: "rgba(255,255,255,0.3)" }}>—</span>
                  )
                }
              />
            </SidebarSection>

            {/* Model Pipeline */}
            <SidebarSection title="Model Pipeline">
              {[
                { name: "Silero VAD v4", color: "#22c55e" },
                { name: "Faster-Whisper V3", color: "#22c55e" },
                { name: "NLLB-200 1.3B", color: "#22c55e" },
                { name: `Piper TTS (${partner?.language ?? myLanguage})`, color: "#22c55e" },
                { name: "Llama 4 Vertex AI", color: "#f59e0b" },
              ].map((m) => (
                <div key={m.name} className="flex items-center gap-2 py-0.5">
                  <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: m.color }} />
                  <span style={{ color: "rgba(255,255,255,0.65)" }}>{m.name}</span>
                </div>
              ))}
            </SidebarSection>

            {/* Stats */}
            <SidebarSection title="Stats">
              <SidebarRow label="Utterances" value={messages.length} />
              <SidebarRow label="Avg ASR Conf." value={stats.avgAsr} />
              <SidebarRow label="Avg NMT Conf." value={stats.avgNmt} />
              <SidebarRow label="Llama Corrections" value={stats.corrections} />
              <SidebarRow label="TTS Segments" value={stats.ttsSegments} />
            </SidebarSection>

            {/* Phase-specific controls */}
            {phase === "ready" && isCreator && (
              <button
                onClick={handleStartSession}
                className="w-full py-2 rounded-md text-xs font-semibold cursor-pointer"
                style={{ background: "#166534", color: "#86efac", border: "none" }}
              >
                ▶ Start Session
              </button>
            )}
          </div>
        </div>

        <ScreenLabel name="REAL-TIME SESSION — LIVE TRANSLATION" />
      </div>
    </>
  )
}
