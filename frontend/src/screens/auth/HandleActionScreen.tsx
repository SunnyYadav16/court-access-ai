import { useState, useEffect } from "react"
import { applyActionCode, confirmPasswordReset } from "firebase/auth"
import { auth } from "@/config/firebase"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"

interface Props {
  mode: string
  oobCode: string
}

export default function HandleActionScreen({ mode, oobCode }: Props) {
  const [password, setPassword] = useState("")
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Handle email verification
  useEffect(() => {
    if (mode !== "verifyEmail") return
    applyActionCode(auth, oobCode)
      .then(async () => {
        if (auth.currentUser) {
          await auth.currentUser.reload()
          await auth.currentUser.getIdToken(true)
        }
        setDone(true)
      })
      .catch(e => {
        // Code already used = email was already verified successfully
        if (e.code === "auth/invalid-action-code") {
          setDone(true)
        } else {
          setError(e.message)
        }
      })
  }, [oobCode, mode])

  const cardWrap = (icon: string, title: string, children: React.ReactNode) => (
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
              style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}>
              <span className="text-2xl">{icon}</span>
            </div>
            <h2 className="text-xl font-bold mb-4"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              {title}
            </h2>
            {children}
          </CardContent>
        </Card>
      </div>
    </div>
  )

  if (mode === "verifyEmail") {
    return cardWrap("📧", "Email Verified", (
      <>
        {error && (
          <div className="mb-4 rounded-md px-3 py-2 text-xs"
            style={{ background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B" }}>
            {error}
          </div>
        )}
        {done && (
          <>
            <div className="mb-4 rounded-md px-3 py-2 text-xs"
              style={{ background: "#DCFCE7", border: "1px solid #86efac", color: "#166534" }}>
              ✓ Your email has been verified!
            </div>
            <Button className="w-full" style={{ background: "#0B1D3A" }}
              onClick={() => window.location.href = "/"}>
              Continue to App →
            </Button>
          </>
        )}
      </>
    ))
  }

  if (mode === "resetPassword") {
    const handleReset = async (e: React.FormEvent) => {
      e.preventDefault()
      setError(null)
      try {
        await confirmPasswordReset(auth, oobCode, password)
        setDone(true)
      } catch {
        setError("This reset link has expired. Please request a new one.")
      }
    }

    return cardWrap("🔑", "Set New Password", (
      <>
        {error && (
          <div className="mb-4 rounded-md px-3 py-2 text-xs"
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
              onClick={() => window.location.href = "/"}>
              Sign In →
            </Button>
          </>
        ) : (
          <form onSubmit={handleReset} className="text-left">
            <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
              New password
            </label>
            <Input
              className="mb-4"
              type="password"
              placeholder="Min 6 characters"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              minLength={6}
            />
            <Button type="submit" className="w-full" style={{ background: "#0B1D3A" }}>
              Set New Password
            </Button>
          </form>
        )}
      </>
    ))
  }

  return cardWrap("⚠️", "Invalid Link", (
    <div>
      <p className="text-sm mb-4" style={{ color: "#8494A7" }}>
        This link is invalid or has expired.
      </p>
      <Button className="w-full" style={{ background: "#0B1D3A" }}
        onClick={() => window.location.href = "/"}>
        Back to App →
      </Button>
    </div>
  ))
}