import { useState } from "react"
import { SCREENS, ScreenId } from "@/lib/constants"
import ScreenNavigator from "@/components/shared/ScreenNavigator"
import { useAuth } from "@/hooks/useAuth"

// Public
import LandingScreen from "@/screens/LandingScreen"

// Auth
import LoginScreen from "@/screens/auth/LoginScreen"
import SignupScreen from "@/screens/auth/SignupScreen"
import ForgotScreen from "@/screens/auth/ForgotScreen"
import ResetScreen from "@/screens/auth/ResetScreen"
import VerifyEmailScreen from "@/screens/auth/VerifyEmailScreen"
import MFAScreen from "@/screens/auth/MFAScreen"
import HandleActionScreen from "@/screens/auth/HandleActionScreen"

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

export default function App() {
  const auth = useAuth()
  const [screen, setScreen] = useState<ScreenId>(SCREENS.LANDING)
  const [authPage, setAuthPage] = useState<"login" | "signup" | "forgot">("login")
  const onNav = (s: ScreenId) => setScreen(s)

  // ── Handle Firebase email action links (?mode=resetPassword&oobCode=...) ──
  const params = new URLSearchParams(window.location.search)
  const mode = params.get("mode")
  const oobCode = params.get("oobCode")
  if (mode && oobCode) {
    return <HandleActionScreen mode={mode} oobCode={oobCode} />
  }

  // ── Auth state gate ────────────────────────────────────────────────────────
  if (auth.authState === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-primary" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (auth.authState === "unauthenticated") {
    if (authPage === "signup") return <SignupScreen auth={auth} onNav={(s) => {
      if (s === SCREENS.LOGIN) setAuthPage("login")
      else if (s === SCREENS.FORGOT) setAuthPage("forgot")
      else onNav(s)
    }} />
    if (authPage === "forgot") return <ForgotScreen auth={auth} onNav={(s) => {
      if (s === SCREENS.LOGIN) setAuthPage("login")
      else onNav(s)
    }} />
    return <LoginScreen auth={auth} onNav={(s) => {
      if (s === SCREENS.SIGNUP) setAuthPage("signup")
      else if (s === SCREENS.FORGOT) setAuthPage("forgot")
      else onNav(s)
    }} />
  }

  if (auth.authState === "needs_email_verification") {
    return <VerifyEmailScreen auth={auth} />
  }

  if (auth.authState === "needs_role_selection") {
    return <SignupScreen auth={auth} onNav={onNav} />
  }

  // ── Authenticated — route to correct home based on role ──────────────────
  if (auth.authState === "authenticated" && screen === SCREENS.LANDING) {
    // Auto-navigate to role-appropriate home on first login
    if (auth.role === "admin") setScreen(SCREENS.HOME_ADMIN)
    else if (auth.role === "court_official") setScreen(SCREENS.HOME_OFFICIAL)
    else if (auth.role === "interpreter") setScreen(SCREENS.HOME_INTERPRETER)
    else setScreen(SCREENS.HOME_PUBLIC)
  }

  // ── Authenticated — use their existing screen router ──────────────────────
  const renderScreen = () => {
    switch (screen) {
      case SCREENS.LANDING:            return <LandingScreen onNav={onNav} />
      case SCREENS.LOGIN:              return <LoginScreen auth={auth} onNav={onNav} />
      case SCREENS.SIGNUP:             return <SignupScreen auth={auth} onNav={onNav} />
      case SCREENS.FORGOT:             return <ForgotScreen auth={auth} onNav={onNav} />
      case SCREENS.RESET:              return <ResetScreen onNav={onNav} />
      case SCREENS.VERIFY_EMAIL:       return <VerifyEmailScreen auth={auth} />
      case SCREENS.MFA:                return <MFAScreen onNav={onNav} />
      case SCREENS.HOME_PUBLIC:        return <HomePublic onNav={onNav} />
      case SCREENS.HOME_OFFICIAL:      return <HomeOfficial onNav={onNav} />
      case SCREENS.HOME_INTERPRETER:   return <HomeInterpreter onNav={onNav} />
      case SCREENS.HOME_ADMIN:         return <HomeAdmin onNav={onNav} />
      case SCREENS.REALTIME_SETUP:     return <RealtimeSetup onNav={onNav} />
      case SCREENS.REALTIME_SESSION:   return <RealtimeSession onNav={onNav} />
      case SCREENS.DOC_UPLOAD:         return <DocUpload onNav={onNav} />
      case SCREENS.DOC_PROCESSING:     return <DocProcessing onNav={onNav} />
      case SCREENS.DOC_RESULTS:        return <DocResults onNav={onNav} />
      case SCREENS.FORMS_LIBRARY:      return <FormsLibrary onNav={onNav} />
      case SCREENS.FORM_DETAIL:        return <FormDetail onNav={onNav} />
      case SCREENS.ADMIN_DASHBOARD:    return <AdminDashboard onNav={onNav} />
      case SCREENS.ADMIN_USERS:        return <AdminUsers onNav={onNav} />
      case SCREENS.ADMIN_FORMS:        return <AdminForms onNav={onNav} />
      case SCREENS.INTERPRETER_REVIEW: return <InterpreterReview onNav={onNav} />
      default:                         return <LandingScreen onNav={onNav} />
    }
  }

  return (
    <div className="flex min-h-screen">
      <ScreenNavigator current={screen} onNav={onNav} />
      <div className="ml-44 flex-1">
        {renderScreen()}
      </div>
    </div>
  )
}