import { useCallback, useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { adminApi, type AdminMetrics, type AdminStats } from "@/services/api"

interface Props { onNav: (s: ScreenId) => void }

// ── Model health config — maps display name to pipeline step key ──────────────
// stepKey null = realtime-only model, no pipeline_steps entry

const MODEL_HEALTH_CONFIG: { name: string; stepKey: string | null }[] = [
  { name: "Faster-Whisper Large V3", stepKey: null },
  { name: "NLLB-200 Distilled 1.3B", stepKey: "translate" },
  { name: "PaddleOCR v3",            stepKey: "ocr_printed_text" },
  { name: "Qwen2.5-VL",              stepKey: "classify_document" },
  { name: "Silero VAD v4",           stepKey: null },
  { name: "Piper TTS",               stepKey: null },
  { name: "Llama 4 (Vertex AI)",     stepKey: "legal_review" },
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

function driftBadge(value: number | null, isLlama = false): { label: string; color: string; critical: boolean } {
  if (value === null) return { label: "No data", color: "#8494A7", critical: false }
  if (isLlama) {
    // avg corrections per document; higher = worse
    if (value > 5.0) return { label: "↑ Increasing", color: "#dc2626", critical: true }
    if (value > 2.0) return { label: "Minor",         color: "#d97706", critical: false }
    return { label: "None", color: "#16a34a", critical: false }
  }
  // Confidence metrics (0–1): lower = worse
  if (value < 0.75) return { label: "Critical", color: "#dc2626", critical: true }
  if (value < 0.85) return { label: "Minor",    color: "#d97706", critical: false }
  return { label: "None", color: "#16a34a", critical: false }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AdminDashboard({ onNav }: Props) {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [metricsError, setMetricsError] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setStatsError(null)
    setMetricsError(null)
    const [statsResult, metricsResult] = await Promise.allSettled([
      adminApi.getStats(),
      adminApi.getMetrics(),
    ])
    if (statsResult.status === "fulfilled") setStats(statsResult.value)
    else setStatsError("Failed to load stats. Please try again.")
    if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value)
    else setMetricsError("Drift data unavailable — metrics query failed.")
    setLoading(false)
  }, [])

  useEffect(() => {
    void fetchAll()
    const id = setInterval(() => void fetchAll(), 30_000)
    return () => clearInterval(id)
  }, [fetchAll])

  const driftRows = [
    { metric: "ASR Confidence",        value: metrics?.asr_confidence_7d        ?? null },
    { metric: "NMT Confidence (ES)",   value: metrics?.nmt_confidence_es_7d    ?? null },
    { metric: "NMT Confidence (PT)",   value: metrics?.nmt_confidence_pt_7d    ?? null },
    { metric: "OCR Confidence",        value: metrics?.ocr_confidence_7d       ?? null },
    { metric: "Llama Correction Rate", value: metrics?.llama_correction_rate_7d ?? null, isLlama: true },
  ]

  const hasCritical = driftRows.some(r => driftBadge(r.value, r.isLlama).critical)

  const statCards = [
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
      val: loading ? "—" : stats?.avg_asr_confidence != null ? stats.avg_asr_confidence.toFixed(2) : "—",
      sub: stats?.avg_asr_confidence != null ? "today's realtime sessions" : "no data today",
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
              onClick={() => void fetchAll()}
              disabled={loading}
              className="text-[10px] px-2 py-1 rounded border cursor-pointer"
              style={{ color: "#8494A7", borderColor: "#E2E6EC", background: "#fff" }}
            >
              {loading ? "…" : "↻ Refresh"}
            </button>
            {hasCritical ? (
              <span className="text-[10px] font-semibold px-2 py-1 rounded"
                style={{ background: "#FEF3C7", color: "#d97706" }}>
                DEGRADED
              </span>
            ) : (
              <span className="text-[10px] font-semibold px-2 py-1 rounded"
                style={{ background: "#DCFCE7", color: "#16a34a" }}>
                ALL SYSTEMS OPERATIONAL
              </span>
            )}
          </div>
        </div>

        {statsError && (
          <div className="rounded-md px-3 py-2 text-xs mb-4"
            style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#991B1B" }}>
            {statsError}
          </div>
        )}
        {metricsError && (
          <div className="rounded-md px-3 py-2 text-xs mb-4"
            style={{ background: "#FEF3C7", border: "1px solid #FDE68A", color: "#92400E" }}>
            {metricsError}
          </div>
        )}

        {/* Metrics */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          {statCards.map((m, i) => (
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
          {/* Model Pipeline Health — live latency from pipeline_steps */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                Model Pipeline Health
              </div>
              {MODEL_HEALTH_CONFIG.map((m, i) => {
                const seconds = m.stepKey != null ? metrics?.model_latencies[m.stepKey] : null
                const latency = seconds != null ? `${Math.round(seconds * 1000)}ms` : "—"
                return (
                  <div key={i} className="flex items-center justify-between py-1.5 text-xs"
                    style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#16a34a" }} />
                      <span style={{ color: "#1A2332" }}>{m.name}</span>
                    </div>
                    <span style={{ color: "#8494A7" }}>{latency}</span>
                  </div>
                )
              })}
              <div className="text-[10px] mt-3 pt-2" style={{ borderTop: "1px solid #E2E6EC", color: "#B0BAC9" }}>
                Avg latency over last 7 days · realtime models not tracked here
              </div>
            </CardContent>
          </Card>

          {/* Drift Report — live 7-day rolling averages */}
          <Card>
            <CardContent className="p-4">
              <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
                Evidently AI — Drift Report
              </div>
              {driftRows.map((d, i) => {
                const badge = driftBadge(d.value, d.isLlama)
                const display = d.value != null ? d.value.toFixed(2) : "—"
                const bg = badge.color === "#16a34a" ? "#DCFCE7"
                         : badge.color === "#d97706" ? "#FEF3C7"
                         : badge.color === "#dc2626" ? "#FEE2E2"
                         : "#F1F5F9"
                return (
                  <div key={i} className="flex items-center justify-between py-1.5 text-xs"
                    style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                    <span style={{ color: "#1A2332" }}>{d.metric}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold" style={{ color: "#1A2332" }}>{display}</span>
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                        style={{ background: bg, color: badge.color }}>
                        {badge.label}
                      </span>
                    </div>
                  </div>
                )
              })}
              <div className="text-[10px] mt-3 pt-2" style={{ borderTop: "1px solid #E2E6EC", color: "#B0BAC9" }}>
                7-day rolling average · refreshes every 30 seconds
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
