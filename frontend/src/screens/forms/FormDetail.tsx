/**
 * screens/forms/FormDetail.tsx
 *
 * Form detail / download screen — renders INSIDE AppShell.
 * Dark-themed with download rows, form metadata sidebar,
 * and machine translation warning.
 *
 * Preserved logic: formsApi.get() via sessionStorage form_id,
 * download signed URLs, version resolution.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { formsApi, FormResponse, FormVersionResponse } from "@/services/api"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

function getHostname(url: string): string {
  try { return new URL(url).hostname } catch { return url }
}

function getLatestVersion(form: FormResponse): FormVersionResponse | null {
  if (!form.versions.length) return null
  return form.versions.reduce((a, b) => a.version > b.version ? a : b)
}

export default function FormDetail({ onNav }: Props) {
  const [form, setForm] = useState<FormResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const formId = sessionStorage.getItem("selected_form_id")
    if (!formId) {
      setError("No form selected. Please go back and choose a form.")
      setLoading(false)
      return
    }
    let cancelled = false
    formsApi
      .get(formId)
      .then((data) => {
        if (cancelled) return
        setForm(data)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Failed to load form. Please go back and try again.")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  // ── Loading state ────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="px-6 lg:px-12 py-8 max-w-5xl mx-auto">
        <div className="flex flex-col items-center justify-center py-20">
          <span className="material-symbols-outlined text-4xl text-secondary animate-spin mb-4">autorenew</span>
          <p className="text-on-surface-variant text-sm">Loading form…</p>
        </div>
      </div>
    )
  }

  // ── Error state ──────────────────────────────────────────────────────────────

  if (error || !form) {
    return (
      <div className="px-6 lg:px-12 py-8 max-w-5xl mx-auto space-y-6">
        {/* Back button */}
        <button
          onClick={() => onNav(SCREENS.FORMS_LIBRARY)}
          className="flex items-center gap-2 text-on-surface-variant hover:text-secondary transition-colors text-sm group bg-transparent border-none cursor-pointer"
        >
          <span className="material-symbols-outlined text-[18px] group-hover:-translate-x-1 transition-transform">
            arrow_back
          </span>
          Back to Forms Library
        </button>

        <div className="bg-error-container/20 border border-error/30 rounded-xl p-8 text-center">
          <span className="material-symbols-outlined text-error text-4xl mb-3 block">error_outline</span>
          <p className="text-error text-sm">{error ?? "Form not found."}</p>
        </div>
      </div>
    )
  }

  // ── Data ──────────────────────────────────────────────────────────────────────

  const latest = getLatestVersion(form)
  const division = form.appearances[0]?.division ?? "—"

  const downloads = [
    {
      lang: "English (Original)",
      icon: "description",
      iconBg: "bg-primary-container",
      iconColor: "text-primary",
      signedUrl: latest?.signed_url_original ?? null,
      label: latest ? `Download ${latest.file_type.toUpperCase()}` : "Download",
      isPrimary: true,
    },
    {
      lang: "Spanish (Español)",
      icon: "translate",
      iconBg: "bg-tertiary-container",
      iconColor: "text-tertiary",
      signedUrl: latest?.signed_url_es ?? null,
      label: latest?.file_type_es ? `Download ${latest.file_type_es.toUpperCase()}` : "Download",
      isPrimary: false,
    },
    {
      lang: "Portuguese (Português)",
      icon: "translate",
      iconBg: "bg-tertiary-container",
      iconColor: "text-tertiary",
      signedUrl: latest?.signed_url_pt ?? null,
      label: latest?.file_type_pt ? `Download ${latest.file_type_pt.toUpperCase()}` : "Download",
      isPrimary: false,
    },
  ]

  const details: { label: string; value: string }[] = [
    { label: "Source", value: getHostname(form.source_url) },
    { label: "Division", value: division },
    { label: "Version", value: String(form.current_version) },
    { label: "Content Hash", value: `${form.content_hash.slice(0, 8)}…${form.content_hash.slice(-4)}` },
    { label: "File Type", value: form.file_type.toUpperCase() },
    { label: "First Added", value: formatDate(form.created_at) },
    { label: "Last Updated", value: formatDate(form.last_scraped_at ?? form.created_at) },
    { label: "Status", value: form.status.charAt(0).toUpperCase() + form.status.slice(1) },
  ]

  return (
    <div className="px-6 lg:px-12 py-8 max-w-5xl mx-auto space-y-8 relative z-10">

      {/* Back button */}
      <button
        onClick={() => onNav(SCREENS.FORMS_LIBRARY)}
        className="flex items-center gap-2 text-on-surface-variant hover:text-secondary transition-colors text-sm group bg-transparent border-none cursor-pointer"
      >
        <span className="material-symbols-outlined text-[18px] group-hover:-translate-x-1 transition-transform">
          arrow_back
        </span>
        Back to Forms Library
      </button>

      {/* Header */}
      <div className="space-y-2">
        <h1 className="text-4xl md:text-5xl font-headline font-bold text-on-surface tracking-tight">
          {form.form_name}
        </h1>
        <p className="text-on-surface-variant font-body text-sm md:text-base">
          {division} · Version {form.current_version} · Last updated {formatDate(form.last_scraped_at ?? form.created_at)}
        </p>
      </div>

      {/* Bento grid layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">

        {/* ── Main content (left column) ──────────────────────────────── */}
        <div className="lg:col-span-8 space-y-6">

          {/* Warning alert */}
          {form.needs_human_review && (
            <div className="bg-amber-500/10 border-l-4 border-amber-500 p-6 rounded-r-lg flex gap-4">
              <span
                className="material-symbols-outlined text-amber-500"
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                warning
              </span>
              <div className="space-y-1">
                <h4 className="text-amber-500 font-bold text-sm uppercase tracking-wider">
                  Pending Human Review
                </h4>
                <p className="text-on-surface text-sm leading-relaxed">
                  The translated versions of this form have not yet been reviewed by a licensed
                  legal professional. They may be used for reference but should not be submitted
                  for official court proceedings without verification.
                </p>
              </div>
            </div>
          )}

          {/* Available Downloads */}
          <div className="bg-surface-container-low rounded-xl overflow-hidden shadow-inner border border-white/5">
            <div className="px-6 py-4 bg-surface-container-high flex items-center justify-between">
              <h3 className="font-headline text-xl text-on-surface">Available Downloads</h3>
              <span className="text-xs uppercase tracking-widest text-on-surface-variant font-bold">
                {downloads.filter((d) => d.signedUrl).length} Available
              </span>
            </div>
            <div className="divide-y divide-white/5">
              {downloads.map((d) => (
                <div
                  key={d.lang}
                  className="p-6 flex items-center justify-between hover:bg-surface-bright/20 transition-colors group"
                >
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 ${d.iconBg} rounded flex items-center justify-center ${d.iconColor} group-hover:scale-110 transition-transform`}>
                      <span className="material-symbols-outlined text-3xl">{d.icon}</span>
                    </div>
                    <div>
                      <p className="font-semibold text-on-surface">{d.lang}</p>
                      <p className="text-xs text-on-surface-variant">
                        {d.signedUrl
                          ? d.isPrimary
                            ? "Standard Document"
                            : form.needs_human_review
                              ? "AI Translated · Pending Review"
                              : "AI Translated · Verified"
                          : "Not available"}
                      </p>
                      {!d.isPrimary && form.needs_human_review && d.signedUrl && (
                        <span className="text-[10px] font-bold text-amber-400 flex items-center gap-1 mt-0.5">
                          <span className="material-symbols-outlined text-[10px]">pending</span>
                          Pending Human Review
                        </span>
                      )}
                    </div>
                  </div>
                  {d.signedUrl ? (
                    <button
                      onClick={() => window.open(d.signedUrl!, "_blank")}
                      className={`px-5 py-2.5 rounded-lg text-sm font-bold flex items-center gap-2 transition-all border-none cursor-pointer ${
                        d.isPrimary
                          ? "bg-[#FFD700] text-[#0D1B2A] hover:brightness-110"
                          : "border border-[#FFD700]/30 text-[#FFD700] hover:bg-[#FFD700]/10"
                      }`}
                      style={d.isPrimary ? undefined : { border: "1px solid rgba(255, 215, 0, 0.3)", background: "transparent" }}
                    >
                      <span className="material-symbols-outlined text-sm">download</span>
                      {d.label}
                    </button>
                  ) : (
                    <span className="text-xs text-on-surface-variant italic">Not available</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Sidebar (right column) ──────────────────────────────────── */}
        <div className="lg:col-span-4 space-y-6">

          {/* Form Details */}
          <div className="bg-surface-container-low p-8 rounded-xl border border-white/5 space-y-8">
            <h3 className="font-headline text-2xl text-on-surface">Form Details</h3>
            <div className="space-y-5">
              {details.map((d) => (
                <div key={d.label} className="space-y-1">
                  <label className="text-[10px] uppercase tracking-[0.2em] text-on-surface-variant font-bold">
                    {d.label}
                  </label>
                  <p className="text-on-surface font-medium text-sm">{d.value}</p>
                </div>
              ))}
            </div>
            <hr className="border-white/5" />
            <div className="space-y-4">
              <p className="text-xs text-on-surface-variant leading-relaxed">
                Documents are scanned for security. Hash: {form.content_hash.slice(0, 6)}…{form.content_hash.slice(-4)}
              </p>
              <a
                href={form.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full text-[#FFD700] text-xs font-bold uppercase tracking-widest flex items-center justify-center gap-2 hover:underline"
              >
                <span className="material-symbols-outlined text-sm">open_in_new</span>
                View Original Source
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
