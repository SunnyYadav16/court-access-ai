import { useState } from "react"
import { SCREENS, ScreenId } from "@/lib/constants"
import ScreenNavigator from "@/components/shared/ScreenNavigator"

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
  const [screen, setScreen] = useState<ScreenId>(SCREENS.LANDING)
  const onNav = (s: ScreenId) => setScreen(s)

  const renderScreen = () => {
    switch (screen) {
      // Public
      case SCREENS.LANDING:         return <LandingScreen onNav={onNav} />
      // Auth
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

  return (
    <div className="flex min-h-screen">
      <ScreenNavigator current={screen} onNav={onNav} />
      <div className="ml-44 flex-1">
        {renderScreen()}
      </div>
    </div>
  )
}
