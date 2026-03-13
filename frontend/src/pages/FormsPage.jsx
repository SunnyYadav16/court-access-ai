/**
 * pages/FormsPage.jsx
 * Public searchable catalog of Massachusetts court forms.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formsApi } from "@/services/api";

export default function FormsPage() {
    const [search, setSearch] = useState("");
    const [division, setDivision] = useState("");
    const [language, setLanguage] = useState("");
    const [input, setInput] = useState("");

    const { data: divisionsData } = useQuery({
        queryKey: ["divisions"],
        queryFn: formsApi.divisions,
        staleTime: Infinity,
    });

    const { data, isLoading } = useQuery({
        queryKey: ["forms", search, division, language],
        queryFn: () =>
            formsApi.list({ q: search || undefined, division: division || undefined, language: language || undefined }),
        keepPreviousData: true,
    });

    const handleSearch = (e) => {
        e.preventDefault();
        setSearch(input);
    };

    return (
        <div className="page">
            <div className="container">
                <div className="page__header">
                    <h1 className="page__title">Court Form Catalog</h1>
                    <p className="page__subtitle">Search Massachusetts court forms — Spanish &amp; Portuguese availability included.</p>
                </div>

                {/* Search + filters */}
                <form onSubmit={handleSearch} style={{ display: "flex", gap: "var(--space-3)", marginBottom: "var(--space-6)", flexWrap: "wrap" }}>
                    <input
                        id="forms-search"
                        type="search"
                        className="form-input"
                        placeholder="Search by name or keyword…"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        style={{ flex: "2", minWidth: "220px" }}
                    />
                    <select
                        id="forms-division"
                        className="form-select"
                        value={division}
                        onChange={(e) => setDivision(e.target.value)}
                        style={{ flex: "1", minWidth: "160px" }}
                    >
                        <option value="">All Divisions</option>
                        {(divisionsData ?? []).map((d) => <option key={d} value={d}>{d}</option>)}
                    </select>
                    <select
                        id="forms-language"
                        className="form-select"
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                        style={{ flex: "1", minWidth: "140px" }}
                    >
                        <option value="">Any language</option>
                        <option value="es">Español</option>
                        <option value="pt">Português</option>
                    </select>
                    <button type="submit" className="btn btn-primary" id="btn-forms-search">Search</button>
                    {(search || division || language) && (
                        <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => { setSearch(""); setDivision(""); setLanguage(""); setInput(""); }}
                        >
                            Clear
                        </button>
                    )}
                </form>

                {isLoading && <div className="loading-center"><div className="spinner" /></div>}

                {data && (
                    <>
                        <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem", marginBottom: "var(--space-4)" }}>
                            {data.total} form{data.total !== 1 ? "s" : ""} found
                        </p>
                        <div style={{ display: "grid", gap: "var(--space-4)", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
                            {data.items.map((form) => (
                                <Link key={form.form_id} to={`/forms/${form.form_id}`} style={{ textDecoration: "none" }}>
                                    <div className="card card--glow" style={{ height: "100%", display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                                        <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "1rem", fontWeight: 600, color: "var(--color-text)" }}>
                                            {form.form_name}
                                        </h3>
                                        {form.divisions?.length > 0 && (
                                            <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>{form.divisions.join(" · ")}</p>
                                        )}
                                        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "auto" }}>
                                            {form.has_spanish && <span className="badge badge--accent">ES</span>}
                                            {form.has_portuguese && <span className="badge badge--primary">PT</span>}
                                            {form.needs_human_review && <span className="badge badge--warn">Pending review</span>}
                                        </div>
                                    </div>
                                </Link>
                            ))}
                        </div>
                    </>
                )}

                {data?.items?.length === 0 && (
                    <div className="card" style={{ textAlign: "center", padding: "var(--space-12)" }}>
                        <p style={{ color: "var(--color-text-muted)" }}>No forms match your search. Try different keywords.</p>
                    </div>
                )}
            </div>
        </div>
    );
}
