/**
 * pages/NewSessionPage.jsx
 * Configure and create a new real-time interpretation session.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { sessionsApi } from "@/services/api";

const LANGUAGES = [
    { value: "es", label: "Español (Spanish)" },
    { value: "pt", label: "Português (Portuguese)" },
];

export default function NewSessionPage() {
    const navigate = useNavigate();
    const [targetLanguage, setTargetLanguage] = useState("es");
    const [isCreating, setIsCreating] = useState(false);
    const [error, setError] = useState(null);

    const handleCreate = async () => {
        setIsCreating(true);
        setError(null);
        try {
            const session = await sessionsApi.create(targetLanguage, "en");
            navigate(`/sessions/${session.session_id}`);
        } catch (err) {
            setError(err.response?.data?.detail ?? "Failed to create session");
            setIsCreating(false);
        }
    };

    return (
        <div className="page" style={{ display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "5rem" }}>
            <div className="card card--glow animate-slide-up" style={{ width: "100%", maxWidth: "500px" }}>
                <div style={{ marginBottom: "var(--space-6)" }}>
                    <div style={{ fontSize: "2.5rem", marginBottom: "var(--space-3)" }}>🎙️</div>
                    <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.75rem", fontWeight: 700 }}>
                        New Interpretation Session
                    </h1>
                    <p style={{ color: "var(--color-text-muted)", marginTop: "var(--space-2)" }}>
                        English audio will be translated live into your chosen language.
                    </p>
                </div>

                {error && <div className="alert alert--error" style={{ marginBottom: "var(--space-4)" }}>{error}</div>}

                <div className="form-group" style={{ marginBottom: "var(--space-6)" }}>
                    <label className="form-label" htmlFor="target-language">Interpretation Language</label>
                    <select
                        id="target-language"
                        className="form-select"
                        value={targetLanguage}
                        onChange={(e) => setTargetLanguage(e.target.value)}
                    >
                        {LANGUAGES.map((l) => (
                            <option key={l.value} value={l.value}>{l.label}</option>
                        ))}
                    </select>
                </div>

                <div style={{ display: "flex", gap: "var(--space-3)" }}>
                    <button
                        id="btn-create-session"
                        className="btn btn-primary btn--lg"
                        onClick={handleCreate}
                        disabled={isCreating}
                        style={{ flex: 1 }}
                    >
                        {isCreating ? <><span className="spinner spinner--sm" /> Creating…</> : "Start Session"}
                    </button>
                    <button className="btn btn-ghost" onClick={() => navigate(-1)}>
                        Cancel
                    </button>
                </div>

                <div className="alert alert--info" style={{ marginTop: "var(--space-5)" }}>
                    <span>ℹ️</span>
                    <span>Allow microphone access when prompted. Audio is processed on-premise and never stored without your consent.</span>
                </div>
            </div>
        </div>
    );
}
