import { useCallback, useEffect, useRef, useMemo } from "react"
import { ScreenId, SCREENS, type UserRole } from "@/lib/constants"
import useAuth from "@/hooks/useAuth"
import useRealtimeStore, { type ChatMessage } from "@/store/realtimeStore"
import { useRealtimeWebSocket, _wsRef } from "@/hooks/useRealtimeWebSocket"
import { useAudioCapture } from "@/hooks/useAudioCapture"
import { useTtsPlayback } from "@/hooks/useTtsPlayback"
import { realtimeApi } from "@/services/api"

const TOAST_SESSION_ENDED = "Session ended. Transcript saved."

// ── Word-level diff ──────────────────────────────────────────────────────────

/**
 * Compute a simple word-level diff between the original NLLB translation and
 * the Llama-verified translation.  Returns an array of segments, each marked
 * as "same", "added" (new word from verifier), or "removed" (dropped by verifier).
 *
 * Uses the classic LCS (Longest Common Subsequence) approach on whitespace-
 * tokenised words.  Good enough for short legal utterances — O(n*m) where n
 * and m are word counts (typically <40).
 */
type DiffSegment = { text: string; type: "same" | "added" | "removed" }

function diffWords(original: string, verified: string): DiffSegment[] {
  const a = original.split(/\s+/).filter(Boolean)
  const b = verified.split(/\s+/).filter(Boolean)

  // Build LCS table
  const m = a.length
  const n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1])

  // Back-trace to build diff
  const segments: DiffSegment[] = []
  let i = m, j = n
  const raw: DiffSegment[] = []
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      raw.push({ text: a[i - 1], type: "same" })
      i--; j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      raw.push({ text: b[j - 1], type: "added" })
      j--
    } else {
      raw.push({ text: a[i - 1], type: "removed" })
      i--
    }
  }
  raw.reverse()

  // Merge consecutive segments of the same type into single spans
  for (const seg of raw) {
    const last = segments[segments.length - 1]
    if (last && last.type === seg.type) {
      last.text += " " + seg.text
    } else {
      segments.push({ ...seg })
    }
  }
  return segments
}

function DiffDisplay({ original, verified }: { original: string; verified: string }) {
  const segments = diffWords(original, verified)
  return (
    <span>
      {segments.map((seg, i) =>
        seg.type === "same" ? (
          <span key={i}>{seg.text} </span>
        ) : seg.type === "added" ? (
          <span key={i} className="bg-green-500/20 text-green-300 rounded px-0.5">{seg.text} </span>
        ) : (
          <span key={i} className="bg-red-500/15 text-red-400/70 line-through rounded px-0.5">{seg.text} </span>
        )
      )}
    </span>
  )
}

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
  en: "EN",
  es: "ES",
  pt: "PT",
}

// ── Sub-components ────────────────────────────────────────────────────────────

function VerificationChip({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  if (score >= 0.9) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-900/30 text-green-400">
        <span className="material-symbols-outlined text-[10px]">check_circle</span> {pct}%
      </span>
    )
  }
  if (score >= 0.7) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-900/30 text-amber-400">
        <span className="material-symbols-outlined text-[10px]">warning</span> {pct}%
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-900/30 text-red-400">
      <span className="material-symbols-outlined text-[10px]">error</span> {pct}%
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
      {/* Speaker + language + timestamp */}
      <div className="flex items-center gap-2 px-1">
        <span className="text-[11px] font-semibold text-white/50">
          {speakerLabel}
        </span>
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/[0.08] text-white/40">
          {LANG_FLAGS[msg.language] ?? msg.language.toUpperCase()}
        </span>
        <span className="text-[10px] text-white/25">
          {timeLabel}
        </span>
      </div>

      {/* Original text bubble */}
      <div
        className={`max-w-xs px-3 py-2 text-sm leading-relaxed text-white/90 ${
          isSelf
            ? "bg-indigo-500/[0.14] rounded-[14px_14px_4px_14px]"
            : "bg-cyan-400/[0.08] rounded-[14px_14px_14px_4px]"
        }`}
      >
        {msg.text}
      </div>

      {/* AI translation block */}
      {msg.translation && (
        <div className="max-w-xs px-3 py-2 text-xs leading-relaxed border-l-2 border-[#C8963E] pl-2.5 text-white/75">
          <div className="text-[10px] font-semibold mb-0.5 text-[#C8963E]">
            {msg.targetLanguage ? LANG_FLAGS[msg.targetLanguage] ?? msg.targetLanguage.toUpperCase() : "Translation"}
          </div>
          {msg.translation}
        </div>
      )}

      {/* Legal verification block — hidden when verifier fell back */}
      {msg.verifiedTranslation && !msg.usedFallback && (
        <div className="max-w-xs px-3 py-2 text-xs leading-relaxed border-l-2 pl-2.5 bg-indigo-500/[0.07] border-indigo-500/40 text-white/70">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold flex items-center gap-1 text-indigo-300">
              <span className="material-symbols-outlined text-xs">gavel</span>
              Legal Verified
            </span>
            {msg.accuracyScore != null && <VerificationChip score={msg.accuracyScore} />}
          </div>
          {msg.verifiedTranslation === msg.translation ? (
            <span className="text-white/40">No changes — legally precise.</span>
          ) : (
            <DiffDisplay original={msg.translation ?? ""} verified={msg.verifiedTranslation} />
          )}
          {msg.accuracyNote && msg.verifiedTranslation !== msg.translation && (
            <div className="mt-1 text-[10px] text-white/40">
              {msg.accuracyNote}
            </div>
          )}
        </div>
      )}

      {/* Duration */}
      {msg.duration != null && (
        <div className="text-[10px] px-1 text-white/25">
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
        <span className="text-[11px] font-semibold text-white/40">
          {speakerLabel}
        </span>
        <span className="blink-dot" />
        <span className="text-[10px] text-white/30">
          speaking
        </span>
      </div>
      <div
        className={`max-w-xs px-3 py-2 text-sm leading-relaxed border border-dashed border-white/10 text-white/60 ${
          isSelf
            ? "bg-indigo-500/[0.07] rounded-[14px_14px_4px_14px]"
            : "bg-cyan-400/[0.04] rounded-[14px_14px_14px_4px]"
        }`}
      >
        {text}
        {translation && (
          <div className="mt-1 text-xs text-white/40">
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
      <div className="text-[10px] uppercase tracking-widest mb-2 text-white/35 font-label">
        {title}
      </div>
      {children}
    </div>
  )
}

function SidebarRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center py-1 border-b border-white/[0.04]">
      <span className="text-white/[0.38]">{label}</span>
      <span className="font-medium text-right text-white/80">{value}</span>
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
  const error      = useRealtimeStore((s) => s.error)
  const setError   = useRealtimeStore((s) => s.setError)
  const toggleMute = useRealtimeStore((s) => s.toggleMute)
  const resetStore = useRealtimeStore((s) => s.reset)

  // ── Auth — role-based home screen ──────────────────────────────────────────
  const { role } = useAuth()
  const ROLE_HOME: Record<UserRole, ScreenId> = {
    public:         SCREENS.HOME_PUBLIC,
    court_official: SCREENS.HOME_OFFICIAL,
    interpreter:    SCREENS.HOME_INTERPRETER,
    admin:          SCREENS.HOME_ADMIN,
  }
  const homeScreen = ROLE_HOME[role ?? "court_official"]

  // ── Hooks ──────────────────────────────────────────────────────────────────
  const { enqueue, clearQueue } = useTtsPlayback()
  const { startCapture, stopCapture } = useAudioCapture()

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

  useEffect(() => { sendAudioRef.current = sendAudio }, [sendAudio])

  // ── Auto-scroll ────────────────────────────────────────────────────────────
  const chatEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, livePartial])

  // ── Preflight mic permission ───────────────────────────────────────────────
  useEffect(() => {
    navigator.permissions
      .query({ name: "microphone" as PermissionName })
      .then((result) => {
        if (result.state === "granted") return
        return navigator.mediaDevices
          .getUserMedia({ audio: true })
          .then((stream) => stream.getTracks().forEach((t) => t.stop()))
      })
      .catch(() => {
        setError("Microphone access denied. Please allow mic access in your browser and reload.")
      })
  }, [setError])

  // ── Reconnect on mount ─────────────────────────────────────────────────────
  const savedIsCreator = useRef(isCreator)
  useEffect(() => {
    if (_wsRef.current && _wsRef.current.readyState === WebSocket.OPEN) {
      return
    }
    if (roomCode && phase !== "idle" && phase !== "ended") {
      connect({ name: myName, roomId: roomCode })
      if (savedIsCreator.current) {
        useRealtimeStore.getState().setIsCreator(true)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // mount only

  // ── Session timer ──────────────────────────────────────────────────────────
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
    const currentIsMuted = useRealtimeStore.getState().isMuted
    sendMarker(currentIsMuted ? "MIC_UNMUTE" : "MIC_MUTE")
    toggleMute()
  }

  function handleStartSession() {
    sendMarker("SESSION_START")
  }

  async function handleEndSession() {
    sendMarker("SESSION_END")

    if (sessionId) {
      realtimeApi.endRoom(sessionId).catch((err) => {
        console.warn("[RealtimeSession] endRoom REST call failed (non-blocking):", err)
      })
    }

    disconnect()
    resetStore()
    sessionStorage.setItem("pending_toast", TOAST_SESSION_ENDED)
    onNav(homeScreen)
  }

  function handleLeave() {
    disconnect()
    resetStore()
    onNav(homeScreen)
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

      <div className="min-h-screen flex flex-col bg-background text-on-surface">

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className="px-6 py-2.5 flex items-center justify-between flex-shrink-0 bg-[#0D1B2A] border-b border-white/[0.07] shadow-xl shadow-black/40">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-[#FFD700] text-lg">gavel</span>
            <span className="font-headline font-bold tracking-wide text-sm text-white">
              CourtAccess AI
            </span>
            {sessionActive && (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-red-500/15 text-red-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-red-400" /> LIVE
              </span>
            )}
          </div>

          <div className="flex items-center gap-4 text-xs">
            {roomCode && (
              <span className="text-white/45">
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
              className={`px-3 py-1.5 rounded text-xs font-semibold cursor-pointer border-none ${
                phase === "ended"
                  ? "bg-white/[0.06] text-white/60"
                  : "bg-red-950 text-red-300"
              }`}
            >
              {phase === "ended" ? "Exit Room" : isCreator ? "End Session" : "Leave Room"}
            </button>
          </div>
        </div>

        {/* ── Error banner ────────────────────────────────────────────────── */}
        {error && (
          <div className="px-5 py-2 text-xs flex items-center gap-2 flex-shrink-0 bg-red-950/85 text-red-300 border-b border-red-500/30">
            <span className="material-symbols-outlined text-sm">warning</span>
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="ml-auto opacity-60 hover:opacity-100 cursor-pointer bg-transparent border-none text-inherit text-sm"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        )}

        {/* ── Body ────────────────────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">

          {/* ── Left: Transcript ──────────────────────────────────────────── */}
          <div className="flex-1 flex flex-col overflow-hidden">

            {/* Sub-header */}
            <div className="px-5 py-2.5 flex justify-between items-center text-xs flex-shrink-0 border-b border-white/[0.06]">
              <span className="font-semibold text-on-surface">Live transcript</span>
              <span className="text-white/[0.38]">{langPairLabel}</span>
            </div>

            {/* Scroll area */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {messages.length === 0 && !livePartial ? (
                /* Empty state — phase-aware */
                <div className="flex flex-col items-center justify-center h-full gap-3">
                  <span className="material-symbols-outlined text-4xl text-white/20">
                    {phase === "waiting" ? "hourglass_top" : phase === "ready" ? "pan_tool" : phase === "ended" ? "waving_hand" : "chat"}
                  </span>
                  <p className="text-sm text-center max-w-xs text-white/45">
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
                    <div className="font-mono text-2xl font-bold tracking-[0.25em] px-5 py-3 rounded-lg bg-white/[0.06] text-[#FFD700]">
                      {roomCode}
                    </div>
                  )}
                  {phase === "ready" && isCreator && (
                    <button
                      onClick={handleStartSession}
                      className="mt-2 px-6 py-2 rounded-lg text-sm font-semibold cursor-pointer bg-green-900 text-green-300 border-none flex items-center gap-2"
                    >
                      <span className="material-symbols-outlined text-base">play_arrow</span>
                      Start Session
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
            <div className="px-5 py-3 flex items-center gap-4 flex-shrink-0 border-t border-white/[0.06]">
              {/* Mic button */}
              <button
                onClick={sessionActive ? handleToggleMute : undefined}
                disabled={!sessionActive || micLocked}
                className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
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
                <span className="material-symbols-outlined text-lg">
                  {isMuted ? "mic_off" : micLocked ? "lock" : "mic"}
                </span>
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
                <div className="text-[10px] text-white/35">
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
                <div className="text-[10px] text-white/40">
                  Confidence
                </div>
                <div
                  className={`text-lg font-bold ${
                    stats.avgAsr !== "—" && parseFloat(stats.avgAsr) >= 0.9
                      ? "text-green-400"
                      : stats.avgAsr !== "—" && parseFloat(stats.avgAsr) >= 0.7
                        ? "text-amber-400"
                        : "text-white/40"
                  }`}
                >
                  {stats.avgAsr !== "—" ? `${Math.round(parseFloat(stats.avgAsr) * 100)}%` : "—"}
                </div>
              </div>
            </div>
          </div>

          {/* ── Right sidebar ──────────────────────────────────────────────── */}
          <div className="w-52 flex flex-col gap-5 p-4 text-xs overflow-y-auto flex-shrink-0 border-l border-outline-variant/20 bg-surface-container-lowest/30">

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
                        className={`w-2 h-2 rounded-full inline-block ${partnerMuted ? "bg-amber-500" : "bg-green-500"}`}
                      />
                      {partner.name}
                    </span>
                  ) : (
                    <span className="text-white/30">—</span>
                  )
                }
              />
            </SidebarSection>

            {/* Model Pipeline */}
            <SidebarSection title="Model Pipeline">
              {[
                { name: "Silero VAD v4", icon: "graphic_eq", color: "text-green-500" },
                { name: "Faster-Whisper V3", icon: "mic", color: "text-green-500" },
                { name: "NLLB-200 1.3B", icon: "translate", color: "text-green-500" },
                { name: `Piper TTS (${partner?.language ?? myLanguage})`, icon: "record_voice_over", color: "text-green-500" },
                { name: "Llama 4 Vertex AI", icon: "gavel", color: "text-amber-500" },
              ].map((m) => (
                <div key={m.name} className="flex items-center gap-2 py-0.5">
                  <span className={`material-symbols-outlined text-[10px] ${m.color}`}>{m.icon}</span>
                  <span className="text-white/65">{m.name}</span>
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
                className="w-full py-2 rounded-md text-xs font-semibold cursor-pointer bg-green-900 text-green-300 border-none flex items-center justify-center gap-1.5"
              >
                <span className="material-symbols-outlined text-sm">play_arrow</span>
                Start Session
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
