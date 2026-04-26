/**
 * screens/documents/DocResults.tsx
 *
 * Document results / download screen — renders INSIDE AppShell.
 * Dark-themed with download cards, processing summary, and retranslate option.
 *
 * Preserved logic: documentsApi.status() for fresh signed URL,
 * documentsApi.retranslate() for second language, OCR metadata from steps,
 * session & result state management.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
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

  const summaryRows: { label: string; value: string; icon: string }[] = [
    { label: "Text regions", value: totalRegions != null ? String(totalRegions) : "—", icon: "text_fields" },
    { label: "Translatable", value: translatable != null ? String(translatable) : "—", icon: "translate" },
    { label: "Avg confidence", value: avgConf != null ? avgConf.toFixed(3) : "—", icon: "verified" },
    { label: "Llama corrections", value: String(corrections), icon: "auto_fix_high" },
    { label: "Processing time", value: formatSeconds(procTime), icon: "schedule" },
  ]

  // ── Guard — navigated here without a result ──────────────────────────────────

  if (!sessionId || !documentResult) {
    return (
      <div className="px-6 lg:px-12 py-8 max-w-4xl mx-auto">
        <div className="bg-surface-container-low rounded-xl p-12 text-center border border-white/5">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4 block">
            search_off
          </span>
          <p className="text-on-surface-variant mb-6">No completed translation found.</p>
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

  const expiresLabel = expiresAt ? minutesLeft(expiresAt) : null

  return (
    <div className="px-6 lg:px-8 py-8 max-w-5xl mx-auto space-y-8">

      {/* Header */}
      <section className="relative overflow-hidden rounded-xl bg-gradient-to-br from-primary-container to-surface-container-lowest p-8 shadow-2xl border border-white/5">
        <div className="relative z-10 flex items-center gap-4">
          <div className="p-3 rounded-xl bg-secondary-container/20">
            <span
              className="material-symbols-outlined text-secondary text-4xl"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              task_alt
            </span>
          </div>
          <div>
            <h1 className="text-3xl font-headline text-on-surface mb-1">
              Translation Complete
            </h1>
            <p className="text-on-surface-variant text-sm">
              Session {sessionId.slice(0, 8)}…
              {procTime != null && ` · Completed in ${formatSeconds(procTime)}`}
            </p>
          </div>
        </div>
        {/* Background glow */}
        <div className="absolute right-0 top-0 w-64 h-64 bg-secondary/5 blur-[100px] rounded-full -translate-y-1/2 translate-x-1/2" />
      </section>

      {/* Action error banner */}
      {actionError && (
        <div className="rounded-xl px-5 py-4 text-sm flex items-start gap-3 bg-error-container/20 border border-error/30">
          <span className="material-symbols-outlined text-error text-lg flex-shrink-0 mt-0.5">warning</span>
          <span className="text-error">{actionError}</span>
        </div>
      )}

      {/* Download Cards */}
      <section>
        <h2 className="font-headline text-2xl text-on-surface mb-2">Certified Deliverables</h2>
        <p className="text-on-surface-variant text-sm italic mb-6">
          Your translated legal documents are ready to download.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

          {/* Primary language — completed */}
          <div className="group bg-surface-container-high rounded-xl p-6 transition-all hover:translate-y-[-4px] hover:shadow-2xl hover:shadow-black/60 relative overflow-hidden border-t-2 border-secondary/0 hover:border-secondary/40">
            <div className="absolute -top-10 -right-10 w-32 h-32 bg-secondary/5 rounded-full blur-3xl group-hover:bg-secondary/10 transition-colors" />
            <div className="flex justify-between items-start mb-4">
              <span className="text-4xl">{FLAG[targetLang] ?? "🌐"}</span>
              <span className="text-[10px] bg-tertiary-container/30 text-tertiary-fixed px-2 py-0.5 rounded uppercase font-bold tracking-widest">
                Translated
              </span>
            </div>
            <h3 className="font-headline text-xl text-on-surface mb-1">
              {LANG_LABEL[targetLang] ?? targetLang}
            </h3>
            {avgConf != null && (
              <p className="text-on-surface-variant text-xs mb-6">
                Avg confidence: {avgConf.toFixed(3)}
              </p>
            )}
            <button
              id="download-pdf-btn"
              onClick={handleDownload}
              disabled={downloading}
              className="w-full bg-secondary text-on-secondary py-3 rounded-lg font-bold text-sm flex items-center justify-center gap-2 hover:bg-secondary-fixed-dim transition-colors active:scale-[0.98] border-none cursor-pointer disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-lg">download</span>
              {downloading ? "Fetching…" : "Download PDF"}
            </button>
          </div>

          {/* Second language — trigger retranslate */}
          <div className="group bg-surface-container-high rounded-xl p-6 transition-all hover:translate-y-[-4px] hover:shadow-2xl hover:shadow-black/60 relative overflow-hidden">
            <div className="absolute -top-10 -right-10 w-32 h-32 bg-primary/5 rounded-full blur-3xl group-hover:bg-primary/10 transition-colors" />
            <div className="flex justify-between items-start mb-4">
              <span className="text-4xl">{FLAG[secondLang] ?? "🌐"}</span>
              <span className="text-[10px] bg-surface-container-highest text-on-surface-variant px-2 py-0.5 rounded uppercase font-bold tracking-widest">
                Available
              </span>
            </div>
            <h3 className="font-headline text-xl text-on-surface mb-1">
              {LANG_LABEL[secondLang] ?? secondLang}
            </h3>
            <p className="text-on-surface-variant text-xs mb-6">Not yet translated</p>
            <button
              id="retranslate-btn"
              onClick={handleRetranslate}
              disabled={retranslating}
              className="w-full py-3 rounded-lg font-bold text-sm flex items-center justify-center gap-2 transition-colors active:scale-[0.98] cursor-pointer border border-secondary/20 text-secondary hover:bg-secondary/10 bg-transparent disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-lg">translate</span>
              {retranslating ? "Starting…" : "Translate Now"}
            </button>
          </div>
        </div>

        {expiresLabel && (
          <p className="text-[11px] text-center mt-4 text-on-surface-variant">
            Signed URL expires in {expiresLabel} · Original file auto-deletes in 24 hours
          </p>
        )}
      </section>

      {/* Processing Summary */}
      <section className="bg-surface-container-low rounded-xl p-6 border border-white/5">
        <h3 className="font-headline text-lg text-on-surface mb-5">Processing Summary</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {summaryRows.map((row) => (
            <div
              key={row.label}
              className="bg-surface-container-high rounded-lg p-4 border border-white/5"
            >
              <span className="material-symbols-outlined text-secondary text-lg mb-2 block">
                {row.icon}
              </span>
              <div className="text-xl font-bold text-on-surface mb-0.5">{row.value}</div>
              <div className="text-[10px] text-on-surface-variant uppercase tracking-widest">
                {row.label}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Legal Review Note — only shown when Llama made corrections */}
      {corrections > 0 && (
        <section className="bg-tertiary-container/20 border border-tertiary/20 rounded-xl p-5 flex items-start gap-4">
          <span className="material-symbols-outlined text-tertiary text-xl flex-shrink-0 mt-0.5"
                style={{ fontVariationSettings: "'FILL' 1" }}>
            auto_awesome
          </span>
          <div>
            <h4 className="text-sm font-bold text-tertiary mb-1">Legal Review Note</h4>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              Llama 4 made {corrections} correction
              {corrections !== 1 ? "s" : ""} to legal terminology during translation.
              Review the translated document to verify term accuracy in the legal context.
            </p>
          </div>
        </section>
      )}

      {/* Bottom actions */}
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
    </div>
  )
}
