import { ScreenId } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const metrics = [
  { label: "Active Sessions", val: "3", sub: "2 real-time · 1 document", color: "#2563eb" },
  { label: "Today's Translations", val: "47", sub: "38 docs · 9 real-time", color: "#0B1D3A" },
  { label: "Avg ASR Confidence", val: "0.94", sub: "↑ 0.02 from last week", color: "#16a34a" },
  { label: "Avg NMT Confidence", val: "0.91", sub: "→ stable", color: "#16a34a" },
]

const modelHealth = [
  { name: "Faster-Whisper Large V3", latency: "42ms", color: "#16a34a" },
  { name: "NLLB-200 Distilled 1.3B", latency: "28ms", color: "#16a34a" },
  { name: "PaddleOCR v3", latency: "156ms", color: "#16a34a" },
  { name: "Qwen2.5-VL", latency: "340ms", color: "#16a34a" },
  { name: "Silero VAD v4", latency: "3ms", color: "#16a34a" },
  { name: "Piper TTS", latency: "22ms", color: "#16a34a" },
  { name: "Llama 4 (Vertex AI)", latency: "890ms", color: "#d97706" },
]

const driftReport = [
  { metric: "ASR Confidence (English)", val: "0.94", drift: "None", color: "#16a34a" },
  { metric: "ASR Confidence (Spanish)", val: "0.91", drift: "None", color: "#16a34a" },
  { metric: "NMT Confidence (ES)", val: "0.92", drift: "None", color: "#16a34a" },
  { metric: "NMT Confidence (PT)", val: "0.88", drift: "Minor", color: "#d97706" },
  { metric: "OCR Confidence", val: "0.96", drift: "None", color: "#16a34a" },
  { metric: "Llama Correction Rate", val: "4.2%", drift: "↑ Increasing", color: "#d97706" },
]

const infrastructure = [
  { resource: "API Pod (FastAPI)", cpu: "23%", mem: "41%", gpu: "—" },
  { resource: "Whisper Pod", cpu: "45%", mem: "62%", gpu: "71%" },
  { resource: "NLLB Pod", cpu: "38%", mem: "55%", gpu: "58%" },
  { resource: "OCR Pod", cpu: "12%", mem: "34%", gpu: "22%" },
  { resource: "TTS Pod", cpu: "8%", mem: "18%", gpu: "—" },
  { resource: "Airflow Worker", cpu: "15%", mem: "28%", gpu: "—" },
]

const alerts = [
  { time: "10:42 AM", msg: "Vertex AI latency >500ms (p95)", sev: "warn" },
  { time: "9:15 AM", msg: "Portuguese NMT confidence below threshold", sev: "warn" },
  { time: "Yesterday", msg: "Form scraper: 2 new forms detected on mass.gov", sev: "info" },
  { time: "Feb 20", msg: "DVC: Model weights updated (Whisper v3-turbo)", sev: "info" },
]

export default function AdminDashboard({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="admin@mass.gov" role="admin" onNav={onNav} />
      <div className="max-w-4xl mx-auto px-5 py-6">

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-xl font-bold"
            style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
            System Monitoring
          </h1>
          <span className="text-[10px] font-semibold px-2 py-1 rounded"
            style={{ background: "#DCFCE7", color: "#16a34a" }}>
            ALL SYSTEMS OPERATIONAL
          </span>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          {metrics.map((m, i) => (
            <Card key={i}>
              <CardContent className="p-4">
                <div className="text-[11px] uppercase tracking-wide mb-1" style={{ color: "#8494A7" }}>
                  {m.label}
                </div>
                <div className="text-2xl font-bold mb-0.5"
                  style={{ color: m.color, fontFamily: "Palatino, Georgia, serif" }}>
                  {m.val}
                </div>
                <div className="text-[11px]" style={{ color: "#8494A7" }}>{m.sub}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3 mb-3">
          {/* Model Health */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                Model Pipeline Health
              </div>
              {modelHealth.map((m, i) => (
                <div key={i} className="flex items-center justify-between py-1.5 text-xs"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: m.color }} />
                    <span style={{ color: "#1A2332" }}>{m.name}</span>
                  </div>
                  <span style={{ color: "#8494A7" }}>{m.latency}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Drift Report */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                Evidently AI — Drift Report
              </div>
              {driftReport.map((d, i) => (
                <div key={i} className="flex items-center justify-between py-1.5 text-xs"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <span style={{ color: "#1A2332" }}>{d.metric}</span>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold" style={{ color: "#1A2332" }}>{d.val}</span>
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                      style={{
                        background: d.color === "#16a34a" ? "#DCFCE7" : "#FEF3C7",
                        color: d.color,
                      }}>
                      {d.drift}
                    </span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {/* Infrastructure */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                GKE Infrastructure
              </div>
              {infrastructure.map((r, i) => (
                <div key={i} className="grid grid-cols-4 py-1.5 text-[11px]"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <span style={{ color: "#1A2332" }}>{r.resource}</span>
                  <span style={{ color: "#8494A7" }}>CPU {r.cpu}</span>
                  <span style={{ color: "#8494A7" }}>MEM {r.mem}</span>
                  <span style={{ color: "#8494A7" }}>{r.gpu !== "—" ? `GPU ${r.gpu}` : "—"}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Alerts */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                Recent Alerts
              </div>
              {alerts.map((a, i) => (
                <div key={i} className="flex items-start gap-2 py-1.5 text-xs"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <span>{a.sev === "warn" ? "⚠️" : "ℹ️"}</span>
                  <div>
                    <div style={{ color: "#1A2332" }}>{a.msg}</div>
                    <div className="text-[10px]" style={{ color: "#8494A7" }}>{a.time}</div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
      <ScreenLabel name="ADMIN — MONITORING DASHBOARD" />
    </div>
  )
}