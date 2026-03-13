import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { AuthHook } from "@/hooks/useAuth"

interface Props { auth: AuthHook }

export default function VerifyEmailScreen({ auth }: Props) {
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
            <div className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4"
              style={{ background: "#DCFCE7", border: "1px solid #86efac" }}>
              <span className="text-2xl">✉️</span>
            </div>
            <h2 className="text-xl font-bold mb-2"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Check your email
            </h2>
            <p className="text-sm leading-relaxed mb-4" style={{ color: "#8494A7" }}>
              We sent a verification link to<br />
              <strong style={{ color: "#1A2332" }}>{auth.user?.email}</strong>
            </p>

            <div className="rounded-md p-3 mb-5 text-left"
              style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}>
              <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
                <strong>Click the link in the email to verify your account.</strong> The link expires in 24 hours.
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <Button
                className="w-full"
                style={{ background: "#0B1D3A" }}
                onClick={auth.checkEmailVerified}>
                I've Verified My Email
              </Button>
              <button
                onClick={auth.resendVerificationEmail}
                className="text-xs font-medium cursor-pointer"
                style={{ color: "#2563eb", background: "none", border: "none" }}>
                Resend verification email
              </button>
              <button
                onClick={auth.signOut}
                className="text-xs cursor-pointer"
                style={{ color: "#8494A7", background: "none", border: "none" }}>
                Sign out
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="EMAIL VERIFICATION" />
    </div>
  )
}