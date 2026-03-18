import { useState, useEffect } from "react"
import { SCREENS, ScreenId } from "@/lib/constants"
import ScreenNavigator from "@/components/shared/ScreenNavigator"
import AuthModal from "@/components/auth/AuthModal"
import useAuth from "@/hooks/useAuth"

// Public
import LandingScreen from "@/screens/LandingScreen"

// Auth (kept for ScreenNavigator dev reference)
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
import RealtimeSession from "@/screens/realtime/RealtimeSession"

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

/** Full-screen loading spinner during auth initialization */
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

export default function App() {
  const { authState, role, authModalOpen } = useAuth()
  const [screen, setScreen] = useState<ScreenId>(SCREENS.LANDING)
  const onNav = (s: ScreenId) => setScreen(s)

  // Auto-navigate to role-appropriate home screen on authentication
  useEffect(() => {
    if (authState === "authenticated" && role) {
      switch (role) {
        case "public":
          setScreen(SCREENS.HOME_PUBLIC)
          break
        case "court_official":
          setScreen(SCREENS.HOME_OFFICIAL)
          break
        case "interpreter":
          setScreen(SCREENS.HOME_INTERPRETER)
          break
        case "admin":
          setScreen(SCREENS.HOME_ADMIN)
          break
      }
    }
  }, [authState, role])

  // Screen renderer (shared between authenticated and dev navigator views)
  const renderScreen = () => {
    switch (screen) {
      // Public
      case SCREENS.LANDING:         return <LandingScreen onNav={onNav} />
      // Auth (dev navigator only)
      case SCREENS.LOGIN:           return <LoginScreen onNav={onNav} />
      case SCREENS.SIGNUP:          return <SignupScreen onNav={onNav} />
      case SCREENS.FORGOT:          return <ForgotScreen onNav={onNav} />
      case SCREENS.RESET:           return <ResetScreen onNav={onNav} />
      case SCREENS.VERIFY_EMAIL:    return <VerifyEmailScreen onNav={onNav} />
      case SCREENS.MFA:             return <MFAScreen onNav={onNav} />
      // Home
      case SCREENS.HOME_PUBLIC:      return <HomePublic onNav={onNav} />
      case SCREENS.HOME_OFFICIAL:    return <HomeOfficial onNav={onNav} />
      case SCREENS.HOME_INTERPRETER: return <HomeInterpreter onNav={onNav} />
      case SCREENS.HOME_ADMIN:       return <HomeAdmin onNav={onNav} />
      // Realtime
      case SCREENS.REALTIME_SETUP:   return <RealtimeSetup onNav={onNav} />
      case SCREENS.REALTIME_SESSION: return <RealtimeSession onNav={onNav} />
      // Documents
      case SCREENS.DOC_UPLOAD:       return <DocUpload onNav={onNav} />
      case SCREENS.DOC_PROCESSING:   return <DocProcessing onNav={onNav} />
      case SCREENS.DOC_RESULTS:      return <DocResults onNav={onNav} />
      // Forms
      case SCREENS.FORMS_LIBRARY:    return <FormsLibrary onNav={onNav} />
      case SCREENS.FORM_DETAIL:      return <FormDetail onNav={onNav} />
      // Admin
      case SCREENS.ADMIN_DASHBOARD:  return <AdminDashboard onNav={onNav} />
      case SCREENS.ADMIN_USERS:      return <AdminUsers onNav={onNav} />
      case SCREENS.ADMIN_FORMS:      return <AdminForms onNav={onNav} />
      case SCREENS.INTERPRETER_REVIEW: return <InterpreterReview onNav={onNav} />
      default:                       return <LandingScreen onNav={onNav} />
    }
  }

  // ── Auth-state-driven rendering ──────────────────────────────────────────

  // Loading: full-screen spinner while Firebase checks cached auth state
  if (authState === "loading") {
    return <LoadingSpinner />
  }

  // Unauthenticated or needs email verification:
  // Show landing page with auth modal overlay when triggered
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

  // Authenticated: full app with screen navigator and role-based routing
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

  // Fallback
  return <LoadingSpinner />
}
