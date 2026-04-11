import { useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { adminApi, type AdminStats } from "@/services/api"

interface Props { onNav: (s: ScreenId) => void }

// ── Static data (no live source yet) ─────────────────────────────────────────

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
  { resource: "API (FastAPI)", cpu: "23%", mem: "41%", gpu: "—" },
  { resource: "Whisper", cpu: "45%", mem: "62%", gpu: "71%" },
  { resource: "NLLB", cpu: "38%", mem: "55%", gpu: "58%" },
  { resource: "OCR", cpu: "12%", mem: "34%", gpu: "22%" },
  { resource: "TTS", cpu: "8%", mem: "18%", gpu: "—" },
  { resource: "Airflow Worker", cpu: "15%", mem: "28%", gpu: "—" },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  document_upload: "Document uploaded",
  document_translated: "Document translated",
  realtime_room_created: "Realtime session created",
  realtime_room_ended: "Realtime session ended",
  realtime_token_issued: "Guest join token issued",
  admin_role_change: "User role changed",
  role_request_approved: "Role request approved",
  role_request_rejected: "Role request rejected",
  form_scrape_triggered: "Form scraper triggered",
}

function labelForAction(actionType: string): string {
  return ACTION_LABELS[actionType] ?? actionType.replace(/_/g, " ")
}

function formatEventTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMins = Math.floor(diffMs / 60_000)
  if (diffMins < 1) return "Just now"
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHrs = Math.floor(diffMins / 60)
  if (diffHrs < 24) return `${diffHrs}h ago`
  return d.toLocaleDateString([], { month: "short", day: "numeric" })
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AdminDashboard({ onNav }: Props) {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function fetchStats() {
    setLoading(true)
    setError(null)
    try {
      setStats(await adminApi.getStats())
    } catch {
      setError("Failed to load stats. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void fetchStats() }, [])

  const metrics = [
    {
      label: "Active Sessions",
      val: loading ? "—" : String(stats?.active_sessions_total ?? 0),
      sub: stats
        ? `${stats.active_sessions_realtime} real-time · ${stats.active_sessions_document} document`
        : "loading…",
      color: "#2563eb",
    },
    {
      label: "Today's Translations",
      val: loading ? "—" : String(stats?.todays_translations_total ?? 0),
      sub: stats
        ? `${stats.todays_translations_docs} docs · ${stats.todays_translations_realtime} real-time`
        : "loading…",
      color: "#0B1D3A",
    },
    {
      label: "Avg NMT Confidence",
      val: loading ? "—" : stats?.avg_nmt_confidence != null ? stats.avg_nmt_confidence.toFixed(2) : "—",
      sub: stats?.avg_nmt_confidence != null ? "today's document pipeline" : "no data today",
      color: "#16a34a",
    },
    {
      label: "Avg ASR Confidence",
      val: "0.94",
      sub: "static — MLflow integration pending",
      color: "#16a34a",
    },
  ]

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-4xl mx-auto px-5 py-6">

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-xl font-bold"
            style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
            System Monitoring
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void fetchStats()}
              disabled={loading}
              className="text-[10px] px-2 py-1 rounded border cursor-pointer"
              style={{ color: "#8494A7", borderColor: "#E2E6EC", background: "#fff" }}
            >
              {loading ? "…" : "↻ Refresh"}
            </button>
            <span className="text-[10px] font-semibold px-2 py-1 rounded"
              style={{ background: "#DCFCE7", color: "#16a34a" }}>
              ALL SYSTEMS OPERATIONAL
            </span>
          </div>
        </div>

        {error && (
          <div className="rounded-md px-3 py-2 text-xs mb-4"
            style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#991B1B" }}>
            {error}
          </div>
        )}

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
          {/* Model Health — static, no live source */}
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
              <div className="text-[10px] mt-3 pt-2" style={{ borderTop: "1px solid #E2E6EC", color: "#B0BAC9" }}>
                Static — live latency metrics pending MLflow integration
              </div>
            </CardContent>
          </Card>

          {/* Drift Report — static, no live source */}
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
              <div className="text-[10px] mt-3 pt-2" style={{ borderTop: "1px solid #E2E6EC", color: "#B0BAC9" }}>
                Static — live drift reports pending MLflow integration
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {/* Infrastructure — static, no live source */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                GCE VM Infrastructure
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
              <div className="text-[10px] mt-3 pt-2" style={{ borderTop: "1px solid #E2E6EC", color: "#B0BAC9" }}>
                Static — live VM metrics pending GCP Monitoring integration
              </div>
            </CardContent>
          </Card>

          {/* Recent Audit Events — live */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                Recent Activity
              </div>
              {loading && (
                <div className="text-xs py-2" style={{ color: "#8494A7" }}>Loading…</div>
              )}
              {!loading && stats?.recent_audit_events.length === 0 && (
                <div className="text-xs py-2" style={{ color: "#8494A7" }}>No recent activity.</div>
              )}
              {!loading && stats?.recent_audit_events.map((e, i) => (
                <div key={e.audit_id} className="flex items-start gap-2 py-1.5 text-xs"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <span>ℹ️</span>
                  <div>
                    <div style={{ color: "#1A2332" }}>{labelForAction(e.action_type)}</div>
                    <div className="text-[10px]" style={{ color: "#8494A7" }}>{formatEventTime(e.created_at)}</div>
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
