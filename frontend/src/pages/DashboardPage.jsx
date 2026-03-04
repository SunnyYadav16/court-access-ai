/**
 * pages/DashboardPage.jsx
 * Authenticated user's home screen with quick-action cards.
 */

import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useQuery } from "@tanstack/react-query";
import { documentsApi, sessionsApi } from "@/services/api";

export default function DashboardPage() {
    const { user } = useAuth();

    const { data: docs } = useQuery({
        queryKey: ["documents"],
        queryFn: () => documentsApi.list(1, 5),
        enabled: !!user,
    });

    return (
        <div className="page">
            <div className="container">
                <div className="page__header">
                    <h1 className="page__title">
                        Welcome back, {user?.username ?? "…"} 👋
                    </h1>
                    <p className="page__subtitle">
                        Role: <span className="badge badge--primary">{user?.role ?? "—"}</span>
                    </p>
                </div>

                {/* Quick actions */}
                <div className="feature-grid" style={{ marginBottom: "var(--space-10)" }}>
                    <Link to="/sessions/new" className="feature-card" style={{ textDecoration: "none", cursor: "pointer" }}>
                        <div className="feature-icon">🎙️</div>
                        <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-2)", color: "var(--color-text)" }}>
                            New Session
                        </h3>
                        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9375rem" }}>
                            Start a real-time court interpretation session.
                        </p>
                    </Link>

                    <Link to="/documents/upload" className="feature-card" style={{ textDecoration: "none" }}>
                        <div className="feature-icon">📄</div>
                        <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-2)", color: "var(--color-text)" }}>
                            Upload Document
                        </h3>
                        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9375rem" }}>
                            Submit a PDF court form for multilingual translation.
                        </p>
                    </Link>

                    <Link to="/forms" className="feature-card" style={{ textDecoration: "none" }}>
                        <div className="feature-icon">📚</div>
                        <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-2)", color: "var(--color-text)" }}>
                            Browse Forms
                        </h3>
                        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9375rem" }}>
                            Search the Massachusetts court form catalog.
                        </p>
                    </Link>
                </div>

                {/* Recent documents */}
                {docs?.items?.length > 0 && (
                    <section>
                        <h2 style={{ fontFamily: "var(--font-heading)", fontSize: "1.25rem", marginBottom: "var(--space-4)" }}>
                            Recent Documents
                        </h2>
                        <div className="table-wrapper">
                            <table>
                                <thead>
                                    <tr>
                                        <th>File</th>
                                        <th>Status</th>
                                        <th>Uploaded</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {docs.items.map((doc) => (
                                        <tr key={doc.document_id}>
                                            <td>
                                                <Link to={`/documents/${doc.document_id}`}>{doc.original_filename}</Link>
                                            </td>
                                            <td>
                                                <span className={`badge badge--${doc.status === "translated" ? "accent" : doc.status === "error" ? "danger" : "warn"}`}>
                                                    {doc.status}
                                                </span>
                                            </td>
                                            <td style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                                                {new Date(doc.created_at).toLocaleDateString()}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <Link to="/documents" style={{ display: "inline-block", marginTop: "var(--space-3)", color: "var(--color-primary-light)", fontSize: "0.9375rem" }}>
                            View all documents →
                        </Link>
                    </section>
                )}
            </div>
        </div>
    );
}
