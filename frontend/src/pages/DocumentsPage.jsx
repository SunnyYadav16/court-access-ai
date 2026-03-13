/**
 * pages/DocumentsPage.jsx
 * List of the current user's document translation requests.
 */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { documentsApi } from "@/services/api";

const STATUS_BADGE = {
    pending: "badge--warn",
    processing: "badge--warn",
    translated: "badge--accent",
    approved: "badge--accent",
    rejected: "badge--danger",
    error: "badge--danger",
};

export default function DocumentsPage() {
    const { data, isLoading, error } = useQuery({
        queryKey: ["documents"],
        queryFn: () => documentsApi.list(1, 50),
    });

    return (
        <div className="page">
            <div className="container">
                <div className="page__header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                        <h1 className="page__title">My Documents</h1>
                        <p className="page__subtitle">Track your document translation submissions.</p>
                    </div>
                    <Link to="/documents/upload" className="btn btn-primary" id="btn-upload-new">
                        + Upload Document
                    </Link>
                </div>

                {isLoading && (
                    <div className="loading-center">
                        <div className="spinner" />
                        <p>Loading documents…</p>
                    </div>
                )}

                {error && (
                    <div className="alert alert--error">{error.message}</div>
                )}

                {data?.items?.length === 0 && (
                    <div className="card" style={{ textAlign: "center", padding: "var(--space-12)" }}>
                        <div style={{ fontSize: "3rem", marginBottom: "var(--space-4)" }}>📄</div>
                        <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "1.25rem", marginBottom: "var(--space-3)" }}>No documents yet</h3>
                        <p style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-5)" }}>
                            Upload a court form PDF to get a multilingual translation.
                        </p>
                        <Link to="/documents/upload" className="btn btn-primary">Upload your first document</Link>
                    </div>
                )}

                {data?.items?.length > 0 && (
                    <div className="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>File</th>
                                    <th>Status</th>
                                    <th>Languages</th>
                                    <th>Uploaded</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.items.map((doc) => (
                                    <tr key={doc.document_id}>
                                        <td style={{ fontWeight: 500 }}>{doc.original_filename}</td>
                                        <td>
                                            <span className={`badge ${STATUS_BADGE[doc.status] ?? "badge--muted"}`}>
                                                {doc.status}
                                            </span>
                                        </td>
                                        <td style={{ color: "var(--color-text-muted)" }}>
                                            {doc.target_languages?.join(", ") ?? "—"}
                                        </td>
                                        <td style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                                            {new Date(doc.created_at).toLocaleDateString()}
                                        </td>
                                        <td>
                                            <Link to={`/documents/${doc.document_id}`} className="btn btn-ghost btn--sm">
                                                View →
                                            </Link>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}
