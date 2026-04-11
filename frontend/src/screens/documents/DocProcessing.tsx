import { useEffect, useRef, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { documentsApi, type PipelineStep, type DocumentStatus } from "@/services/api"
import useAuthStore from "@/store/authStore"

// ── Step label map (DAG step_name → display name) ─────────────────────────────

const STEP_LABELS: Record<string, string> = {
  validate_upload:   "Validating file",
  classify_document: "Classifying document",
  ocr_printed_text:  "Extracting & OCR text",
  translate:         "Translating",
  legal_review:      "Legal term review",
  reconstruct_pdf:   "Rebuilding PDF",
  upload_to_gcs:     "Uploading result",
  finalize:          "Finalizing",
  log_summary:       "Complete",
}

// Canonical order — drives progress bar and "pending" rows
const STEP_ORDER = [
  "validate_upload",
  "classify_document",
  "ocr_printed_text",
  "translate",
  "legal_review",
  "reconstruct_pdf",
  "upload_to_gcs",
  "finalize",
  "log_summary",
]

const TERMINAL_STATUSES = ["translated", "completed", "error", "failed", "rejected"]

// ── Per-step detail formatter ──────────────────────────────────────────────────
// DAG tasks write internal diagnostic strings (raw GCS URIs, model names, etc.)
// into step.detail. This function converts them to user-facing copy.

function formatDetail(stepName: string, detail: string): string {
  if (!detail) return ""

  switch (stepName) {
    case "validate_upload":
      return detail.replace(/^PDF validated/, "Valid PDF")

    case "classify_document":
      if (detail.startsWith("LEGAL")) {
        const m = detail.match(/confidence=([\d.]+)/)
        const pct = m ? ` · ${Math.round(parseFloat(m[1]) * 100)}% confidence` : ""
        return `Legal document confirmed${pct}`
      }
      if (/rejected|non.legal/i.test(detail)) return "Not recognised as a legal document"
      return detail.replace(/^.*?·\s*/, "").slice(0, 80)

    case "ocr_printed_text":
      // "PaddleOCR: 27 regions · 26 translatable · avg 0.99 conf"
      return detail.replace(/^PaddleOCR:\s*/, "").replace("avg ", "avg conf ")

    case "translate":
      // "NLLB-200: 2/26 regions changed in 0.3s"
      return detail.replace(/^NLLB-200:\s*/, "")

    case "legal_review":
      // "Llama: 3 correction(s) on 26 spans in 7.3s"
      return detail.replace(/^Llama:\s*/, "")

    case "reconstruct_pdf":
      // "PDF rebuilt · 0.21 MB" — already clean
      return detail

    case "upload_to_gcs":
      if (detail.startsWith("Uploading to gs://")) return "Uploading translated PDF…"
      if (detail.startsWith("Uploaded · signed")) return "Upload complete · Download link ready"
      if (detail.startsWith("Uploaded · download link unavailable")) return "Upload complete · Download link unavailable"
      return detail.replace(/gs:\/\/[^\s]+/g, "")

    case "finalize":
      return "Saving final results"

    case "log_summary":
      return detail.replace("Pipeline complete — ", "").replace(" translation ready", " ready")

    default:
      return detail.replace(/gs:\/\/[^\s]+/g, "[GCS path]").slice(0, 80)
  }
}

// ── Terminal error formatter ────────────────────────────────────────────────────
// Converts raw DB error_message strings to user-friendly copy.

function friendlyError(raw: string | null): string {
  if (!raw) return "Translation failed. Please try again."
  if (/validate_upload|invalid|corrupt/i.test(raw)) return "The file could not be processed. Please check it and try again."
  if (/classify|non.legal|rejected/i.test(raw)) return "This document was not recognised as a legal filing and cannot be translated."
  if (/upload_to_gcs|signed|gcs/i.test(raw)) return "Translation completed but the download link could not be generated. Please try again."
  if (/ocr/i.test(raw)) return "Text extraction failed. The document may be scanned at too low a resolution."
  if (/translate|nllb/i.test(raw)) return "Translation service unavailable. Please try again in a few minutes."
  return "Translation failed. Please try uploading again."
}

// ── Status icon ────────────────────────────────────────────────────────────────

function stepIcon(status: string | undefined) {
  switch (status) {
    case "success":  return "✅"
    case "running":  return "⏳"
    case "failed":   return "❌"
    case "skipped":  return "—"
    default:         return "○"
  }
}

function stepLabelStyle(status: string | undefined): React.CSSProperties {
  switch (status) {
    case "running": return { fontWeight: 600, color: "#1A2332" }
    case "failed":  return { fontWeight: 500, color: "#B91C1C" }
    case "skipped": return { color: "#8494A7" }
    case undefined: return { color: "#8494A7" }
    default:        return { color: "#1A2332" }
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function DocProcessing({ onNav }: Props) {
  const documentSession  = useAuthStore((s) => s.documentSession)
  const setDocumentResult = useAuthStore((s) => s.setDocumentResult)

  const sessionId    = documentSession?.sessionId    ?? null
  const targetLang   = documentSession?.targetLanguage ?? "es"
  const langLabel    = targetLang === "es" ? "Spanish" : "Portuguese"

  // ── Local state ─────────────────────────────────────────────────────────────

  const [steps, setSteps]           = useState<PipelineStep[]>([])
  const [overallStatus, setOverallStatus] = useState<string>("processing")
  const [terminalError, setTerminalError] = useState<string | null>(null)
  const [pollError, setPollError]   = useState<string | null>(null)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Polling ─────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!sessionId) return

    const poll = async () => {
      try {
        const [fetchedSteps, statusResp] = await Promise.all([
          documentsApi.steps(sessionId),
          documentsApi.status(sessionId),
        ])

        setSteps(fetchedSteps)
        setOverallStatus(statusResp.status)
        setPollError(null)

        if (TERMINAL_STATUSES.includes(statusResp.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current)

          if (statusResp.status === "translated" || statusResp.status === "completed") {
            setDocumentResult(statusResp as DocumentStatus)
            onNav(SCREENS.DOC_RESULTS)
          } else {
            // error / failed / rejected
            setTerminalError(friendlyError(statusResp.error_message ?? null))
          }
        }
      } catch {
        setPollError("Could not reach the server. Retrying…")
      }
    }

    poll()
    intervalRef.current = setInterval(poll, 2500)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Progress ─────────────────────────────────────────────────────────────────

  const stepMap = new Map(steps.map((s) => [s.step_name, s]))
  const successCount = steps.filter((s) => s.status === "success").length
  const progressPct  = Math.round((successCount / STEP_ORDER.length) * 100)

  // ── Render ───────────────────────────────────────────────────────────────────

  // Translate step label gets the language injected
  function resolveLabel(stepName: string) {
    if (stepName === "translate") return `Translating to ${langLabel}`
    return STEP_LABELS[stepName] ?? stepName
  }

  if (!sessionId) {
    return (
      <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
        <TopBar onNav={onNav} />
        <div className="max-w-lg mx-auto px-5 py-8">
          <Card>
            <CardContent className="p-6 text-center">
              <p className="text-sm mb-4" style={{ color: "#8494A7" }}>
                No active upload session.
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

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">

        <h1
          className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          Translating Document
        </h1>
        <p className="text-xs mb-6" style={{ color: "#8494A7" }}>
          Session {sessionId.slice(0, 8)}… · {langLabel}
        </p>

        {/* Terminal error card */}
        {terminalError && (
          <Card className="mb-4" style={{ border: "1px solid #FECACA", background: "#FEF2F2" }}>
            <CardContent className="p-4">
              <div className="flex items-start gap-2">
                <span className="text-xl flex-shrink-0">❌</span>
                <div>
                  <p className="text-sm font-semibold mb-1" style={{ color: "#B91C1C" }}>
                    Translation Failed
                  </p>
                  <p className="text-xs leading-relaxed" style={{ color: "#7F1D1D" }}>
                    {terminalError}
                  </p>
                </div>
              </div>
              <Button
                size="sm"
                className="mt-3 cursor-pointer"
                style={{ background: "#0B1D3A" }}
                onClick={() => onNav(SCREENS.DOC_UPLOAD)}
              >
                ← Try Again
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Poll error (transient network blip) */}
        {pollError && !terminalError && (
          <div
            className="rounded-md px-3 py-2 text-xs mb-4 flex items-center gap-2"
            style={{ background: "#FEF9C3", color: "#713F12", border: "1px solid #FEF08A" }}
          >
            <span>⚠️</span> {pollError}
          </div>
        )}

        <Card>
          <CardContent className="p-6">

            {/* Progress bar */}
            <div className="h-1.5 rounded-full mb-1 overflow-hidden" style={{ background: "#E5E7EB" }}>
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${progressPct}%`,
                  background: "linear-gradient(90deg, #0B1D3A, #C8963E)",
                }}
              />
            </div>
            <div className="text-right text-[10px] mb-5" style={{ color: "#8494A7" }}>
              {progressPct}% · {successCount}/{STEP_ORDER.length} steps
            </div>

            {/* Step list */}
            <div className="flex flex-col">
              {STEP_ORDER.map((stepName, i) => {
                const step          = stepMap.get(stepName)
                const status        = step?.status
                const detail        = step?.detail ?? ""
                const cleanedDetail = formatDetail(stepName, detail)

                return (
                  <div
                    key={stepName}
                    className="flex items-start gap-3 py-2.5"
                    style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}
                  >
                    {/* Icon */}
                    <span className="text-sm w-5 text-center flex-shrink-0 mt-0.5">
                      {stepIcon(status)}
                    </span>

                    {/* Label + detail */}
                    <div className="min-w-0">
                      <div className="text-sm" style={stepLabelStyle(status)}>
                        {resolveLabel(stepName)}
                        {status === "running" && (
                          <span
                            className="ml-2 inline-block text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
                            style={{ background: "#E0F2FE", color: "#0369A1" }}
                          >
                            RUNNING
                          </span>
                        )}
                      </div>
                      {cleanedDetail && (status === "running" || status === "success" || status === "failed") && (
                        <div
                          className="text-[11px] mt-0.5"
                          style={{ color: status === "failed" ? "#EF4444" : "#8494A7" }}
                        >
                          {cleanedDetail}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Overall status footer */}
            {!terminalError && (
              <div
                className="mt-4 pt-4 text-center text-xs"
                style={{ borderTop: "1px solid #E2E6EC", color: "#8494A7" }}
              >
                {overallStatus === "processing"
                  ? "Pipeline running — this page updates automatically every 2.5 s"
                  : `Status: ${overallStatus}`}
              </div>
            )}

          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="DOCUMENT PROCESSING — PIPELINE STATUS" />
    </div>
  )
}
