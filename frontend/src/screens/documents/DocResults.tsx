import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const summary = [
  ["Pages", "4"],
  ["Text Regions", "850"],
  ["Handwritten Regions", "3 (flagged)"],
  ["PII Findings", "2"],
  ["Llama Corrections", "1"],
  ["Avg Confidence", "0.92"],
]

export default function DocResults({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="maria.santos@gmail.com" role="public" onNav={onNav} />
      <div className="max-w-xl mx-auto px-5 py-8">

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <span className="text-3xl">✅</span>
          <div>
            <h1 className="text-xl font-bold m-0"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Translation Complete
            </h1>
            <p className="text-xs m-0" style={{ color: "#8494A7" }}>
              Request TR-20260222-001 · Completed in 18.4 seconds
            </p>
          </div>
        </div>

        {/* Downloads */}
        <Card className="mb-3">
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Download Translations
            </div>
            <div className="flex gap-3">
              {/* Spanish */}
              <div className="flex-1 rounded-lg p-4 text-center"
                style={{ border: "1.5px solid #0B1D3A" }}>
                <div className="text-3xl mb-1">🇪🇸</div>
                <div className="text-sm font-semibold mb-0.5" style={{ color: "#1A2332" }}>Spanish</div>
                <div className="text-[11px] mb-3" style={{ color: "#8494A7" }}>Avg confidence: 0.92</div>
                <Button size="sm" className="w-full cursor-pointer" style={{ background: "#0B1D3A" }}>
                  ⬇ Download PDF
                </Button>
              </div>
              {/* Portuguese */}
              <div className="flex-1 rounded-lg p-4 text-center"
                style={{ border: "1.5px solid #E2E6EC" }}>
                <div className="text-3xl mb-1">🇧🇷</div>
                <div className="text-sm font-semibold mb-0.5" style={{ color: "#1A2332" }}>Portuguese</div>
                <div className="text-[11px] mb-3" style={{ color: "#8494A7" }}>Not yet translated</div>
                <Button size="sm" variant="outline" className="w-full cursor-pointer">
                  🔄 Translate Now
                </Button>
              </div>
            </div>
            <p className="text-[11px] text-center mt-3" style={{ color: "#8494A7" }}>
              Signed URL expires in 58 minutes · Original file auto-deletes in 24 hours
            </p>
          </CardContent>
        </Card>

        {/* Summary */}
        <Card className="mb-3">
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Processing Summary
            </div>
            <div className="grid grid-cols-2 gap-2">
              {summary.map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs py-1">
                  <span style={{ color: "#8494A7" }}>{k}</span>
                  <span className="font-medium" style={{ color: "#1A2332" }}>{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Legal note */}
        <Card className="mb-5" style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}>
          <CardContent className="p-4">
            <p className="text-xs leading-relaxed m-0" style={{ color: "#1e40af" }}>
              <strong>⚡ Legal Review Note:</strong> Llama 4 corrected 1 term: "motion to suppress"
              was adjusted from <em>moción de suprimir</em> to{" "}
              <em>moción para excluir evidencia</em>.
            </p>
          </CardContent>
        </Card>

        <div className="flex gap-3">
          <Button variant="outline" className="cursor-pointer"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)}>
            📄 Upload Another
          </Button>
          <Button variant="outline" className="cursor-pointer"
            onClick={() => onNav(SCREENS.HOME_PUBLIC)}>
            🏠 Home
          </Button>
        </div>
      </div>
      <ScreenLabel name="DOCUMENT RESULTS — DOWNLOAD" />
    </div>
  )
}