import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18">
    <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908C16.618 14.013 17.64 11.705 17.64 9.2z" fill="#4285F4" />
    <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853" />
    <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05" />
    <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335" />
  </svg>
)

const MicrosoftIcon = () => (
  <svg width="18" height="18" viewBox="0 0 21 21">
    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
  </svg>
)

const AppleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z" />
  </svg>
)

export default function LoginScreen({ onNav }: Props) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10"
      style={{ background: "linear-gradient(160deg, #06101F 0%, #162d52 40%, #1a3660 100%)" }}>
      <div className="w-full max-w-sm">

        {/* Back to landing */}
        <button
          onClick={() => onNav(SCREENS.LANDING)}
          className="flex items-center gap-1 text-xs mb-6 cursor-pointer"
          style={{ color: "rgba(255,255,255,0.5)", background: "none", border: "none" }}>
          ← Back to home
        </button>

        {/* Logo */}
        <div className="text-center mb-8">
          <div className="text-4xl mb-2">⚖</div>
          <h1 className="text-2xl font-bold tracking-wide text-white"
            style={{ fontFamily: "Palatino, Georgia, serif" }}>
            CourtAccess AI
          </h1>
          <p className="text-xs mt-1" style={{ color: "rgba(255,255,255,0.45)" }}>
            Sign in to access services
          </p>
        </div>

        <Card className="shadow-xl border-0">
          <CardContent className="p-7">
            <h2 className="text-xl font-bold mb-1"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Welcome back
            </h2>
            <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
              Sign in to access court translation services
            </p>

            {/* OAuth Buttons */}
            <button
              onClick={() => onNav(SCREENS.HOME_OFFICIAL)}
              className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-2 cursor-pointer hover:bg-slate-50 transition-colors"
              style={{ borderColor: "#E2E6EC", color: "#1A2332" }}>
              <GoogleIcon /> Continue with Google
            </button>
            <button
              onClick={() => onNav(SCREENS.HOME_OFFICIAL)}
              className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-2 cursor-pointer hover:bg-slate-50 transition-colors"
              style={{ borderColor: "#E2E6EC", color: "#1A2332" }}>
              <MicrosoftIcon /> Continue with Microsoft
            </button>
            <button
              onClick={() => onNav(SCREENS.HOME_OFFICIAL)}
              className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-3 cursor-pointer hover:opacity-90 transition-opacity"
              style={{ background: "#000", color: "#fff", borderColor: "#000" }}>
              <AppleIcon /> Continue with Apple
            </button>

            {/* Divider */}
            <div className="flex items-center gap-3 my-4">
              <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
              <span className="text-[11px]" style={{ color: "#8494A7" }}>or sign in with email</span>
              <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
            </div>

            <div className="mb-3">
              <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                Email address
              </label>
              <Input placeholder="name@example.com" type="email" />
            </div>
            <div className="mb-4">
              <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                Password
              </label>
              <Input placeholder="••••••••" type="password" />
            </div>

            <div className="flex justify-between items-center mb-5">
              <label className="flex items-center gap-2 text-xs cursor-pointer"
                style={{ color: "#4A5568" }}>
                <input type="checkbox" className="accent-slate-800" /> Remember me
              </label>
              <button
                onClick={() => onNav(SCREENS.FORGOT)}
                className="text-xs font-medium cursor-pointer"
                style={{ color: "#2563eb", background: "none", border: "none" }}>
                Forgot password?
              </button>
            </div>

            <Button
              className="w-full cursor-pointer"
              style={{ background: "#0B1D3A" }}
              onClick={() => onNav(SCREENS.MFA)}>
              Sign In
            </Button>

            <p className="text-center text-xs mt-4" style={{ color: "#8494A7" }}>
              Don't have an account?{" "}
              <button
                onClick={() => onNav(SCREENS.SIGNUP)}
                className="font-semibold cursor-pointer"
                style={{ color: "#2563eb", background: "none", border: "none" }}>
                Create account
              </button>
            </p>
          </CardContent>
        </Card>

        <p className="text-center text-[10px] mt-6 leading-relaxed"
          style={{ color: "rgba(255,255,255,0.25)" }}>
          Protected system · All translations are AI-generated and not official legal records
        </p>
      </div>
      <ScreenLabel name="LOGIN — SIGN IN" />
    </div>
  )
}
