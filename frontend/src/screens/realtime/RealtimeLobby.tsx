/**
 * RealtimeLobby — court official waits here after creating a room.
 *
 * Shows the room code, QR code, and shareable link so the official can hand
 * them to the LEP individual. Polls GET /api/sessions/rooms/{code}/status
 * every 3 s; when the partner joins, briefly shows a confirmation message
 * then navigates to RealtimeSession.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import QRCode from "react-qr-code"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
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

/** Format seconds as MM:SS */
function fmtCountdown(totalSeconds: number): string {
  const s = Math.max(0, totalSeconds)
  return `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`
}

/** Seconds remaining until an ISO-8601 expiry string. */
function secondsUntil(isoString: string): number {
  return Math.floor((new Date(isoString).getTime() - Date.now()) / 1000)
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

const NAVY = "#0B1D3A"

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


  // Prevent navigation from firing twice
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
          // Partner hit join and got a JWT — show "joining" state immediately
          setPartnerPhase("joining")
        } else if (status.phase === "active") {
          setPartnerPhase("active")
          // Brief pause so the user reads the confirmation, then navigate
          setTimeout(goToSession, JOIN_CONFIRM_DELAY_MS)
        } else if (status.phase === "ended") {
          clearInterval(pollId)
          setPollError("This room has ended. Please create a new session.")
        }
      } catch {
        // Silently swallow transient network blips; show persistent failures
        setPollError("Unable to reach server — retrying…")
        setTimeout(() => setPollError(null), 4_000)
      }
    }

    // Immediate first poll, then every POLL_INTERVAL_MS
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

  // ─────────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────────

  const partnerName = partner?.name ?? "the LEP individual"
  const partnerLang = partner?.language ?? "es"
  const isExpired   = countdown <= 0

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />

      <div className="max-w-xl mx-auto px-5 py-8">
        <h1
          className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          Waiting Room
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Share the room code or link below with {partnerName}.
        </p>

        {/* ── Partner joining banner (JWT issued, WS not yet open) ──────────── */}
        {partnerPhase === "joining" && (
          <div
            className="rounded-md p-4 mb-4 flex items-center gap-3"
            style={{ background: "#EFF6FF", border: "1.5px solid #93C5FD" }}
          >
            <span className="text-xl">🔗</span>
            <div>
              <p className="text-sm font-semibold" style={{ color: "#1D4ED8" }}>
                {partnerName} is connecting…
              </p>
              <p className="text-xs" style={{ color: "#2563EB" }}>
                They have the code — waiting for their connection to open.
              </p>
            </div>
          </div>
        )}

        {/* ── Partner fully connected banner ───────────────────────────────── */}
        {partnerPhase === "active" && (
          <div
            className="rounded-md p-4 mb-4 flex items-center gap-3"
            style={{ background: "#F0FDF4", border: "1.5px solid #86EFAC" }}
          >
            <span className="text-xl">✅</span>
            <div>
              <p className="text-sm font-semibold" style={{ color: "#166534" }}>
                {partnerName} has joined
              </p>
              <p className="text-xs" style={{ color: "#15803D" }}>
                Starting session…
              </p>
            </div>
          </div>
        )}

        {/* ── Poll error ──────────────────────────────────────────────────── */}
        {pollError && partnerPhase === "waiting" && (
          <div
            className="rounded-md p-3 mb-4 text-xs"
            style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#991B1B" }}
          >
            {pollError}
          </div>
        )}

        {/* ── Code + QR card ──────────────────────────────────────────────── */}
        <Card className="mb-4">
          <CardContent className="p-6">

            {/* Room code */}
            <div className="text-center mb-6">
              <p className="text-xs font-semibold uppercase tracking-widest mb-2"
                style={{ color: "#8494A7" }}>
                Room Code
              </p>
              <div className="flex items-center justify-center gap-3">
                <span
                  className="text-4xl font-mono font-bold tracking-[0.2em] select-all"
                  style={{ color: NAVY, letterSpacing: "0.2em" }}
                >
                  {roomCode}
                </span>
                <button
                  onClick={handleCopyCode}
                  title="Copy code"
                  className="text-xs px-2.5 py-1 rounded-md font-semibold transition-colors"
                  style={{
                    background: copied ? "#DCFCE7" : "#E2E6EC",
                    color: copied ? "#166534" : "#4A5568",
                  }}
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>

              {/* Expiry countdown */}
              <p
                className="text-xs mt-2"
                style={{ color: isExpired ? "#DC2626" : "#8494A7" }}
              >
                {isExpired
                  ? "Code expired — please create a new session"
                  : `Expires in ${fmtCountdown(countdown)}`}
              </p>
            </div>

            {/* QR code */}
            {joinUrl && !isExpired && (
              <div className="flex justify-center mb-5">
                <div className="p-3 bg-white rounded-lg inline-block"
                  style={{ border: "1.5px solid #E2E6EC" }}>
                  <QRCode
                    value={joinUrl}
                    size={160}
                    fgColor={NAVY}
                    bgColor="#ffffff"
                    level="M"
                  />
                </div>
              </div>
            )}

            {/* Shareable link */}
            <div>
              <p className="text-xs font-semibold mb-1.5" style={{ color: "#4A5568" }}>
                Shareable link
              </p>
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-md"
                style={{ background: "#F6F7F9", border: "1.5px solid #E2E6EC" }}
              >
                <span
                  className="flex-1 text-xs truncate font-mono"
                  style={{ color: "#1A2332" }}
                >
                  {joinUrl}
                </span>
                <button
                  onClick={handleCopyLink}
                  className="text-xs px-2 py-0.5 rounded font-semibold shrink-0"
                  style={{ background: "#E2E6EC", color: "#4A5568" }}
                >
                  Copy
                </button>
              </div>
            </div>

          </CardContent>
        </Card>

        {/* ── Session details ──────────────────────────────────────────────── */}
        <Card className="mb-4">
          <CardContent className="p-4">
            <p className="text-xs font-semibold mb-3" style={{ color: "#1A2332" }}>
              Session Details
            </p>
            <div className="flex flex-col gap-1.5">
              {[
                { label: "LEP Individual", value: partnerName },
                { label: "Language", value: LANG_LABELS[partnerLang] ?? partnerLang },
                { label: "Court Division", value: courtDivision || "—" },
                { label: "Courtroom", value: courtroom || "—" },
                { label: "Your Language", value: LANG_LABELS[myLanguage] ?? myLanguage },
                ...(caseDocket ? [{ label: "Case Docket", value: caseDocket }] : []),
              ].map(({ label, value }) => (
                <div key={label}
                  className="flex justify-between items-center text-xs py-1"
                  style={{ borderBottom: "1px solid #F0F2F5" }}>
                  <span style={{ color: "#8494A7" }}>{label}</span>
                  <span className="font-medium" style={{ color: "#1A2332" }}>{value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* ── Status indicator ─────────────────────────────────────────────── */}
        {partnerPhase === "waiting" && (
          <div className="flex items-center gap-3 justify-center py-2">
            <span className="relative flex h-2.5 w-2.5">
              <span
                className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
                style={{ background: "#F59E0B" }}
              />
              <span
                className="relative inline-flex rounded-full h-2.5 w-2.5"
                style={{ background: "#F59E0B" }}
              />
            </span>
            <p className="text-sm" style={{ color: "#4A5568" }}>
              Waiting for <strong style={{ color: "#1A2332" }}>{partnerName}</strong> to join…
            </p>
          </div>
        )}
      </div>

      <ScreenLabel name="REAL-TIME — WAITING LOBBY" />
    </div>
  )
}
