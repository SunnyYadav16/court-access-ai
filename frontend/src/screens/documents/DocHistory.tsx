import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { documentsApi, type DocumentStatus } from "@/services/api"
import useAuthStore from "@/store/authStore"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const PAGE_SIZE = 20

const FLAG: Record<string, string> = { es: "🇪🇸", pt: "🇧🇷" }
const LANG_LABEL: Record<string, string> = { es: "Spanish", pt: "Portuguese" }

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diffMs / 60_000)
  if (mins < 1)  return "just now"
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)  return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function StatusBadge({ status }: { status: string }) {
  const isProcessing = status === "processing" || status === "pending"
  const isSuccess    = status === "translated" || status === "completed"
  const style = isProcessing
    ? { background: "#FEF3C7", color: "#d97706" }
    : isSuccess
    ? { background: "#DCFCE7", color: "#16a34a" }
    : { background: "#FEE2E2", color: "#dc2626" }
  return (
    <span className="text-[10px] font-semibold px-2 py-0.5 rounded uppercase" style={style}>
      {status}
    </span>
  )
}

export default function DocHistory({ onNav }: Props) {
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)
  const setDocumentResult  = useAuthStore((s) => s.setDocumentResult)

  const [items, setItems]   = useState<DocumentStatus[]>([])
  const [total, setTotal]   = useState(0)
  const [page, setPage]     = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState<string | null>(null)

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

  function handleViewProgress(row: DocumentStatus) {
    setDocumentSession({ sessionId: row.session_id, targetLanguage: row.target_language })
    onNav(SCREENS.DOC_PROCESSING)
  }

  function handleViewResults(row: DocumentStatus) {
    setDocumentSession({ sessionId: row.session_id, targetLanguage: row.target_language })
    setDocumentResult(row)
    onNav(SCREENS.DOC_RESULTS)
  }

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-2xl mx-auto px-5 py-8">
        <h1
          className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          My Translations
        </h1>
        <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
          {total} translation{total !== 1 ? "s" : ""} · tap a row to continue or download
        </p>

        {loading ? (
          <div className="text-sm text-center py-12" style={{ color: "#8494A7" }}>
            Loading history…
          </div>
        ) : error ? (
          <div className="text-sm text-center py-12" style={{ color: "#dc2626" }}>
            {error}
          </div>
        ) : items.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center">
              <p className="text-sm mb-4" style={{ color: "#8494A7" }}>
                No translations yet.
              </p>
              <Button
                size="sm"
                className="cursor-pointer"
                style={{ background: "#0B1D3A" }}
                onClick={() => onNav(SCREENS.DOC_UPLOAD)}
              >
                📄 Upload a Document
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="flex flex-col gap-2">
            {items.map((row) => {
              const isProcessing = row.status === "processing" || row.status === "pending"
              const isSuccess    = row.status === "translated" || row.status === "completed"
              const isFailed     = !isProcessing && !isSuccess

              return (
                <Card key={row.session_id} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-4 flex items-center justify-between gap-3">

                    {/* Left — flag + info */}
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-2xl flex-shrink-0">
                        {FLAG[row.target_language] ?? "🌐"}
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium" style={{ color: "#1A2332" }}>
                            {LANG_LABEL[row.target_language] ?? row.target_language}
                          </span>
                          <StatusBadge status={row.status} />
                        </div>
                        <div className="text-[11px] mt-0.5" style={{ color: "#8494A7" }}>
                          Translating to {LANG_LABEL[row.target_language] ?? row.target_language}
                          {" · "}Started {timeAgo(row.created_at)}
                          {" · "}{formatDate(row.created_at)}
                        </div>
                      </div>
                    </div>

                    {/* Right — action */}
                    <div className="flex-shrink-0">
                      {isProcessing && (
                        <Button
                          size="sm"
                          className="cursor-pointer"
                          style={{ background: "#0B1D3A" }}
                          onClick={() => handleViewProgress(row)}
                        >
                          View Progress
                        </Button>
                      )}
                      {isSuccess && row.signed_url && (
                        <Button
                          size="sm"
                          className="cursor-pointer"
                          style={{ background: "#0B1D3A" }}
                          onClick={() => window.open(row.signed_url!, "_blank")}
                        >
                          ⬇ Download
                        </Button>
                      )}
                      {isSuccess && !row.signed_url && (
                        <Button
                          size="sm"
                          className="cursor-pointer"
                          style={{ background: "#0B1D3A" }}
                          onClick={() => handleViewResults(row)}
                        >
                          View Results
                        </Button>
                      )}
                      {isFailed && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="cursor-pointer"
                          onClick={() => onNav(SCREENS.DOC_UPLOAD)}
                        >
                          Try Again
                        </Button>
                      )}
                    </div>

                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between mt-6">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="text-xs font-medium px-3 py-1.5 rounded"
              style={{
                border: "1.5px solid #E2E6EC",
                color: page === 1 ? "#8494A7" : "#1A2332",
                background: "#fff",
                cursor: page === 1 ? "default" : "pointer",
                opacity: page === 1 ? 0.5 : 1,
              }}
            >
              ← Previous
            </button>
            <span className="text-xs" style={{ color: "#8494A7" }}>
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="text-xs font-medium px-3 py-1.5 rounded"
              style={{
                border: "1.5px solid #E2E6EC",
                color: page === totalPages ? "#8494A7" : "#1A2332",
                background: "#fff",
                cursor: page === totalPages ? "default" : "pointer",
                opacity: page === totalPages ? 0.5 : 1,
              }}
            >
              Next →
            </button>
          </div>
        )}

        <div className="mt-6">
          <Button
            variant="outline"
            className="cursor-pointer"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)}
          >
            📄 Upload New Document
          </Button>
        </div>
      </div>
      <ScreenLabel name="DOCUMENT HISTORY" />
    </div>
  )
}
