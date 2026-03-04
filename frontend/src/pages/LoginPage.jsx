/**
 * pages/LoginPage.jsx
 * Handles user authentication with username + password.
 */

import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export default function LoginPage() {
    const { login, isLoading, error } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const from = location.state?.from?.pathname ?? "/dashboard";

    const [form, setForm] = useState({ username: "", password: "" });

    const handleChange = (e) => setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));

    const handleSubmit = async (e) => {
        e.preventDefault();
        const result = await login(form.username, form.password);
        if (result.success) navigate(from, { replace: true });
    };

    return (
        <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div className="card card--glow animate-slide-up" style={{ width: "100%", maxWidth: "440px" }}>
                <div style={{ marginBottom: "var(--space-6)", textAlign: "center" }}>
                    <div style={{ fontSize: "2rem", marginBottom: "var(--space-3)" }}>⚖️</div>
                    <h1 style={{ fontFamily: "var(--font-heading)", fontSize: "1.75rem", fontWeight: 700, color: "var(--color-text)" }}>
                        Welcome back
                    </h1>
                    <p style={{ color: "var(--color-text-muted)", marginTop: "var(--space-2)" }}>
                        Sign in to your CourtAccess account
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
                            <label className="form-label" htmlFor="password">Password</label>
                            <input
                                id="password"
                                name="password"
                                type="password"
                                className="form-input"
                                placeholder="••••••••"
                                value={form.password}
                                onChange={handleChange}
                                required
                                autoComplete="current-password"
                            />
                        </div>

                        <button
                            id="btn-login-submit"
                            type="submit"
                            className="btn btn-primary btn--lg"
                            disabled={isLoading}
                            style={{ marginTop: "var(--space-2)" }}
                        >
                            {isLoading ? <><span className="spinner spinner--sm" /> Signing in…</> : "Sign in"}
                        </button>
                    </div>
                </form>

                <p style={{ marginTop: "var(--space-6)", textAlign: "center", color: "var(--color-text-muted)", fontSize: "0.9375rem" }}>
                    Don't have an account?{" "}
                    <Link to="/register" style={{ color: "var(--color-primary-light)", fontWeight: 500 }}>
                        Create one
                    </Link>
                </p>
            </div>
        </div>
    );
}
