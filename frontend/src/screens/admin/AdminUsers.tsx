/**
 * screens/admin/AdminUsers.tsx
 *
 * User management / registry — renders INSIDE AppShell.
 * Dark-themed with search, user table with inline role editing,
 * status badges, and pagination.
 *
 * Preserved logic: adminApi.listUsers(), adminApi.setUserRole(),
 * in-place role editing, client-side search filter, pagination.
 */

import { useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { adminApi, type AdminUserRow } from "@/services/api"

interface Props { onNav: (s: ScreenId) => void }

const ROLES = ["public", "court_official", "interpreter", "admin"] as const

function formatLastActive(iso: string | null): string {
  if (!iso) return "Never"
  const d = new Date(iso)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000)
  if (diffDays === 0) return "Today"
  if (diffDays === 1) return "Yesterday"
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString([], { month: "short", day: "numeric" })
}

const PAGE_SIZE = 50

export default function AdminUsers({ onNav: _onNav }: Props) {
  const [users, setUsers] = useState<AdminUserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [search, setSearch] = useState("")
  const [editing, setEditing] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)

  async function fetchUsers(p: number) {
    setLoading(true)
    setError(null)
    try {
      const rows = await adminApi.listUsers(p, PAGE_SIZE)
      setUsers(rows)
      setHasMore(rows.length === PAGE_SIZE)
    } catch {
      setError("Failed to load users. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void fetchUsers(page) }, [page])

  async function handleSaveRole(userId: string) {
    const newRole = editing[userId]
    if (!newRole) return
    setSaving(userId)
    try {
      const updated = await adminApi.setUserRole(userId, newRole)
      setUsers((prev) =>
        prev.map((u) => (u.user_id === userId ? { ...u, role: updated.role } : u))
      )
      setEditing((prev) => { const next = { ...prev }; delete next[userId]; return next })
    } catch {
      setError(`Failed to update role for user.`)
    } finally {
      setSaving(null)
    }
  }

  const filtered = search.trim()
    ? users.filter(
        (u) =>
          u.name.toLowerCase().includes(search.toLowerCase()) ||
          u.email.toLowerCase().includes(search.toLowerCase())
      )
    : users

  return (
    <div className="px-6 lg:px-8 py-8 max-w-7xl mx-auto space-y-8">

      {/* Header */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6">
        <div className="max-w-2xl">
          <h1 className="font-headline text-4xl text-on-surface mb-2">User Registry</h1>
          <p className="text-on-surface-variant">Monitor and manage access credentials across the ecosystem.</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-sm">
              search
            </span>
            <input
              type="search"
              placeholder="Search by name or email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-surface-container-high border-none rounded-lg pl-10 pr-4 py-2 w-72 focus:ring-1 focus:ring-secondary text-sm text-on-surface placeholder:text-outline-variant outline-none"
            />
          </div>
        </div>
      </header>

      {/* Error */}
      {error && (
        <div className="rounded-lg px-4 py-3 text-xs bg-red-950 border border-red-900 text-red-300">
          {error}
        </div>
      )}

      {/* Bento stat cards */}
      <section className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-surface-container-low p-6 rounded-xl border border-white/5 shadow-sm">
          <p className="text-xs font-sans uppercase tracking-widest text-on-surface-variant mb-1">Total Users</p>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-headline text-on-surface">{loading ? "—" : filtered.length}</span>
          </div>
        </div>
        <div className="bg-surface-container-low p-6 rounded-xl border border-white/5 shadow-sm">
          <p className="text-xs font-sans uppercase tracking-widest text-on-surface-variant mb-1">Active Now</p>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-headline text-on-surface">
              {loading ? "—" : filtered.filter(u => u.is_active).length}
            </span>
            <span className="flex h-2 w-2 rounded-full bg-secondary-fixed-dim animate-pulse" />
          </div>
        </div>
        <div className="bg-surface-container-low p-6 rounded-xl border border-white/5 shadow-sm">
          <p className="text-xs font-sans uppercase tracking-widest text-on-surface-variant mb-1">Average Sessions</p>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-headline text-on-surface">
              {loading || filtered.length === 0 ? "—" : (filtered.reduce((s, u) => s + u.session_count, 0) / filtered.length).toFixed(1)}
            </span>
          </div>
        </div>
        <div className="bg-tertiary-container/30 p-6 rounded-xl border border-tertiary/10 backdrop-blur-sm">
          <p className="text-xs font-sans uppercase tracking-widest text-tertiary mb-1">System Health</p>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-headline text-tertiary">99.9%</span>
            <span className="material-symbols-outlined text-xs text-tertiary">verified</span>
          </div>
        </div>
      </section>

      {/* User Table */}
      <div className="bg-surface-container-low rounded-xl overflow-hidden shadow-2xl border border-white/5">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-surface-container-highest/50">
              {["User Details", "Role", "Last Active", "Sessions", "Status", "Actions"].map(h => (
                <th key={h} className={`px-6 py-4 text-xs font-sans uppercase tracking-widest text-on-surface-variant font-medium ${
                  h === "Last Active" || h === "Sessions" ? "text-center" : h === "Actions" ? "text-right" : ""
                }`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading && (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-sm text-on-surface-variant">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-sm text-on-surface-variant">
                  {search ? "No users match your search." : "No users found."}
                </td>
              </tr>
            )}
            {!loading && filtered.map((u) => {
              const isEditingThis = u.user_id in editing
              const isSavingThis = saving === u.user_id
              return (
                <tr key={u.user_id} className="hover:bg-surface-bright/30 transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold ${
                        isEditingThis ? "border-2 border-secondary bg-primary-container text-secondary" : "bg-surface-container-highest text-on-surface-variant"
                      }`}>
                        {u.name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-on-surface">{u.name}</p>
                        <p className="text-xs text-on-surface-variant">{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {isEditingThis ? (
                      <select
                        value={editing[u.user_id]}
                        onChange={(e) => setEditing((prev) => ({ ...prev, [u.user_id]: e.target.value }))}
                        className="bg-surface-container-highest border-none rounded text-xs text-secondary-fixed focus:ring-1 focus:ring-secondary py-1 px-2 cursor-pointer appearance-none outline-none"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>{r.replace("_", " ")}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="px-2 py-1 rounded-lg bg-surface-container-high text-xs text-on-surface-variant">
                        {u.role.replace("_", " ")}
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span className="text-xs text-on-surface-variant">{formatLastActive(u.last_login_at)}</span>
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span className="text-xs text-on-surface-variant">{u.session_count}</span>
                  </td>
                  <td className="px-6 py-4">
                    {u.is_active ? (
                      <span className="px-2 py-0.5 rounded-full bg-secondary-fixed/10 text-secondary-fixed text-[10px] font-bold uppercase tracking-tighter">
                        Active
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-outline-variant/20 text-on-surface-variant text-[10px] font-bold uppercase tracking-tighter">
                        Idle
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right">
                    {isEditingThis ? (
                      <div className="flex justify-end gap-2">
                        <button
                          className="text-secondary hover:text-secondary-fixed transition-colors cursor-pointer disabled:opacity-50"
                          disabled={isSavingThis}
                          onClick={() => void handleSaveRole(u.user_id)}
                        >
                          <span className="material-symbols-outlined text-xl">check_circle</span>
                        </button>
                        <button
                          className="text-error hover:text-on-error-container transition-colors cursor-pointer disabled:opacity-50"
                          disabled={isSavingThis}
                          onClick={() => setEditing((prev) => { const next = { ...prev }; delete next[u.user_id]; return next })}
                        >
                          <span className="material-symbols-outlined text-xl">cancel</span>
                        </button>
                      </div>
                    ) : (
                      <button
                        className="text-on-surface-variant hover:text-secondary transition-colors cursor-pointer"
                        onClick={() => setEditing((prev) => ({ ...prev, [u.user_id]: u.role }))}
                      >
                        <span className="material-symbols-outlined text-xl">edit_square</span>
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {/* Table footer with pagination */}
        {!loading && (hasMore || page > 1) && (
          <footer className="px-6 py-4 bg-surface-container-low border-t border-white/5 flex justify-between items-center">
            <p className="text-xs text-on-surface-variant italic font-headline">
              Page {page}
            </p>
            <div className="flex gap-2">
              <button
                className="p-2 rounded hover:bg-surface-container-highest text-on-surface-variant transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <span className="material-symbols-outlined text-sm">chevron_left</span>
              </button>
              <button
                className="p-2 rounded hover:bg-surface-container-highest text-on-surface-variant transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                disabled={!hasMore}
                onClick={() => setPage((p) => p + 1)}
              >
                <span className="material-symbols-outlined text-sm">chevron_right</span>
              </button>
            </div>
          </footer>
        )}
      </div>
    </div>
  )
}
