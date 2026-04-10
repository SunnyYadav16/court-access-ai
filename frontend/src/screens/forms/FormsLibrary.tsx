import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { formsApi, FormResponse } from "@/services/api"
import { formatDate } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const PAGE_SIZE = 20

function getLatestVersion(form: FormResponse) {
  if (!form.versions.length) return null
  return form.versions.reduce((a, b) => a.version > b.version ? a : b)
}

export default function FormsLibrary({ onNav }: Props) {
  const [forms, setForms] = useState<FormResponse[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [divisions, setDivisions] = useState<string[]>([])
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [selectedDivision, setSelectedDivision] = useState("")
  const [selectedLanguage, setSelectedLanguage] = useState<"es" | "pt" | "">("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Non-fatal if it fails — dropdown falls back to "All Divisions" only
  useEffect(() => {
    formsApi.divisions().then(setDivisions).catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    formsApi
      .list({
        q: debouncedSearch || undefined,
        division: selectedDivision || undefined,
        language: selectedLanguage || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      .then((data) => {
        if (cancelled) return
        setForms(data.items)
        setTotal(data.total)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Failed to load forms. Please try again.")
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [debouncedSearch, selectedDivision, selectedLanguage, page])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const makeFilterSetter = (setter: (v: string) => void) => (v: string) => {
    setter(v)
    setPage(1)
  }
  const handleDivisionChange = makeFilterSetter(setSelectedDivision)
  const handleLanguageChange = makeFilterSetter((v) => setSelectedLanguage(v as "es" | "pt" | ""))

  const handleFormClick = (form: FormResponse) => {
    sessionStorage.setItem("selected_form_id", form.form_id)
    onNav(SCREENS.FORM_DETAIL)
  }

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-2xl mx-auto px-5 py-8">
        <h1
          className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          Government Forms Library
        </h1>
        <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
          Pre-translated Massachusetts court forms · {total} forms available
        </p>

        {/* Filters */}
        <div className="flex gap-2 mb-4">
          <div className="flex-1">
            <Input
              placeholder="🔍 Search forms..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            className="px-3 py-2 rounded-md text-xs"
            style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}
            value={selectedDivision}
            onChange={(e) => handleDivisionChange(e.target.value)}
          >
            <option value="">All Divisions</option>
            {divisions.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <select
            className="px-3 py-2 rounded-md text-xs"
            style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}
            value={selectedLanguage}
            onChange={(e) => handleLanguageChange(e.target.value)}
          >
            <option value="">All Languages</option>
            <option value="es">Spanish</option>
            <option value="pt">Portuguese</option>
          </select>
        </div>

        {/* Form list */}
        {loading ? (
          <div className="text-sm text-center py-12" style={{ color: "#8494A7" }}>
            Loading forms...
          </div>
        ) : error ? (
          <div className="text-sm text-center py-12" style={{ color: "#dc2626" }}>
            {error}
          </div>
        ) : forms.length === 0 ? (
          <div className="text-sm text-center py-12" style={{ color: "#8494A7" }}>
            No forms match your search.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {forms.map((form) => {
              const latest = getLatestVersion(form)
              const division = form.appearances[0]?.division ?? "All Divisions"
              const hasEs = latest?.file_path_es != null
              const hasPt = latest?.file_path_pt != null
              return (
                <Card
                  key={form.form_id}
                  onClick={() => handleFormClick(form)}
                  className="cursor-pointer hover:shadow-md transition-shadow"
                >
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-xl" style={{ color: "#8494A7" }}>📋</span>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium" style={{ color: "#1A2332" }}>
                            {form.form_name}
                          </span>
                          {form.needs_human_review && (
                            <span
                              className="text-[10px] font-semibold px-2 py-0.5 rounded"
                              style={{ background: "#FEF3C7", color: "#d97706" }}
                            >
                              PENDING REVIEW
                            </span>
                          )}
                          {form.status === "archived" && (
                            <span
                              className="text-[10px] font-semibold px-2 py-0.5 rounded"
                              style={{ background: "#FEE2E2", color: "#dc2626" }}
                            >
                              ARCHIVED
                            </span>
                          )}
                        </div>
                        <div
                          className="text-[11px] mt-0.5 flex items-center gap-1 flex-wrap"
                          style={{ color: "#8494A7" }}
                        >
                          <span>{division}</span>
                          <span>·</span>
                          <span>Updated {formatDate(form.last_scraped_at)}</span>
                          <span>·</span>
                          {hasEs && (
                            <span
                              className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                              style={{ background: "#E5E7EB", color: "#4A5568" }}
                            >
                              ES
                            </span>
                          )}
                          {hasPt && (
                            <span
                              className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                              style={{ background: "#E5E7EB", color: "#4A5568" }}
                            >
                              PT
                            </span>
                          )}
                          <span
                            className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                            style={{ background: "#E5E7EB", color: "#4A5568" }}
                          >
                            {form.file_type.toUpperCase()}
                          </span>
                        </div>
                      </div>
                    </div>
                    <span style={{ color: "#8494A7" }}>›</span>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between mt-6">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="text-xs font-medium px-3 py-1.5 rounded"
              style={{
                border: "1.5px solid #E2E6EC",
                color: page === 1 ? "#8494A7" : "#1A2332",
                background: "#fff",
                cursor: page === 1 ? "default" : "pointer",
                opacity: page === 1 ? 0.5 : 1,
              }}
            >
              ← Previous
            </button>
            <span className="text-xs" style={{ color: "#8494A7" }}>
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="text-xs font-medium px-3 py-1.5 rounded"
              style={{
                border: "1.5px solid #E2E6EC",
                color: page === totalPages ? "#8494A7" : "#1A2332",
                background: "#fff",
                cursor: page === totalPages ? "default" : "pointer",
                opacity: page === totalPages ? 0.5 : 1,
              }}
            >
              Next →
            </button>
          </div>
        )}
      </div>
      <ScreenLabel name="GOVERNMENT FORMS LIBRARY" />
    </div>
  )
}
