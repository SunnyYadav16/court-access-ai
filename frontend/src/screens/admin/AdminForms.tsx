/**
 * screens/admin/AdminForms.tsx
 *
 * Form scraper management — renders INSIDE AppShell.
 * Dark-themed with Airflow DAG status bar, scrape summary,
 * pending review queue, and system stats footer.
 *
 * Preserved logic: formsApi.list() for pending forms, adminApi.triggerScraper(),
 * formsApi.review() for approve, navigation to forms library for review.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { adminApi, formsApi, type FormResponse } from "@/services/api"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const scenarios = [
  { label: "Scenario A", sub: "New Forms",     icon: "add_circle",    accent: "text-green-400" },
  { label: "Scenario B", sub: "Updated",        icon: "update",        accent: "text-blue-400" },
  { label: "Scenario C", sub: "Deleted (404)",  icon: "link_off",      accent: "text-slate-500" },
  { label: "Scenario D", sub: "Renamed",        icon: "drive_file_rename_outline", accent: "text-amber-400" },
  { label: "Scenario E", sub: "No Changes",     icon: "check_circle",  accent: "text-slate-500" },
]

export default function AdminForms({ onNav }: Props) {
  const [pendingForms, setPendingForms] = useState<FormResponse[]>([])
  const [lastScrapeAt, setLastScrapeAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [triggerBanner, setTriggerBanner] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [approving, setApproving] = useState<string | null>(null)

  async function fetchData() {
    setLoading(true)
    setError(null)
    try {
      const formsResp = await formsApi.list({ status: "active", page_size: 200 })
      const pending = formsResp.items.filter((f) => f.needs_human_review)
      setPendingForms(pending)
      const sorted = formsResp.items
        .map((f) => f.last_scraped_at)
        .filter((d): d is string => d !== null)
        .sort()
      const latest = sorted.length > 0 ? sorted[sorted.length - 1] : null
      setLastScrapeAt(latest)
    } catch {
      setError("Failed to load forms data. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void fetchData() }, [])

  async function handleTriggerScrape() {
    setTriggering(true)
    setTriggerBanner(null)
    setError(null)
    try {
      const res = await adminApi.triggerScraper()
      setTriggerBanner(`Scrape triggered — DAG run ID: ${res.dag_run_id}`)
      setTimeout(() => void fetchData(), 3_000)
    } catch {
      setError("Failed to trigger scraper. Is Airflow running?")
    } finally {
      setTriggering(false)
    }
  }

  async function handleApprove(formId: string) {
    setApproving(formId)
    try {
      await formsApi.review(formId, true)
      setPendingForms((prev) => prev.filter((f) => f.form_id !== formId))
    } catch {
      setError(`Failed to approve form.`)
    } finally {
      setApproving(null)
    }
  }

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl mx-auto space-y-8">

      {/* Header */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6">
        <div>
          <h1 className="font-headline text-4xl text-on-surface mb-2">Form Scraper Management</h1>
          <p className="text-on-surface-variant text-lg max-w-2xl">
            Orchestrate high-precision legal document ingestion and neural entity extraction workflows.
          </p>
        </div>
        <button
          disabled={triggering}
          onClick={() => void handleTriggerScrape()}
          className="px-8 py-4 bg-secondary text-on-secondary rounded-md font-bold text-sm flex items-center gap-3 shadow-lg shadow-secondary/10 hover:scale-[1.02] transition-transform active:scale-95 duration-150 cursor-pointer disabled:opacity-50 border-none"
        >
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>
          {triggering ? "TRIGGERING…" : "TRIGGER MANUAL SCRAPE"}
        </button>
      </header>

      {/* Errors / Banners */}
      {error && (
        <div className="rounded-lg px-4 py-3 text-xs bg-red-950 border border-red-900 text-red-300">
          {error}
        </div>
      )}
      {triggerBanner && (
        <div className="rounded-lg px-4 py-3 text-xs bg-green-950 border border-green-900 text-green-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-green-400">check_circle</span>
            {triggerBanner}
          </div>
          <button onClick={() => setTriggerBanner(null)} className="text-green-400 hover:text-white cursor-pointer bg-transparent border-none">
            <span className="material-symbols-outlined text-base">close</span>
          </button>
        </div>
      )}

      {/* Airflow DAG Status Bar */}
      <section className="bg-surface-container-low p-6 rounded-xl relative overflow-hidden">
        <div className="absolute top-0 left-0 w-1 h-full bg-tertiary" />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1 font-bold">Pipeline ID</span>
              <span className="text-lg font-mono text-tertiary">form_scraper_dag</span>
            </div>
            <div className="h-10 w-px bg-outline-variant/30" />
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1 font-bold">Last Run</span>
              <span className="font-medium text-on-surface">
                {loading ? "loading…" : formatDate(lastScrapeAt)}
              </span>
            </div>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-12 gap-6">
        {/* Last Scrape Results */}
        <section className="col-span-12 lg:col-span-7 bg-surface-container-high rounded-xl p-8 flex flex-col gap-8 relative overflow-hidden">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="font-headline text-2xl text-on-surface">Last Scrape Analysis</h3>
              <p className="text-on-surface-variant text-sm mt-1">
                Scenario breakdown not yet stored in DB — pending form_scraper_dag update.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-5 gap-4">
            {scenarios.map((s, i) => (
              <div key={i} className="text-center py-3 flex flex-col items-center">
                <span className={`material-symbols-outlined text-2xl ${s.accent} mb-2`}>{s.icon}</span>
                <div className="text-2xl font-headline text-on-surface-variant mb-1">—</div>
                <div className="text-[10px] text-slate-500 font-label uppercase tracking-wider">{s.label}</div>
                <div className="text-[10px] text-slate-600">{s.sub}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Pending Human Review */}
        <section className="col-span-12 lg:col-span-5 bg-surface-container-high rounded-xl p-8 flex flex-col gap-6">
          <div className="flex items-center justify-between">
            <h3 className="font-headline text-2xl text-on-surface">Pending Review</h3>
            {!loading && (
              <span className="w-8 h-8 rounded-full bg-secondary text-on-secondary flex items-center justify-center font-bold text-xs">
                {pendingForms.length}
              </span>
            )}
          </div>

          {loading && (
            <div className="text-sm py-3 text-on-surface-variant">Loading…</div>
          )}

          {!loading && pendingForms.length === 0 && (
            <div className="text-sm py-3 text-on-surface-variant">No forms pending review.</div>
          )}

          <div className="space-y-4 overflow-y-auto max-h-[440px] pr-2">
            {!loading && pendingForms.map((f) => {
              const langs = [
                f.versions.some((v) => v.file_path_es) ? "ES" : null,
                f.versions.some((v) => v.file_path_pt) ? "PT" : null,
              ].filter(Boolean).join(", ") || "—"

              return (
                <div
                  key={f.form_id}
                  className="p-4 bg-surface-container-low rounded-lg group hover:bg-surface-bright transition-colors cursor-pointer border-l-2 border-transparent hover:border-secondary"
                >
                  <div className="flex justify-between items-start mb-2">
                    <h4 className="font-semibold text-on-surface text-sm">{f.form_name}</h4>
                    <span className="text-[10px] text-[#FFD700] font-bold uppercase">Pending</span>
                  </div>
                  <p className="text-xs text-on-surface-variant mb-3">
                    {langs} · since {formatDate(f.last_scraped_at)}
                  </p>
                  <div className="flex items-center justify-between">
                    <button
                      className="text-on-surface-variant text-[10px] font-bold uppercase tracking-widest group-hover:text-white bg-transparent border-none cursor-pointer"
                      onClick={() => {
                        sessionStorage.setItem("admin_review_form_id", f.form_id)
                        sessionStorage.setItem("forms_search_prefill", f.form_name)
                        onNav(SCREENS.FORMS_LIBRARY)
                      }}
                    >
                      Review
                    </button>
                    <button
                      className="text-secondary text-[10px] font-bold uppercase tracking-widest group-hover:underline bg-transparent border-none cursor-pointer disabled:opacity-50"
                      disabled={approving === f.form_id}
                      onClick={() => void handleApprove(f.form_id)}
                    >
                      {approving === f.form_id ? "…" : "Approve"}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      </div>

      {/* System Stats Footer Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {[
          { label: "Worker Nodes", value: "12", extra: <span className="text-xs text-green-500 flex items-center"><span className="material-symbols-outlined text-sm">arrow_upward</span> 100%</span> },
          { label: "Avg Processing Time", value: "1.4s", extra: <span className="text-xs text-on-surface-variant">/ page</span> },
          { label: "Total Tokens Ingested", value: "1.2M", extra: <span className="text-xs text-tertiary">Current Session</span> },
          { label: "DB Latency", value: "14ms", extra: <span className="text-xs text-green-500">Stable</span> },
        ].map((s) => (
          <div key={s.label} className="p-6 bg-surface-container-low rounded-xl border border-outline-variant/5">
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold block mb-4">{s.label}</span>
            <div className="flex items-center gap-3">
              <span className="text-3xl font-headline">{s.value}</span>
              {s.extra}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
