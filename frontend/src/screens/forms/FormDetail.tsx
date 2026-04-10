import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
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

function BackButton({ onNav }: { onNav: (s: ScreenId) => void }) {
  return (
    <button
      onClick={() => onNav(SCREENS.FORMS_LIBRARY)}
      className="text-xs font-medium mb-4 flex items-center gap-1 cursor-pointer"
      style={{ color: "#2563eb", background: "none", border: "none" }}
    >
      ← Back to Forms Library
    </button>
  )
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

  if (loading) {
    return (
      <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
        <TopBar onNav={onNav} />
        <div className="max-w-lg mx-auto px-5 py-8">
          <div className="text-sm text-center py-12" style={{ color: "#8494A7" }}>
            Loading form...
          </div>
        </div>
        <ScreenLabel name="FORM DETAIL — DOWNLOAD" />
      </div>
    )
  }

  if (error || !form) {
    return (
      <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
        <TopBar onNav={onNav} />
        <div className="max-w-lg mx-auto px-5 py-8">
          <BackButton onNav={onNav} />
          <div className="text-sm text-center py-12" style={{ color: "#dc2626" }}>
            {error ?? "Form not found."}
          </div>
        </div>
        <ScreenLabel name="FORM DETAIL — DOWNLOAD" />
      </div>
    )
  }

  const latest = getLatestVersion(form)
  const division = form.appearances[0]?.division ?? "—"

  const downloads = [
    {
      lang: "English (Original)",
      flag: "🇺🇸",
      signedUrl: latest?.signed_url_original ?? null,
      label: latest ? `Download ${latest.file_type.toUpperCase()}` : "Download",
    },
    {
      lang: "Spanish (Español)",
      flag: "🇪🇸",
      signedUrl: latest?.signed_url_es ?? null,
      label: latest?.file_type_es ? `Download ${latest.file_type_es.toUpperCase()}` : "Download",
    },
    {
      lang: "Portuguese (Português)",
      flag: "🇧🇷",
      signedUrl: latest?.signed_url_pt ?? null,
      label: latest?.file_type_pt ? `Download ${latest.file_type_pt.toUpperCase()}` : "Download",
    },
  ]

  const details: [string, string][] = [
    ["Source", getHostname(form.source_url)],
    ["Division", division],
    ["Version", String(form.current_version)],
    ["Content Hash", `${form.content_hash.slice(0, 8)}...${form.content_hash.slice(-4)}`],
    ["File Type", form.file_type.toUpperCase()],
    ["First Added", formatDate(form.created_at)],
    ["Last Updated", formatDate(form.last_scraped_at ?? form.created_at)],
    ["Status", form.status.charAt(0).toUpperCase() + form.status.slice(1)],
  ]

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-lg mx-auto px-5 py-8">
        <BackButton onNav={onNav} />

        <h1
          className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          {form.form_name}
        </h1>
        <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
          {division} · Version {form.current_version} · Last updated {formatDate(form.last_scraped_at)}
        </p>

        <Card className="mb-3">
          <CardContent className="p-5">
            {form.needs_human_review && (
              <div
                className="rounded-md p-3 mb-4"
                style={{ background: "#FEF3C7", border: "1px solid #FDE68A" }}
              >
                <p className="text-xs m-0" style={{ color: "#92400e" }}>
                  <strong>⚠ Machine-translated</strong> — Pending human verification.
                  Use with caution for legal proceedings.
                </p>
              </div>
            )}

            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Available Downloads
            </div>
            <div className="flex flex-col gap-2">
              {downloads.map((d) => (
                <div
                  key={d.lang}
                  className="flex items-center justify-between px-3 py-2.5 rounded-md"
                  style={{ border: "1px solid #E2E6EC" }}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{d.flag}</span>
                    <span className="text-sm" style={{ color: "#1A2332" }}>{d.lang}</span>
                  </div>
                  {d.signedUrl
                    ? (
                      <Button
                        size="sm"
                        className="cursor-pointer"
                        style={{ background: "#0B1D3A" }}
                        onClick={() => window.open(d.signedUrl!, "_blank")}
                      >
                        ⬇ {d.label}
                      </Button>
                    )
                    : (
                      <span className="text-xs" style={{ color: "#8494A7" }}>Not available</span>
                    )
                  }
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>Form Details</div>
            {details.map(([k, v], i) => (
              <div
                key={k}
                className="flex justify-between text-xs py-1.5"
                style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}
              >
                <span style={{ color: "#8494A7" }}>{k}</span>
                <span style={{ color: "#1A2332" }}>{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="FORM DETAIL — DOWNLOAD" />
    </div>
  )
}
