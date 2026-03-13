import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const downloads = [
  { lang: "English (Original)", flag: "🇺🇸", available: true },
  { lang: "Spanish (Español)", flag: "🇪🇸", available: true },
  { lang: "Portuguese (Português)", flag: "🇧🇷", available: false },
]

const details = [
  ["Source", "mass.gov"],
  ["Division", "Probate & Family Court"],
  ["Version", "3"],
  ["Content Hash", "a4f8c2...e91b"],
  ["First Added", "Oct 12, 2025"],
  ["Last Updated", "Feb 10, 2026"],
  ["Status", "Active"],
]

export default function FormDetail({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="maria.santos@gmail.com" role="public" onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">
        <button
          onClick={() => onNav(SCREENS.FORMS_LIBRARY)}
          className="text-xs font-medium mb-4 flex items-center gap-1 cursor-pointer"
          style={{ color: "#2563eb", background: "none", border: "none" }}>
          ← Back to Forms Library
        </button>

        <h1 className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Restraining Order Application (209A)
        </h1>
        <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
          Probate & Family Court · Version 3 · Last updated Feb 10, 2026
        </p>

        <Card className="mb-3">
          <CardContent className="p-5">
            {/* Warning */}
            <div className="rounded-md p-3 mb-4"
              style={{ background: "#FEF3C7", border: "1px solid #FDE68A" }}>
              <p className="text-xs m-0" style={{ color: "#92400e" }}>
                <strong>⚠ Machine-translated</strong> — Pending human verification.
                Use with caution for legal proceedings.
              </p>
            </div>

            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Available Downloads
            </div>
            <div className="flex flex-col gap-2">
              {downloads.map((d, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2.5 rounded-md"
                  style={{ border: "1px solid #E2E6EC" }}>
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{d.flag}</span>
                    <span className="text-sm" style={{ color: "#1A2332" }}>{d.lang}</span>
                  </div>
                  {d.available
                    ? <Button size="sm" className="cursor-pointer" style={{ background: "#0B1D3A" }}>
                        ⬇ Download PDF
                      </Button>
                    : <span className="text-xs" style={{ color: "#8494A7" }}>Not available</span>
                  }
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>Form Details</div>
            {details.map(([k, v], i) => (
              <div key={k} className="flex justify-between text-xs py-1.5"
                style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                <span style={{ color: "#8494A7" }}>{k}</span>
                <span style={{ color: "#1A2332" }}>{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="FORM DETAIL — DOWNLOAD" />
    </div>
  )
}
