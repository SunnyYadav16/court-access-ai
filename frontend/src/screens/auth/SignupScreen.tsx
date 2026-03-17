import { useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { AuthHook } from "@/hooks/useAuth"
import api from "@/services/api"

interface Props {
  onNav: (s: ScreenId) => void
  auth: AuthHook
}

const ROLES = [
  { id: "public", label: "Public User", desc: "Access translated documents" },
  { id: "court_official", label: "Court Official", desc: "Upload & manage court documents" },
  { id: "interpreter", label: "Interpreter", desc: "Assist with translation" },
]

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18">
    <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908C16.618 14.013 17.64 11.705 17.64 9.2z" fill="#4285F4"/>
    <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
    <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
    <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
  </svg>
)

const MicrosoftIcon = () => (
  <svg width="18" height="18" viewBox="0 0 21 21">
    <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
    <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
    <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
  </svg>
)

export default function SignupScreen({ onNav, auth }: Props) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [selectedRole, setSelectedRole] = useState<string | null>(null)
  const [roleError, setRoleError] = useState<string | null>(null)
  const [showRoleSelect, setShowRoleSelect] = useState(false)
  const [signupSuccess, setSignupSuccess] = useState(false)

  // Password strength
  const strength = [
    password.length >= 8,
    /[A-Z]/.test(password),
    /[0-9]/.test(password),
    /[^A-Za-z0-9]/.test(password),
  ]
  const strengthColors = strength.map(s => s ? "#16a34a" : "#E2E6EC")

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!strength.every(Boolean)) {
      auth.setError("Password must meet all requirements.")
      return
    }
    if (password !== confirmPassword) {
      auth.setError("Passwords do not match.")
      return
    }
    await auth.createAccount(email, password)
  }

  if (signupSuccess) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4"
        style={{ background: "linear-gradient(160deg, #06101F 0%, #162d52 40%, #1a3660 100%)" }}>
        
        <div className="w-full max-w-sm">
          <Card className="border-0 shadow-xl">
            <CardContent className="p-7 text-center">
  
              <div className="text-3xl mb-3">✅</div>
  
              <h2
                className="text-xl font-bold mb-2"
                style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
              >
                Account Created
              </h2>
  
              <p className="text-sm mb-6" style={{ color: "#8494A7" }}>
                Your Google account has been registered successfully.
                <br />
                Please return to the login page and sign in.
              </p>
  
              <Button
                className="w-full"
                style={{ background: "#0B1D3A" }}
                onClick={() => onNav(SCREENS.LOGIN)}
              >
                Go to Sign In
              </Button>
  
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const handleRoleConfirm = async () => {
    if (!selectedRole) {
      setRoleError("Please select a role to continue.")
      return
    }
    setRoleError(null)
    try {
      await api.post("/auth/select-role", { selected_role: selectedRole })
      window.location.reload()
    } catch {
      setRoleError("Failed to save role. Please try again.")
    }
  }

  // Role selection screen shown when authState === "needs_role_selection"
  if (auth.authState === "needs_role_selection" || showRoleSelect) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4"
        style={{ background: "linear-gradient(160deg, #06101F 0%, #162d52 40%, #1a3660 100%)" }}>
        <div className="w-full max-w-sm">
          <div className="text-center mb-6">
            <div className="text-3xl mb-1">⚖</div>
            <h1 className="text-xl font-bold text-white" style={{ fontFamily: "Palatino, Georgia, serif" }}>CourtAccess AI</h1>
          </div>
          <Card className="border-0 shadow-xl">
            <CardContent className="p-7">
              <h2 className="text-xl font-bold mb-1"
                style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
                Select your role
              </h2>
              <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
                How will you use CourtAccess AI?
              </p>

              {roleError && (
                <div className="mb-4 rounded-md px-3 py-2 text-xs"
                  style={{ background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B" }}>
                  {roleError}
                </div>
              )}

              <div className="flex flex-col gap-3 mb-5">
                {ROLES.map(r => (
                  <button key={r.id}
                    onClick={() => setSelectedRole(r.id)}
                    className="w-full text-left px-4 py-3 rounded-md border transition-colors cursor-pointer"
                    style={{
                      borderColor: selectedRole === r.id ? "#0B1D3A" : "#E2E6EC",
                      background: selectedRole === r.id ? "#EFF6FF" : "#fff",
                    }}>
                    <div className="text-sm font-semibold" style={{ color: "#1A2332" }}>{r.label}</div>
                    <div className="text-xs mt-0.5" style={{ color: "#8494A7" }}>{r.desc}</div>
                  </button>
                ))}
              </div>

              {(selectedRole === "court_official" || selectedRole === "interpreter") && (
                <div className="mb-4 rounded-md px-3 py-2 text-xs"
                  style={{ background: "#EFF6FF", border: "1px solid #BFDBFE", color: "#1e40af" }}>
                  This role requires admin approval. You'll have public access until approved.
                </div>
              )}

              <Button className="w-full" style={{ background: "#0B1D3A" }} onClick={handleRoleConfirm}>
                Continue →
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10"
      style={{ background: "linear-gradient(160deg, #06101F 0%, #162d52 40%, #1a3660 100%)" }}>
      <div className="w-full max-w-sm">

        <div className="text-center mb-6">
          <div className="text-3xl mb-1">⚖</div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: "Palatino, Georgia, serif" }}>
            CourtAccess AI
          </h1>
        </div>

        <Card className="border-0 shadow-xl">
          <CardContent className="p-7">
            <h2 className="text-xl font-bold mb-1"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Create your account
            </h2>
            <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
              Get access to court translation and interpretation services
            </p>

            {auth.error && (
              <div className="mb-4 rounded-md px-3 py-2 text-xs"
                style={{ background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B" }}>
                {auth.error}
              </div>
            )}

            <button
              onClick={async () => {
                try {
                  await auth.signInWithGoogle()
                  setSignupSuccess(true)
                } catch {
                  auth.setError("Google signup failed.")
                }
              }}
            // >
            // <button
            //   onClick={auth.signInWithGoogle}
              className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-2 cursor-pointer hover:bg-slate-50 transition-colors"
              style={{ borderColor: "#E2E6EC", color: "#1A2332" }}>
              <GoogleIcon /> Sign up with Google
            </button>
            <button
              onClick={auth.signInWithMicrosoft}
              className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-3 cursor-pointer hover:bg-slate-50 transition-colors"
              style={{ borderColor: "#E2E6EC", color: "#1A2332" }}>
              <MicrosoftIcon /> Sign up with Microsoft
            </button>

            <div className="flex items-center gap-3 my-4">
              <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
              <span className="text-[11px]" style={{ color: "#8494A7" }}>or create account with email</span>
              <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
            </div>

            <form onSubmit={handleCreate}>
              <div className="mb-3">
                <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                  Email address
                </label>
                <Input
                  placeholder="name@example.com"
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                />
              </div>

              <div className="mb-1">
                <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                  Password
                </label>
                <Input
                  placeholder="Create a strong password"
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                />
              </div>

              <div className="mb-3">
                <div className="flex gap-1 mb-1">
                  {strengthColors.map((c, i) => (
                    <div key={i} className="flex-1 h-1 rounded-full" style={{ background: c }} />
                  ))}
                </div>
                <div className="flex gap-3 text-[10px]">
                  <span style={{ color: strength[0] ? "#16a34a" : "#8494A7" }}>✓ 8+ chars</span>
                  <span style={{ color: strength[1] ? "#16a34a" : "#8494A7" }}>✓ Uppercase</span>
                  <span style={{ color: strength[2] ? "#16a34a" : "#8494A7" }}>✓ Number</span>
                  <span style={{ color: strength[3] ? "#16a34a" : "#8494A7" }}>○ Special char</span>
                </div>
              </div>

              <div className="mb-5">
                <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                  Confirm password
                </label>
                <Input
                  placeholder="Confirm your password"
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  required
                />
              </div>

              <Button type="submit" className="w-full cursor-pointer" style={{ background: "#0B1D3A" }}>
                Create Account
              </Button>
            </form>

            <p className="text-center text-xs mt-4" style={{ color: "#8494A7" }}>
              Already have an account?{" "}
              <button
                onClick={() => onNav(SCREENS.LOGIN)}
                className="font-semibold cursor-pointer"
                style={{ color: "#2563eb", background: "none", border: "none" }}>
                Sign in
              </button>
            </p>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="SIGNUP — CREATE ACCOUNT" />
    </div>
  )
}