/**
 * screens/documents/DocUpload.tsx
 *
 * Document upload screen — renders INSIDE AppShell.
 * Dark-themed with large drop zone, processing queue sidebar,
 * and AI suggestion panel.
 *
 * Preserved logic: documentsApi.upload(), drag-drop, progress tracking,
 * file validation, language selector, and document session state.
 */

import { useRef, useState, DragEvent, ChangeEvent } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { documentsApi } from "@/services/api"
import useAuthStore from "@/store/authStore"

// ── Constants ─────────────────────────────────────────────────────────────────

const ALLOWED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/msword",
]
const MAX_SIZE_BYTES = 50 * 1024 * 1024 // 50 MB

// ── Helpers ───────────────────────────────────────────────────────────────────

function validateFile(file: File): string | null {
  if (!ALLOWED_TYPES.includes(file.type)) {
    return "Only PDF or Word (.docx / .doc) files are accepted."
  }
  if (file.size > MAX_SIZE_BYTES) {
    return `File is too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum is 50 MB.`
  }
  return null
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

type Stage = "idle" | "uploading" | "finalizing" | "done"

export default function DocUpload({ onNav }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)

  const [file, setFile] = useState<File | null>(null)
  const [targetLanguage, setTargetLanguage] = useState<"es" | "pt">("es")
  const [stage, setStage] = useState<Stage>("idle")
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  const busy = stage === "uploading" || stage === "finalizing"

  // ── File selection ──────────────────────────────────────────────────────────

  function handleFile(candidate: File) {
    const err = validateFile(candidate)
    if (err) {
      setError(err)
      setFile(null)
    } else {
      setError(null)
      setFile(candidate)
    }
  }

  function onInputChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) handleFile(f)
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f) handleFile(f)
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(true)
  }

  function onDragLeave() {
    setDragOver(false)
  }

  // ── Upload ──────────────────────────────────────────────────────────────────

  async function handleUpload() {
    if (!file) {
      setError("Please select a file before uploading.")
      return
    }
    setStage("uploading")
    setUploadProgress(0)
    setError(null)

    try {
      const resp = await documentsApi.upload(file, targetLanguage, null, (pct) => {
        setUploadProgress(pct)
        if (pct >= 100) setStage("finalizing")
      })
      setStage("done")
      setDocumentSession({ sessionId: resp.session_id, targetLanguage: resp.target_language })
      onNav(SCREENS.DOC_PROCESSING)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Upload failed. Please try again."
      setError(msg)
      setStage("idle")
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const langLabel = targetLanguage === "es" ? "Spanish (Español)" : "Portuguese (Português)"

  return (
    <div className="px-6 lg:px-12 py-8 max-w-7xl mx-auto">

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">

        {/* ── Main Upload Zone (Left Column) ─────────────────────────────── */}
        <div className="lg:col-span-8 space-y-8">

          {/* Header */}
          <header>
            <h2 className="text-3xl font-headline font-bold text-on-surface">
              Legal Intake Protocol
            </h2>
            <div className="flex items-center gap-2 mt-2">
              <span className="px-3 py-1 bg-tertiary-container text-tertiary rounded-full text-[10px] font-bold tracking-widest border border-tertiary/20 uppercase">
                AI-Assisted Processing
              </span>
            </div>
          </header>

          {/* Error banner */}
          {error && (
            <div className="rounded-xl px-5 py-4 text-sm flex items-start gap-3 bg-error-container/20 border border-error/30">
              <span className="material-symbols-outlined text-error text-lg flex-shrink-0 mt-0.5">warning</span>
              <span className="text-error">{error}</span>
            </div>
          )}

          {/* Hidden file input */}
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.doc,.docx"
            className="hidden"
            onChange={onInputChange}
            id="doc-upload-input"
          />

          {/* Drop zone */}
          <div className="relative group rounded-xl bg-surface-container-low p-1 border border-white/5 overflow-hidden flex flex-col"
            style={{ minHeight: "420px" }}
          >
            {/* Background gradient overlay */}
            <div className="absolute inset-0 bg-gradient-to-br from-primary-container/20 via-transparent to-secondary-container/5 pointer-events-none" />

            <div
              role="button"
              tabIndex={0}
              onClick={() => !busy && inputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (!busy) inputRef.current?.click() } }}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              className={`flex-1 flex flex-col items-center justify-center border-2 border-dashed rounded-lg m-4 transition-all cursor-pointer ${dragOver
                  ? "border-[#FFD700]/60 bg-[#FFD700]/5"
                  : file
                    ? "border-secondary/40 bg-surface-container/30"
                    : "border-outline/20 hover:border-[#FFD700]/40 bg-surface-container/30"
                }`}
              style={{ cursor: busy ? "not-allowed" : "pointer" }}
            >
              <div className="w-24 h-24 rounded-full bg-surface-container-highest flex items-center justify-center mb-6 shadow-2xl">
                <span
                  className="material-symbols-outlined text-4xl text-[#FFD700]"
                  style={file ? { fontVariationSettings: "'FILL' 1" } : undefined}
                >
                  {file ? "description" : "cloud_upload"}
                </span>
              </div>

              {file ? (
                <>
                  <h3 className="text-2xl font-headline mb-2 text-on-surface">{file.name}</h3>
                  <p className="text-on-surface-variant text-center max-w-md mb-2">
                    {(file.size / 1024 / 1024).toFixed(2)} MB · {langLabel}
                  </p>
                  {!busy && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setFile(null) }}
                      className="mt-2 text-xs text-on-surface-variant hover:text-error underline bg-transparent border-none cursor-pointer"
                    >
                      Remove file
                    </button>
                  )}
                </>
              ) : (
                <>
                  <h3 className="text-2xl font-headline mb-2 text-on-surface">
                    Drop Official Documents Here
                  </h3>
                  <p className="text-on-surface-variant text-center max-w-md mb-8">
                    PDF, DOCX, or scanned documents. Files are encrypted and analyzed
                    using the Magistrate-V2 Neural Network.
                  </p>
                  <button
                    className="bg-[#FFD700] text-[#0D1B2A] px-8 py-3 rounded-lg font-bold shadow-xl hover:scale-105 transition-transform active:scale-95 border-none cursor-pointer"
                    onClick={(e) => { e.stopPropagation(); inputRef.current?.click() }}
                  >
                    Select Files from Repository
                  </button>
                </>
              )}
            </div>

            {/* Upload progress overlay */}
            {stage === "uploading" && (
              <div className="mx-4 mb-4">
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-on-surface-variant">Uploading…</span>
                  <span className="text-secondary font-bold">{uploadProgress}%</span>
                </div>
                <div className="h-2 rounded-full overflow-hidden bg-surface-container-highest">
                  <div
                    className="h-full rounded-full transition-all duration-300 bg-gradient-to-r from-secondary-container to-secondary"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Finalizing state */}
            {stage === "finalizing" && (
              <div className="mx-4 mb-4 flex items-center gap-3 text-sm text-on-surface-variant">
                <span className="material-symbols-outlined animate-spin text-secondary text-lg">autorenew</span>
                Finalizing upload…
              </div>
            )}

            {/* Bottom status bar */}
            <div className="px-8 py-4 flex items-center justify-between bg-surface-container-highest/50 backdrop-blur-md">
              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-tertiary text-sm">verified</span>
                  <span className="text-[10px] uppercase font-bold tracking-widest text-on-surface-variant">
                    OCR 4.0 Active
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-[#FFD700] text-sm">gavel</span>
                  <span className="text-[10px] uppercase font-bold tracking-widest text-on-surface-variant">
                    Legal Processing
                  </span>
                </div>
              </div>
              <span className="text-[10px] text-on-surface-variant italic">
                Max file size: 50MB per document
              </span>
            </div>
          </div>

          {/* Language selector + Upload button */}
          <div className="bg-surface-container-low rounded-xl p-6 border border-white/5 space-y-5">
            <div>
              <label
                htmlFor="target-language-select"
                className="text-xs font-bold block mb-2 uppercase tracking-widest text-on-surface-variant"
              >
                Target Language
              </label>
              <select
                id="target-language-select"
                value={targetLanguage}
                onChange={(e) => setTargetLanguage(e.target.value as "es" | "pt")}
                disabled={busy}
                className="w-full px-4 py-3 rounded-lg text-sm bg-surface-container-high border border-outline-variant/20 text-on-surface focus:border-secondary focus:ring-1 focus:ring-secondary/30 transition-colors"
              >
                <option value="es">Spanish (Español)</option>
                <option value="pt">Portuguese (Português)</option>
              </select>
            </div>

            {/* Legal notice */}
            <div className="rounded-lg p-4 bg-[#FFD700]/5 border border-[#FFD700]/10">
              <div className="flex items-center gap-2 mb-2">
                <span className="material-symbols-outlined text-[#FFD700] text-sm">info</span>
                <p className="text-[10px] font-bold tracking-widest uppercase text-[#FFD700]">
                  Legal Documents Only
                </p>
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                This system is designed for court forms, legal filings, orders, and related documents.
                Non-legal documents will be rejected by the classification engine.
              </p>
            </div>

            <button
              id="upload-translate-btn"
              className="w-full py-3.5 rounded-lg font-bold text-sm flex items-center justify-center gap-2 transition-all active:scale-[0.98] border-none cursor-pointer"
              style={{
                background: busy ? "#44474c" : "#FFD700",
                color: busy ? "#c4c6cc" : "#0D1B2A",
              }}
              disabled={busy}
              onClick={handleUpload}
            >
              {stage === "finalizing" ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-lg">autorenew</span>
                  Finalizing…
                </>
              ) : stage === "uploading" ? (
                `Uploading… ${uploadProgress}%`
              ) : (
                <>
                  <span className="material-symbols-outlined text-lg">translate</span>
                  Upload and Translate
                </>
              )}
            </button>
          </div>
        </div>

        {/* ── Right Sidebar (Queue Panel) ────────────────────────────────── */}
        <div className="lg:col-span-4 space-y-6">
          <div className="bg-surface-container-low rounded-xl p-6 border border-white/5 relative overflow-hidden flex flex-col"
            style={{ minHeight: "500px" }}
          >
            <h3 className="font-headline text-xl text-on-surface mb-6 flex items-center justify-between">
              Current Queue
              <span className="text-xs font-sans text-on-surface-variant font-normal">
                0 Files Active
              </span>
            </h3>

            {/* Empty state */}
            <div className="flex-1 flex flex-col items-center justify-center text-center py-12 opacity-60">
              <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4">inbox</span>
              <p className="text-sm text-on-surface-variant">No documents in queue</p>
              <p className="text-xs text-on-surface-variant mt-1">
                Upload a document to begin processing
              </p>
            </div>

            {/* AI Suggestion */}
            <div className="mt-6 pt-6 border-t border-white/5">
              <div className="p-4 bg-[#FFD700]/5 rounded-lg border border-[#FFD700]/10 backdrop-blur-sm">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-[#FFD700] text-sm">auto_awesome</span>
                  <p className="text-[10px] font-bold tracking-widest uppercase text-[#FFD700]">
                    AI Suggestion
                  </p>
                </div>
                <p className="text-xs text-on-surface-variant leading-relaxed">
                  Batching multiple files together improves cross-reference accuracy
                  by up to 14%.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
