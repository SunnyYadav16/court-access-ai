import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { documentsApi, type PipelineStep } from "@/services/api"
import useAuthStore from "@/store/authStore"

// ── Helpers ───────────────────────────────────────────────────────────────────

const FLAG: Record<string, string> = { es: "🇪🇸", pt: "🇧🇷" }
const LANG_LABEL: Record<string, string> = { es: "Spanish", pt: "Portuguese" }
const OTHER_LANG: Record<string, string> = { es: "pt", pt: "es" }

function formatSeconds(secs: number | null): string {
  if (secs == null) return "—"
  return secs >= 60 ? `${(secs / 60).toFixed(1)} min` : `${secs.toFixed(1)} s`
}

function minutesLeft(iso: string | null): string {
  if (!iso) return ""
  const diff = Math.round((new Date(iso).getTime() - Date.now()) / 60_000)
  return diff > 0 ? `${diff} min` : "expired"
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function DocResults({ onNav }: Props) {
  const documentSession    = useAuthStore((s) => s.documentSession)
  const documentResult     = useAuthStore((s) => s.documentResult)
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)
  const setDocumentResult  = useAuthStore((s) => s.setDocumentResult)

  const sessionId   = documentSession?.sessionId ?? null
  const targetLang  = documentResult?.target_language ?? documentSession?.targetLanguage ?? "es"
  const secondLang  = OTHER_LANG[targetLang] ?? (targetLang === "es" ? "pt" : "es")

  // ── OCR metadata from pipeline steps ────────────────────────────────────────
  const [ocrMeta, setOcrMeta] = useState<Record<string, unknown>>({})
  const [downloading, setDownloading] = useState(false)
  const [retranslating, setRetranslating] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) return
    documentsApi.steps(sessionId).then((steps: PipelineStep[]) => {
      const ocrStep = steps.find((s) => s.step_name === "ocr_printed_text")
      if (ocrStep?.metadata) setOcrMeta(ocrStep.metadata)
    }).catch(() => {/* non-critical — summary will show "—" */})
  }, [sessionId])

  // ── Download ─────────────────────────────────────────────────────────────────

  const handleDownload = async () => {
    if (!sessionId) return
    setDownloading(true)
    setActionError(null)
    try {
      // Fetch fresh status — signed_url may have been refreshed since we last polled
      const fresh = await documentsApi.status(sessionId)
      if (!fresh.signed_url) {
        setActionError("Download URL is not yet available. Please wait and try again.")
        return
      }
      window.open(fresh.signed_url, "_blank")
    } catch {
      setActionError("Could not fetch download link. Please try again.")
    } finally {
      setDownloading(false)
    }
  }

  // ── Retranslate ──────────────────────────────────────────────────────────────

  const handleRetranslate = async () => {
    if (!sessionId) return
    setRetranslating(true)
    setActionError(null)
    try {
      const resp = await documentsApi.retranslate(sessionId, secondLang)
      // Update store: keep same sessionId, switch current target language to secondLang,
      // clear old result so DocProcessing polls fresh
      setDocumentSession({ sessionId: resp.session_id, targetLanguage: resp.target_language })
      setDocumentResult(null)
      onNav(SCREENS.DOC_PROCESSING)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not start re-translation. Please try again."
      setActionError(msg)
      setRetranslating(false)
    }
  }

  // ── Derived summary rows ─────────────────────────────────────────────────────

  const avgConf    = documentResult?.avg_confidence_score
  const corrections = documentResult?.llama_corrections_count ?? 0
  const procTime   = documentResult?.processing_time_seconds ?? null
  const expiresAt  = documentResult?.signed_url_expires_at ?? null
  const totalRegions = (ocrMeta.total_regions as number | undefined) ?? null
  const translatable = (ocrMeta.translatable as number | undefined) ?? null

  const summaryRows: [string, string][] = [
    ["Text regions", totalRegions != null ? String(totalRegions) : "—"],
    ["Translatable", translatable != null ? String(translatable) : "—"],
    ["Avg confidence", avgConf != null ? avgConf.toFixed(3) : "—"],
    ["Llama corrections", String(corrections)],
    ["Processing time", formatSeconds(procTime)],
  ]

  // ── Guard — navigated here without a result ──────────────────────────────────

  if (!sessionId || !documentResult) {
    return (
      <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
        <TopBar onNav={onNav} />
        <div className="max-w-xl mx-auto px-5 py-8">
          <Card>
            <CardContent className="p-6 text-center">
              <p className="text-sm mb-4" style={{ color: "#8494A7" }}>
                No completed translation found.
              </p>
              <div className="flex justify-center gap-3">
                <Button
                  size="sm"
                  className="cursor-pointer"
                  style={{ background: "#0B1D3A" }}
                  onClick={() => onNav(SCREENS.DOC_HISTORY)}
                >
                  📜 View Document History
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="cursor-pointer"
                  onClick={() => onNav(SCREENS.DOC_UPLOAD)}
                >
                  📄 Upload New Document
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const expiresLabel = expiresAt ? minutesLeft(expiresAt) : null

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-xl mx-auto px-5 py-8">

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <span className="text-3xl">✅</span>
          <div>
            <h1
              className="text-xl font-bold m-0"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
            >
              Translation Complete
            </h1>
            <p className="text-xs m-0" style={{ color: "#8494A7" }}>
              Session {sessionId.slice(0, 8)}…
              {procTime != null && ` · Completed in ${formatSeconds(procTime)}`}
            </p>
          </div>
        </div>

        {/* Action error banner */}
        {actionError && (
          <div
            className="rounded-md px-4 py-3 text-sm flex items-start gap-2 mb-4"
            style={{ background: "#FEF2F2", color: "#B91C1C", border: "1px solid #FECACA" }}
          >
            <span className="flex-shrink-0">⚠️</span>
            <span>{actionError}</span>
          </div>
        )}

        {/* Downloads */}
        <Card className="mb-3">
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Download Translations
            </div>
            <div className="flex gap-3">

              {/* Primary language — completed */}
              <div
                className="flex-1 rounded-lg p-4 text-center"
                style={{ border: "1.5px solid #0B1D3A" }}
              >
                <div className="text-3xl mb-1">{FLAG[targetLang] ?? "🌐"}</div>
                <div className="text-sm font-semibold mb-0.5" style={{ color: "#1A2332" }}>
                  {LANG_LABEL[targetLang] ?? targetLang}
                </div>
                {avgConf != null && (
                  <div className="text-[11px] mb-3" style={{ color: "#8494A7" }}>
                    Avg confidence: {avgConf.toFixed(3)}
                  </div>
                )}
                <Button
                  id="download-pdf-btn"
                  size="sm"
                  className="w-full cursor-pointer"
                  style={{ background: downloading ? "#4A5568" : "#0B1D3A" }}
                  disabled={downloading}
                  onClick={handleDownload}
                >
                  {downloading ? "Fetching…" : "⬇ Download PDF"}
                </Button>
              </div>

              {/* Second language — trigger retranslate */}
              <div
                className="flex-1 rounded-lg p-4 text-center"
                style={{ border: "1.5px solid #E2E6EC" }}
              >
                <div className="text-3xl mb-1">{FLAG[secondLang] ?? "🌐"}</div>
                <div className="text-sm font-semibold mb-0.5" style={{ color: "#1A2332" }}>
                  {LANG_LABEL[secondLang] ?? secondLang}
                </div>
                <div className="text-[11px] mb-3" style={{ color: "#8494A7" }}>
                  Not yet translated
                </div>
                <Button
                  id="retranslate-btn"
                  size="sm"
                  variant="outline"
                  className="w-full cursor-pointer"
                  disabled={retranslating}
                  onClick={handleRetranslate}
                >
                  {retranslating ? "Starting…" : "🔄 Translate Now"}
                </Button>
              </div>
            </div>

            {expiresLabel && (
              <p className="text-[11px] text-center mt-3" style={{ color: "#8494A7" }}>
                Signed URL expires in {expiresLabel} · Original file auto-deletes in 24 hours
              </p>
            )}
          </CardContent>
        </Card>

        {/* Summary */}
        <Card className="mb-3">
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Processing Summary
            </div>
            <div className="grid grid-cols-2 gap-2">
              {summaryRows.map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs py-1">
                  <span style={{ color: "#8494A7" }}>{k}</span>
                  <span className="font-medium" style={{ color: "#1A2332" }}>{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Legal note — only shown when Llama made corrections */}
        {corrections > 0 && (
          <Card className="mb-5" style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}>
            <CardContent className="p-4">
              <p className="text-xs leading-relaxed m-0" style={{ color: "#1e40af" }}>
                <strong>⚡ Legal Review Note:</strong> Llama 4 made {corrections} correction
                {corrections !== 1 ? "s" : ""} to legal terminology during translation.
              </p>
            </CardContent>
          </Card>
        )}

        <div className="flex gap-3">
          <Button
            variant="outline"
            className="cursor-pointer"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)}
          >
            📄 Upload Another
          </Button>
          <Button
            variant="outline"
            className="cursor-pointer"
            onClick={() => onNav(SCREENS.HOME_PUBLIC)}
          >
            🏠 Home
          </Button>
        </div>

      </div>
      <ScreenLabel name="DOCUMENT RESULTS — DOWNLOAD" />
    </div>
  )
}
