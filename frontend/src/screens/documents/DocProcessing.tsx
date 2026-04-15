/**
 * screens/documents/DocProcessing.tsx
 *
 * Unified document processing & results screen — renders INSIDE AppShell.
 *
 * While the pipeline is running: shows a 9-step visual pipeline + processing log.
 * When complete: shows completed pipeline + certified deliverables + insights.
 * When failed: shows error card + retry.
 *
 * Merges the former DocProcessing + DocResults into a single view matching
 * the "Process Intelligence" design mockup.
 */

import { useEffect, useRef, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { documentsApi, type PipelineStep, type DocumentStatus } from "@/services/api"
import useAuthStore from "@/store/authStore"

// ── Step config ──────────────────────────────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  validate_upload:   "Upload Check",
  classify_document: "Classification",
  ocr_printed_text:  "Text Extraction",
  translate:         "Translation",
  legal_review:      "Legal Review",
  reconstruct_pdf:   "Rebuilding",
  upload_to_gcs:     "Uploading",
  finalize:          "Finalize",
  log_summary:       "Complete",
}

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

const STEP_ICONS: Record<string, string> = {
  validate_upload:   "verified",
  classify_document: "category",
  ocr_printed_text:  "document_scanner",
  translate:         "translate",
  legal_review:      "policy",
  reconstruct_pdf:   "picture_as_pdf",
  upload_to_gcs:     "cloud_upload",
  finalize:          "inventory",
  log_summary:       "check_circle",
}

const TERMINAL_STATUSES = ["translated", "completed", "error", "failed", "rejected"]

// ── Language helpers ──────────────────────────────────────────────────────────

const LANG_LABEL: Record<string, string> = { es: "Spanish", pt: "Portuguese" }
const LANG_DESC: Record<string, string> = {
  es: "Localization for Madrid jurisdiction including legal footnotes.",
  pt: "Certified legal translation optimized for Brazilian court filing.",
}
const OTHER_LANG: Record<string, string> = { es: "pt", pt: "es" }

// ── Detail formatter ─────────────────────────────────────────────────────────

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
      return detail.replace(/^PaddleOCR:\s*/, "").replace("avg ", "avg conf ")
    case "translate":
      return detail.replace(/^NLLB-200:\s*/, "")
    case "legal_review":
      return detail.replace(/^Llama:\s*/, "")
    case "reconstruct_pdf":
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

// ── Error formatter ──────────────────────────────────────────────────────────

function friendlyError(raw: string | null): string {
  if (!raw) return "Translation failed. Please try again."
  if (/Pipeline failed at 'validate_upload'/i.test(raw))
    return "The file could not be processed. Please check it and try again."
  if (/Pipeline failed at 'classify_document'|non.legal|rejected/i.test(raw))
    return "This document was not recognised as a legal filing and cannot be translated."
  if (/Pipeline failed at 'ocr_printed_text'/i.test(raw))
    return "Text extraction failed. The document may be scanned at too low a resolution."
  if (/Pipeline failed at 'translate'/i.test(raw))
    return "Translation service unavailable. Please try again in a few minutes."
  if (/Pipeline failed at 'legal_review'/i.test(raw))
    return "Legal review step failed. The translated document may still be available."
  if (/Pipeline failed at 'reconstruct_pdf'/i.test(raw))
    return "PDF reconstruction failed. Please try uploading again."
  if (/Pipeline failed at 'upload_to_gcs'|signed|gcs/i.test(raw))
    return "Translation completed but the download link could not be generated. Please try again."
  return "Translation failed. Please try uploading again."
}

// ── Component ────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function DocProcessing({ onNav }: Props) {
  const documentSession    = useAuthStore((s) => s.documentSession)
  const documentResult     = useAuthStore((s) => s.documentResult)
  const setDocumentResult  = useAuthStore((s) => s.setDocumentResult)
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)

  const sessionId  = documentSession?.sessionId ?? null
  const targetLang = documentResult?.target_language ?? documentSession?.targetLanguage ?? "es"
  const langLabel  = LANG_LABEL[targetLang] ?? targetLang
  const secondLang = OTHER_LANG[targetLang] ?? (targetLang === "es" ? "pt" : "es")

  // ── Pipeline state ──────────────────────────────────────────────────────────

  const [steps, setSteps]                   = useState<PipelineStep[]>([])
  const [, setOverallStatus]                = useState<string>("processing")
  const [terminalError, setTerminalError]   = useState<string | null>(null)
  const [pollError, setPollError]           = useState<string | null>(null)

  // ── Results state (merged from DocResults) ──────────────────────────────────

  const [, setOcrMeta]                = useState<Record<string, unknown>>({})
  const [downloading, setDownloading] = useState(false)
  const [retranslating, setRetranslating] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isComplete = documentResult != null &&
    (documentResult.status === "translated" || documentResult.status === "completed")

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
          } else {
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

  // ── Fetch OCR metadata once complete ────────────────────────────────────────

  useEffect(() => {
    if (!sessionId || !isComplete) return
    documentsApi.steps(sessionId).then((s: PipelineStep[]) => {
      const ocrStep = s.find((st) => st.step_name === "ocr_printed_text")
      if (ocrStep?.metadata) setOcrMeta(ocrStep.metadata)
    }).catch(() => {/* non-critical */})
  }, [sessionId, isComplete])

  // ── Download handler ────────────────────────────────────────────────────────

  const handleDownload = async () => {
    if (!sessionId) return
    setDownloading(true)
    setActionError(null)
    try {
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

  // ── Retranslate handler ─────────────────────────────────────────────────────

  const handleRetranslate = async () => {
    if (!sessionId) return
    setRetranslating(true)
    setActionError(null)
    try {
      const resp = await documentsApi.retranslate(sessionId, secondLang)
      setDocumentSession({ sessionId: resp.session_id, targetLanguage: resp.target_language })
      setDocumentResult(null)
      setOverallStatus("processing")
      setSteps([])
      setTerminalError(null)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not start re-translation. Please try again."
      setActionError(msg)
    } finally {
      setRetranslating(false)
    }
  }

  // ── Pipeline derived data ───────────────────────────────────────────────────

  const stepMap      = new Map(steps.map((s) => [s.step_name, s]))
  const successCount = steps.filter((s) => s.status === "success").length
  const progressPct  = Math.round((successCount / STEP_ORDER.length) * 100)

  // Find the index of the failed step (if any) so subsequent steps
  // show "Cancelled" instead of "Pending" when the pipeline has stopped.
  const failedStepIndex = terminalError
    ? STEP_ORDER.findIndex((s) => stepMap.get(s)?.status === "failed")
    : -1

  // ── Results derived data ────────────────────────────────────────────────────

  const avgConf     = documentResult?.avg_confidence_score
  const corrections = documentResult?.llama_corrections_count ?? 0
  const procTime    = documentResult?.processing_time_seconds ?? null

  function getStepStatus(stepName: string) {
    return stepMap.get(stepName)?.status
  }

  // ── No session guard ────────────────────────────────────────────────────────

  if (!sessionId) {
    return (
      <div className="px-6 lg:px-12 py-8 max-w-4xl mx-auto">
        <div className="bg-surface-container-low rounded-xl p-12 text-center border border-white/5">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4 block">
            search_off
          </span>
          <p className="text-on-surface-variant mb-6">No active upload session.</p>
          <div className="flex justify-center gap-4">
            <button
              className="px-6 py-3 bg-[#FFD700] text-[#0D1B2A] rounded-lg font-bold text-sm hover:scale-105 transition-transform active:scale-95 border-none cursor-pointer flex items-center gap-2"
              onClick={() => onNav(SCREENS.DOC_HISTORY)}
            >
              <span className="material-symbols-outlined text-lg">history</span>
              View Document History
            </button>
            <button
              className="px-6 py-3 bg-surface-container-high text-on-surface rounded-lg font-bold text-sm hover:bg-surface-bright transition-colors border border-white/10 cursor-pointer flex items-center gap-2"
              onClick={() => onNav(SCREENS.DOC_UPLOAD)}
            >
              <span className="material-symbols-outlined text-lg">upload_file</span>
              Upload New Document
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Main render ─────────────────────────────────────────────────────────────

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-10">

      {/* ── Header ─────────────────────────────────────────────────── */}
      <section>
        <h1 className="font-headline text-4xl text-on-surface mb-2">Process Intelligence</h1>
        <p className="text-on-surface-variant font-body max-w-2xl">
          {isComplete ? `${langLabel} translation complete.` : `Translating to ${langLabel}. Your document is being translated and verified for legal accuracy.`}
        </p>
      </section>

      {/* ── Terminal error ──────────────────────────────────────────── */}
      {terminalError && (
        <div className="bg-error-container/20 border border-error/30 rounded-xl p-6">
          <div className="flex items-start gap-4">
            <span className="material-symbols-outlined text-error text-3xl flex-shrink-0" style={{ fontVariationSettings: "'FILL' 1" }}>
              error
            </span>
            <div>
              <h3 className="text-lg font-headline text-error mb-2">Translation Failed</h3>
              <p className="text-sm text-on-error-container leading-relaxed mb-4">{terminalError}</p>
              <button
                className="px-6 py-2.5 bg-[#FFD700] text-[#0D1B2A] rounded-lg font-bold text-sm hover:scale-105 transition-transform active:scale-95 border-none cursor-pointer flex items-center gap-2"
                onClick={() => onNav(SCREENS.DOC_UPLOAD)}
              >
                <span className="material-symbols-outlined text-lg">arrow_back</span>
                Try Again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Action error (download/retranslate) ────────────────────── */}
      {actionError && (
        <div className="rounded-xl px-5 py-4 text-sm flex items-start gap-3 bg-error-container/20 border border-error/30">
          <span className="material-symbols-outlined text-error text-lg flex-shrink-0 mt-0.5">warning</span>
          <span className="text-error">{actionError}</span>
        </div>
      )}

      {/* ── Poll error (transient) ─────────────────────────────────── */}
      {pollError && !terminalError && (
        <div className="rounded-xl px-5 py-3 text-xs flex items-center gap-2 bg-secondary-container/10 border border-secondary/20">
          <span className="material-symbols-outlined text-secondary text-sm">wifi_off</span>
          <span className="text-secondary">{pollError}</span>
        </div>
      )}

      {/* ── Visual Pipeline (9-step horizontal) ────────────────────── */}
      <section>
        <div className="bg-surface-container-low rounded-xl p-8 shadow-inner overflow-hidden relative">
          <div className="absolute top-0 right-0 w-64 h-64 bg-tertiary/5 blur-[100px] -z-10" />

          <h2 className="font-headline text-xl text-secondary-fixed mb-8 flex items-center gap-2">
            <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: "'FILL' 1" }}>
              analytics
            </span>
            Document Pipeline Analysis
          </h2>

          <div className="grid grid-cols-3 md:grid-cols-9 gap-4 relative">
            <div className="hidden md:block absolute top-6 left-0 w-full h-[2px] bg-surface-container-highest -z-0" />

            {STEP_ORDER.map((stepName, i) => {
              const status      = getStepStatus(stepName)
              const isSuccess   = status === "success"
              const isRunning   = status === "running"
              const isFailed    = status === "failed"
              const isCancelled = failedStepIndex >= 0 && i > failedStepIndex

              return (
                <div key={stepName} className="flex flex-col items-center text-center gap-3 relative z-10">
                  <div
                    className={`w-12 h-12 rounded-full flex items-center justify-center shadow-lg transition-all ${
                      isSuccess
                        ? "bg-secondary-container text-on-secondary-container"
                        : isRunning
                        ? "bg-surface-container-highest border-2 border-secondary text-secondary"
                        : isFailed
                        ? "bg-error-container text-error"
                        : isCancelled
                        ? "bg-surface-container-highest border border-outline-variant/30 text-outline/30 opacity-30"
                        : "bg-surface-container-highest border border-outline-variant/30 text-outline opacity-40"
                    }`}
                    style={isRunning ? {
                      boxShadow: "0 0 0 0 rgba(251, 188, 0, 0.4)",
                      animation: "pulse-gold 2s infinite",
                    } : undefined}
                  >
                    {isSuccess ? (
                      <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    ) : isRunning ? (
                      <span className="material-symbols-outlined animate-spin" style={{ fontSize: "20px" }}>autorenew</span>
                    ) : isFailed ? (
                      <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>cancel</span>
                    ) : isCancelled ? (
                      <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 0" }}>block</span>
                    ) : (
                      <span className="material-symbols-outlined">{STEP_ICONS[stepName] ?? "radio_button_unchecked"}</span>
                    )}
                  </div>

                  <span className={`text-[10px] font-bold uppercase tracking-tighter ${
                    isRunning ? "text-secondary" : isSuccess ? "text-on-surface" : isFailed ? "text-error" : isCancelled ? "text-outline/30" : "text-outline"
                  }`}>
                    {STEP_LABELS[stepName] ?? stepName}
                  </span>

                  <div className={`text-[9px] ${
                    isRunning ? "text-secondary/70" : isSuccess ? "text-on-surface-variant" : isFailed ? "text-error/70" : isCancelled ? "text-outline-variant/50" : "text-outline-variant"
                  }`}>
                    {isSuccess ? "Complete" : isRunning ? "Processing…" : isFailed ? "Failed" : isCancelled ? "Cancelled" : "Pending"}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════
           PROCESSING STATE: show detailed log
         ══════════════════════════════════════════════════════════════ */}
      {!isComplete && (
        <section className="bg-surface-container-low rounded-xl overflow-hidden border border-white/5">
          <div className="px-8 py-5 bg-surface-container-high/40 border-b border-white/5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-headline text-lg text-on-surface">Processing Log</h3>
              <span className="text-xs text-on-surface-variant font-mono">
                {successCount}/{STEP_ORDER.length} steps · {progressPct}%
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden bg-surface-container-highest">
              <div
                className={`h-full rounded-full transition-all duration-700 ${
                  terminalError
                    ? "bg-gradient-to-r from-error-container to-error"
                    : "bg-gradient-to-r from-secondary-container to-secondary"
                }`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>

          <div className="px-8 py-2">
            {STEP_ORDER.map((stepName, i) => {
              const step   = stepMap.get(stepName)
              const status = step?.status
              const detail = step?.detail ?? ""
              const cleaned = formatDetail(stepName, detail)
              const isCancelled = failedStepIndex >= 0 && i > failedStepIndex

              return (
                <div
                  key={stepName}
                  className="flex items-start gap-4 py-4"
                  style={{ borderTop: i ? "1px solid rgba(255,255,255,0.05)" : "none" }}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    {status === "success" ? (
                      <span className="material-symbols-outlined text-secondary text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    ) : status === "running" ? (
                      <span className="material-symbols-outlined text-secondary text-lg animate-spin">autorenew</span>
                    ) : status === "failed" ? (
                      <span className="material-symbols-outlined text-error text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>cancel</span>
                    ) : status === "skipped" ? (
                      <span className="material-symbols-outlined text-outline text-lg">remove_circle_outline</span>
                    ) : isCancelled ? (
                      <span className="material-symbols-outlined text-outline-variant/40 text-lg">block</span>
                    ) : (
                      <span className="material-symbols-outlined text-outline-variant text-lg">radio_button_unchecked</span>
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className={`text-sm font-medium ${
                      status === "running" ? "text-on-surface font-semibold"
                      : status === "failed" ? "text-error"
                      : status === "success" ? "text-on-surface"
                      : isCancelled ? "text-outline/30"
                      : "text-on-surface-variant"
                    }`}>
                      {STEP_LABELS[stepName] ?? stepName}
                      {stepName === "translate" && ` to ${langLabel}`}
                      {status === "running" && (
                        <span className="ml-2 inline-block text-[10px] px-2 py-0.5 rounded-full font-bold bg-secondary-container/20 text-secondary border border-secondary/20">
                          RUNNING
                        </span>
                      )}
                      {isCancelled && (
                        <span className="ml-2 inline-block text-[10px] px-2 py-0.5 rounded-full font-bold bg-surface-container-highest text-outline-variant/50">
                          CANCELLED
                        </span>
                      )}
                    </div>
                    {cleaned && (status === "running" || status === "success" || status === "failed") && (
                      <div className={`text-[11px] mt-1 ${status === "failed" ? "text-error/70" : "text-on-surface-variant"}`}>
                        {cleaned}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {!terminalError && (
            <div className="px-8 py-4 text-center text-xs bg-surface-container-high/20 border-t border-white/5 text-on-surface-variant">
              Pipeline running — this page updates automatically every 2.5 s
            </div>
          )}
        </section>
      )}

      {/* ══════════════════════════════════════════════════════════════
           COMPLETE STATE: show deliverables + insights
         ══════════════════════════════════════════════════════════════ */}
      {isComplete && (
        <>
          {/* ── Certified Deliverables ─────────────────────────────── */}
          <section>
            <div className="flex justify-between items-end mb-6">
              <div>
                <h2 className="font-headline text-2xl text-on-surface">Certified Deliverables</h2>
                <p className="text-on-surface-variant text-sm italic">
                  Your translated legal documents are ready to download.
                </p>
              </div>
              {avgConf != null && (
                <div className="flex items-center gap-2 text-tertiary-fixed text-xs font-bold uppercase tracking-widest bg-tertiary-container/30 px-3 py-1.5 rounded-full border border-tertiary/20">
                  <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>verified</span>
                  AI Verified Accuracy
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Translated language — download */}
              <div className="group bg-surface-container-high rounded-xl p-6 transition-all hover:translate-y-[-4px] hover:shadow-2xl hover:shadow-black/60 relative overflow-hidden border-t-2 border-secondary/0 hover:border-secondary/40">
                <div className="absolute -top-10 -right-10 w-32 h-32 bg-secondary/5 rounded-full blur-3xl group-hover:bg-secondary/10 transition-colors" />
                <div className="flex justify-between items-start mb-4">
                  <span className="material-symbols-outlined text-secondary text-3xl">translate</span>
                  <span className="text-[10px] bg-tertiary-container/30 text-tertiary-fixed px-2 py-0.5 rounded uppercase font-bold tracking-widest">
                    Translated
                  </span>
                </div>
                <h3 className="font-headline text-xl text-on-surface mb-1">{langLabel}</h3>
                <p className="text-on-surface-variant text-xs mb-6">
                  {LANG_DESC[targetLang] ?? "Certified legal translation."}
                </p>
                <button
                  onClick={handleDownload}
                  disabled={downloading}
                  className="w-full bg-secondary text-on-secondary py-3 rounded-lg font-bold text-sm flex items-center justify-center gap-2 hover:bg-secondary-fixed-dim transition-colors active:scale-[0.98] border-none cursor-pointer disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-lg">download</span>
                  {downloading ? "Fetching…" : "Download PDF"}
                </button>
              </div>

              {/* Second language — retranslate */}
              <div className="group bg-surface-container-high rounded-xl p-6 transition-all hover:translate-y-[-4px] hover:shadow-2xl hover:shadow-black/60 relative overflow-hidden">
                <div className="absolute -top-10 -right-10 w-32 h-32 bg-primary/5 rounded-full blur-3xl group-hover:bg-primary/10 transition-colors" />
                <div className="flex justify-between items-start mb-4">
                  <span className="material-symbols-outlined text-primary text-3xl">language</span>
                  <span className="text-[10px] bg-surface-container-highest text-on-surface-variant px-2 py-0.5 rounded uppercase font-bold tracking-widest">
                    Available
                  </span>
                </div>
                <h3 className="font-headline text-xl text-on-surface mb-1">
                  {LANG_LABEL[secondLang] ?? secondLang}
                </h3>
                <p className="text-on-surface-variant text-xs mb-6">Not yet translated</p>
                <button
                  onClick={handleRetranslate}
                  disabled={retranslating}
                  className="w-full py-3 rounded-lg font-bold text-sm flex items-center justify-center gap-2 transition-colors active:scale-[0.98] cursor-pointer border border-secondary/20 text-secondary hover:bg-secondary/10 bg-transparent disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-lg">translate</span>
                  {retranslating ? "Starting…" : "Translate Now"}
                </button>
              </div>
            </div>
          </section>

          {/* ── Insights Bento ──────────────────────────────────────── */}
          <section className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            {/* AI Summary — 2-col */}
            <div className="lg:col-span-2 bg-primary-container p-6 rounded-xl relative overflow-hidden border border-primary/10">
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-headline text-lg text-primary">Cross-Examination AI Summary</h3>
                <span className="material-symbols-outlined text-primary">psychology</span>
              </div>
              <p className="text-on-primary-container text-sm leading-relaxed mb-4">
                {corrections > 0
                  ? `The AI has identified ${corrections} potential correction${corrections !== 1 ? "s" : ""} during legal term review. Review recommended before finalized filing.`
                  : "No corrections were needed. The translation passed all legal verification checks."}
              </p>
              {corrections > 0 && (
                <button
                  onClick={handleDownload}
                  className="text-xs font-bold text-on-primary bg-primary px-4 py-2 rounded uppercase tracking-wider hover:opacity-90 transition-opacity border-none cursor-pointer"
                >
                  Review Discrepancies
                </button>
              )}
            </div>

            {/* Data Integrity */}
            <div className="bg-surface-container-high p-6 rounded-xl border border-outline-variant/10">
              <h3 className="font-headline text-lg mb-2 text-on-surface">Data Integrity</h3>
              <div className="text-3xl font-bold text-secondary-fixed mb-1">
                {avgConf != null ? `${(avgConf * 100).toFixed(2)}%` : "—"}
              </div>
              <div className="text-[10px] text-on-surface-variant uppercase tracking-widest">
                Confidence Score
              </div>
            </div>

            {/* Processing Time */}
            <div className="bg-surface-container-high p-6 rounded-xl border border-outline-variant/10">
              <h3 className="font-headline text-lg mb-2 text-on-surface">Processing Time</h3>
              <div className="text-3xl font-bold text-on-surface mb-1">
                {procTime != null ? (
                  <>
                    {procTime >= 60 ? (procTime / 60).toFixed(1) : procTime.toFixed(1)}
                    <span className="text-sm font-normal text-on-surface-variant ml-1">
                      {procTime >= 60 ? "min" : "s"}
                    </span>
                  </>
                ) : "—"}
              </div>
              <div className="text-[10px] text-on-surface-variant uppercase tracking-widest">
                Saved vs Manual
              </div>
            </div>
          </section>

          {/* ── Bottom actions ──────────────────────────────────────── */}
          <div className="flex gap-4 pt-2">
            <button
              onClick={() => onNav(SCREENS.DOC_UPLOAD)}
              className="px-6 py-3 rounded-lg font-bold text-sm flex items-center gap-2 bg-surface-container-high text-on-surface hover:bg-surface-bright transition-colors border border-white/10 cursor-pointer"
            >
              <span className="material-symbols-outlined text-lg">upload_file</span>
              Upload Another
            </button>
            <button
              onClick={() => onNav(SCREENS.DOC_HISTORY)}
              className="px-6 py-3 rounded-lg font-bold text-sm flex items-center gap-2 bg-surface-container-high text-on-surface hover:bg-surface-bright transition-colors border border-white/10 cursor-pointer"
            >
              <span className="material-symbols-outlined text-lg">history</span>
              View History
            </button>
          </div>
        </>
      )}
    </div>
  )
}
