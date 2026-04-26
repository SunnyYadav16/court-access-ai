/**
 * screens/admin/AdminDashboard.tsx
 *
 * System monitoring dashboard — renders INSIDE AppShell.
 * Dark-themed with stat cards, model pipeline health, drift report,
 * infrastructure table, and recent activity audit log.
 *
 * Preserved logic: adminApi.getStats() + adminApi.getMetrics() polling,
 * model latency display, drift badge calculation, audit event formatting.
 */

import { useCallback, useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { adminApi, type AdminMetrics, type AdminStats, type ContainerStat } from "@/services/api"

interface Props { onNav: (s: ScreenId) => void }

type Tab = "monitoring" | "infrastructure"

const MODEL_HEALTH_CONFIG: { name: string; icon: string; stepKey: string | null }[] = [
  { name: "Faster-Whisper Large V3", icon: "mic",             stepKey: null },
  { name: "NLLB-200 Distilled 1.3B", icon: "translate",       stepKey: "translate" },
  { name: "PaddleOCR v3",            icon: "document_scanner", stepKey: "ocr_printed_text" },
  { name: "Llama 4 (Classifier)",     icon: "category",          stepKey: "classify_document" },
  { name: "Silero VAD v4",           icon: "graphic_eq",       stepKey: null },
  { name: "Piper TTS",               icon: "record_voice_over", stepKey: null },
  { name: "Llama 4 (Vertex AI)",     icon: "gavel",            stepKey: "legal_review" },
]

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

function driftBadge(value: number | null, isLlama = false): { label: string; color: string; bg: string; critical: boolean } {
  if (value === null) return { label: "No data", color: "text-slate-500", bg: "bg-slate-800", critical: false }
  if (isLlama) {
    if (value > 5.0) return { label: "Increasing", color: "text-red-400", bg: "bg-red-950", critical: true }
    if (value > 2.0) return { label: "Minor", color: "text-amber-400", bg: "bg-amber-950", critical: false }
    return { label: "None", color: "text-green-400", bg: "bg-green-950", critical: false }
  }
  if (value < 0.75) return { label: "Critical", color: "text-red-400", bg: "bg-red-950", critical: true }
  if (value < 0.85) return { label: "Minor", color: "text-amber-400", bg: "bg-amber-950", critical: false }
  return { label: "None", color: "text-green-400", bg: "bg-green-950", critical: false }
}

export default function AdminDashboard({ onNav: _onNav }: Props) {
  const [tab, setTab] = useState<Tab>("monitoring")
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [containerStats, setContainerStats] = useState<ContainerStat[] | null>(null)
  const [infraLoading, setInfraLoading] = useState(false)
  const [cleaning, setCleaning] = useState(false)

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
  }, [fetchAll])

  useEffect(() => {
    if (tab === "infrastructure") {
      setInfraLoading(true)
      adminApi.getContainerStats()
        .then(setContainerStats)
        .catch(() => setContainerStats(null))
        .finally(() => setInfraLoading(false))
    }
  }, [tab])

  const handleCleanup = useCallback(async () => {
    setCleaning(true)
    try {
      const result = await adminApi.cleanupStaleSessions()
      if (result.cleaned > 0) void fetchAll()
    } catch { /* non-critical */ }
    finally { setCleaning(false) }
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
      icon: "groups",
      accent: "text-secondary",
    },
    {
      label: "Today's Translations",
      val: loading ? "—" : String(stats?.todays_translations_total ?? 0),
      sub: stats
        ? `${stats.todays_translations_docs} docs · ${stats.todays_translations_realtime} real-time`
        : "loading…",
      icon: "language",
      accent: "text-tertiary",
    },
    {
      label: "Avg NMT Confidence",
      val: loading ? "—" : stats?.avg_nmt_confidence != null ? stats.avg_nmt_confidence.toFixed(2) : "—",
      sub: stats?.avg_nmt_confidence != null ? "today's document pipeline" : "no data today",
      icon: "verified",
      accent: "text-primary",
    },
    {
      label: "Avg ASR Confidence",
      val: loading ? "—" : stats?.avg_asr_confidence != null ? stats.avg_asr_confidence.toFixed(2) : "—",
      sub: stats?.avg_asr_confidence != null ? "today's realtime sessions" : "no data today",
      icon: "settings_voice",
      accent: "text-secondary",
    },
  ]

  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: "monitoring", label: "Monitoring", icon: "monitoring" },
    { key: "infrastructure", label: "Infrastructure", icon: "dns" },
  ]

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-8">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <div className="flex items-center gap-3 mb-4">
            {hasCritical ? (
              <span className="px-3 py-1 rounded-full bg-amber-950/50 text-amber-400 text-[10px] font-bold uppercase tracking-widest border border-amber-500/20 flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
                </span>
                SYSTEMS DEGRADED
              </span>
            ) : (
              <span className="px-3 py-1 rounded-full bg-green-950/50 text-green-400 text-[10px] font-bold uppercase tracking-widest border border-green-500/20 flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                </span>
                ALL SYSTEMS OPERATIONAL
              </span>
            )}
          </div>
          <h1 className="text-5xl font-headline text-on-surface tracking-tight">System Monitoring</h1>
          <p className="text-on-surface-variant mt-2 max-w-xl">
            Monitor translation processing, system health, and recent activity across all services.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleCleanup}
            disabled={cleaning}
            className="flex items-center gap-2 px-5 py-2.5 bg-surface-container-high rounded-lg text-sm font-medium hover:bg-surface-bright transition-colors border border-outline-variant/15 cursor-pointer disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">cleaning_services</span>
            {cleaning ? "Cleaning…" : "Clean Stale Sessions"}
          </button>
          <button
            onClick={() => void fetchAll()}
            disabled={loading}
            className="flex items-center gap-2 px-5 py-2.5 bg-surface-container-high rounded-lg text-sm font-medium hover:bg-surface-bright transition-colors border border-outline-variant/15 cursor-pointer disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            {loading ? "Loading…" : "Refresh Data"}
          </button>
        </div>
      </div>

      {/* Errors */}
      {statsError && (
        <div className="rounded-lg px-4 py-3 text-xs bg-red-950 border border-red-900 text-red-300">
          {statsError}
        </div>
      )}
      {metricsError && (
        <div className="rounded-lg px-4 py-3 text-xs bg-amber-950 border border-amber-900 text-amber-300">
          {metricsError}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {statCards.map((m) => (
          <div key={m.label} className="bg-surface-container-low p-6 rounded-xl">
            <div className="flex justify-between items-start mb-4">
              <span
                className={`material-symbols-outlined ${m.accent}`}
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                {m.icon}
              </span>
            </div>
            <h3 className="text-3xl font-headline text-white mb-1">{m.val}</h3>
            <p className="text-on-surface-variant text-xs uppercase tracking-wider">{m.label}</p>
            <p className="text-[11px] text-slate-500 mt-1">{m.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface-container-lowest rounded-lg p-1 w-fit">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-label transition-colors cursor-pointer ${
              tab === t.key
                ? "bg-surface-container-high text-white"
                : "text-on-surface-variant hover:text-white"
            }`}
          >
            <span className="material-symbols-outlined text-base">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Monitoring Tab */}
      {tab === "monitoring" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Model Pipeline Health — wide card */}
          <div className="lg:col-span-2 bg-surface-container-low rounded-xl p-8 flex flex-col">
            <div className="flex items-center justify-between mb-8">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-tertiary">analytics</span>
                <h2 className="text-xl font-headline text-white">Model Pipeline Health</h2>
              </div>
              <span className="px-2 py-0.5 rounded bg-tertiary/10 text-tertiary text-[10px] font-bold">OPTIMIZED</span>
            </div>
            <div className="space-y-0">
              {MODEL_HEALTH_CONFIG.map((m, i) => {
                const seconds = m.stepKey != null ? metrics?.model_latencies[m.stepKey] : null
                const latency = seconds != null ? `${Math.round(seconds * 1000)}ms` : "—"
                return (
                  <div key={i} className={`flex items-center justify-between py-3 text-sm ${
                    i ? "border-t border-white/5" : ""
                  }`}>
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-base text-green-400">{m.icon}</span>
                      <span className="text-on-surface">{m.name}</span>
                    </div>
                    <span className="text-on-surface-variant font-mono text-xs">{latency}</span>
                  </div>
                )
              })}
            </div>
            <div className="text-[11px] mt-4 pt-3 border-t border-white/5 text-slate-600">
              Avg latency over last 7 days · realtime models not tracked here
            </div>
          </div>

          {/* GCE Infrastructure Card — side accent */}
          <div className="bg-primary-container rounded-xl overflow-hidden relative group border border-outline-variant/10">
            <div className="absolute inset-0 bg-gradient-to-br from-primary-container to-surface-container-lowest opacity-90 z-0" />
            <div className="relative z-10 p-8 h-full flex flex-col">
              <div className="mb-6">
                <h2 className="text-xl font-headline text-white mb-2">GCE VM Infrastructure</h2>
                <p className="text-on-primary-container text-sm">Distributed across 4 regions.</p>
              </div>
              <div className="space-y-4 mt-auto">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-on-primary-container">us-east1-b</span>
                  <span className="text-green-400">99.9% Up</span>
                </div>
                <div className="w-full bg-white/5 h-1 rounded-full overflow-hidden">
                  <div className="bg-primary h-full" style={{ width: "99.9%" }} />
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-on-primary-container">europe-west4-a</span>
                  <span className="text-green-400">99.8% Up</span>
                </div>
                <div className="w-full bg-white/5 h-1 rounded-full overflow-hidden">
                  <div className="bg-primary h-full" style={{ width: "99.8%" }} />
                </div>
              </div>
            </div>
          </div>

          {/* Drift Report — full width */}
          <div className="lg:col-span-3 bg-surface-container-low rounded-xl p-6 border border-white/5">
            <div className="flex items-center gap-2 mb-5">
              <span className="material-symbols-outlined text-tertiary">analytics</span>
              <h3 className="text-lg text-white font-headline">Evidently AI — Drift Report</h3>
            </div>
            <div className="space-y-0">
              {driftRows.map((d, i) => {
                const badge = driftBadge(d.value, d.isLlama)
                const display = d.value != null ? d.value.toFixed(2) : "—"
                return (
                  <div key={i} className={`flex items-center justify-between py-3 text-sm ${
                    i ? "border-t border-white/5" : ""
                  }`}>
                    <span className="text-on-surface">{d.metric}</span>
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs text-on-surface">{display}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${badge.bg} ${badge.color}`}>
                        {badge.label}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="text-[11px] mt-4 pt-3 border-t border-white/5 text-slate-600">
              7-day rolling average · manual refresh only
            </div>
          </div>

          {/* Recent Activity — full width */}
          <div className="lg:col-span-3 bg-surface-container-low rounded-xl p-8">
            <div className="flex items-center justify-between mb-8">
              <h2 className="text-xl font-headline text-white">Recent Activity Audit Log</h2>
            </div>
            {loading && (
              <div className="text-sm py-3 text-on-surface-variant">Loading…</div>
            )}
            {!loading && stats?.recent_audit_events.length === 0 && (
              <div className="text-sm py-3 text-on-surface-variant">No recent activity.</div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-left border-separate border-spacing-y-2">
                <thead>
                  <tr className="text-on-surface-variant text-[10px] uppercase tracking-widest">
                    <th className="pb-2 px-4">Action</th>
                    <th className="pb-2 px-4">Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {!loading && stats?.recent_audit_events.map((e) => (
                    <tr key={e.audit_id} className="bg-surface-container-high/50 group hover:bg-surface-container-high transition-colors">
                      <td className="py-4 px-4 rounded-l-lg">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-secondary/10 flex items-center justify-center">
                            <span className="material-symbols-outlined text-secondary text-sm">info</span>
                          </div>
                          <span className="text-sm font-medium text-white">{labelForAction(e.action_type)}</span>
                        </div>
                      </td>
                      <td className="py-4 px-4 rounded-r-lg text-sm text-on-surface-variant">
                        {formatEventTime(e.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Infrastructure Tab */}
      {tab === "infrastructure" && (
        <div className="bg-surface-container-low rounded-xl p-6 border border-white/5">
          <div className="flex items-center gap-2 mb-5">
            <span className="material-symbols-outlined text-secondary">dns</span>
            <h3 className="text-lg text-white font-headline">Container Resource Usage</h3>
          </div>
          {/* Table header */}
          <div className="grid grid-cols-4 py-2 text-[11px] uppercase tracking-widest font-label text-on-surface-variant border-b border-white/10">
            <span>Container</span>
            <span>CPU</span>
            <span>Memory</span>
            <span>GPU</span>
          </div>
          {infraLoading && (
            <div className="text-sm text-on-surface-variant py-4">Loading container stats…</div>
          )}
          {!infraLoading && containerStats && containerStats.map((r, i) => (
            <div key={i} className={`grid grid-cols-4 py-3 text-sm ${
              i ? "border-t border-white/5" : ""
            }`}>
              <span className="text-on-surface font-medium">{r.name}</span>
              <span className={parseFloat(r.cpu) > 80 ? "text-red-400" : "text-on-surface-variant"}>{r.cpu}</span>
              <span className={parseFloat(r.mem) > 80 ? "text-red-400" : "text-on-surface-variant"}>{r.mem}</span>
              <span className="text-on-surface-variant">{r.gpu ?? "—"}</span>
            </div>
          ))}
          {!infraLoading && !containerStats && (
            <div className="text-sm text-on-surface-variant py-4">Container stats unavailable.</div>
          )}
        </div>
      )}
    </div>
  )
}
