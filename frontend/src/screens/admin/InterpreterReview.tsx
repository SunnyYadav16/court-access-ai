/**
 * screens/admin/InterpreterReview.tsx
 *
 * Translation review queue — renders INSIDE AppShell.
 * Two views:
 *   A) Queue table — lists all completed translations with review status
 *   B) Detail view — download originals, review, approve/flag for recorrection
 */

import { useCallback, useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { interpreterApi, type InterpreterReviewSummary } from "@/services/api"

interface Props { onNav: (s: ScreenId) => void }

type View = "queue" | "detail"

const LANG_LABEL: Record<string, string> = { es: "Spanish", pt: "Portuguese" }

function formatDate(iso: string): string {
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

function ReviewStatusBadge({ status }: { status: string }) {
  if (status === "approved")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-green-900/30 text-green-400">
        <span className="material-symbols-outlined text-[10px]">check_circle</span>
        Approved
      </span>
    )
  if (status === "flagged")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-red-900/30 text-red-400">
        <span className="material-symbols-outlined text-[10px]">flag</span>
        Flagged
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-900/30 text-amber-400">
      <span className="material-symbols-outlined text-[10px]">pending</span>
      Pending
    </span>
  )
}

function StatCard({ label, value, icon, color }: { label: string; value: string; icon: string; color: string }) {
  return (
    <div className={`bg-surface-container-low p-5 rounded-lg border-l-4 ${color} flex items-center gap-4`}>
      <div className="w-10 h-10 rounded-full bg-surface-container-high flex items-center justify-center">
        <span className="material-symbols-outlined text-on-surface-variant">{icon}</span>
      </div>
      <div>
        <p className="text-[10px] uppercase text-outline tracking-wider">{label}</p>
        <p className="text-xl font-bold text-on-surface">{value}</p>
      </div>
    </div>
  )
}

function ConfidenceLabel({ score }: { score: number | null }) {
  if (score == null) return <span className="text-sm text-on-surface-variant">--</span>
  const pct = (score * 100).toFixed(1)
  const color = score >= 0.9 ? "text-green-400" : score >= 0.7 ? "text-amber-400" : "text-red-400"
  return <span className={`text-sm font-bold ${color}`}>{pct}%</span>
}

export default function InterpreterReview({ onNav: _onNav }: Props) {
  const [view, setView] = useState<View>("queue")
  const [sessions, setSessions] = useState<InterpreterReviewSummary[]>([])
  const [selectedSession, setSelectedSession] = useState<InterpreterReviewSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [langFilter, setLangFilter] = useState<"" | "es" | "pt">("")
  const [page, setPage] = useState(1)
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // ── Fetch review queue ───────────────────────────────────────────────────

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await interpreterApi.listReview(page, langFilter || undefined)
      setSessions(data)
    } catch {
      setError("Failed to load review queue. Please try again.")
    } finally {
      setLoading(false)
    }
  }, [page, langFilter])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // ── Actions ──────────────────────────────────────────────────────────────

  async function handleApprove() {
    if (!selectedSession) return
    setSubmitting(true)
    setError(null)
    try {
      await interpreterApi.approve(selectedSession.session_id)
      const updated = { ...selectedSession, review_status: "approved" as const }
      setSessions((prev) =>
        prev.map((s) => (s.session_id === selectedSession.session_id ? updated : s)),
      )
      setSelectedSession(updated)
      setNotes("")
      setView("queue")
    } catch {
      setError("Failed to approve translation.")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleFlag() {
    if (!selectedSession || !notes.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await interpreterApi.flag(selectedSession.session_id, notes, true)
      const updated = { ...selectedSession, review_status: "flagged" as const }
      setSessions((prev) =>
        prev.map((s) => (s.session_id === selectedSession.session_id ? updated : s)),
      )
      setNotes("")
      setView("queue")
    } catch {
      setError("Failed to flag translation.")
    } finally {
      setSubmitting(false)
    }
  }

  function openDetail(session: InterpreterReviewSummary) {
    setSelectedSession(session)
    setNotes("")
    setError(null)
    setView("detail")
  }

  // ── Derived counts ───────────────────────────────────────────────────────

  const pendingCount = sessions.filter((s) => s.review_status === "pending").length
  const approvedCount = sessions.filter((s) => s.review_status === "approved").length
  const flaggedCount = sessions.filter((s) => s.review_status === "flagged").length

  // ══════════════════════════════════════════════════════════════════════════
  // Detail View
  // ══════════════════════════════════════════════════════════════════════════

  if (view === "detail" && selectedSession) {
    const s = selectedSession
    return (
      <div className="px-6 lg:px-8 py-8 max-w-5xl mx-auto space-y-8">
        {/* Back + Header */}
        <header className="space-y-4">
          <button
            onClick={() => setView("queue")}
            className="flex items-center gap-1 text-sm text-on-surface-variant hover:text-on-surface cursor-pointer bg-transparent border-none transition-colors"
          >
            <span className="material-symbols-outlined text-sm">arrow_back</span>
            Back to queue
          </button>
          <div className="flex items-center gap-3">
            <span className="bg-secondary text-on-secondary px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider">
              Interpreter Review
            </span>
            <ReviewStatusBadge status={s.review_status} />
          </div>
          <h1 className="font-headline text-3xl text-on-surface">
            {s.original_filename?.replace(/\.[^.]+$/, "").replace(/_/g, " ") ?? `Session ${s.session_id.slice(0, 8)}`}
          </h1>
          <p className="text-on-surface-variant text-sm">
            {LANG_LABEL[s.target_language] ?? s.target_language} translation &middot; {formatDate(s.created_at)}
          </p>
        </header>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-3 rounded-lg bg-error-container/20 text-error text-sm flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
          </div>
        )}

        {/* Download panels */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-surface-container-low rounded-xl p-6 border border-white/5">
            <div className="flex items-center gap-2 mb-1">
              <span className="material-symbols-outlined text-primary text-lg">description</span>
              <h3 className="font-headline text-lg text-on-surface">English (Original)</h3>
            </div>
            <p className="text-xs text-on-surface-variant mb-4">Source document from upload</p>
            {s.signed_url_original ? (
              <button
                onClick={() => window.open(s.signed_url_original!, "_blank")}
                className="w-full py-2.5 bg-[#FFD700] text-[#0D1B2A] rounded-lg font-bold text-sm flex items-center justify-center gap-2 cursor-pointer border-none hover:brightness-110 active:scale-[0.98] transition-all"
              >
                <span className="material-symbols-outlined text-sm">download</span>
                Download Original
              </button>
            ) : (
              <span className="text-xs text-on-surface-variant italic">Not available</span>
            )}
          </div>

          <div className="bg-surface-container-low rounded-xl p-6 border border-secondary/20">
            <div className="flex items-center gap-2 mb-1">
              <span className="material-symbols-outlined text-secondary text-lg">translate</span>
              <h3 className="font-headline text-lg text-on-surface">
                {LANG_LABEL[s.target_language] ?? s.target_language} (Translated)
              </h3>
            </div>
            <p className="text-xs text-on-surface-variant mb-4">
              AI-translated &middot; {s.llama_corrections_count} Llama correction{s.llama_corrections_count !== 1 ? "s" : ""}
            </p>
            {s.signed_url_translated ? (
              <button
                onClick={() => window.open(s.signed_url_translated!, "_blank")}
                className="w-full py-2.5 border border-secondary/30 text-secondary rounded-lg font-bold text-sm flex items-center justify-center gap-2 cursor-pointer bg-transparent hover:bg-secondary/5 active:scale-[0.98] transition-all"
              >
                <span className="material-symbols-outlined text-sm">download</span>
                Download Translation
              </button>
            ) : (
              <span className="text-xs text-on-surface-variant italic">Not available</span>
            )}
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard
            label="AI Confidence"
            value={s.avg_confidence_score != null ? `${(s.avg_confidence_score * 100).toFixed(1)}%` : "--"}
            icon="psychology"
            color="border-tertiary"
          />
          <StatCard
            label="Llama Corrections"
            value={String(s.llama_corrections_count)}
            icon="gavel"
            color="border-secondary"
          />
          <StatCard
            label="Review Status"
            value={s.review_status.charAt(0).toUpperCase() + s.review_status.slice(1)}
            icon="verified_user"
            color="border-primary"
          />
        </div>

        {/* Notes textarea */}
        <div className="space-y-2">
          <label htmlFor="review-notes" className="text-xs uppercase tracking-widest text-outline ml-1">
            Reviewer Notes / Corrections
          </label>
          <div className="relative group">
            <textarea
              id="review-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full bg-surface-container-highest rounded-xl p-4 text-on-surface placeholder:text-outline/50 min-h-[120px] resize-y outline-none border-none focus:ring-2 focus:ring-secondary/50 transition-all"
              placeholder="Add reviewer notes, corrections, or reasons for flagging..."
            />
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row gap-4">
          <button
            onClick={handleApprove}
            disabled={submitting || s.review_status === "approved"}
            className="flex-1 h-12 bg-secondary text-on-secondary font-bold rounded-lg flex items-center justify-center gap-2 cursor-pointer border-none hover:brightness-110 active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ boxShadow: "0px 8px 24px rgba(0, 0, 0, 0.3)" }}
          >
            <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>verified_user</span>
            {s.review_status === "approved" ? "Already Approved" : "Approve & Certify"}
          </button>
          <button
            onClick={handleFlag}
            disabled={submitting || !notes.trim() || s.review_status === "flagged"}
            className="flex-1 h-12 bg-error-container/20 text-error border border-error/30 font-bold rounded-lg flex items-center justify-center gap-2 cursor-pointer hover:bg-error-container/30 active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="material-symbols-outlined">flag</span>
            {s.review_status === "flagged" ? "Already Flagged" : "Flag for Recorrection"}
          </button>
        </div>
        {!notes.trim() && s.review_status !== "flagged" && (
          <p className="text-xs text-on-surface-variant -mt-2">Notes are required to flag a translation.</p>
        )}
      </div>
    )
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Queue Table View
  // ══════════════════════════════════════════════════════════════════════════

  return (
    <div className="px-6 lg:px-8 py-8 max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center gap-3">
          <span className="bg-secondary text-on-secondary px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider">
            Interpreter Role
          </span>
          <span className="text-tertiary font-medium text-sm flex items-center gap-1">
            <span className="material-symbols-outlined text-xs" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>
            AI Analysis Active
          </span>
        </div>
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
          <div>
            <h1 className="font-headline text-4xl text-on-surface mb-2">Translation Review Queue</h1>
            <p className="text-on-surface-variant max-w-2xl">
              Review AI-translated Massachusetts court forms automatically scraped from mass.gov
              and processed through the DAG pipeline. Download originals and translations to compare,
              then approve or flag for recorrection.
            </p>
          </div>
        </div>
      </header>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Pending Review" value={String(pendingCount)} icon="pending" color="border-amber-500" />
        <StatCard label="Approved" value={String(approvedCount)} icon="check_circle" color="border-green-500" />
        <StatCard label="Flagged" value={String(flaggedCount)} icon="flag" color="border-red-500" />
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-4">
        <label className="text-xs uppercase tracking-widest text-outline">Language:</label>
        <div className="flex gap-2">
          {[
            { value: "" as const, label: "All" },
            { value: "es" as const, label: "Spanish" },
            { value: "pt" as const, label: "Portuguese" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setLangFilter(opt.value); setPage(1) }}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold cursor-pointer border transition-all ${
                langFilter === opt.value
                  ? "bg-secondary text-on-secondary border-secondary"
                  : "bg-surface-container-high text-on-surface-variant border-white/10 hover:bg-surface-container-highest"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-4 py-3 rounded-lg bg-error-container/20 text-error text-sm flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">error</span>
          {error}
          <button onClick={fetchSessions} className="ml-auto text-xs underline cursor-pointer bg-transparent border-none text-error">
            Retry
          </button>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-on-surface-variant">
          <span className="material-symbols-outlined animate-spin mr-2">progress_activity</span>
          Loading review queue...
        </div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-20 text-on-surface-variant">
          <span className="material-symbols-outlined text-4xl mb-2 block">inbox</span>
          <p className="text-sm">No translations to review{langFilter ? ` for ${LANG_LABEL[langFilter]}` : ""}.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] uppercase tracking-widest text-on-surface-variant border-b border-white/5">
                <th className="pb-3 pr-4">Document</th>
                <th className="pb-3 pr-4">Language</th>
                <th className="pb-3 pr-4">Confidence</th>
                <th className="pb-3 pr-4">Corrections</th>
                <th className="pb-3 pr-4">Date</th>
                <th className="pb-3 pr-4">Status</th>
                <th className="pb-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.session_id}
                  className="border-b border-white/[0.03] hover:bg-surface-container-high/50 transition-colors"
                >
                  <td className="py-3.5 pr-4">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-secondary text-base">description</span>
                      <span className="text-sm font-medium text-on-surface truncate max-w-[200px]">
                        {s.original_filename
                          ?.replace(/\.[^.]+$/, "")
                          .replace(/_/g, " ") ?? s.session_id.slice(0, 8)}
                      </span>
                    </div>
                  </td>
                  <td className="py-3.5 pr-4">
                    <span className="text-xs text-on-surface-variant">
                      {LANG_LABEL[s.target_language] ?? s.target_language}
                    </span>
                  </td>
                  <td className="py-3.5 pr-4">
                    <ConfidenceLabel score={s.avg_confidence_score} />
                  </td>
                  <td className="py-3.5 pr-4">
                    <span className="text-sm text-on-surface">{s.llama_corrections_count}</span>
                  </td>
                  <td className="py-3.5 pr-4">
                    <span className="text-xs text-on-surface-variant">{formatDate(s.created_at)}</span>
                  </td>
                  <td className="py-3.5 pr-4">
                    <ReviewStatusBadge status={s.review_status} />
                  </td>
                  <td className="py-3.5">
                    <button
                      onClick={() => openDetail(s)}
                      className="text-xs text-secondary font-bold cursor-pointer bg-transparent border-none hover:underline transition-all"
                    >
                      Review &rarr;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && sessions.length > 0 && (
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-4 py-2 text-xs font-bold text-on-surface-variant bg-surface-container-high rounded-lg cursor-pointer border border-white/10 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-surface-container-highest transition-all"
          >
            Previous
          </button>
          <span className="text-xs text-on-surface-variant">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={sessions.length < 20}
            className="px-4 py-2 text-xs font-bold text-on-surface-variant bg-surface-container-high rounded-lg cursor-pointer border border-white/10 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-surface-container-highest transition-all"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
