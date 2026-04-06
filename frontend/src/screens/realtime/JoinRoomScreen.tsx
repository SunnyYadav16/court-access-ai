/**
 * JoinRoomScreen — public guest entry point for real-time interpretation rooms.
 * Rendered at /join/:code — outside the auth shell, no TopBar, no sidebar.
 *
 * Page phases:
 *   checking    → fetching room preview (spinner)
 *   landing     → show room details + "Sign In" / "Continue as Guest"
 *   confirm     → guest: editable name field + "Join Session"
 *   signing_in  → Firebase Google popup in progress
 *   joining     → POST /sessions/rooms/join in progress
 *   session     → live guest WS session (renders GuestSession)
 *   error       → room not found / expired / already active
 */

import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { GoogleAuthProvider, getRedirectResult, signInWithRedirect, type User as FirebaseUser } from "firebase/auth"
import { auth } from "@/config/firebase"
import { Input } from "@/components/ui/input"
import useRealtimeStore from "@/store/realtimeStore"
import { realtimeApi } from "@/services/api"
import GuestSession, { type GuestMeta } from "@/screens/realtime/GuestSession"

// ── Types ─────────────────────────────────────────────────────────────────────

type PagePhase =
  | "checking"
  | "landing"
  | "confirm"
  | "signing_in"
  | "joining"
  | "session"
  | "error"

interface RoomPreview {
  phase: string
  targetLanguage: string
  courtDivision: string | null
  courtroom: string | null
  partnerName: string
  roomCodeExpiresAt: string
}

// ── Design tokens ─────────────────────────────────────────────────────────────

const NAVY = "#0B1D3A"
const BG = "#F6F7F9"

const LANG_LABELS: Record<string, string> = {
  en: "English",
  es: "Spanish (Español)",
  pt: "Portuguese (Português)",
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function Logo() {
  return (
    <div className="flex flex-col items-center gap-1 mb-6">
      <span className="text-4xl">⚖</span>
      <h1
        className="text-xl font-bold"
        style={{ fontFamily: "Palatino, Georgia, serif", color: NAVY }}
      >
        CourtAccess AI
      </h1>
    </div>
  )
}

function Spinner() {
  return (
    <svg
      className="animate-spin h-5 w-5"
      viewBox="0 0 24 24"
      fill="none"
      style={{ color: NAVY }}
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

function PrimaryButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full py-2.5 rounded-lg text-sm font-semibold transition-opacity"
      style={{
        background: NAVY,
        color: "#fff",
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  )
}

function OutlineButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full py-2.5 rounded-lg text-sm font-semibold transition-opacity"
      style={{
        background: "#fff",
        color: NAVY,
        border: `1.5px solid ${NAVY}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  )
}

// ── Detail row (used in landing + session) ────────────────────────────────────

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="flex justify-between items-center text-xs py-1.5"
      style={{ borderBottom: "1px solid #F0F2F5" }}
    >
      <span style={{ color: "#8494A7" }}>{label}</span>
      <span className="font-medium" style={{ color: "#1A2332" }}>{value}</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function JoinRoomScreen() {
  const { code } = useParams<{ code: string }>()
  const navigate = useNavigate()

  const [pagePhase, setPagePhase] = useState<PagePhase>("checking")
  const [preview, setPreview]     = useState<RoomPreview | null>(null)
  const [partnerName, setPartnerName] = useState("")
  const [joinMeta, setJoinMeta]   = useState<GuestMeta | null>(null)
  const [error, setError]         = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  // Store actions needed for the authenticated path
  const reset       = useRealtimeStore((s) => s.reset)
  const setRoomCode = useRealtimeStore((s) => s.setRoomCode)
  const setMyName   = useRealtimeStore((s) => s.setMyName)
  const setMyLanguage = useRealtimeStore((s) => s.setMyLanguage)
  const setIsCreator  = useRealtimeStore((s) => s.setIsCreator)
  const setCourtInfo  = useRealtimeStore((s) => s.setCourtInfo)

  // ── Fetch room preview on mount ─────────────────────────────────────────────

  useEffect(() => {
    if (!code) {
      setError("No room code in URL.")
      setPagePhase("error")
      return
    }

    async function fetchPreview() {
      try {
        const data = await realtimeApi.getRoomPreview(code!)
        const preview: RoomPreview = {
          phase: data.phase,
          targetLanguage: data.target_language,
          courtDivision: data.court_division,
          courtroom: data.courtroom,
          partnerName: data.partner_name,
          roomCodeExpiresAt: data.room_code_expires_at,
        }
        setPreview(preview)
        setPartnerName(data.partner_name)  // pre-fill name field

        if (data.phase === "active") {
          setError("This session has already started.")
          setPagePhase("error")
        } else if (data.phase === "ended" || new Date(data.room_code_expires_at) <= new Date()) {
          setError("This session link has expired or is no longer valid.")
          setPagePhase("error")
        } else {
          setPagePhase("landing")
        }
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } }).response?.status
        if (status === 404) {
          setError("This session link has expired or is invalid.")
        } else {
          setError("Unable to reach the server. Please try again.")
        }
        setPagePhase("error")
      }
    }

    void fetchPreview()
  }, [code])

  // ── Auto-join if Firebase user is already present (post-redirect) ────────────
  // Runs once on mount. Covers two cases:
  //   1. Firebase just redirected back here — getRedirectResult returns a user.
  //   2. The user was already signed in before visiting this page.
  // In both cases we skip the landing screen and call the join endpoint directly.

  useEffect(() => {
    if (!code) return

    async function checkAuthOnMount() {
      // Check for a completed sign-in redirect first.
      let user: FirebaseUser | null = null
      try {
        const result = await getRedirectResult(auth)
        user = result?.user ?? null
      } catch {
        // No redirect result or it errored — fall through.
      }

      // Fallback: an already-authenticated user visiting the link directly.
      if (!user) {
        user = auth.currentUser
      }

      if (user) {
        await handleAuthJoin(user)
      }
    }

    void checkAuthOnMount()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // intentionally empty — one-time check on mount; code/handleAuthJoin are stable

  // ── Authenticated join (after Google sign-in) ─────────────────────────────

  async function handleAuthJoin(user: FirebaseUser) {
    if (!code) return
    setPagePhase("joining")
    try {
      const token = await user.getIdToken()
      const res = await fetch("/api/sessions/rooms/join", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ room_code: code }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json() as {
        session_id: string
        room_token: string
        partner_name: string
        target_language: string
        court_division: string | null
        courtroom: string | null
      }

      // Seed store so RealtimeSession renders correctly
      reset()
      setRoomCode(code)
      setMyName(data.partner_name)
      setMyLanguage(data.target_language)
      setIsCreator(false)
      setCourtInfo(data.court_division ?? "", data.courtroom ?? "", "")
      sessionStorage.setItem("app_screen", "REALTIME_SESSION")
      navigate("/")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to join session.")
      setPagePhase("error")
    }
  }

  // ── Sign in with Google (redirect flow) ──────────────────────────────────────
  // Saves the room code to sessionStorage before navigating away so it can be
  // recovered if the redirect URL ever loses the :code param.
  // getRedirectResult() on the next mount (above) will detect the returning user.

  async function handleSignIn() {
    if (!code) return
    setPagePhase("signing_in")
    sessionStorage.setItem("join_room_code", code)
    try {
      await signInWithRedirect(auth, new GoogleAuthProvider())
      // Page navigates away — nothing below runs.
    } catch (err: unknown) {
      setError("Sign-in failed. Please try again.")
      setPagePhase("error")
    }
  }

  // ── Guest join ──────────────────────────────────────────────────────────────

  async function handleGuestJoin() {
    if (!code) return
    const name = partnerName.trim()
    if (!name) {
      setFormError("Please enter your name.")
      return
    }
    setFormError(null)
    setPagePhase("joining")
    try {
      const res = await fetch("/api/sessions/rooms/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_code: code, partner_name: name }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json() as {
        room_token: string
        partner_name: string
        target_language: string
        court_division: string | null
        courtroom: string | null
      }
      setJoinMeta({
        roomToken: data.room_token,
        partnerName: data.partner_name,
        targetLanguage: data.target_language,
        courtDivision: data.court_division,
        courtroom: data.courtroom,
      })
      setPagePhase("session")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to join session.")
      setPagePhase("error")
    }
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────────

  // ── Live guest session ────────────────────────────────────────────────────
  if (pagePhase === "session" && joinMeta && code) {
    return <GuestSession meta={joinMeta} code={code} />
  }

  // ── Outer shell (all pre-session states) ──────────────────────────────────
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-10"
      style={{ background: BG }}
    >
      <div className="w-full max-w-sm">
        <Logo />

        {/* ── Checking ───────────────────────────────────────────────────── */}
        {pagePhase === "checking" && (
          <div className="flex flex-col items-center gap-3">
            <Spinner />
            <p className="text-sm" style={{ color: "#6B7280" }}>
              Loading session details…
            </p>
          </div>
        )}

        {/* ── Error ──────────────────────────────────────────────────────── */}
        {pagePhase === "error" && (
          <div
            className="rounded-xl p-6 text-center"
            style={{ background: "#fff", border: "1.5px solid #E2E6EC" }}
          >
            <div className="text-3xl mb-3">⚠️</div>
            <p className="text-sm font-semibold mb-1" style={{ color: "#1A2332" }}>
              Unable to join session
            </p>
            <p className="text-xs" style={{ color: "#6B7280" }}>
              {error ?? "An unexpected error occurred."}
            </p>
          </div>
        )}

        {/* ── Signing in ─────────────────────────────────────────────────── */}
        {pagePhase === "signing_in" && (
          <div className="flex flex-col items-center gap-3">
            <Spinner />
            <p className="text-sm" style={{ color: "#6B7280" }}>Opening sign-in…</p>
          </div>
        )}

        {/* ── Joining ────────────────────────────────────────────────────── */}
        {pagePhase === "joining" && (
          <div className="flex flex-col items-center gap-3">
            <Spinner />
            <p className="text-sm" style={{ color: "#6B7280" }}>Joining session…</p>
          </div>
        )}

        {/* ── Landing ────────────────────────────────────────────────────── */}
        {pagePhase === "landing" && preview && (
          <div className="rounded-xl overflow-hidden" style={{ background: "#fff", border: "1.5px solid #E2E6EC" }}>
            {/* Session details header */}
            <div className="px-5 py-4" style={{ background: NAVY, color: "#fff" }}>
              <p className="text-xs font-semibold uppercase tracking-widest mb-0.5"
                style={{ color: "rgba(255,255,255,0.5)" }}>
                You're invited to join
              </p>
              <p className="text-base font-semibold" style={{ fontFamily: "Palatino, Georgia, serif" }}>
                Court Interpretation Session
              </p>
              <p className="text-xs mt-0.5" style={{ color: "rgba(255,255,255,0.65)" }}>
                Room {code}
              </p>
            </div>

            <div className="px-5 py-4">
              {/* Session info */}
              <div className="mb-4">
                <DetailRow label="Language" value={LANG_LABELS[preview.targetLanguage] ?? preview.targetLanguage} />
                {preview.courtDivision && <DetailRow label="Court" value={preview.courtDivision} />}
                {preview.courtroom && <DetailRow label="Courtroom" value={preview.courtroom} />}
                <DetailRow label="Joining as" value={preview.partnerName} />
              </div>

              {/* AI notice */}
              <div
                className="rounded-md p-2.5 mb-5 text-xs leading-relaxed"
                style={{ background: "#FFF7ED", border: "1px solid #FED7AA", color: "#9A3412" }}
              >
                This session uses AI-assisted interpretation. Translations are for communication
                assistance only and are not the official court record.
              </div>

              {/* Action buttons */}
              <div className="flex flex-col gap-2.5">
                <PrimaryButton onClick={() => setPagePhase("confirm")}>
                  Continue as Guest
                </PrimaryButton>
                <OutlineButton onClick={handleSignIn}>
                  Sign In / Create Account
                </OutlineButton>
              </div>
            </div>
          </div>
        )}

        {/* ── Confirm name (guest path) ───────────────────────────────────── */}
        {pagePhase === "confirm" && preview && (
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: "#fff", border: "1.5px solid #E2E6EC" }}
          >
            <div className="px-5 py-4" style={{ background: NAVY, color: "#fff" }}>
              <p className="text-xs font-semibold uppercase tracking-widest mb-0.5"
                style={{ color: "rgba(255,255,255,0.5)" }}>
                Joining as guest
              </p>
              <p className="text-base font-semibold" style={{ fontFamily: "Palatino, Georgia, serif" }}>
                Confirm your name
              </p>
            </div>

            <div className="px-5 py-5 flex flex-col gap-4">
              <div>
                <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
                  Your name
                </label>
                <Input
                  value={partnerName}
                  onChange={(e) => setPartnerName(e.target.value)}
                  placeholder="Enter your name"
                  maxLength={100}
                  onKeyDown={(e) => e.key === "Enter" && handleGuestJoin()}
                  autoFocus
                />
                {formError && (
                  <p className="text-xs mt-1" style={{ color: "#DC2626" }}>{formError}</p>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <PrimaryButton onClick={handleGuestJoin}>
                  Join Session
                </PrimaryButton>
                <OutlineButton onClick={() => setPagePhase("landing")}>
                  Back
                </OutlineButton>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
