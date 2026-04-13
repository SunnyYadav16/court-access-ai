/**
 * screens/forms/FormsLibrary.tsx
 *
 * Government Forms Library — renders INSIDE AppShell.
 * Dark-themed bento card grid with search, division & language filters,
 * and pagination.
 *
 * Preserved logic: formsApi.list() with dynamic filters, debounced search,
 * division dropdown, session-based form selection, pagination.
 */

import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
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

  // Read search prefill from admin review navigation
  useEffect(() => {
    const prefill = sessionStorage.getItem("forms_search_prefill")
    if (prefill) {
      setSearch(prefill)
      sessionStorage.removeItem("forms_search_prefill")
    }
  }, [])

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
    <div className="px-6 lg:px-12 py-8 max-w-7xl mx-auto relative overflow-hidden">

      {/* Header */}
      <header className="mb-10 relative z-10">
        <h1 className="text-5xl font-headline text-on-surface mb-2">Government Forms Library</h1>
        <p className="text-on-surface-variant font-body text-lg">
          {total} forms available for immediate processing and AI-assisted filing.
        </p>
      </header>

      {/* Filters — bento style row */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-10 relative z-10">
        {/* Search */}
        <div className="lg:col-span-2 bg-surface-container-low p-4 rounded-xl flex items-center gap-3 border border-outline-variant/10">
          <span className="material-symbols-outlined text-on-surface-variant">search</span>
          <input
            className="bg-transparent border-none focus:ring-0 text-on-surface w-full placeholder:text-on-surface-variant/50 outline-none"
            placeholder="Search by form name or ID..."
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Division filter */}
        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/10 relative">
          <select
            className="bg-transparent border-none focus:ring-0 text-on-surface w-full appearance-none cursor-pointer outline-none"
            value={selectedDivision}
            onChange={(e) => handleDivisionChange(e.target.value)}
          >
            <option value="">All Divisions</option>
            {divisions.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-on-surface-variant text-sm">
            expand_more
          </span>
        </div>

        {/* Language filter */}
        <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant/10 relative">
          <select
            className="bg-transparent border-none focus:ring-0 text-on-surface w-full appearance-none cursor-pointer outline-none"
            value={selectedLanguage}
            onChange={(e) => handleLanguageChange(e.target.value)}
          >
            <option value="">All Languages</option>
            <option value="es">Spanish (ES)</option>
            <option value="pt">Portuguese (PT)</option>
          </select>
          <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-on-surface-variant text-sm">
            expand_more
          </span>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex flex-col items-center justify-center py-20">
          <span className="material-symbols-outlined text-4xl text-secondary animate-spin mb-4">autorenew</span>
          <p className="text-on-surface-variant text-sm">Loading forms…</p>
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="bg-error-container/20 border border-error/30 rounded-xl p-8 text-center">
          <span className="material-symbols-outlined text-error text-4xl mb-3 block">cloud_off</span>
          <p className="text-error text-sm">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && forms.length === 0 && (
        <div className="bg-surface-container-low rounded-xl p-12 text-center border border-white/5">
          <span className="material-symbols-outlined text-5xl text-on-surface-variant mb-4 block">search_off</span>
          <p className="text-on-surface-variant">No forms match your search.</p>
        </div>
      )}

      {/* Form cards grid */}
      {!loading && !error && forms.length > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 relative z-10">
            {forms.map((form) => {
              const latest = getLatestVersion(form)
              const division = form.appearances[0]?.division ?? "All Divisions"
              const hasEs = latest?.file_path_es != null
              const hasPt = latest?.file_path_pt != null

              return (
                <div
                  key={form.form_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleFormClick(form)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleFormClick(form) } }}
                  className="group bg-surface-container-low hover:bg-surface-container-high transition-all duration-300 p-6 rounded-xl border border-outline-variant/10 hover:border-secondary/30 flex flex-col justify-between cursor-pointer shadow-sm hover:shadow-xl hover:shadow-black/60"
                >
                  <div>
                    {/* Top row: icon + chevron */}
                    <div className="flex justify-between items-start mb-4">
                      <div className="p-3 bg-primary-container rounded-lg text-secondary">
                        <span className="material-symbols-outlined">assignment</span>
                      </div>
                      <span className="material-symbols-outlined text-on-surface-variant/30 group-hover:text-secondary group-hover:translate-x-1 transition-all">
                        chevron_right
                      </span>
                    </div>

                    {/* Form name */}
                    <h3 className="text-xl font-headline text-on-surface mb-1">{form.form_name}</h3>

                    {/* Badges row */}
                    <div className="flex flex-wrap gap-2 mb-6">
                      {/* Division badge */}
                      <span className="px-2 py-1 bg-primary-fixed/10 text-primary-fixed text-[10px] uppercase font-bold tracking-wider rounded">
                        {division}
                      </span>

                      {/* Status badges */}
                      {form.needs_human_review && (
                        <span className="px-2 py-1 bg-secondary-container/20 text-secondary text-[10px] uppercase font-bold tracking-wider rounded">
                          Pending Review
                        </span>
                      )}
                      {form.status === "archived" && (
                        <span className="px-2 py-1 bg-error-container/20 text-error text-[10px] uppercase font-bold tracking-wider rounded">
                          Archived
                        </span>
                      )}

                      {/* Language tags */}
                      {hasEs && (
                        <span className="px-2 py-1 bg-surface-container-highest text-on-surface-variant text-[10px] uppercase font-bold tracking-wider rounded">
                          ES
                        </span>
                      )}
                      {hasPt && (
                        <span className="px-2 py-1 bg-surface-container-highest text-on-surface-variant text-[10px] uppercase font-bold tracking-wider rounded">
                          PT
                        </span>
                      )}

                      {/* File type */}
                      <span className="px-2 py-1 bg-surface-container-highest text-on-surface-variant text-[10px] uppercase font-bold tracking-wider rounded">
                        {form.file_type.toUpperCase()}
                      </span>
                    </div>
                  </div>

                  {/* Footer */}
                  <div className="flex justify-between items-center text-xs text-on-surface-variant/60 font-medium">
                    <span>Updated {formatDate(form.last_scraped_at)}</span>
                    <span className="flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">verified</span>
                      {form.needs_human_review ? "Unverified" : "Verified"}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="mt-12 flex justify-center items-center gap-4 relative z-10">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors border-none cursor-pointer ${
                  page === 1
                    ? "bg-surface-container-low text-outline-variant opacity-50 cursor-default"
                    : "bg-surface-container-low border border-outline-variant/10 text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                <span className="material-symbols-outlined">keyboard_arrow_left</span>
              </button>
              <span className="text-on-surface-variant text-sm">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors border-none cursor-pointer ${
                  page === totalPages
                    ? "bg-surface-container-low text-outline-variant opacity-50 cursor-default"
                    : "bg-surface-container-low border border-outline-variant/10 text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                <span className="material-symbols-outlined">keyboard_arrow_right</span>
              </button>
            </div>
          )}
        </>
      )}

      {/* Decorative glow */}
      <div className="fixed bottom-0 right-0 w-96 h-96 bg-secondary/5 blur-[120px] rounded-full -mr-48 -mb-48 pointer-events-none" />
    </div>
  )
}
