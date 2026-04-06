import { useCallback, useState, useEffect } from "react"
import { Route, Routes, useNavigate } from "react-router-dom"

import { SCREENS, SCREEN_TO_PATH, ScreenId, UserRole } from "@/lib/constants"
import ScreenNavigator from "@/components/shared/ScreenNavigator"
import AuthModal from "@/components/auth/AuthModal"
import useAuth from "@/hooks/useAuth"

// Public
import LandingScreen from "@/screens/LandingScreen"

// Auth
import LoginScreen from "@/screens/auth/LoginScreen"
import SignupScreen from "@/screens/auth/SignupScreen"
import ForgotScreen from "@/screens/auth/ForgotScreen"
import ResetScreen from "@/screens/auth/ResetScreen"
import VerifyEmailScreen from "@/screens/auth/VerifyEmailScreen"
import MFAScreen from "@/screens/auth/MFAScreen"

// Home
import HomePublic from "@/screens/home/HomePublic"
import HomeOfficial from "@/screens/home/HomeOfficial"
import HomeInterpreter from "@/screens/home/HomeInterpreter"
import HomeAdmin from "@/screens/home/HomeAdmin"

// Realtime
import RealtimeSetup from "@/screens/realtime/RealtimeSetup"
import RealtimeLobby from "@/screens/realtime/RealtimeLobby"
import RealtimeSession from "@/screens/realtime/RealtimeSession"
import JoinRoomScreen from "@/screens/realtime/JoinRoomScreen"

// Documents
import DocUpload from "@/screens/documents/DocUpload"
import DocProcessing from "@/screens/documents/DocProcessing"
import DocResults from "@/screens/documents/DocResults"

// Forms
import FormsLibrary from "@/screens/forms/FormsLibrary"
import FormDetail from "@/screens/forms/FormDetail"

// Admin
import AdminDashboard from "@/screens/admin/AdminDashboard"
import AdminUsers from "@/screens/admin/AdminUsers"
import AdminForms from "@/screens/admin/AdminForms"
import InterpreterReview from "@/screens/admin/InterpreterReview"

// Settings
import Settings from "@/screens/settings/Settings"

// ─────────────────────────────────────────────────────────────────────────────
// Role-based access control
// ─────────────────────────────────────────────────────────────────────────────

/** Screens each role is permitted to view. */
const ROLE_SCREENS: Record<UserRole, Set<ScreenId>> = {
  public: new Set([
    SCREENS.LANDING,
    SCREENS.LOGIN, SCREENS.SIGNUP, SCREENS.FORGOT, SCREENS.RESET,
    SCREENS.VERIFY_EMAIL, SCREENS.MFA,
    SCREENS.HOME_PUBLIC,
    SCREENS.DOC_UPLOAD, SCREENS.DOC_PROCESSING, SCREENS.DOC_RESULTS,
    SCREENS.FORMS_LIBRARY, SCREENS.FORM_DETAIL,
    SCREENS.SETTINGS,
  ]),
  court_official: new Set([
    SCREENS.LANDING,
    SCREENS.LOGIN, SCREENS.SIGNUP, SCREENS.FORGOT, SCREENS.RESET,
    SCREENS.VERIFY_EMAIL, SCREENS.MFA,
    SCREENS.HOME_OFFICIAL,
    SCREENS.REALTIME_SETUP, SCREENS.REALTIME_LOBBY, SCREENS.REALTIME_SESSION,
    SCREENS.DOC_UPLOAD, SCREENS.DOC_PROCESSING, SCREENS.DOC_RESULTS,
    SCREENS.FORMS_LIBRARY, SCREENS.FORM_DETAIL,
    SCREENS.SETTINGS,
  ]),
  interpreter: new Set([
    SCREENS.LANDING,
    SCREENS.LOGIN, SCREENS.SIGNUP, SCREENS.FORGOT, SCREENS.RESET,
    SCREENS.VERIFY_EMAIL, SCREENS.MFA,
    SCREENS.HOME_INTERPRETER,
    SCREENS.INTERPRETER_REVIEW,
    SCREENS.FORMS_LIBRARY, SCREENS.FORM_DETAIL,
    SCREENS.SETTINGS,
  ]),
  admin: new Set(Object.values(SCREENS) as ScreenId[]),
}

/** Role-appropriate home screen for redirect-on-deny. */
const ROLE_HOME: Record<UserRole, ScreenId> = {
  public:         SCREENS.HOME_PUBLIC,
  court_official: SCREENS.HOME_OFFICIAL,
  interpreter:    SCREENS.HOME_INTERPRETER,
  admin:          SCREENS.HOME_ADMIN,
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Full-screen loading spinner during auth initialisation */
function LoadingSpinner() {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center"
      style={{ background: "#F6F7F9" }}
    >
      <div className="text-4xl mb-4">⚖</div>
      <h1
        className="text-xl font-bold mb-4"
        style={{ fontFamily: "Palatino, Georgia, serif", color: "#0B1D3A" }}
      >
        CourtAccess AI
      </h1>
      <svg
        className="animate-spin h-6 w-6"
        viewBox="0 0 24 24"
        fill="none"
        style={{ color: "#0B1D3A" }}
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Public route wrappers
// Rendered completely outside the authenticated app shell — no sidebar, no
// TopBar, no role context.  onNav maps ScreenId values to URL paths so the
// existing screen components work without modification.
// ─────────────────────────────────────────────────────────────────────────────

function PublicLoginRoute() {
  const navigate = useNavigate()
  const onNav = useCallback(
    (s: ScreenId) => navigate(SCREEN_TO_PATH[s] ?? "/"),
    [navigate],
  )
  return <LoginScreen onNav={onNav} />
}

function PublicSignupRoute() {
  const navigate = useNavigate()
  const onNav = useCallback(
    (s: ScreenId) => navigate(SCREEN_TO_PATH[s] ?? "/"),
    [navigate],
  )
  return <SignupScreen onNav={onNav} />
}

// ─────────────────────────────────────────────────────────────────────────────
// Protected app — requires a valid Firebase session.
// This is the existing App logic, extracted into its own component so the
// router can guard it as a single catch-all route.
// ─────────────────────────────────────────────────────────────────────────────

function ProtectedApp() {
  const { authState, role, authModalOpen } = useAuth()
  const [screen, setScreen] = useState<ScreenId>(SCREENS.LANDING)
  const onNav = (s: ScreenId) => {
    // Silently redirect to role home if the target screen is not permitted
    const target = role && !ROLE_SCREENS[role].has(s) ? ROLE_HOME[role] : s
    sessionStorage.setItem("app_screen", target) // navigation hint only — not sensitive data
    setScreen(target)
  }

  // Auto-navigate to role-appropriate home screen on authentication
  useEffect(() => {
    if (authState === "unauthenticated") {
      setScreen(SCREENS.LANDING)
      return
    }

    if (authState === "authenticated" && role) {
      const saved = sessionStorage.getItem("app_screen") as ScreenId | null
      const AUTH_SCREENS = new Set<string>([
        SCREENS.LOGIN,
        SCREENS.SIGNUP,
        SCREENS.FORGOT,
        SCREENS.RESET,
        SCREENS.VERIFY_EMAIL,
        SCREENS.MFA,
      ])

      if (
        saved &&
        !AUTH_SCREENS.has(saved) &&
        ROLE_SCREENS[role].has(saved as ScreenId)
      ) {
        setScreen(saved as ScreenId)
      } else {
        setScreen(ROLE_HOME[role])
      }
    }
  }, [authState, role])

  // Screen renderer
  const renderScreen = () => {
    // If the active screen is outside the role's allowed set (e.g. direct URL
    // manipulation or stale sessionStorage), fall back to the role home screen.
    const effectiveScreen =
      role && !ROLE_SCREENS[role].has(screen) ? ROLE_HOME[role] : screen

    switch (effectiveScreen) {
      // Public
      case SCREENS.LANDING:            return <LandingScreen onNav={onNav} />
      // Auth (accessible within ProtectedApp via ScreenNavigator dev flow)
      case SCREENS.LOGIN:              return <LoginScreen onNav={onNav} />
      case SCREENS.SIGNUP:             return <SignupScreen onNav={onNav} />
      case SCREENS.FORGOT:             return <ForgotScreen onNav={onNav} />
      case SCREENS.RESET:              return <ResetScreen onNav={onNav} />
      case SCREENS.VERIFY_EMAIL:       return <VerifyEmailScreen onNav={onNav} />
      case SCREENS.MFA:                return <MFAScreen onNav={onNav} />
      // Home
      case SCREENS.HOME_PUBLIC:        return <HomePublic onNav={onNav} />
      case SCREENS.HOME_OFFICIAL:      return <HomeOfficial onNav={onNav} />
      case SCREENS.HOME_INTERPRETER:   return <HomeInterpreter onNav={onNav} />
      case SCREENS.HOME_ADMIN:         return <HomeAdmin onNav={onNav} />
      // Realtime
      case SCREENS.REALTIME_SETUP:     return <RealtimeSetup onNav={onNav} />
      case SCREENS.REALTIME_LOBBY:     return <RealtimeLobby onNav={onNav} />
      case SCREENS.REALTIME_SESSION:   return <RealtimeSession onNav={onNav} />
      // Documents
      case SCREENS.DOC_UPLOAD:         return <DocUpload onNav={onNav} />
      case SCREENS.DOC_PROCESSING:     return <DocProcessing onNav={onNav} />
      case SCREENS.DOC_RESULTS:        return <DocResults onNav={onNav} />
      // Forms
      case SCREENS.FORMS_LIBRARY:      return <FormsLibrary onNav={onNav} />
      case SCREENS.FORM_DETAIL:        return <FormDetail onNav={onNav} />
      // Admin
      case SCREENS.ADMIN_DASHBOARD:    return <AdminDashboard onNav={onNav} />
      case SCREENS.ADMIN_USERS:        return <AdminUsers onNav={onNav} />
      case SCREENS.ADMIN_FORMS:        return <AdminForms onNav={onNav} />
      case SCREENS.INTERPRETER_REVIEW: return <InterpreterReview onNav={onNav} />
      // Settings
      case SCREENS.SETTINGS:           return <Settings onNav={onNav} />
      default:                         return <LandingScreen onNav={onNav} />
    }
  }

  if (authState === "loading") {
    return <LoadingSpinner />
  }

  if (
    authState === "unauthenticated" ||
    authState === "needs_email_verification" ||
    authState === "needs_role_selection"
  ) {
    return (
      <>
        <LandingScreen onNav={onNav} />
        {authModalOpen && <AuthModal />}
      </>
    )
  }

  if (authState === "authenticated") {
    return (
      <div className="flex min-h-screen">
        <ScreenNavigator current={screen} onNav={onNav} />
        <div className="ml-44 flex-1">
          {renderScreen()}
        </div>
      </div>
    )
  }

  return <LoadingSpinner />
}

// ─────────────────────────────────────────────────────────────────────────────
// Root router
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Route layout:
 *   /login        → public LoginScreen  (no auth, no app shell)
 *   /signup       → public SignupScreen (no auth, no app shell)
 *   /join/:code   → JoinRoomScreen      (no auth, no app shell)
 *   /*            → ProtectedApp        (Firebase auth required)
 */
export default function App() {
  return (
    <Routes>
      <Route path="/login"      element={<PublicLoginRoute />} />
      <Route path="/signup"     element={<PublicSignupRoute />} />
      <Route path="/join/:code" element={<JoinRoomScreen />} />
      <Route path="/*"          element={<ProtectedApp />} />
    </Routes>
  )
}
