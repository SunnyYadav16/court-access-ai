import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const steps = [
  { name: "Validating file", status: "done", detail: "PDF format confirmed, 4 pages" },
  { name: "Classifying document", status: "done", detail: "LEGAL — Court motion with docket header" },
  { name: "Extracting pages", status: "done", detail: "4 pages extracted as images" },
  { name: "OCR — Printed text", status: "done", detail: "PaddleOCR: 847 text regions, avg 0.97 confidence" },
  { name: "OCR — Handwritten text", status: "done", detail: "Qwen2.5-VL: 3 regions, avg 0.84 confidence" },
  { name: "PII scan", status: "done", detail: "Presidio: 2 findings flagged" },
  { name: "Translating to Spanish", status: "active", detail: "NLLB-200: processing region 412/850..." },
  { name: "Legal term review", status: "pending", detail: "" },
  { name: "Rebuilding PDF", status: "pending", detail: "" },
]

const statusIcon = (status: string) => {
  if (status === "done") return "✅"
  if (status === "active") return "⏳"
  return "○"
}

export default function DocProcessing({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="maria.santos@gmail.com" role="public" onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">
        <h1 className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Translating Document
        </h1>
        <p className="text-xs mb-6" style={{ color: "#8494A7" }}>
          Request TR-20260222-001 · Spanish
        </p>
        <Card>
          <CardContent className="p-6">
            {/* Progress bar */}
            <div className="h-1.5 rounded-full mb-6 overflow-hidden" style={{ background: "#E5E7EB" }}>
              <div className="h-full rounded-full transition-all duration-500"
                style={{ width: "68%", background: "linear-gradient(90deg, #0B1D3A, #C8963E)" }} />
            </div>

            {/* Steps */}
            <div className="flex flex-col">
              {steps.map((s, i) => (
                <div key={i} className="flex items-start gap-3 py-2.5"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <span className="text-sm w-5 text-center flex-shrink-0 mt-0.5">
                    {statusIcon(s.status)}
                  </span>
                  <div>
                    <div className="text-sm"
                      style={{
                        fontWeight: s.status === "active" ? 600 : 400,
                        color: s.status === "pending" ? "#8494A7" : "#1A2332",
                      }}>
                      {s.name}
                    </div>
                    {s.detail && (
                      <div className="text-[11px] mt-0.5" style={{ color: "#8494A7" }}>
                        {s.detail}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="text-center mt-4">
              <Button variant="outline" size="sm"
                onClick={() => onNav(SCREENS.DOC_RESULTS)}
                className="cursor-pointer text-xs">
                Skip to Results (Demo) →
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="DOCUMENT PROCESSING — PIPELINE STATUS" />
    </div>
  )
}