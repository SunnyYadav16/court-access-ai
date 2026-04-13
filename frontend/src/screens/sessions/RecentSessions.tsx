/**
 * screens/sessions/RecentSessions.tsx
 *
 * Recent Sessions — renders INSIDE AppShell.
 * Card-based bento grid showing both document translations and real-time
 * interpretation sessions with search, type filtering, and load-more pagination.
 *
 * Currently fetches document sessions from documentsApi.list().
 * Real-time session history will be integrated when the list API is available.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { documentsApi, type DocumentStatus } from "@/services/api"
import useAuthStore from "@/store/authStore"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const PAGE_SIZE = 20

const LANG_LABEL: Record<string, string> = { es: "Spanish", pt: "Portuguese" }
const LANG_CODE: Record<string, string> = { es: "ES", pt: "PT" }

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60_000)
  if (mins < 1)  return "just now"
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)  return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

// ── Status badge ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const isProcessing = status === "processing" || status === "pending"
  const isSuccess    = status === "translated" || status === "completed"

  const classes = isProcessing
    ? "bg-secondary-container/20 text-secondary"
    : isSuccess
    ? "bg-emerald-900/30 text-emerald-400"
    : "bg-red-900/30 text-red-400"

  return (
    <span className={`px-3 py-1 rounded-full text-[10px] font-bold tracking-widest uppercase ${classes}`}>
      {status}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────

export default function RecentSessions({ onNav }: Props) {
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)
  const setDocumentResult  = useAuthStore((s) => s.setDocumentResult)

  const [items, setItems]       = useState<DocumentStatus[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [search, setSearch_]     = useState("")
  const [typeFilter, setTypeFilter_] = useState<"all" | "document" | "realtime">("all")

  // Reset pagination when filters change so accumulated items don't go stale
  const setSearch = (v: string) => { setSearch_(v); setPage(1) }
  const setTypeFilter = (v: "all" | "document" | "realtime") => { setTypeFilter_(v); setPage(1) }
  const [hasMore, setHasMore]   = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    documentsApi
      .list(page, PAGE_SIZE)
      .then((data) => {
        if (cancelled) return
        setItems((prev) => (page === 1 ? data.items : [...prev, ...data.items]))
        setTotal(data.total)
        setHasMore(data.items.length === PAGE_SIZE)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Failed to load sessions. Please try again.")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [page])

  // ── Navigation handlers ─────────────────────────────────────────────────

  function handleViewSession(row: DocumentStatus) {
    setDocumentSession({ sessionId: row.session_id, targetLanguage: row.target_language })

    if (row.status === "translated" || row.status === "completed") {
      setDocumentResult(row)
    }

    onNav(SCREENS.DOC_PROCESSING)
  }

  // ── Client-side filtering ───────────────────────────────────────────────

  const filteredItems = items.filter((row) => {
    if (typeFilter === "realtime") return false // No realtime sessions in document list
    const langName = LANG_LABEL[row.target_language] ?? row.target_language
    const searchable = `${langName} ${row.session_id} ${row.status}`.toLowerCase()
    return search === "" || searchable.includes(search.toLowerCase())
  })

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl mx-auto">

      {/* Header */}
      <div className="mb-10">
        <h1 className="text-4xl font-headline font-bold text-on-surface mb-2 tracking-tight flex items-baseline gap-3">
          Recent Sessions
          {total > 0 && (
            <span className="text-base font-label font-medium text-on-surface-variant tracking-normal">
              {total} session{total !== 1 ? "s" : ""}
            </span>
          )}
        </h1>
        <p className="text-on-surface-variant max-w-2xl text-lg leading-relaxed">
          Review and manage your past document translations and real-time interpretation sessions.
        </p>
      </div>

      {/* Filters row */}
      <div className="flex flex-col md:flex-row items-center gap-4 mb-8">
        <div className="relative flex-1 w-full">
          <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-outline">
            search
          </span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-surface-container-high border-none rounded-lg pl-12 pr-4 py-3 text-on-surface placeholder:text-outline focus:ring-2 focus:ring-primary-container transition-all"
            placeholder="Search sessions by title or case number..."
          />
        </div>
        <div className="relative w-full md:w-64">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as "all" | "document" | "realtime")}
            className="w-full bg-surface-container-high border-none rounded-lg px-4 py-3 text-on-surface appearance-none focus:ring-2 focus:ring-primary-container cursor-pointer"
          >
            <option value="all">Session Type: All</option>
            <option value="document">Document</option>
            <option value="realtime">Real-Time</option>
          </select>
          <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-outline">
            expand_more
          </span>
        </div>
      </div>

      {/* Loading (initial load only) */}
      {loading && items.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20">
          <span className="material-symbols-outlined text-4xl text-secondary animate-spin mb-4">autorenew</span>
          <p className="text-on-surface-variant text-sm">Loading sessions…</p>
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="bg-error-container/20 border border-error/30 rounded-xl p-8 text-center">
          <span className="material-symbols-outlined text-error text-4xl mb-3 block">cloud_off</span>
          <p className="text-error text-sm">{error}</p>
        </div>
      )}

      {/* Empty */}
      {!loading && !error && filteredItems.length === 0 && (
        <div className="bg-surface-container-low rounded-xl p-12 text-center border border-white/5">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4 block">
            folder_open
          </span>
          <p className="text-on-surface-variant mb-6">
            {typeFilter === "realtime"
              ? "No real-time sessions yet."
              : search
              ? "No sessions match your search."
              : "No sessions yet."}
          </p>
          <button
            className="px-6 py-3 bg-[#FFD700] text-[#0D1B2A] rounded-lg font-bold text-sm hover:scale-105 transition-transform active:scale-95 border-none cursor-pointer flex items-center gap-2 mx-auto"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)}
          >
            <span className="material-symbols-outlined text-lg">upload_file</span>
            Upload a Document
          </button>
        </div>
      )}

      {/* ── Bento card grid ──────────────────────────────────────────── */}
      {filteredItems.length > 0 && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {filteredItems.map((row) => {
              const isProcessing = row.status === "processing" || row.status === "pending"
              const isSuccess    = row.status === "translated" || row.status === "completed"
              const isFailed     = !isProcessing && !isSuccess

              return (
                <div
                  key={row.session_id}
                  className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all duration-300 group shadow-sm flex flex-col border border-white/5"
                >
                  {/* Top: icon + status badge */}
                  <div className="flex justify-between items-start mb-4">
                    <div className="p-3 rounded-lg bg-primary-container text-amber-400">
                      <span className="material-symbols-outlined text-2xl">description</span>
                    </div>
                    <StatusBadge status={row.status} />
                  </div>

                  {/* Title */}
                  <h3 className="text-xl font-headline font-bold text-on-surface mb-1">
                    {LANG_LABEL[row.target_language] ?? row.target_language} Translation
                  </h3>

                  {/* Language direction */}
                  <p className="text-on-surface-variant text-sm mb-6 flex items-center gap-2">
                    <span className="material-symbols-outlined text-xs">language</span>
                    EN → {LANG_CODE[row.target_language] ?? row.target_language.toUpperCase()}
                  </p>

                  {/* Meta row */}
                  <div className="mt-auto space-y-3">
                    <div className="flex justify-between text-xs text-on-surface-variant border-t border-outline-variant/10 pt-4">
                      <span>Date: {formatDate(row.created_at)}</span>
                      <span>{timeAgo(row.created_at)}</span>
                    </div>

                    {/* Action button */}
                    {isProcessing && (
                      <button
                        onClick={() => handleViewSession(row)}
                        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-secondary-container/20 text-secondary hover:bg-secondary-container/40 transition-colors font-medium text-sm border-none cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-sm animate-spin">autorenew</span>
                        View Progress
                      </button>
                    )}

                    {isSuccess && row.signed_url && (
                      <button
                        onClick={() => window.open(row.signed_url!, "_blank")}
                        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-secondary/20 text-secondary hover:bg-secondary/10 transition-colors font-medium text-sm bg-transparent cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-sm">download</span>
                        Download
                      </button>
                    )}

                    {isSuccess && !row.signed_url && (
                      <button
                        onClick={() => handleViewSession(row)}
                        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-secondary/20 text-secondary hover:bg-secondary/10 transition-colors font-medium text-sm bg-transparent cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-sm">visibility</span>
                        View Results
                      </button>
                    )}

                    {isFailed && (
                      <button
                        onClick={() => onNav(SCREENS.DOC_UPLOAD)}
                        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-error-container/20 text-error hover:bg-error-container/40 transition-colors font-medium text-sm border-none cursor-pointer"
                      >
                        <span className="material-symbols-outlined text-sm">refresh</span>
                        Retry Translation
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Load more */}
          {hasMore && (
            <div className="mt-12 flex justify-center">
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={loading}
                className="flex items-center gap-2 px-6 py-3 rounded-lg bg-surface-container-high text-on-surface hover:bg-surface-bright transition-all text-sm font-semibold tracking-wide uppercase border-none cursor-pointer disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <span className="material-symbols-outlined text-lg animate-spin">autorenew</span>
                    Loading…
                  </>
                ) : (
                  <>
                    Load Older Sessions
                    <span className="material-symbols-outlined text-lg">keyboard_arrow_down</span>
                  </>
                )}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
