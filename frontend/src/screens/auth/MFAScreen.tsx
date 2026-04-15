import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

export default function MFAScreen({ onNav }: Props) {
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
            <div className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4"
              style={{ background: "#F5EDE0", border: "1px solid rgba(200,150,62,0.3)" }}>
              <span className="text-2xl">🔐</span>
            </div>
            <h2 className="text-xl font-bold mb-1" style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Two-factor authentication
            </h2>
            <p className="text-xs mb-5 leading-relaxed" style={{ color: "#8494A7" }}>
              Enter the 6-digit code from your authenticator app to continue.
            </p>

            <div className="flex gap-2 justify-center mb-2">
              {["1", "2", "3", "4", "5", "6"].map((d, i) => (
                <input key={i} readOnly value={d} maxLength={1}
                  className="w-10 h-12 text-center text-lg font-bold rounded-md outline-none"
                  style={{ border: "1.5px solid #0B1D3A", fontFamily: "sans-serif", color: "#1A2332" }} />
              ))}
            </div>
            <p className="text-[11px] mb-5" style={{ color: "#8494A7" }}>Code refreshes in 22 seconds</p>

            <Button className="w-full" style={{ background: "#1D4ED8" }}
              onClick={() => onNav(SCREENS.HOME_OFFICIAL)}>
              Verify
            </Button>

            <div className="mt-4 flex flex-col gap-2 items-center">
              <span className="text-xs" style={{ color: "#8494A7" }}>
                Lost your authenticator?{" "}
                <button className="font-medium" style={{ color: "#2563eb", background: "none", border: "none", cursor: "pointer" }}>
                  Use a backup code
                </button>
              </span>
              <button onClick={() => onNav(SCREENS.LOGIN)}
                className="text-xs font-medium flex items-center gap-1"
                style={{ color: "#2563eb", background: "none", border: "none", cursor: "pointer" }}>
                ← Back to sign in
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="MULTI-FACTOR AUTHENTICATION" />
    </div>
  )
}
