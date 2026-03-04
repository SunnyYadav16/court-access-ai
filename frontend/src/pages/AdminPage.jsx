/**
 * pages/AdminPage.jsx
 * Admin / court official panel — form review queue and system stats.
 * Accessible only to court_official and admin roles.
 */

import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { formsApi, documentsApi } from "@/services/api";

export default function AdminPage() {
    const { hasRole, isAuthenticated } = useAuth();
    const navigate = useNavigate();

    // Redirect non-authorised users
    useEffect(() => {
        if (isAuthenticated && !hasRole("court_official", "admin")) {
            navigate("/dashboard", { replace: true });
        }
    }, [isAuthenticated, hasRole, navigate]);

    // Forms pending review
    const { data: reviewForms, isLoading: loadingForms } = useQuery({
        queryKey: ["forms", "pending-review"],
        queryFn: () => formsApi.list({ status: "active", page_size: 20 }),
        enabled: hasRole("court_official", "admin"),
    });

    // Pending documents
    const { data: pendingDocs, isLoading: loadingDocs } = useQuery({
        queryKey: ["documents", "pending"],
        queryFn: () => documentsApi.list(1, 20),
        enabled: hasRole("court_official", "admin"),
    });

    const pendingDocCount = pendingDocs?.items?.filter((d) => d.status === "pending" || d.status === "processing").length ?? 0;
    const reviewFormCount = reviewForms?.items?.filter((f) => f.needs_human_review).length ?? 0;

    return (
        <div className="page">
            <div className="container">
                <div className="page__header">
                    <h1 className="page__title">Admin Panel</h1>
                    <p className="page__subtitle">Form review queue and system overview.</p>
                </div>

                {/* Stats cards */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)", marginBottom: "var(--space-8)" }}>
                    {[
                        { label: "Forms Awaiting Review", value: reviewFormCount, color: "var(--color-warn)", icon: "📋" },
                        { label: "Docs In Progress", value: pendingDocCount, color: "var(--color-primary-light)", icon: "📄" },
                    ].map(({ label, value, color, icon }) => (
                        <div key={label} className="card" style={{ textAlign: "center" }}>
                            <div style={{ fontSize: "2.5rem", marginBottom: "var(--space-2)" }}>{icon}</div>
                            <div style={{ fontSize: "2.5rem", fontWeight: 800, color, fontFamily: "var(--font-heading)", marginBottom: "var(--space-1)" }}>
                                {value}
                            </div>
                            <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>{label}</p>
                        </div>
                    ))}
                </div>

                {/* Form review queue */}
                <section style={{ marginBottom: "var(--space-8)" }}>
                    <h2 style={{ fontFamily: "var(--font-heading)", fontSize: "1.25rem", marginBottom: "var(--space-4)" }}>
                        Form Review Queue
                    </h2>
                    {loadingForms ? (
                        <div className="loading-center"><div className="spinner" /></div>
                    ) : reviewForms?.items?.filter((f) => f.needs_human_review).length === 0 ? (
                        <div className="alert alert--success">✅ All forms have been reviewed</div>
                    ) : (
                        <div className="table-wrapper">
                            <table>
                                <thead>
                                    <tr><th>Form Name</th><th>Division</th><th>Languages</th><th>Action</th></tr>
                                </thead>
                                <tbody>
                                    {reviewForms?.items?.filter((f) => f.needs_human_review).map((form) => (
                                        <tr key={form.form_id}>
                                            <td style={{ fontWeight: 500 }}>{form.form_name}</td>
                                            <td style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                                                {form.divisions?.join(", ") ?? "—"}
                                            </td>
                                            <td>
                                                <div style={{ display: "flex", gap: "var(--space-1)" }}>
                                                    {form.has_spanish && <span className="badge badge--accent">ES</span>}
                                                    {form.has_portuguese && <span className="badge badge--primary">PT</span>}
                                                </div>
                                            </td>
                                            <td>
                                                <a href={`/forms/${form.form_id}`} className="btn btn-secondary btn--sm">Review →</a>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
}
