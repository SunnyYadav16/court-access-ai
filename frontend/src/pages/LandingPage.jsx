/**
 * pages/LandingPage.jsx
 *
 * Public home page — hero, feature grid, language support highlights, CTAs.
 */

import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

const FEATURES = [
    { icon: "🎙️", title: "Real-Time Interpretation", desc: "Stream audio and receive translated transcripts instantly via WebSocket — no interpreter needed in the room." },
    { icon: "📄", title: "Document Translation", desc: "Upload court forms and legal documents as PDFs. Get multilingual translations reviewed by AI and human experts." },
    { icon: "📚", title: "Court Form Catalog", desc: "Browse the Massachusetts court form catalog with full Spanish and Portuguese availability markers." },
    { icon: "🔒", title: "Privacy-First", desc: "PII detection before translation, audit logs, end-to-end encryption. Built for courthouse compliance." },
    { icon: "🌍", title: "Spanish & Portuguese", desc: "Optimised for the two largest LEP populations in Massachusetts courthouses." },
    { icon: "⚡", title: "Instant Results", desc: "Powered by NLLB-200, Whisper, and Groq — on-premise models for sub-second latency." },
];

export default function LandingPage() {
    const { isAuthenticated } = useAuth();

    return (
        <div style={{ minHeight: "85vh" }}>
            {/* ── Hero section ── */}
            <section
                style={{
                    position: "relative",
                    overflow: "hidden",
                    padding: "var(--space-20) var(--space-6)",
                    textAlign: "center",
                }}
            >
                <div className="hero-orb hero-orb--1" aria-hidden />
                <div className="hero-orb hero-orb--2" aria-hidden />

                <div className="container container--narrow" style={{ position: "relative", zIndex: 1 }}>
                    <div className="badge badge--accent" style={{ display: "inline-flex", marginBottom: "var(--space-5)" }}>
                        ✨ AI-Powered Court Access
                    </div>

                    <h1
                        className="page__title animate-slide-up"
                        style={{ fontSize: "clamp(2.25rem, 5vw, 3.5rem)", marginBottom: "var(--space-5)" }}
                    >
                        Justice Speaks Every Language
                    </h1>

                    <p
                        style={{
                            fontSize: "1.1875rem",
                            color: "var(--color-text-muted)",
                            maxWidth: "560px",
                            margin: "0 auto var(--space-8)",
                            lineHeight: "1.65",
                        }}
                        className="animate-slide-up"
                    >
                        Real-time court interpretation and document translation for limited English proficiency
                        individuals — powered by open-source AI, built for Massachusetts courthouses.
                    </p>

                    <div style={{ display: "flex", gap: "var(--space-4)", justifyContent: "center", flexWrap: "wrap" }}>
                        {isAuthenticated ? (
                            <>
                                <Link to="/sessions/new" className="btn btn-primary btn--lg" id="btn-start-session">
                                    🎙️ Start Interpretation
                                </Link>
                                <Link to="/documents/upload" className="btn btn-secondary btn--lg" id="btn-upload-doc">
                                    📄 Translate Document
                                </Link>
                            </>
                        ) : (
                            <>
                                <Link to="/register" className="btn btn-primary btn--lg" id="btn-cta-register">
                                    Get Started — It's Free
                                </Link>
                                <Link to="/forms" className="btn btn-secondary btn--lg" id="btn-browse-forms">
                                    Browse Court Forms
                                </Link>
                            </>
                        )}
                    </div>

                    {/* Language badges */}
                    <div style={{ marginTop: "var(--space-8)", display: "flex", gap: "var(--space-3)", justifyContent: "center", flexWrap: "wrap" }}>
                        {["English", "Español", "Português"].map((lang) => (
                            <span key={lang} className="badge badge--muted" style={{ fontSize: "0.875rem", padding: "0.4rem 0.875rem" }}>
                                {lang}
                            </span>
                        ))}
                    </div>
                </div>
            </section>

            {/* ── Features ── */}
            <section style={{ padding: "var(--space-10) var(--space-6) var(--space-16)" }}>
                <div className="container">
                    <h2
                        style={{
                            fontFamily: "var(--font-heading)",
                            fontSize: "2rem",
                            fontWeight: 700,
                            textAlign: "center",
                            marginBottom: "var(--space-10)",
                            color: "var(--color-text)",
                        }}
                    >
                        Everything a courthouse needs
                    </h2>

                    <div className="feature-grid">
                        {FEATURES.map((f) => (
                            <div key={f.title} className="feature-card">
                                <div className="feature-icon">{f.icon}</div>
                                <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-2)" }}>
                                    {f.title}
                                </h3>
                                <p style={{ color: "var(--color-text-muted)", lineHeight: "1.65", fontSize: "0.9375rem" }}>
                                    {f.desc}
                                </p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>
        </div>
    );
}
