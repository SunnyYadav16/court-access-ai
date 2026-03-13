/**
 * pages/NotFoundPage.jsx
 * 404 page for unmatched routes.
 */

import { Link } from "react-router-dom";

export default function NotFoundPage() {
    return (
        <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1 }}>
            <div style={{ textAlign: "center", maxWidth: "480px" }} className="animate-slide-up">
                <div style={{ fontSize: "6rem", fontFamily: "var(--font-heading)", fontWeight: 800, color: "var(--color-primary)", lineHeight: 1, marginBottom: "var(--space-4)" }}>
                    404
                </div>
                <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.75rem", fontWeight: 700, marginBottom: "var(--space-3)" }}>
                    Page Not Found
                </h1>
                <p style={{ color: "var(--color-text-muted)", fontSize: "1.0625rem", marginBottom: "var(--space-8)", lineHeight: 1.65 }}>
                    The page you're looking for doesn't exist, or you may not have permission to view it.
                </p>
                <div style={{ display: "flex", gap: "var(--space-3)", justifyContent: "center", flexWrap: "wrap" }}>
                    <Link to="/" className="btn btn-primary" id="btn-404-home">Back to Home</Link>
                    <Link to="/forms" className="btn btn-secondary" id="btn-404-forms">Browse Court Forms</Link>
                </div>
            </div>
        </div>
    );
}
