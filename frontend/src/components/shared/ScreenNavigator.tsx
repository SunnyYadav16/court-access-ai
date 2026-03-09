import { ScreenId, SCREENS } from "@/lib/constants"

const ALL_SCREENS: [ScreenId, string][] = [
  [SCREENS.LANDING, "🌐 Landing Page"],
  [SCREENS.LOGIN, "🔐 Login"],
  [SCREENS.SIGNUP, "📝 Sign Up"],
  [SCREENS.FORGOT, "🔑 Forgot Password"],
  [SCREENS.RESET, "🔄 Reset Password"],
  [SCREENS.VERIFY_EMAIL, "✉️ Verify Email"],
  [SCREENS.MFA, "🛡 Two-Factor Auth"],
  [SCREENS.HOME_PUBLIC, "🏠 Home (Public)"],
  [SCREENS.HOME_OFFICIAL, "🏠 Home (Official)"],
  [SCREENS.HOME_INTERPRETER, "🏠 Home (Interpreter)"],
  [SCREENS.HOME_ADMIN, "🏠 Home (Admin)"],
  [SCREENS.REALTIME_SETUP, "🎙 RT Setup"],
  [SCREENS.REALTIME_SESSION, "🎙 RT Live Session"],
  [SCREENS.DOC_UPLOAD, "📄 Doc Upload"],
  [SCREENS.DOC_PROCESSING, "⏳ Doc Processing"],
  [SCREENS.DOC_RESULTS, "✅ Doc Results"],
  [SCREENS.FORMS_LIBRARY, "🏛 Forms Library"],
  [SCREENS.FORM_DETAIL, "📋 Form Detail"],
  [SCREENS.ADMIN_DASHBOARD, "📊 Admin Dashboard"],
  [SCREENS.ADMIN_USERS, "👥 Admin Users"],
  [SCREENS.ADMIN_FORMS, "🗂 Admin Forms"],
  [SCREENS.INTERPRETER_REVIEW, "✏️ Interpreter Review"],
]

interface Props {
  current: ScreenId
  onNav: (s: ScreenId) => void
}

export default function ScreenNavigator({ current, onNav }: Props) {
  return (
    <div className="fixed top-0 left-0 bottom-0 w-44 overflow-y-auto z-50 p-2"
      style={{ background: "#0a0f1a", borderRight: "1px solid rgba(255,255,255,0.06)" }}>
      <div className="text-[10px] uppercase tracking-widest px-2 py-1 mb-1"
        style={{ color: "rgba(255,255,255,0.3)" }}>
        22 Screens
      </div>
      {ALL_SCREENS.map(([id, label]) => (
        <button
          key={id}
          onClick={() => onNav(id)}
          className="w-full text-left px-2 py-1.5 rounded text-[11px] mb-0.5 cursor-pointer transition-all"
          style={{
            background: current === id ? "rgba(200,150,62,0.15)" : "transparent",
            color: current === id ? "#C8963E" : "rgba(255,255,255,0.5)",
            border: "none",
            fontWeight: current === id ? 600 : 400,
          }}>
          {label}
        </button>
      ))}
    </div>
  )
}