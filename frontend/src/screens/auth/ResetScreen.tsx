import { useState, useEffect } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { confirmPasswordReset } from "firebase/auth"
import { auth } from "@/config/firebase"

interface Props { onNav: (s: ScreenId) => void }

export default function ResetScreen({ onNav }: Props) {
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Get oobCode from URL params
  const params = new URLSearchParams(window.location.search)
  const oobCode = params.get("oobCode") ?? ""

  const strength = [
    password.length >= 8,
    /[A-Z]/.test(password),
    /[0-9]/.test(password),
    /[^A-Za-z0-9]/.test(password),
  ]

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError("Passwords do not match.")
      return
    }
    if (!oobCode) {
      setError("Invalid reset link. Please request a new one.")
      return
    }
    try {
      await confirmPasswordReset(auth, oobCode, password)
      setDone(true)
    } catch {
      setError("This reset link has expired. Please request a new one.")
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: "linear-gradient(160deg, #06101F 0%, #162d52 40%, #1a3660 100%)" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-3xl mb-1">⚖</div>
          <h1 className="text-xl font-bold text-white"
            style={{ fontFamily: "Palatino, Georgia, serif" }}>CourtAccess AI</h1>
        </div>
        <Card className="border-0 shadow-xl">
          <CardContent className="p-7 text-center">
            <div className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4"
              style={{ background: "#F5EDE0", border: "1px solid rgba(200,150,62,0.3)" }}>
              <span className="text-2xl">🔄</span>
            </div>
            <h2 className="text-xl font-bold mb-2"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Set new password
            </h2>

            {error && (
              <div className="mb-4 rounded-md px-3 py-2 text-xs text-left"
                style={{ background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B" }}>
                {error}
              </div>
            )}

            {done ? (
              <>
                <div className="mb-4 rounded-md px-3 py-2 text-xs"
                  style={{ background: "#DCFCE7", border: "1px solid #86efac", color: "#166534" }}>
                  ✓ Password updated successfully!
                </div>
                <Button className="w-full" style={{ background: "#0B1D3A" }}
                  onClick={() => onNav(SCREENS.LOGIN)}>
                  Sign In →
                </Button>
              </>
            ) : (
              <form onSubmit={handleSubmit}>
                <div className="text-left mb-3">
                  <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                    New password
                  </label>
                  <Input
                    placeholder="Enter new password"
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                    minLength={6}
                  />
                </div>
                <div className="flex gap-1 mb-1">
                  {strength.map((s, i) => (
                    <div key={i} className="flex-1 h-1 rounded-full"
                      style={{ background: s ? "#16a34a" : "#E2E6EC" }} />
                  ))}
                </div>
                <p className="text-[10px] mb-3 text-left font-medium"
                  style={{ color: strength.every(Boolean) ? "#16a34a" : "#8494A7" }}>
                  {strength.every(Boolean) ? "Strong password ✓" : "Add uppercase, number & special character"}
                </p>
                <div className="text-left mb-5">
                  <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
                    Confirm new password
                  </label>
                  <Input
                    placeholder="Confirm new password"
                    type="password"
                    value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    required
                  />
                </div>
                <Button type="submit" className="w-full" style={{ background: "#0B1D3A" }}>
                  Reset Password
                </Button>
              </form>
            )}

            <button
              onClick={() => onNav(SCREENS.LOGIN)}
              className="mt-4 text-xs font-medium flex items-center gap-1 mx-auto cursor-pointer"
              style={{ color: "#2563eb", background: "none", border: "none" }}>
              ← Back to sign in
            </button>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="RESET PASSWORD" />
    </div>
  )
}