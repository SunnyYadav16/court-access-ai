/**
 * screens/documents/DocHistory.tsx
 *
 * Translation History — renders INSIDE AppShell.
 * Table-based layout showing all document translation sessions
 * with status badges, language info, and pagination.
 *
 * Preserved logic: documentsApi.list() with pagination, document session
 * state management, navigation to processing/results screens.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { documentsApi, type DocumentStatus } from "@/services/api"
import useAuthStore from "@/store/authStore"

interface Props { onNav: (s: ScreenId) => void }

const PAGE_SIZE = 20

const LANG_LABEL: Record<string, string> = { es: "Spanish", pt: "Portuguese" }
const LANG_CODE: Record<string, string> = { es: "ES", pt: "PT" }

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

// ── Status badges matching the design system ──────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-secondary-container/20 text-secondary-fixed border border-secondary/20">
        <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse" />
        In Progress
      </span>
    )
  }

  if (status === "translated" || status === "completed") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-tertiary-container/30 text-tertiary-fixed border border-tertiary/20">
        <span
          className="material-symbols-outlined text-[12px]"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          check_circle
        </span>
        Translated
      </span>
    )
  }

  if (status === "pending") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-surface-container-highest text-on-surface-variant border border-outline-variant/30">
        <span className="material-symbols-outlined text-[12px]">schedule</span>
        Pending Review
      </span>
    )
  }

  // error / rejected
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-red-900/30 text-red-400 border border-red-500/20">
      <span className="material-symbols-outlined text-[12px]">error</span>
      {status === "rejected" ? "Rejected" : "Failed"}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────

export default function DocHistory({ onNav }: Props) {
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)
  const setDocumentResult  = useAuthStore((s) => s.setDocumentResult)

  const [items, setItems]     = useState<DocumentStatus[]>([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    documentsApi
      .list(page, PAGE_SIZE)
      .then((data) => {
        if (cancelled) return
        setItems(data.items)
        setTotal(data.total)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Failed to load history. Please try again.")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [page])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  function handleRowClick(row: DocumentStatus) {
    setDocumentSession({ sessionId: row.session_id, targetLanguage: row.target_language })

    if (row.status === "translated" || row.status === "completed") {
      setDocumentResult(row)
    }

    onNav(SCREENS.DOC_PROCESSING)
  }

  return (
    <div className="px-6 lg:px-10 py-8 max-w-7xl mx-auto">

      {/* Header */}
      <section className="mb-10">
        <h1 className="font-headline text-4xl text-on-surface mb-2">Translation History</h1>
        <p className="text-on-surface-variant max-w-2xl">
          A record of all your legal document translations processed by Court Access AI.
        </p>
      </section>

      {/* Loading state */}
      {loading && (
        <div className="flex flex-col items-center justify-center py-20">
          <span className="material-symbols-outlined text-4xl text-secondary animate-spin mb-4">autorenew</span>
          <p className="text-on-surface-variant text-sm">Loading history…</p>
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="bg-error-container/20 border border-error/30 rounded-xl p-8 text-center">
          <span className="material-symbols-outlined text-error text-4xl mb-3 block">cloud_off</span>
          <p className="text-error text-sm">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && items.length === 0 && (
        <div className="bg-surface-container-low rounded-xl p-12 text-center border border-white/5">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4 block">
            folder_open
          </span>
          <p className="text-on-surface-variant mb-6">No translations yet.</p>
          <button
            className="px-6 py-3 bg-[#FFD700] text-[#0D1B2A] rounded-lg font-bold text-sm hover:scale-105 transition-transform active:scale-95 border-none cursor-pointer flex items-center gap-2 mx-auto"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)}
          >
            <span className="material-symbols-outlined text-lg">upload_file</span>
            Upload a Document
          </button>
        </div>
      )}

      {/* Translation history table */}
      {!loading && !error && items.length > 0 && (
        <section className="bg-surface-container-low rounded-xl overflow-hidden border border-white/5 shadow-2xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container-high border-b border-white/5">
                  <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
                    Document Name
                  </th>
                  <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
                    Target Language
                  </th>
                  <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
                    Processing Status
                  </th>
                  <th className="px-6 py-4 text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
                    Date Initiated
                  </th>
                  <th className="px-6 py-4" />
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.map((row) => (
                  <tr
                    key={row.session_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleRowClick(row)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleRowClick(row) } }}
                    className="hover:bg-primary/5 cursor-pointer transition-colors group"
                  >
                    <td className="px-6 py-5">
                      <div className="flex items-center gap-3">
                        <span className="material-symbols-outlined text-secondary-fixed">description</span>
                        <div>
                          <p className="text-sm font-medium text-on-surface">
                            {LANG_LABEL[row.target_language] ?? row.target_language} Translation
                          </p>
                          <p className="text-[10px] text-on-surface-variant uppercase tracking-tighter">
                            Session #{row.session_id.slice(0, 8).toUpperCase()}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-primary text-sm">translate</span>
                        <span className="text-sm">
                          {LANG_LABEL[row.target_language] ?? row.target_language} ({LANG_CODE[row.target_language] ?? row.target_language.toUpperCase()})
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-6 py-5 text-sm text-on-surface-variant">
                      {formatDateTime(row.created_at)}
                    </td>
                    <td className="px-6 py-5 text-right">
                      <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary transition-colors">
                        arrow_forward_ios
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination footer */}
          <div className="px-6 py-4 bg-surface-container-high/50 flex justify-between items-center text-[11px] text-on-surface-variant font-medium">
            <p>Showing {items.length} of {total} document translation{total !== 1 ? "s" : ""}</p>
            <div className="flex gap-4">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="hover:text-on-surface transition-colors flex items-center gap-1 disabled:opacity-50 bg-transparent border-none text-on-surface-variant cursor-pointer disabled:cursor-default"
              >
                <span className="material-symbols-outlined text-sm">chevron_left</span>
                Previous
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="hover:text-on-surface transition-colors flex items-center gap-1 disabled:opacity-50 bg-transparent border-none text-on-surface-variant cursor-pointer disabled:cursor-default"
              >
                Next
                <span className="material-symbols-outlined text-sm">chevron_right</span>
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
