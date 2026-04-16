import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

export default function VerifyEmailScreen({ onNav }: Props) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ background: "linear-gradient(160deg, #06101F 0%, #162d52 40%, #1a3660 100%)" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-3xl mb-1">⚖</div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: "Palatino, Georgia, serif" }}>CourtAccess AI</h1>
        </div>
        <Card className="border-0 shadow-xl">
          <CardContent className="p-7 text-center">
            <div className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4"
              style={{ background: "#DCFCE7", border: "1px solid #86efac" }}>
              <span className="text-2xl">✉️</span>
            </div>
            <h2 className="text-xl font-bold mb-2" style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Check your email
            </h2>
            <p className="text-sm leading-relaxed mb-4" style={{ color: "#8494A7" }}>
              We sent a verification link to<br />
              <strong style={{ color: "#1A2332" }}>maria.santos@gmail.com</strong>
            </p>

            <div className="rounded-md p-3 mb-4 text-left"
              style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}>
              <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
                <strong>Click the link in the email to verify your account.</strong> The link expires in 24 hours.
              </p>
            </div>

            <p className="text-xs mb-3" style={{ color: "#4A5568" }}>Or enter the 6-digit code:</p>
            <div className="flex gap-2 justify-center mb-5">
              {["4","4","4","","",""].map((d, i) => (
                <input key={i} readOnly value={d} maxLength={1} placeholder="·"
                  className="w-10 h-12 text-center text-lg font-bold rounded-md outline-none"
                  style={{
                    border: `1.5px solid ${i < 3 ? "#0B1D3A" : "#E2E6EC"}`,
                    color: "#1A2332"
                  }} />
              ))}
            </div>

            <Button className="w-full" style={{ background: "#1D4ED8" }}
              onClick={() => onNav(SCREENS.HOME_PUBLIC)}>
              Verify Email
            </Button>

            <div className="mt-4 flex flex-col gap-2 items-center">
              <span className="text-xs" style={{ color: "#8494A7" }}>
                Didn't receive it?{" "}
                <button className="font-medium cursor-pointer" style={{ color: "#2563eb", background: "none", border: "none" }}>
                  Resend in 58s
                </button>
              </span>
              <button onClick={() => onNav(SCREENS.SIGNUP)}
                className="text-xs cursor-pointer" style={{ color: "#8494A7", background: "none", border: "none" }}>
                Wrong email? <span style={{ color: "#2563eb", fontWeight: 600 }}>Change address</span>
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="EMAIL VERIFICATION" />
    </div>
  )
}
