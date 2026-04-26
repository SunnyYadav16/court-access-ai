/**
 * JoinRoomScreen — public guest entry point for real-time interpretation rooms.
 * Rendered at /join/:code — outside the auth shell, no sidebar.
 *
 * Page phases:
 *   checking    → fetching room preview (spinner)
 *   landing     → show room details + "Sign In" / "Continue as Guest"
 *   confirm     → guest: editable name field + "Join Session"
 *   signing_in  → Firebase Google popup in progress
 *   joining     → POST /sessions/rooms/join in progress
 *   session     → live guest WS session (renders GuestSession)
 *   error       → room not found / expired / already active
 *
 * Dark-themed standalone page with primary-container hero card,
 * AI transparency notice, and styled guest name input.
 */

import { useEffect, useRef, useState, type ReactNode } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { GoogleAuthProvider, getRedirectResult, signInWithRedirect, type User as FirebaseUser } from "firebase/auth"
import { auth } from "@/config/firebase"
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

// ── Constants ─────────────────────────────────────────────────────────────────

const LANG_LABELS: Record<string, string> = {
  en: "English",
  es: "Spanish (Español)",
  pt: "Portuguese (Português)",
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function Logo() {
  return (
    <header className="flex justify-center mb-8">
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-secondary text-3xl">account_balance</span>
        <span className="font-headline italic text-2xl tracking-tight text-on-surface">COURT ACCESS AI</span>
      </div>
    </header>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin h-5 w-5 text-secondary" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

function PrimaryButton({ onClick, disabled, children }: { onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full bg-secondary hover:bg-secondary-fixed-dim text-on-secondary font-bold py-5 rounded-lg text-lg transition-transform active:scale-[0.98] shadow-lg shadow-secondary/10 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed border-none"
    >
      {children}
    </button>
  )
}

function OutlineButton({ onClick, disabled, children, icon }: { onClick: () => void; disabled?: boolean; children: ReactNode; icon?: string }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center justify-center gap-3 px-6 py-4 rounded-lg border border-secondary/20 text-secondary font-medium hover:bg-secondary/5 transition-colors text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {icon && <span className="material-symbols-outlined text-sm">{icon}</span>}
      {children}
    </button>
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

  // Guards fetchPreview from running when auth auto-join is in progress.
  const authJoinInProgressRef = useRef(false)

  // ── Reconnect: if store already has a live guest session for this room, skip
  //    straight to the session view instead of re-fetching the preview. ────────
  //    Computed synchronously so the initial render already shows GuestSession
  //    and the preview-fetch effect can skip itself.
  const storeState = useRealtimeStore.getState()
  const _canReconnect =
    !!code &&
    storeState.isGuest &&
    !!storeState.roomToken &&
    storeState.roomCode.toUpperCase() === code.toUpperCase() &&
    storeState.phase !== "idle" &&
    storeState.phase !== "ended"

  const [reconnecting] = useState(() => _canReconnect)

  useEffect(() => {
    if (!reconnecting) return
    setJoinMeta({
      roomToken: storeState.roomToken!,
      partnerName: storeState.myName,
      targetLanguage: storeState.myLanguage,
      courtDivision: storeState.courtDivision || null,
      courtroom: storeState.courtroom || null,
    })
    setPagePhase("session")
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // mount only

  // ── Fetch room preview on mount ─────────────────────────────────────────────

  useEffect(() => {
    if (!code) {
      setError("No room code in URL.")
      setPagePhase("error")
      return
    }

    // Skip fetching if we're reconnecting to an existing session or if
    // an auth-based auto-join is in progress (post sign-in redirect).
    if (reconnecting || authJoinInProgressRef.current) return

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
        setPartnerName(data.partner_name)

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

  useEffect(() => {
    if (!code) return

    async function checkAuthOnMount() {
      // Only auto-join after a redirect-based sign-in (join_room_code was
      // stored before the redirect).  Without this guard, any signed-in user
      // who visits /join/:code would be silently auto-joined without seeing
      // the landing page first.
      const pendingJoinCode = sessionStorage.getItem("join_room_code")
      if (!pendingJoinCode || pendingJoinCode.toUpperCase() !== code!.toUpperCase()) return

      let user: FirebaseUser | null = null
      try {
        const result = await getRedirectResult(auth)
        user = result?.user ?? null
      } catch {
        // No redirect result or it errored — fall through.
      }

      if (!user) {
        user = auth.currentUser
      }

      if (user) {
        sessionStorage.removeItem("join_room_code")
        authJoinInProgressRef.current = true
        await handleAuthJoin(user)
      }
    }

    void checkAuthOnMount()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Authenticated join ─────────────────────────────────────────────────────
  // Stays on /join/:code and renders GuestSession with the room JWT — same as
  // the guest flow, but the POST includes the Firebase Bearer token so the
  // backend can record partner_user_id in the DB.

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

      // Render GuestSession in-place (same as guest flow) — the room JWT
      // is what authenticates the WebSocket, not the Firebase token.
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

  // ── Sign in with Google ──────────────────────────────────────────────────────

  async function handleSignIn() {
    if (!code) return
    setPagePhase("signing_in")
    sessionStorage.setItem("join_room_code", code)
    try {
      await signInWithRedirect(auth, new GoogleAuthProvider())
    } catch {
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

  // ── Render ──────────────────────────────────────────────────────────────────

  // Live guest session
  if (pagePhase === "session" && joinMeta && code) {
    return <GuestSession meta={joinMeta} code={code} />
  }

  const inputCls = "w-full bg-surface-container-highest border-none rounded-lg p-5 text-on-surface font-headline italic text-xl focus:ring-1 focus:ring-secondary/50 placeholder:text-outline-variant transition-all outline-none"

  // Outer shell (all pre-session states)
  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-10 bg-background text-on-surface relative">
      {/* Background decoration */}
      <div className="fixed inset-0 -z-10 overflow-hidden pointer-events-none">
        <div className="absolute -top-[20%] -right-[10%] w-[60%] h-[60%] rounded-full bg-primary-container/20 blur-[120px]" />
        <div className="absolute -bottom-[10%] -left-[5%] w-[40%] h-[40%] rounded-full bg-tertiary-container/10 blur-[100px]" />
      </div>

      <main className="w-full max-w-2xl mx-auto space-y-8">
        <Logo />

        {/* Checking */}
        {pagePhase === "checking" && (
          <div className="flex flex-col items-center gap-3">
            <Spinner />
            <p className="text-sm text-on-surface-variant">Loading session details…</p>
          </div>
        )}

        {/* Error */}
        {pagePhase === "error" && (
          <div className="bg-surface-container-low rounded-xl p-8 text-center border border-white/5">
            <span className="material-symbols-outlined text-red-400 text-4xl mb-3 block">error</span>
            <p className="text-lg font-headline text-on-surface mb-2">Unable to join session</p>
            <p className="text-sm text-on-surface-variant">{error ?? "An unexpected error occurred."}</p>
          </div>
        )}

        {/* Signing in */}
        {pagePhase === "signing_in" && (
          <div className="flex flex-col items-center gap-3">
            <Spinner />
            <p className="text-sm text-on-surface-variant">Opening sign-in…</p>
          </div>
        )}

        {/* Joining */}
        {pagePhase === "joining" && (
          <div className="flex flex-col items-center gap-3">
            <Spinner />
            <p className="text-sm text-on-surface-variant">Joining session…</p>
          </div>
        )}

        {/* Landing */}
        {pagePhase === "landing" && preview && (
          <>
            {/* Hero invite card */}
            <div className="relative overflow-hidden rounded-xl bg-primary-container shadow-2xl p-10 border border-white/5">
              <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
                <span className="material-symbols-outlined text-[120px]">account_balance</span>
              </div>
              <div className="relative z-10 space-y-6">
                <div className="space-y-2">
                  <p className="font-label text-secondary-fixed-dim tracking-[0.2em] uppercase text-xs font-semibold">
                    Verification Protocol
                  </p>
                  <h1 className="font-headline text-5xl italic text-on-surface leading-tight">
                    You're invited
                  </h1>
                </div>
                <div className="flex items-center gap-4 bg-surface-container-lowest/50 p-4 rounded-lg w-fit border border-white/5">
                  <span className="text-on-surface-variant text-sm font-label uppercase tracking-widest">Room Code</span>
                  <span className="text-secondary font-headline text-2xl tracking-widest font-bold">{code}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-4">
                  {preview.courtDivision && (
                    <div className="space-y-1">
                      <span className="text-on-primary-container text-[10px] uppercase tracking-wider font-bold">Jurisdiction</span>
                      <p className="text-primary font-medium">{preview.courtDivision}</p>
                    </div>
                  )}
                  <div className="space-y-1">
                    <span className="text-on-primary-container text-[10px] uppercase tracking-wider font-bold">Primary Language</span>
                    <p className="text-primary font-medium">{LANG_LABELS[preview.targetLanguage] ?? preview.targetLanguage}</p>
                  </div>
                  <div className="space-y-1">
                    <span className="text-on-primary-container text-[10px] uppercase tracking-wider font-bold">Joining as</span>
                    <p className="text-primary font-medium">{preview.partnerName}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* AI notice */}
            <div className="bg-secondary-container/5 rounded-xl p-6 border border-secondary-container/20 flex gap-5 items-start">
              <div className="bg-secondary-container/10 p-3 rounded-lg">
                <span className="material-symbols-outlined text-secondary-fixed-dim">auto_awesome</span>
              </div>
              <div className="space-y-1">
                <h3 className="text-secondary-fixed-dim font-bold text-sm">AI Protocol Transparency Notice</h3>
                <p className="text-on-surface-variant text-sm leading-relaxed">
                  This session uses AI-assisted interpretation. All spoken testimony is transcribed
                  in real-time. Translations are for communication assistance only and are not
                  the official court record.
                </p>
              </div>
            </div>

            {/* Guest name + action buttons */}
            <div className="bg-surface-container-low rounded-xl p-10 space-y-8 shadow-xl">
              <div className="space-y-6">
                <div className="space-y-3">
                  <label htmlFor="guest-name" className="block text-on-surface-variant text-xs uppercase tracking-widest font-bold px-1">
                    Confirm your name
                  </label>
                  <input
                    id="guest-name"
                    type="text"
                    value={partnerName}
                    onChange={(e) => setPartnerName(e.target.value)}
                    placeholder="Enter full legal name"
                    maxLength={100}
                    onKeyDown={(e) => e.key === "Enter" && handleGuestJoin()}
                    autoFocus
                    className={inputCls}
                  />
                  {formError && <p className="text-xs text-red-400 px-1">{formError}</p>}
                  <p className="text-[10px] text-outline px-1">
                    This name will be visible to the court official and clerks.
                  </p>
                </div>

                <div className="pt-4 flex flex-col gap-4">
                  <PrimaryButton onClick={handleGuestJoin}>
                    Continue as Guest
                  </PrimaryButton>

                  <div className="flex items-center gap-4 py-2">
                    <div className="h-px bg-outline-variant flex-grow" />
                    <span className="text-outline text-[10px] uppercase tracking-[0.2em]">or elevate access</span>
                    <div className="h-px bg-outline-variant flex-grow" />
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <OutlineButton onClick={handleSignIn} icon="login">
                      Sign In
                    </OutlineButton>
                    <OutlineButton onClick={() => {
                      if (code) sessionStorage.setItem("join_room_code", code)
                      navigate("/signup")
                    }} icon="app_registration">
                      Create Account
                    </OutlineButton>
                  </div>
                </div>
              </div>
            </div>

            {/* Footer */}
            <footer className="flex justify-between items-center px-4">
              <div className="flex items-center gap-3 opacity-40">
                <div className="w-2 h-2 rounded-full bg-error animate-pulse" />
                <span className="text-[10px] uppercase tracking-widest font-bold">Secure Connection Active</span>
              </div>
            </footer>
          </>
        )}

        {/* Confirm name (legacy — now merged into landing) */}
        {pagePhase === "confirm" && preview && (
          <div className="rounded-xl overflow-hidden bg-surface-container-low border border-white/5">
            <div className="px-5 py-4 bg-gradient-to-r from-[#0D1B2A] to-[#1B263B]">
              <p className="text-[10px] font-label uppercase tracking-widest text-slate-400 mb-0.5">
                Joining as guest
              </p>
              <p className="text-base font-headline text-white">Confirm your name</p>
            </div>

            <div className="px-5 py-5 flex flex-col gap-4">
              <div>
                <label className="text-xs font-label uppercase tracking-widest block mb-2 text-on-surface-variant">
                  Your name
                </label>
                <input
                  type="text"
                  value={partnerName}
                  onChange={(e) => setPartnerName(e.target.value)}
                  placeholder="Enter your name"
                  maxLength={100}
                  onKeyDown={(e) => e.key === "Enter" && handleGuestJoin()}
                  autoFocus
                  className="w-full px-3 py-2.5 rounded-lg text-sm bg-surface-container-lowest text-on-surface border border-white/10 placeholder:text-slate-600 focus:outline-none focus:border-secondary/40"
                />
                {formError && (
                  <p className="text-xs mt-1.5 text-red-400">{formError}</p>
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
      </main>
    </div>
  )
}
