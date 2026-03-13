/**
 * pages/DocumentStatusPage.jsx
 * Shows translation status for a specific document, with auto-polling.
 */

import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { documentsApi } from "@/services/api";

const STEPS = ["pending", "processing", "translated", "approved"];
const STEP_LABEL = { pending: "Queued", processing: "Translating", translated: "Translated", approved: "Approved" };

function ProgressStepper({ status }) {
    const current = STEPS.indexOf(status);
    return (
        <div style={{ display: "flex", gap: 0, marginBottom: "var(--space-8)" }}>
            {STEPS.map((s, i) => (
                <div key={s} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "var(--space-2)" }}>
                    <div style={{
                        width: 32, height: 32, borderRadius: "50%",
                        background: i <= current ? "var(--color-primary)" : "var(--color-surface-2)",
                        border: `2px solid ${i <= current ? "var(--color-primary)" : "var(--color-border)"}`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: "0.8125rem", fontWeight: 600,
                        color: i <= current ? "#fff" : "var(--color-text-faint)",
                        transition: "all 0.3s",
                    }}>
                        {i < current ? "✓" : i + 1}
                    </div>
                    <span style={{ fontSize: "0.75rem", color: i <= current ? "var(--color-text)" : "var(--color-text-faint)" }}>
                        {STEP_LABEL[s]}
                    </span>
                </div>
            ))}
        </div>
    );
}

export default function DocumentStatusPage() {
    const { id } = useParams();

    const { data: doc, isLoading, error } = useQuery({
        queryKey: ["document", id],
        queryFn: () => documentsApi.status(id),
        // Auto-poll while pending/processing
        refetchInterval: (query) => {
            const s = query.state.data?.status;
            return s === "pending" || s === "processing" ? 4000 : false;
        },
    });

    if (isLoading) {
        return <div className="loading-center page"><div className="spinner spinner--lg" /><p>Loading…</p></div>;
    }
    if (error) {
        return <div className="page"><div className="container"><div className="alert alert--error">{error.message}</div></div></div>;
    }

    return (
        <div className="page">
            <div className="container container--narrow">
                <div style={{ marginBottom: "var(--space-4)" }}>
                    <Link to="/documents" style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>← My Documents</Link>
                </div>

                <div className="card animate-fade">
                    <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.5rem", fontWeight: 700, marginBottom: "var(--space-2)" }}>
                        {doc?.original_filename}
                    </h1>
                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem", marginBottom: "var(--space-6)" }}>
                        Document ID: <code style={{ color: "var(--color-primary-light)" }}>{id}</code>
                    </p>

                    {doc?.status && !["error", "rejected"].includes(doc.status) && (
                        <ProgressStepper status={doc.status} />
                    )}

                    {doc?.status === "error" && (
                        <div className="alert alert--error" style={{ marginBottom: "var(--space-5)" }}>
                            ❌ {doc.error_message ?? "Translation failed. Please try re-uploading."}
                        </div>
                    )}

                    {doc?.status === "rejected" && (
                        <div className="alert alert--warn" style={{ marginBottom: "var(--space-5)" }}>
                            ⚠️ Document rejected during review. Please contact your courthouse team.
                        </div>
                    )}

                    {/* Translation download links */}
                    {doc?.translated_uris && Object.entries(doc.translated_uris).length > 0 && (
                        <div style={{ marginBottom: "var(--space-5)" }}>
                            <h3 style={{ fontFamily: "var(--font-heading)", fontWeight: 600, marginBottom: "var(--space-3)" }}>
                                Translated Files
                            </h3>
                            <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                                {Object.entries(doc.translated_uris).map(([lang, uri]) => (
                                    <a key={lang} href={uri} className="btn btn-secondary" target="_blank" rel="noopener noreferrer">
                                        📥 {lang.toUpperCase()} Translation
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Metadata */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", paddingTop: "var(--space-5)", borderTop: "1px solid var(--color-border)" }}>
                        {[
                            ["Status", <span className="badge badge--primary">{doc?.status}</span>],
                            ["Submitted", doc?.created_at ? new Date(doc.created_at).toLocaleString() : "—"],
                            ["Languages", doc?.target_languages?.join(", ") ?? "—"],
                            ["File size", doc?.file_size_bytes ? `${(doc.file_size_bytes / 1024).toFixed(0)} KB` : "—"],
                        ].map(([label, val]) => (
                            <div key={label}>
                                <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)", marginBottom: "2px" }}>{label}</p>
                                <p style={{ fontWeight: 500 }}>{val}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
