/**
 * RealtimeLobby — court official waits here after creating a room.
 *
 * Shows the room code, QR code, and shareable link so the official can hand
 * them to the LEP individual. Polls GET /api/sessions/rooms/{code}/status
 * every 3 s; when the partner joins, briefly shows a confirmation message
 * then navigates to RealtimeSession.
 *
 * Renders INSIDE AppShell. Dark-themed with centered hero lobby card,
 * 2-column QR/countdown layout, session parameters, and AI model status.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import QRCode from "react-qr-code"
import { ScreenId, SCREENS } from "@/lib/constants"
import useRealtimeStore from "@/store/realtimeStore"
import { realtimeApi } from "@/services/api"

// ── Constants ─────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 3_000
const JOIN_CONFIRM_DELAY_MS = 2_000

const LANG_LABELS: Record<string, string> = {
  en: "English",
  es: "Spanish (Español)",
  pt: "Portuguese (Português)",
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCountdown(totalSeconds: number): string {
  const s = Math.max(0, totalSeconds)
  return `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`
}

function secondsUntil(isoString: string): number {
  return Math.floor((new Date(isoString).getTime() - Date.now()) / 1000)
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function RealtimeLobby({ onNav }: Props) {
  // Store
  const roomCode          = useRealtimeStore((s) => s.roomCode)
  const joinUrl           = useRealtimeStore((s) => s.joinUrl)
  const roomCodeExpiresAt = useRealtimeStore((s) => s.roomCodeExpiresAt)
  const partner           = useRealtimeStore((s) => s.partner)
  const myLanguage        = useRealtimeStore((s) => s.myLanguage)
  const courtDivision     = useRealtimeStore((s) => s.courtDivision)
  const courtroom         = useRealtimeStore((s) => s.courtroom)
  const caseDocket        = useRealtimeStore((s) => s.caseDocket)

  // UI state
  const [copied, setCopied]               = useState(false)
  const [partnerPhase, setPartnerPhase]   = useState<"waiting" | "joining" | "active">("waiting")
  const [countdown, setCountdown]         = useState<number>(
    roomCodeExpiresAt ? secondsUntil(roomCodeExpiresAt) : 0,
  )
  const [pollError, setPollError]         = useState<string | null>(null)

  const navigatedRef = useRef(false)

  // ── Navigate to session ────────────────────────────────────────────────────

  const goToSession = useCallback(() => {
    if (navigatedRef.current) return
    navigatedRef.current = true
    onNav(SCREENS.REALTIME_SESSION)
  }, [onNav])

  // ── Countdown timer ────────────────────────────────────────────────────────

  useEffect(() => {
    if (!roomCodeExpiresAt) return
    const id = window.setInterval(() => {
      setCountdown(secondsUntil(roomCodeExpiresAt))
    }, 1_000)
    return () => clearInterval(id)
  }, [roomCodeExpiresAt])

  // ── Status polling ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!roomCode || partnerPhase === "active") return

    let pollId: number

    async function poll() {
      try {
        const status = await realtimeApi.getRoomStatus(roomCode)
        setPollError(null)

        if (status.phase === "joining" && partnerPhase === "waiting") {
          setPartnerPhase("joining")
        } else if (status.phase === "active") {
          setPartnerPhase("active")
          setTimeout(goToSession, JOIN_CONFIRM_DELAY_MS)
        } else if (status.phase === "ended") {
          clearInterval(pollId)
          setPollError("This room has ended. Please create a new session.")
        }
      } catch {
        setPollError("Unable to reach server — retrying…")
        setTimeout(() => setPollError(null), 4_000)
      }
    }

    void poll()
    pollId = window.setInterval(() => { void poll() }, POLL_INTERVAL_MS)
    return () => clearInterval(pollId)
  }, [roomCode, partnerPhase, goToSession])

  // ── Copy handlers ──────────────────────────────────────────────────────────

  async function handleCopyCode() {
    await navigator.clipboard.writeText(roomCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2_000)
  }

  async function handleCopyLink() {
    await navigator.clipboard.writeText(joinUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2_000)
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const partnerName = partner?.name ?? "the LEP individual"
  const partnerLang = partner?.language ?? "es"
  const isExpired   = countdown <= 0

  return (
    <div className="px-6 lg:px-8 py-8 max-w-6xl mx-auto space-y-6">

      {/* Status banner */}
      <div className="p-4 bg-primary-container/40 backdrop-blur-md rounded-xl border border-secondary/10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="w-3 h-3 bg-amber-500 rounded-full animate-pulse" />
          <span className="text-sm font-medium tracking-wide uppercase text-on-surface-variant">
            Realtime Synchronization Protocol Active
          </span>
        </div>
        <div className="text-sm text-secondary font-medium hidden sm:block">
          {partnerPhase === "waiting" && "Waiting for interpreter…"}
          {partnerPhase === "joining" && `${partnerName} is connecting…`}
          {partnerPhase === "active" && "Connected — starting session…"}
        </div>
      </div>

      {/* Partner joining banner */}
      {partnerPhase === "joining" && (
        <div className="rounded-lg px-4 py-3 bg-blue-950 border border-blue-900 flex items-center gap-3">
          <span className="material-symbols-outlined text-blue-400">link</span>
          <div>
            <p className="text-sm font-semibold text-blue-300">{partnerName} is connecting…</p>
            <p className="text-xs text-blue-400">They have the code — waiting for their connection to open.</p>
          </div>
        </div>
      )}

      {/* Partner fully connected banner */}
      {partnerPhase === "active" && (
        <div className="rounded-lg px-4 py-3 bg-green-950 border border-green-900 flex items-center gap-3">
          <span className="material-symbols-outlined text-green-400">check_circle</span>
          <div>
            <p className="text-sm font-semibold text-green-300">{partnerName} has joined</p>
            <p className="text-xs text-green-400">Starting session…</p>
          </div>
        </div>
      )}

      {/* Poll error */}
      {pollError && partnerPhase === "waiting" && (
        <div className="rounded-lg px-4 py-3 text-xs bg-red-950 border border-red-900 text-red-300">
          {pollError}
        </div>
      )}

      {/* ── Hero Lobby Card ───────────────────────────────────────── */}
      <section className="bg-surface-container-low rounded-xl p-8 border border-white/5 shadow-2xl relative overflow-hidden">
        {/* Ambient glow */}
        <div className="absolute top-0 right-0 w-64 h-64 bg-amber-500/5 blur-3xl -mr-32 -mt-32 rounded-full" />

        <div className="relative z-10 flex flex-col items-center text-center">
          <h2 className="text-4xl font-headline mb-2">Courtroom Lobby</h2>
          <p className="text-on-surface-variant mb-8">Secure digital gateway for judicial proceedings</p>

          {/* Room code */}
          <div className="w-full max-w-sm bg-surface-container-highest rounded-2xl p-6 mb-8 border border-white/10">
            <span className="text-xs uppercase tracking-widest text-on-surface-variant block mb-3 font-semibold">
              Access Room Code
            </span>
            <div className="flex items-center justify-center gap-4">
              <code className="text-5xl font-mono tracking-tighter text-amber-500 font-bold select-all">
                {roomCode}
              </code>
              <button
                onClick={handleCopyCode}
                title="Copy Code"
                className={`p-2 rounded-lg transition-colors cursor-pointer border-none ${
                  copied
                    ? "bg-green-950 text-green-400"
                    : "hover:bg-white/10 text-amber-500"
                }`}
              >
                <span className="material-symbols-outlined">content_copy</span>
              </button>
            </div>
          </div>

          {/* QR + Countdown + Link */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 w-full max-w-2xl">
            {/* QR side */}
            <div className="flex flex-col items-center gap-4 p-6 bg-surface-container-lowest rounded-xl border border-white/5">
              {joinUrl && !isExpired ? (
                <div className="p-2 bg-white rounded-lg">
                  <QRCode
                    value={joinUrl}
                    size={160}
                    fgColor="#0D1B2A"
                    bgColor="#ffffff"
                    level="M"
                  />
                </div>
              ) : (
                <div className="w-40 h-40 bg-surface-container-high rounded-lg flex items-center justify-center">
                  <span className="material-symbols-outlined text-4xl text-outline">qr_code</span>
                </div>
              )}
              <span className="text-xs text-on-surface-variant uppercase tracking-widest">Guest Scan Joining</span>
            </div>

            {/* Countdown + Link side */}
            <div className="flex flex-col justify-center gap-4">
              <div className="text-left">
                <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2">
                  Expiry Countdown
                </label>
                <div className={`flex items-center gap-2 text-3xl font-light ${isExpired ? "text-error" : "text-on-surface-variant"}`}>
                  <span className="material-symbols-outlined">schedule</span>
                  <span>{isExpired ? "Expired" : fmtCountdown(countdown)}</span>
                </div>
              </div>

              <div className="w-full">
                <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2">
                  Shareable Link
                </label>
                <div className="flex items-center bg-surface-container-lowest rounded-lg border border-white/10 overflow-hidden">
                  <span className="bg-transparent text-sm text-on-surface-variant flex-grow px-4 truncate font-mono">
                    {joinUrl}
                  </span>
                  <button
                    onClick={handleCopyLink}
                    className="bg-amber-500 text-on-secondary px-4 py-2 hover:bg-amber-400 transition-colors cursor-pointer border-none shrink-0"
                  >
                    <span className="material-symbols-outlined text-sm">content_copy</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Waiting indicator */}
      {partnerPhase === "waiting" && (
        <div className="bg-surface-container-high rounded-xl p-6 border border-amber-500/10 flex items-center justify-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-4 h-4 bg-amber-500 rounded-full animate-pulse" />
            <span className="text-lg font-headline italic text-amber-500">
              Waiting for {partnerName} to join…
            </span>
          </div>
        </div>
      )}

      {/* ── Session Details + AI Status ────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Session Parameters */}
        <section className="bg-surface-container-low rounded-xl border border-white/5 overflow-hidden">
          <div className="p-5 border-b border-white/5 bg-primary-container/20">
            <h3 className="text-xl font-headline">Session Parameters</h3>
          </div>
          <div className="p-6 space-y-4">
            {[
              { label: "LEP Individual", value: partnerName },
              { label: "Language", value: LANG_LABELS[partnerLang] ?? partnerLang },
              { label: "Court Division", value: courtDivision || "—" },
              { label: "Courtroom", value: courtroom || "—" },
              { label: "Your Language", value: LANG_LABELS[myLanguage] ?? myLanguage },
              ...(caseDocket ? [{ label: "Case Docket", value: caseDocket }] : []),
            ].map(({ label, value }) => (
              <div key={label} className="flex justify-between items-center">
                <span className="text-xs text-on-surface-variant uppercase tracking-widest">{label}</span>
                <span className="font-medium">{value}</span>
              </div>
            ))}
          </div>
        </section>

        {/* AI Model Status */}
        <section className="bg-surface-container-high rounded-xl p-6 border border-white/5">
          <h3 className="text-lg font-headline mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-amber-500">memory</span>
            AI Model Status
          </h3>
          <div className="space-y-3">
            {[
              { name: "Vocal Analysis", status: "READY", color: "text-green-400 bg-green-500/10" },
              { name: "Legal Semantics", status: "WARMING", color: "text-amber-500 bg-amber-500/10" },
              { name: "Contextual Parsing", status: "READY", color: "text-green-400 bg-green-500/10" },
            ].map((m) => (
              <div key={m.name} className="flex items-center justify-between text-sm">
                <span className="text-on-surface-variant">{m.name}</span>
                <span className={`text-[10px] ${m.color} px-2 py-0.5 rounded font-bold`}>{m.status}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
