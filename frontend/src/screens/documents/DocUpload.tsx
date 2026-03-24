import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

export default function DocUpload({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">
        <h1 className="text-xl font-bold mb-6"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Upload Document for Translation
        </h1>
        <Card>
          <CardContent className="p-6 flex flex-col gap-4">

            {/* Drop zone */}
            <div
              onClick={() => onNav(SCREENS.DOC_PROCESSING)}
              className="rounded-lg p-10 text-center cursor-pointer hover:border-slate-400 transition-colors"
              style={{ border: "2px dashed #E2E6EC" }}>
              <div className="text-4xl mb-2">📄</div>
              <p className="text-sm font-semibold mb-1" style={{ color: "#1A2332" }}>
                Drag and drop your PDF here
              </p>
              <p className="text-xs mb-3" style={{ color: "#8494A7" }}>or click to browse files</p>
              <span className="text-[10px] font-semibold px-2 py-1 rounded tracking-wide"
                style={{ background: "#F5EDE0", color: "#C8963E" }}>
                PDF ONLY · MAX 50MB
              </span>
            </div>

            {/* Language selector */}
            <div>
              <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
                Translate to
              </label>
              <select className="w-full px-3 py-2.5 rounded-md text-sm"
                style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}>
                <option>Spanish (Español)</option>
                <option>Portuguese (Português)</option>
              </select>
            </div>

            {/* Notice */}
            <div className="rounded-md p-3" style={{ background: "#F5EDE0" }}>
              <p className="text-xs leading-relaxed m-0" style={{ color: "#4A5568" }}>
                <strong>Legal documents only.</strong> This system is designed for court forms,
                legal filings, orders, and related documents. Non-legal documents will be rejected.
              </p>
            </div>

            <Button
              className="w-full cursor-pointer"
              style={{ background: "#0B1D3A" }}
              onClick={() => onNav(SCREENS.DOC_PROCESSING)}>
              🔄 Upload and Translate
            </Button>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="DOCUMENT UPLOAD" />
    </div>
  )
}
