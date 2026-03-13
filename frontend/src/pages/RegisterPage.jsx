/**
 * pages/RegisterPage.jsx
 * New user registration form.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

const LANGUAGES = [
    { value: "en", label: "English" },
    { value: "es", label: "Español" },
    { value: "pt", label: "Português" },
];

export default function RegisterPage() {
    const { register, isLoading, error } = useAuth();
    const navigate = useNavigate();

    const [form, setForm] = useState({
        username: "",
        email: "",
        password: "",
        preferred_language: "en",
    });
    const [success, setSuccess] = useState(false);

    const handleChange = (e) => setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));

    const handleSubmit = async (e) => {
        e.preventDefault();
        const result = await register(form);
        if (result.success) {
            setSuccess(true);
            setTimeout(() => navigate("/login"), 2000);
        }
    };

    if (success) {
        return (
            <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div className="card animate-slide-up" style={{ textAlign: "center", maxWidth: 440 }}>
                    <div style={{ fontSize: "3rem", marginBottom: "var(--space-4)" }}>✅</div>
                    <h2 style={{ fontFamily: "var(--font-heading)", fontSize: "1.5rem", marginBottom: "var(--space-3)" }}>Account created!</h2>
                    <p style={{ color: "var(--color-text-muted)" }}>Redirecting you to login…</p>
                </div>
            </div>
        );
    }

    return (
        <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div className="card card--glow animate-slide-up" style={{ width: "100%", maxWidth: "480px" }}>
                <div style={{ marginBottom: "var(--space-6)", textAlign: "center" }}>
                    <div style={{ fontSize: "2rem", marginBottom: "var(--space-3)" }}>⚖️</div>
                    <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.75rem", fontWeight: 700 }}>
                        Create your account
                    </h1>
                    <p style={{ color: "var(--color-text-muted)", marginTop: "var(--space-2)" }}>
                        Free access to court interpretation & document translation
                    </p>
                </div>

                {error && <div className="alert alert--error" style={{ marginBottom: "var(--space-4)" }}>{error}</div>}

                <form onSubmit={handleSubmit} noValidate>
                    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                        <div className="form-group">
                            <label className="form-label" htmlFor="username">Username</label>
                            <input
                                id="username"
                                name="username"
                                type="text"
                                className="form-input"
                                placeholder="your_username"
                                value={form.username}
                                onChange={handleChange}
                                required
                                autoComplete="username"
                            />
                        </div>

                        <div className="form-group">
                            <label className="form-label" htmlFor="email">Email</label>
                            <input
                                id="email"
                                name="email"
                                type="email"
                                className="form-input"
                                placeholder="you@example.com"
                                value={form.email}
                                onChange={handleChange}
                                required
                                autoComplete="email"
                            />
                        </div>

                        <div className="form-group">
                            <label className="form-label" htmlFor="password">Password</label>
                            <input
                                id="password"
                                name="password"
                                type="password"
                                className="form-input"
                                placeholder="Min. 8 characters"
                                value={form.password}
                                onChange={handleChange}
                                required
                                minLength={8}
                                autoComplete="new-password"
                            />
                        </div>

                        <div className="form-group">
                            <label className="form-label" htmlFor="preferred_language">Preferred Language</label>
                            <select
                                id="preferred_language"
                                name="preferred_language"
                                className="form-select"
                                value={form.preferred_language}
                                onChange={handleChange}
                            >
                                {LANGUAGES.map((l) => (
                                    <option key={l.value} value={l.value}>{l.label}</option>
                                ))}
                            </select>
                        </div>

                        <button
                            id="btn-register-submit"
                            type="submit"
                            className="btn btn-primary btn--lg"
                            disabled={isLoading}
                            style={{ marginTop: "var(--space-2)" }}
                        >
                            {isLoading ? <><span className="spinner spinner--sm" /> Creating account…</> : "Create account"}
                        </button>
                    </div>
                </form>

                <p style={{ marginTop: "var(--space-6)", textAlign: "center", color: "var(--color-text-muted)", fontSize: "0.9375rem" }}>
                    Already registered?{" "}
                    <Link to="/login" style={{ color: "var(--color-primary-light)", fontWeight: 500 }}>Sign in</Link>
                </p>
            </div>
        </div>
    );
}
