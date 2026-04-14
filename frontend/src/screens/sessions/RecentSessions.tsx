/**
 * screens/sessions/RecentSessions.tsx
 *
 * Recent Sessions — renders INSIDE AppShell.
 * Card-based bento grid showing both document translations and real-time
 * interpretation sessions with search, type filtering, and load-more pagination.
 *
 * Fetches document sessions from documentsApi.list() and realtime sessions
 * from realtimeApi.history(), merges them, and filters client-side by type.
 * Each user only sees their own sessions (enforced by the backend via user_id).
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import {
  documentsApi,
  realtimeApi,
  type DocumentStatus,
  type RealtimeSessionSummary,
} from "@/services/api"
import useAuthStore from "@/store/authStore"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

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

// ── Unified session type ─────────────────────────────────────────────────────

interface UnifiedSession {
  id: string
  type: "document" | "realtime"
  status: string
  targetLanguage: string
  createdAt: string
  // Document-specific
  doc?: DocumentStatus
  // Realtime-specific
  rt?: RealtimeSessionSummary
}

function mergeToUnified(docs: DocumentStatus[], rts: RealtimeSessionSummary[]): UnifiedSession[] {
  const unified: UnifiedSession[] = []

  for (const d of docs) {
    unified.push({
      id: d.session_id,
      type: "document",
      status: d.status,
      targetLanguage: d.target_language,
      createdAt: d.created_at,
      doc: d,
    })
  }

  for (const r of rts) {
    unified.push({
      id: r.session_id,
      type: "realtime",
      status: r.status,
      targetLanguage: r.target_language,
      createdAt: r.created_at,
      rt: r,
    })
  }

  // Sort by most recent first
  unified.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
  return unified
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const isProcessing = status === "processing" || status === "pending" || status === "waiting"
  const isActive     = status === "active"
  const isSuccess    = status === "translated" || status === "completed" || status === "ended"

  const classes = isActive
    ? "bg-red-900/30 text-red-400"
    : isProcessing
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

function TypeBadge({ type }: { type: "document" | "realtime" }) {
  return (
    <span className={`px-2 py-0.5 rounded text-[9px] font-bold tracking-widest uppercase ${
      type === "realtime"
        ? "bg-indigo-900/30 text-indigo-400"
        : "bg-amber-900/20 text-amber-400"
    }`}>
      {type === "realtime" ? "Real-Time" : "Document"}
    </span>
  )
}

// ── Component ────────────────────────────────────────────────────────────────

export default function RecentSessions({ onNav }: Props) {
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)
  const setDocumentResult  = useAuthStore((s) => s.setDocumentResult)

  const [docItems, setDocItems]   = useState<DocumentStatus[]>([])
  const [rtItems, setRtItems]     = useState<RealtimeSessionSummary[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [search, setSearch_]      = useState("")
  const [typeFilter, setTypeFilter_] = useState<"all" | "document" | "realtime">("all")

  const setSearch = (v: string) => { setSearch_(v) }
  const setTypeFilter = (v: "all" | "document" | "realtime") => { setTypeFilter_(v) }

  // Fetch both document and realtime sessions in parallel
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([
      documentsApi.list(1, 100).catch(() => ({ items: [] as DocumentStatus[], total: 0, page: 1, page_size: 100 })),
      realtimeApi.history(1, 100).catch(() => ({ items: [] as RealtimeSessionSummary[], total: 0, page: 1, page_size: 100 })),
    ]).then(([docData, rtData]) => {
      if (cancelled) return
      setDocItems(docData.items)
      setRtItems(rtData.items)
      setLoading(false)
    }).catch(() => {
      if (cancelled) return
      setError("Failed to load sessions. Please try again.")
      setLoading(false)
    })

    return () => { cancelled = true }
  }, [])

  // ── Merge and filter ───────────────────────────────────────────────────────

  const allSessions = mergeToUnified(docItems, rtItems)
  const total = allSessions.length

  const filteredItems = allSessions.filter((row) => {
    // Type filter
    if (typeFilter === "document" && row.type !== "document") return false
    if (typeFilter === "realtime" && row.type !== "realtime") return false

    // Search
    if (search) {
      const langName = LANG_LABEL[row.targetLanguage] ?? row.targetLanguage
      const extra = row.rt?.partner_name ?? ""
      const searchable = `${langName} ${row.id} ${row.status} ${extra}`.toLowerCase()
      if (!searchable.includes(search.toLowerCase())) return false
    }

    return true
  })

  // ── Navigation handlers ────────────────────────────────────────────────────

  function handleViewDocSession(row: DocumentStatus) {
    setDocumentSession({ sessionId: row.session_id, targetLanguage: row.target_language })
    if (row.status === "translated" || row.status === "completed") {
      setDocumentResult(row)
    }
    onNav(SCREENS.DOC_PROCESSING)
  }

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
            placeholder="Search sessions by language, status, or name..."
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

      {/* Loading */}
      {loading && (
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

      {/* Empty — clean, no CTA (matches FormsLibrary pattern) */}
      {!loading && !error && filteredItems.length === 0 && (
        <div className="bg-surface-container-low rounded-xl p-12 text-center border border-white/5">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4 block">
            {search ? "search_off" : "folder_open"}
          </span>
          <p className="text-on-surface-variant">
            {search
              ? "No sessions match your search."
              : typeFilter === "realtime"
              ? "No real-time sessions yet."
              : typeFilter === "document"
              ? "No document translations yet."
              : "No sessions yet."}
          </p>
        </div>
      )}

      {/* ── Bento card grid ──────────────────────────────────────────── */}
      {filteredItems.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredItems.map((row) => {
            if (row.type === "document" && row.doc) {
              return <DocumentCard key={row.id} row={row.doc} onView={handleViewDocSession} onNav={onNav} />
            }
            if (row.type === "realtime" && row.rt) {
              return <RealtimeCard key={row.id} row={row.rt} />
            }
            return null
          })}
        </div>
      )}
    </div>
  )
}

// ── Document session card ────────────────────────────────────────────────────

function DocumentCard({
  row,
  onView,
  onNav,
}: {
  row: DocumentStatus
  onView: (r: DocumentStatus) => void
  onNav: (s: ScreenId) => void
}) {
  const isProcessing = row.status === "processing" || row.status === "pending"
  const isSuccess    = row.status === "translated" || row.status === "completed"
  const isFailed     = !isProcessing && !isSuccess

  return (
    <div className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all duration-300 group shadow-sm flex flex-col border border-white/5">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <div className="p-3 rounded-lg bg-primary-container text-amber-400">
            <span className="material-symbols-outlined text-2xl">description</span>
          </div>
          <TypeBadge type="document" />
        </div>
        <StatusBadge status={row.status} />
      </div>

      <h3 className="text-xl font-headline font-bold text-on-surface mb-1">
        {LANG_LABEL[row.target_language] ?? row.target_language} Translation
      </h3>

      <p className="text-on-surface-variant text-sm mb-6 flex items-center gap-2">
        <span className="material-symbols-outlined text-xs">language</span>
        EN → {LANG_CODE[row.target_language] ?? row.target_language.toUpperCase()}
      </p>

      <div className="mt-auto space-y-3">
        <div className="flex justify-between text-xs text-on-surface-variant border-t border-outline-variant/10 pt-4">
          <span>Date: {formatDate(row.created_at)}</span>
          <span>{timeAgo(row.created_at)}</span>
        </div>

        {isProcessing && (
          <button
            onClick={() => onView(row)}
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
            onClick={() => onView(row)}
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
}

// ── Realtime session card ────────────────────────────────────────────────────

function RealtimeCard({ row }: { row: RealtimeSessionSummary }) {
  const isActive = row.status === "active"
  const isEnded  = row.status === "ended"

  const durationLabel = row.duration_seconds != null
    ? `${Math.floor(row.duration_seconds / 60)}m ${Math.round(row.duration_seconds % 60)}s`
    : null

  return (
    <div className="bg-surface-container-low rounded-xl p-6 hover:bg-surface-container-high transition-all duration-300 group shadow-sm flex flex-col border border-white/5">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <div className="p-3 rounded-lg bg-indigo-900/30 text-indigo-400">
            <span className="material-symbols-outlined text-2xl">interpreter_mode</span>
          </div>
          <TypeBadge type="realtime" />
        </div>
        <StatusBadge status={row.status} />
      </div>

      <h3 className="text-xl font-headline font-bold text-on-surface mb-1">
        {LANG_LABEL[row.target_language] ?? row.target_language} Interpretation
      </h3>

      <p className="text-on-surface-variant text-sm mb-2 flex items-center gap-2">
        <span className="material-symbols-outlined text-xs">person</span>
        {row.partner_name ?? "Unknown participant"}
      </p>

      {row.court_division && (
        <p className="text-on-surface-variant text-xs mb-1 flex items-center gap-2">
          <span className="material-symbols-outlined text-xs">gavel</span>
          {row.court_division}{row.courtroom ? ` · ${row.courtroom}` : ""}
        </p>
      )}

      <div className="mt-auto space-y-3 pt-4">
        <div className="flex justify-between text-xs text-on-surface-variant border-t border-outline-variant/10 pt-4">
          <span>Date: {formatDate(row.created_at)}</span>
          <span>{timeAgo(row.created_at)}</span>
        </div>

        {/* Stats row */}
        {(isEnded || isActive) && (
          <div className="flex gap-4 text-xs text-on-surface-variant">
            {row.total_utterances > 0 && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">chat</span>
                {row.total_utterances} utterances
              </span>
            )}
            {durationLabel && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">schedule</span>
                {durationLabel}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
