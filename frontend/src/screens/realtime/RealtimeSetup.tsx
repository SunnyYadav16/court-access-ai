import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

export default function RealtimeSetup({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="judge.thompson@mass.gov" role="court_official" onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">
        <h1 className="text-xl font-bold mb-6"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Start Real-Time Session
        </h1>
        <Card>
          <CardContent className="p-6 flex flex-col gap-4">

            {/* Target Language */}
            <div>
              <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
                Target Language
              </label>
              <select className="w-full px-3 py-2.5 rounded-md text-sm"
                style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}>
                <option>Spanish (Español)</option>
                <option>Portuguese (Português)</option>
              </select>
            </div>

            {/* Court Division */}
            <div>
              <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
                Court Division
              </label>
              <select className="w-full px-3 py-2.5 rounded-md text-sm"
                style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}>
                <option>Boston Municipal Court</option>
                <option>Worcester District Court</option>
                <option>Suffolk Superior Court</option>
                <option>Springfield District Court</option>
              </select>
            </div>

            {/* Courtroom */}
            <div>
              <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
                Courtroom
              </label>
              <select className="w-full px-3 py-2.5 rounded-md text-sm"
                style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}>
                <option>Courtroom 3</option>
                <option>Courtroom 5A</option>
                <option>Courtroom 12</option>
              </select>
            </div>

            {/* Case Docket */}
            <div>
              <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
                Case Docket (Optional)
              </label>
              <Input placeholder="2026-CR-001234" />
            </div>

            {/* Mic notice */}
            <div className="rounded-md p-3" style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}>
              <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
                <strong>Microphone Required:</strong> This session requires browser microphone access.
                Ensure your device has a working microphone and grant permission when prompted.
              </p>
            </div>

            {/* Consent */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" className="accent-slate-800" />
              <span className="text-xs" style={{ color: "#4A5568" }}>
                Both parties consent to AI-assisted interpretation
              </span>
            </label>

            <Button
              className="w-full cursor-pointer"
              style={{ background: "#0B1D3A" }}
              onClick={() => onNav(SCREENS.REALTIME_SESSION)}>
              🎙 Start Session
            </Button>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="REAL-TIME — SESSION SETUP" />
    </div>
  )
}
