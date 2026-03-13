import { ScreenId } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

export default function InterpreterReview({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="ana.garcia@interpreter.org" role="interpreter" onNav={onNav} />
      <div className="max-w-3xl mx-auto px-5 py-6">
        <h1 className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Translation Review Queue
        </h1>
        <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
          Review AI translations and provide corrections to improve system accuracy
        </p>

        <Card>
          <CardContent className="p-5">
            {/* Side by side */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "#8494A7" }}>
                  Original (English)
                </div>
                <div className="rounded-md p-4 text-sm leading-relaxed"
                  style={{ background: "#F9FAFB", border: "1px solid #E2E6EC", color: "#1A2332" }}>
                  The Court hereby orders that the Defendant shall appear before this Court on
                  March 15, 2026 at 9:00 AM for a <strong>pretrial conference</strong>. Failure
                  to appear may result in the issuance of a <strong>default judgment</strong> or
                  a <strong>capias warrant</strong>.
                </div>
              </div>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "#8494A7" }}>
                  AI Translation (Spanish)
                </div>
                <div className="rounded-md p-4 text-sm leading-relaxed"
                  style={{ background: "#F5EDE0", border: "1px solid rgba(200,150,62,0.25)", color: "#1A2332" }}>
                  El Tribunal por la presente ordena que el Acusado deberá comparecer ante este
                  Tribunal el 15 de marzo de 2026 a las 9:00 AM para una{" "}
                  <strong className="px-0.5 rounded" style={{ background: "#FEF3C7" }}>
                    conferencia previa al juicio
                  </strong>. La falta de comparecencia puede resultar en la emisión de un{" "}
                  <strong className="px-0.5 rounded" style={{ background: "#FEF3C7" }}>
                    sentencia en rebeldía
                  </strong>{" "}
                  o una{" "}
                  <strong className="px-0.5 rounded" style={{ background: "#FEF3C7" }}>
                    orden de capias
                  </strong>.
                </div>
              </div>
            </div>

            {/* Corrections */}
            <div className="rounded-md p-4 mb-4"
              style={{ background: "#F9FAFB", border: "1px solid #E2E6EC" }}>
              <div className="text-[11px] font-semibold uppercase tracking-wider mb-2"
                style={{ color: "#8494A7" }}>
                Your Corrections
              </div>
              <textarea
                placeholder="Enter corrections or notes about the translation..."
                className="w-full text-xs p-2 rounded resize-y outline-none"
                rows={3}
                style={{ border: "1px solid #E2E6EC", fontFamily: "inherit", color: "#1A2332" }}
              />
            </div>

            {/* Actions */}
            <div className="flex items-center justify-between">
              <Button variant="outline" size="sm" className="cursor-pointer">Skip</Button>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" className="cursor-pointer">
                  ✏️ Submit Corrections
                </Button>
                <Button size="sm" className="cursor-pointer" style={{ background: "#0B1D3A" }}>
                  ✅ Approve Translation
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="INTERPRETER — TRANSLATION REVIEW" />
    </div>
  )
}
