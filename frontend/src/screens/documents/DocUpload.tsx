import { useRef, useState, DragEvent, ChangeEvent } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
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

export default function DocUpload({ onNav }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const setDocumentSession = useAuthStore((s) => s.setDocumentSession)

  // Local state
  const [file, setFile]                   = useState<File | null>(null)
  const [targetLanguage, setTargetLanguage] = useState<"es" | "pt">("es")
  const [uploading, setUploading]         = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError]                 = useState<string | null>(null)
  const [dragOver, setDragOver]           = useState(false)

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
    setUploading(true)
    setUploadProgress(0)
    setError(null)

    try {
      const resp = await documentsApi.upload(file, targetLanguage, null, setUploadProgress)
      setDocumentSession({ sessionId: resp.session_id, targetLanguage: resp.target_language })
      onNav(SCREENS.DOC_PROCESSING)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Upload failed. Please try again."
      setError(msg)
      setUploading(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const langLabel = targetLanguage === "es" ? "Spanish (Español)" : "Portuguese (Português)"

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">
        <h1
          className="text-xl font-bold mb-6"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          Upload Document for Translation
        </h1>

        <Card>
          <CardContent className="p-6 flex flex-col gap-4">

            {/* Error banner */}
            {error && (
              <div
                className="rounded-md px-4 py-3 text-sm flex items-start gap-2"
                style={{ background: "#FEF2F2", color: "#B91C1C", border: "1px solid #FECACA" }}
              >
                <span className="flex-shrink-0">⚠️</span>
                <span>{error}</span>
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
            <div
              onClick={() => !uploading && inputRef.current?.click()}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              className="rounded-lg p-10 text-center transition-colors"
              style={{
                border: `2px dashed ${dragOver ? "#0B1D3A" : file ? "#22C55E" : "#E2E6EC"}`,
                background: dragOver ? "#F0F4FF" : "transparent",
                cursor: uploading ? "not-allowed" : "pointer",
              }}
            >
              <div className="text-4xl mb-2">{file ? "📄" : "📂"}</div>

              {file ? (
                <>
                  <p className="text-sm font-semibold mb-1" style={{ color: "#1A2332" }}>
                    {file.name}
                  </p>
                  <p className="text-xs" style={{ color: "#8494A7" }}>
                    {(file.size / 1024 / 1024).toFixed(2)} MB · {langLabel}
                  </p>
                  {!uploading && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setFile(null) }}
                      className="mt-2 text-xs underline"
                      style={{ color: "#8494A7" }}
                    >
                      Remove
                    </button>
                  )}
                </>
              ) : (
                <>
                  <p className="text-sm font-semibold mb-1" style={{ color: "#1A2332" }}>
                    Drag and drop your PDF here
                  </p>
                  <p className="text-xs mb-3" style={{ color: "#8494A7" }}>or click to browse files</p>
                  <span
                    className="text-[10px] font-semibold px-2 py-1 rounded tracking-wide"
                    style={{ background: "#F5EDE0", color: "#C8963E" }}
                  >
                    PDF / DOCX · MAX 50MB
                  </span>
                </>
              )}
            </div>

            {/* Upload progress bar — shown only while uploading */}
            {uploading && (
              <div>
                <div className="flex justify-between text-xs mb-1" style={{ color: "#4A5568" }}>
                  <span>Uploading…</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "#E5E7EB" }}>
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${uploadProgress}%`,
                      background: "linear-gradient(90deg, #0B1D3A, #C8963E)",
                    }}
                  />
                </div>
              </div>
            )}

            {/* Language selector */}
            <div>
              <label
                htmlFor="target-language-select"
                className="text-xs font-semibold block mb-1.5"
                style={{ color: "#4A5568" }}
              >
                Translate to
              </label>
              <select
                id="target-language-select"
                value={targetLanguage}
                onChange={(e) => setTargetLanguage(e.target.value as "es" | "pt")}
                disabled={uploading}
                className="w-full px-3 py-2.5 rounded-md text-sm"
                style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}
              >
                <option value="es">Spanish (Español)</option>
                <option value="pt">Portuguese (Português)</option>
              </select>
            </div>

            {/* Notice */}
            <div className="rounded-md p-3" style={{ background: "#F5EDE0" }}>
              <p className="text-xs leading-relaxed m-0" style={{ color: "#4A5568" }}>
                <strong>Legal documents only.</strong> This system is designed for court forms,
                legal filings, orders, and related documents. Non-legal documents will be rejected.
              </p>
            </div>

            <Button
              id="upload-translate-btn"
              className="w-full cursor-pointer"
              style={{ background: uploading ? "#4A5568" : "#0B1D3A" }}
              disabled={uploading}
              onClick={handleUpload}
            >
              {uploading ? `Uploading… ${uploadProgress}%` : "🔄 Upload and Translate"}
            </Button>

          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="DOCUMENT UPLOAD" />
    </div>
  )
}
