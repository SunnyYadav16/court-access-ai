import { useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { adminApi, formsApi, type FormResponse } from "@/services/api"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

// Scenario breakdown has no live source yet — scraped counts are not stored
// in a queryable column. Kept static until form_scraper_dag writes per-run stats.
const scenarios = [
  { label: "Scenario A", val: "—", sub: "New Forms", color: "#16a34a" },
  { label: "Scenario B", val: "—", sub: "Updated", color: "#2563eb" },
  { label: "Scenario C", val: "—", sub: "Deleted (404)", color: "#8494A7" },
  { label: "Scenario D", val: "—", sub: "Renamed", color: "#d97706" },
  { label: "Scenario E", val: "—", sub: "No Changes", color: "#8494A7" },
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
      // Derive last scrape time from the most recently scraped form rather than
      // making a separate stats call just for this one timestamp.
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
      // Re-fetch after a short delay so last_scrape_at may update
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
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-3xl mx-auto px-5 py-6">

        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-bold mb-0.5"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Form Scraper Management
            </h1>
            <p className="text-xs" style={{ color: "#8494A7" }}>
              Airflow DAG: form_scraper_dag · Last run:{" "}
              {loading ? "loading…" : formatDate(lastScrapeAt)}
            </p>
          </div>
          <Button
            size="sm"
            style={{ background: triggering ? "#8494A7" : "#0B1D3A" }}
            className="cursor-pointer"
            disabled={triggering}
            onClick={() => void handleTriggerScrape()}
          >
            {triggering ? "Triggering…" : "🔄 Trigger Manual Scrape"}
          </Button>
        </div>

        {error && (
          <div className="rounded-md px-3 py-2 text-xs mb-4"
            style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#991B1B" }}>
            {error}
          </div>
        )}

        {triggerBanner && (
          <div className="rounded-md px-3 py-2 text-xs mb-4 flex items-center justify-between"
            style={{ background: "#F0FDF4", border: "1px solid #86EFAC", color: "#166534" }}>
            <span>✅ {triggerBanner}</span>
            <button onClick={() => setTriggerBanner(null)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#166534" }}>✕</button>
          </div>
        )}

        {/* Scrape summary */}
        <Card className="mb-3">
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-1" style={{ color: "#1A2332" }}>
              Last Scrape Results
            </div>
            <div className="text-[11px] mb-4" style={{ color: "#8494A7" }}>
              Scenario breakdown not yet stored in DB — pending form_scraper_dag update.
            </div>
            <div className="grid grid-cols-5 gap-3">
              {scenarios.map((s, i) => (
                <div key={i} className="text-center">
                  <div className="text-2xl font-bold mb-0.5"
                    style={{ color: s.color, fontFamily: "Palatino, Georgia, serif" }}>
                    {s.val}
                  </div>
                  <div className="text-[10px]" style={{ color: "#8494A7" }}>{s.label}</div>
                  <div className="text-[10px]" style={{ color: "#8494A7" }}>{s.sub}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Pending review */}
        <Card>
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Pending Human Review{" "}
              {!loading && (
                <span style={{ color: "#8494A7", fontWeight: 400 }}>
                  ({pendingForms.length} form{pendingForms.length !== 1 ? "s" : ""})
                </span>
              )}
            </div>

            {loading && (
              <div className="text-xs py-2" style={{ color: "#8494A7" }}>Loading…</div>
            )}

            {!loading && pendingForms.length === 0 && (
              <div className="text-xs py-2" style={{ color: "#8494A7" }}>
                No forms pending review.
              </div>
            )}

            {!loading && pendingForms.map((f, i) => {
              const langs = [
                f.versions.some((v) => v.file_path_es) ? "ES" : null,
                f.versions.some((v) => v.file_path_pt) ? "PT" : null,
              ].filter(Boolean).join(", ") || "—"

              return (
                <div key={f.form_id} className="flex items-center justify-between py-2.5 text-xs"
                  style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                  <div>
                    <span className="font-medium" style={{ color: "#1A2332" }}>{f.form_name}</span>
                    <span className="ml-2" style={{ color: "#8494A7" }}>
                      {langs} · since {formatDate(f.last_scraped_at)}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="cursor-pointer text-xs"
                      onClick={() => {
                        sessionStorage.setItem("admin_review_form_id", f.form_id)
                        // Navigate to forms library where the form can be reviewed
                        sessionStorage.setItem("forms_search_prefill", f.form_name)
                        onNav("FORMS_LIBRARY" as ScreenId)
                      }}
                    >
                      Review
                    </Button>
                    <Button
                      size="sm"
                      className="cursor-pointer text-xs"
                      style={{ background: approving === f.form_id ? "#8494A7" : "#0B1D3A" }}
                      disabled={approving === f.form_id}
                      onClick={() => void handleApprove(f.form_id)}
                    >
                      {approving === f.form_id ? "…" : "Approve"}
                    </Button>
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="ADMIN — FORM SCRAPER MANAGEMENT" />
    </div>
  )
}
