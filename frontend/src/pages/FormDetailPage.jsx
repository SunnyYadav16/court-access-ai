/**
 * pages/FormDetailPage.jsx
 * Court form detail view with version history and translation download links.
 */

import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formsApi } from "@/services/api";
import { useAuth } from "@/hooks/useAuth";

export default function FormDetailPage() {
    const { id } = useParams();
    const { hasRole } = useAuth();

    const { data: form, isLoading, error } = useQuery({
        queryKey: ["form", id],
        queryFn: () => formsApi.get(id),
    });

    if (isLoading) {
        return <div className="loading-center page"><div className="spinner spinner--lg" /></div>;
    }
    if (error) {
        return (
            <div className="page"><div className="container">
                <div className="alert alert--error">{error.message}</div>
                <Link to="/forms" className="btn btn-ghost" style={{ marginTop: "var(--space-4)" }}>← Back to Forms</Link>
            </div></div>
        );
    }

    return (
        <div className="page">
            <div className="container container--narrow">
                <div style={{ marginBottom: "var(--space-5)" }}>
                    <Link to="/forms" style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>← Court Form Catalog</Link>
                </div>

                <div className="card animate-fade">
                    {/* Header */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-4)", marginBottom: "var(--space-5)" }}>
                        <div>
                            <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.5rem", fontWeight: 700, marginBottom: "var(--space-2)" }}>
                                {form?.form_name}
                            </h1>
                            <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                                <span className={`badge ${form?.status === "active" ? "badge--accent" : "badge--muted"}`}>
                                    {form?.status}
                                </span>
                                {form?.has_spanish && <span className="badge badge--primary">Español disponible</span>}
                                {form?.has_portuguese && <span className="badge badge--primary">Português disponível</span>}
                                {form?.needs_human_review && <span className="badge badge--warn">⏳ Pending review</span>}
                            </div>
                        </div>
                        <a
                            href={form?.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="btn btn-secondary btn--sm"
                        >
                            Official PDF ↗
                        </a>
                    </div>

                    {/* Division / version metadata */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", padding: "var(--space-4) 0", borderTop: "1px solid var(--color-border)", borderBottom: "1px solid var(--color-border)", marginBottom: "var(--space-5)" }}>
                        {[
                            ["Divisions", form?.divisions?.join(", ") || "—"],
                            ["Current version", form?.current_version ?? "—"],
                            ["Languages", form?.languages_available?.join(", ") ?? "—"],
                            ["Last scraped", form?.last_scraped_at ? new Date(form.last_scraped_at).toLocaleDateString() : "—"],
                        ].map(([label, val]) => (
                            <div key={label}>
                                <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)", marginBottom: "2px" }}>{label}</p>
                                <p style={{ fontWeight: 500 }}>{val}</p>
                            </div>
                        ))}
                    </div>

                    {/* Version history */}
                    {form?.versions_json?.length > 0 && (
                        <div style={{ marginBottom: "var(--space-5)" }}>
                            <h3 style={{ fontFamily: "var(--font-heading)", fontWeight: 600, marginBottom: "var(--space-3)" }}>Version History</h3>
                            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                                {form.versions_json.map((v) => (
                                    <div key={v.version} style={{ display: "flex", justifyContent: "space-between", padding: "var(--space-2) var(--space-3)", background: "var(--color-surface-2)", borderRadius: "var(--radius)", fontSize: "0.875rem" }}>
                                        <span style={{ fontWeight: 500 }}>v{v.version}</span>
                                        <span style={{ color: "var(--color-text-muted)" }}>{v.scraped_at ? new Date(v.scraped_at).toLocaleDateString() : ""}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Admin review action */}
                    {hasRole("court_official", "admin") && (
                        <div className="alert alert--info">
                            <span>🔐</span>
                            <span>
                                As a court official, you can submit a review decision.{" "}
                                <Link to="#" style={{ color: "var(--color-primary-light)", fontWeight: 500 }}>
                                    Review this form →
                                </Link>
                            </span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
