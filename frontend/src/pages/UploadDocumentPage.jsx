/**
 * pages/UploadDocumentPage.jsx
 * PDF upload form with drag-and-drop and progress indicator.
 */

import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { documentsApi } from "@/services/api";

const SUPPORTED_LANGUAGES = [
    { code: "es", label: "Spanish (Español)" },
    { code: "pt", label: "Portuguese (Português)" },
];

export default function UploadDocumentPage() {
    const navigate = useNavigate();
    const fileInputRef = useRef(null);

    const [file, setFile] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [langs, setLangs] = useState(["es"]);
    const [notes, setNotes] = useState("");
    const [progress, setProgress] = useState(0);
    const [isUploading, setIsUploading] = useState(false);
    const [error, setError] = useState(null);

    const validateFile = (f) => {
        if (!f) return "No file selected.";
        if (f.type !== "application/pdf") return "Only PDF files are accepted.";
        if (f.size > 20 * 1024 * 1024) return "File must be smaller than 20 MB.";
        return null;
    };

    const pickFile = (f) => {
        const err = validateFile(f);
        if (err) { setError(err); return; }
        setFile(f);
        setError(null);
    };

    const onDrop = useCallback((e) => {
        e.preventDefault();
        setIsDragging(false);
        pickFile(e.dataTransfer.files[0]);
    }, []);

    const onDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
    const onDragLeave = () => setIsDragging(false);

    const toggleLang = (code) =>
        setLangs((prev) => prev.includes(code) ? prev.filter((l) => l !== code) : [...prev, code]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        const err = validateFile(file);
        if (err) { setError(err); return; }
        if (langs.length === 0) { setError("Select at least one target language."); return; }

        setIsUploading(true);
        setError(null);
        try {
            const result = await documentsApi.upload(file, langs, notes || null, setProgress);
            navigate(`/documents/${result.document_id}`);
        } catch (err) {
            setError(err.response?.data?.detail ?? "Upload failed. Please try again.");
            setIsUploading(false);
        }
    };

    return (
        <div className="page">
            <div className="container container--narrow">
                <div className="page__header">
                    <h1 className="page__title">Upload Document</h1>
                    <p className="page__subtitle">Upload a court form PDF for AI-powered multilingual translation.</p>
                </div>

                {error && <div className="alert alert--error" style={{ marginBottom: "var(--space-5)" }}>{error}</div>}

                <form onSubmit={handleSubmit}>
                    <div className="card" style={{ marginBottom: "var(--space-5)" }}>
                        {/* Drop zone */}
                        <div
                            id="drop-zone"
                            onClick={() => fileInputRef.current?.click()}
                            onDrop={onDrop}
                            onDragOver={onDragOver}
                            onDragLeave={onDragLeave}
                            style={{
                                border: `2px dashed ${isDragging ? "var(--color-primary)" : "var(--color-border-strong)"}`,
                                borderRadius: "var(--radius-lg)",
                                padding: "var(--space-10)",
                                textAlign: "center",
                                cursor: "pointer",
                                transition: "border-color var(--transition), background var(--transition)",
                                background: isDragging ? "rgba(99,102,241,0.06)" : "transparent",
                            }}
                        >
                            <div style={{ fontSize: "3rem", marginBottom: "var(--space-3)" }}>
                                {file ? "📄" : "☁️"}
                            </div>
                            {file ? (
                                <div>
                                    <p style={{ fontWeight: 600, marginBottom: "var(--space-1)" }}>{file.name}</p>
                                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                                        {(file.size / 1024).toFixed(0)} KB — click to replace
                                    </p>
                                </div>
                            ) : (
                                <div>
                                    <p style={{ fontWeight: 500, marginBottom: "var(--space-2)" }}>
                                        Drag & drop a PDF, or click to browse
                                    </p>
                                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                                        PDF only · max 20 MB
                                    </p>
                                </div>
                            )}
                        </div>
                        <input
                            ref={fileInputRef}
                            id="file-input"
                            type="file"
                            accept="application/pdf,application/x-pdf"
                            style={{ display: "none" }}
                            onChange={(e) => pickFile(e.target.files[0])}
                        />
                    </div>

                    {/* Language selection */}
                    <div className="card" style={{ marginBottom: "var(--space-5)" }}>
                        <h3 style={{ fontFamily: "var(--font-heading)", fontWeight: 600, marginBottom: "var(--space-4)" }}>
                            Target Languages
                        </h3>
                        <div style={{ display: "flex", gap: "var(--space-4)" }}>
                            {SUPPORTED_LANGUAGES.map(({ code, label }) => (
                                <label
                                    key={code}
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "var(--space-2)",
                                        cursor: "pointer",
                                        padding: "0.5rem var(--space-4)",
                                        borderRadius: "var(--radius)",
                                        border: `1px solid ${langs.includes(code) ? "var(--color-primary)" : "var(--color-border)"}`,
                                        background: langs.includes(code) ? "rgba(99,102,241,0.12)" : "transparent",
                                        transition: "all var(--transition)",
                                        userSelect: "none",
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={langs.includes(code)}
                                        onChange={() => toggleLang(code)}
                                        style={{ accentColor: "var(--color-primary)" }}
                                    />
                                    {label}
                                </label>
                            ))}
                        </div>
                    </div>

                    {/* Notes */}
                    <div className="form-group card" style={{ marginBottom: "var(--space-5)" }}>
                        <label className="form-label" htmlFor="submitter-notes">Notes (optional)</label>
                        <textarea
                            id="submitter-notes"
                            className="form-textarea"
                            rows={3}
                            placeholder="Any context the reviewer should know about this document…"
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            maxLength={500}
                        />
                    </div>

                    {/* Progress bar */}
                    {isUploading && (
                        <div style={{ marginBottom: "var(--space-5)" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.875rem", marginBottom: "var(--space-2)", color: "var(--color-text-muted)" }}>
                                <span>Uploading…</span><span>{progress}%</span>
                            </div>
                            <div style={{ background: "var(--color-surface-2)", borderRadius: "var(--radius-full)", height: "6px" }}>
                                <div style={{ width: `${progress}%`, background: "var(--color-primary)", borderRadius: "var(--radius-full)", height: "100%", transition: "width 0.3s" }} />
                            </div>
                        </div>
                    )}

                    <div style={{ display: "flex", gap: "var(--space-3)" }}>
                        <button
                            id="btn-submit-upload"
                            type="submit"
                            className="btn btn-primary btn--lg"
                            disabled={isUploading || !file}
                            style={{ flex: 1 }}
                        >
                            {isUploading ? "Uploading…" : "Submit for Translation"}
                        </button>
                        <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>Cancel</button>
                    </div>
                </form>
            </div>
        </div>
    );
}
