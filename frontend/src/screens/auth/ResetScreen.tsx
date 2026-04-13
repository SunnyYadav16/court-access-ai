import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

export default function ResetScreen({ onNav }: Props) {
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
              <span className="text-2xl">🔄</span>
            </div>
            <h2 className="text-xl font-bold mb-2" style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Set new password
            </h2>
            <p className="text-xs mb-5 leading-relaxed" style={{ color: "#8494A7" }}>
              Your new password must be different from previously used passwords.
            </p>
            <div className="text-left mb-3">
              <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>New password</label>
              <Input placeholder="Enter new password" type="password" />
            </div>
            <div className="flex gap-1 mb-1">
              {["#16a34a", "#16a34a", "#16a34a", "#16a34a"].map((c, i) => (
                <div key={i} className="flex-1 h-1 rounded-full" style={{ background: c }} />
              ))}
            </div>
            <p className="text-[10px] mb-3 text-left font-medium" style={{ color: "#16a34a" }}>Strong password ✓</p>
            <div className="text-left mb-5">
              <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>Confirm new password</label>
              <Input placeholder="Confirm new password" type="password" />
            </div>
            <Button className="w-full" style={{ background: "#0B1D3A" }}
              onClick={() => onNav(SCREENS.LOGIN)}>
              Reset Password
            </Button>
            <button onClick={() => onNav(SCREENS.LOGIN)}
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
