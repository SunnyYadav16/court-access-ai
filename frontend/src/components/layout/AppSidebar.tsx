/**
 * components/layout/AppSidebar.tsx
 *
 * Shared sidebar for all authenticated screens.
 * Role-based navigation — items are filtered by the current user's role.
 * Active state is derived from the `current` screen prop.
 *
 * Desktop-only layout (hidden on < lg breakpoint).
 */

import { useState, useEffect } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import type { UserRole } from "@/lib/constants"

// ── Types ──────────────────────────────────────────────────────────────────

interface NavItem {
  icon: string
  label: string
  screen: ScreenId
  roles: UserRole[]
  children?: NavItem[]
}

interface Props {
  current: ScreenId
  onNav: (s: ScreenId) => void
  role: UserRole | null
}

// ── Role → Home screen mapping ─────────────────────────────────────────────

const ROLE_HOME: Record<UserRole, ScreenId> = {
  public:         SCREENS.HOME_PUBLIC,
  court_official: SCREENS.HOME_OFFICIAL,
  interpreter:    SCREENS.HOME_INTERPRETER,
  admin:          SCREENS.HOME_ADMIN,
}

// ── Role → Sidebar heading ─────────────────────────────────────────────────

const ROLE_LABEL: Record<UserRole, string> = {
  public:         "Public Access",
  court_official: "Court Official Access",
  interpreter:    "Interpreter Access",
  admin:          "Administrator",
}

// ── Navigation config ──────────────────────────────────────────────────────

const NAV_ITEMS: NavItem[] = [
  {
    icon: "dashboard",
    label: "Dashboard",
    screen: SCREENS.HOME_PUBLIC, // overridden at render time via ROLE_HOME
    roles: ["public", "court_official", "interpreter", "admin"],
  },
  {
    icon: "upload_file",
    label: "Upload Document",
    screen: SCREENS.DOC_UPLOAD,
    roles: ["public", "court_official", "interpreter", "admin"],
    children: [
      { icon: "history_edu", label: "Translation History", screen: SCREENS.DOC_HISTORY, roles: ["public", "court_official", "interpreter", "admin"] },
    ],
  },
  {
    icon: "interpreter_mode",
    label: "Start Session",
    screen: SCREENS.REALTIME_SETUP,
    roles: ["court_official", "admin"],
  },
  {
    icon: "translate",
    label: "Translation Review",
    screen: SCREENS.INTERPRETER_REVIEW,
    roles: ["interpreter", "admin"],
  },
  {
    icon: "description",
    label: "Government Forms",
    screen: SCREENS.FORMS_LIBRARY,
    roles: ["public", "court_official", "interpreter", "admin"],
  },
  {
    icon: "history",
    label: "Recent Sessions",
    screen: SCREENS.RECENT_SESSIONS,
    roles: ["public", "court_official", "interpreter", "admin"],
  },
  {
    icon: "settings_suggest",
    label: "Admin Tools",
    screen: SCREENS.ADMIN_DASHBOARD,
    roles: ["admin"],
    children: [
      { icon: "", label: "Overview",        screen: SCREENS.ADMIN_DASHBOARD, roles: ["admin"] },
      { icon: "", label: "User Management", screen: SCREENS.ADMIN_USERS,     roles: ["admin"] },
      { icon: "", label: "Form Scraper",    screen: SCREENS.ADMIN_FORMS,     roles: ["admin"] },
    ],
  },
]

const BOTTOM_ITEMS: NavItem[] = [
  {
    icon: "person",
    label: "Profile",
    screen: SCREENS.SETTINGS,
    roles: ["public", "court_official", "interpreter", "admin"],
  },
]

// ── Active state helpers ───────────────────────────────────────────────────

/** Screens that should highlight the "Dashboard" nav item */
const HOME_SCREENS = new Set<ScreenId>([
  SCREENS.HOME_PUBLIC,
  SCREENS.HOME_OFFICIAL,
  SCREENS.HOME_INTERPRETER,
  SCREENS.HOME_ADMIN,
])

function isActive(item: NavItem, current: ScreenId): boolean {
  if (item.label === "Dashboard" && HOME_SCREENS.has(current)) return true
  if (item.children) return item.screen === current || item.children.some((c) => c.screen === current)
  return item.screen === current
}

// ── Component ──────────────────────────────────────────────────────────────

export default function AppSidebar({ current, onNav, role }: Props) {
  // Generic expandable-menu state — auto-opens when a child screen is active
  const [openMenus, setOpenMenus] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = { "Admin Tools": true }
    for (const item of NAV_ITEMS) {
      if (item.children) {
        const match = current === item.screen || item.children.some((c) => c.screen === current)
        if (match) init[item.label] = true
      }
    }
    return init
  })

  // Auto-open menus when navigating to a matching child screen
  useEffect(() => {
    setOpenMenus((prev) => {
      const next = { ...prev }
      let changed = false
      for (const item of NAV_ITEMS) {
        if (item.children) {
          const match = current === item.screen || item.children.some((c) => c.screen === current)
          if (match && !prev[item.label]) {
            next[item.label] = true
            changed = true
          }
        }
      }
      return changed ? next : prev
    })
  }, [current])

  const effectiveRole: UserRole = role ?? "public"
  const visibleItems  = NAV_ITEMS.filter((item) => item.roles.includes(effectiveRole))
  const visibleBottom = BOTTOM_ITEMS.filter((item) => item.roles.includes(effectiveRole))

  function handleNav(item: NavItem) {
    if (item.label === "Dashboard") {
      onNav(ROLE_HOME[effectiveRole])
    } else {
      onNav(item.screen)
    }
  }

  const activeClass   = "bg-[#132233] text-[#FFD700] border-l-4 border-[#FFD700] font-semibold"
  const inactiveClass = "text-slate-400 hover:bg-[#132233]/50 hover:text-white border-l-4 border-transparent"

  return (
    <aside className="fixed left-0 top-0 h-full w-64 bg-[#0D1B2A] flex-col pt-20 pb-6 shadow-2xl z-40 hidden lg:flex">

      {/* Branding + role label */}
      <div className="px-6 mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-lg bg-[#132233] flex items-center justify-center border border-slate-700">
            <span
              className="material-symbols-outlined text-[#FFD700]"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              gavel
            </span>
          </div>
          <h2 className="font-headline text-lg text-[#FFD700] leading-tight">
            CourtAccess AI
          </h2>
        </div>
        <p className="text-[10px] font-sans text-slate-400 uppercase tracking-widest mt-1">
          {ROLE_LABEL[effectiveRole]}
        </p>
      </div>

      {/* ── Main nav ──────────────────────────────────────────────── */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto">
        {visibleItems.map((item) => {
          const active = isActive(item, current)

          // ── Expandable submenu item ────────────────────────────
          if (item.children) {
            const menuOpen = openMenus[item.label] ?? false
            // If parent screen is NOT duplicated in children, clicking parent also navigates
            const parentNavigates = !item.children.some((c) => c.screen === item.screen)

            return (
              <div key={item.label}>
                <button
                  aria-expanded={menuOpen}
                  onClick={() => {
                    if (parentNavigates) {
                      onNav(item.screen)
                      setOpenMenus((prev) => ({ ...prev, [item.label]: true }))
                    } else {
                      setOpenMenus((prev) => ({ ...prev, [item.label]: !menuOpen }))
                    }
                  }}
                  className={`w-full flex items-center justify-between px-4 py-3 transition-all duration-300 cursor-pointer ${
                    active ? activeClass : inactiveClass
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="material-symbols-outlined"
                      style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
                    >
                      {item.icon}
                    </span>
                    <span className="text-sm font-sans">{item.label}</span>
                  </div>
                  <span
                    role="button"
                    tabIndex={-1}
                    onClick={(e) => {
                      e.stopPropagation()
                      setOpenMenus((prev) => ({ ...prev, [item.label]: !menuOpen }))
                    }}
                    className={`material-symbols-outlined text-sm transition-transform ${
                      menuOpen ? "rotate-180" : ""
                    }`}
                  >
                    expand_more
                  </span>
                </button>

                {menuOpen && (
                  <div className="ml-4 mt-1 space-y-0.5 border-l border-[#FFD700]/30">
                    {item.children
                      .filter((c) => c.roles.includes(effectiveRole))
                      .map((child) => {
                        const childActive = child.screen === current
                        return (
                          <button
                            key={child.label}
                            onClick={() => onNav(child.screen)}
                            className={`w-full flex items-center gap-3 text-xs py-2 px-6 transition-all cursor-pointer ${
                              childActive
                                ? "bg-secondary/10 text-secondary-fixed border-l-2 border-[#FFD700] font-medium"
                                : "text-slate-400 hover:text-[#FFD700] border-l-2 border-transparent"
                            }`}
                          >
                            {child.icon && (
                              <span
                                className="material-symbols-outlined text-sm"
                                style={childActive ? { fontVariationSettings: "'FILL' 1" } : undefined}
                              >
                                {child.icon}
                              </span>
                            )}
                            <span className="font-sans">{child.label}</span>
                          </button>
                        )
                      })}
                  </div>
                )}
              </div>
            )
          }

          // ── Regular nav item ──────────────────────────────────
          return (
            <button
              key={item.label}
              onClick={() => handleNav(item)}
              className={`w-full flex items-center gap-3 px-4 py-3 transition-all duration-300 cursor-pointer ${
                active ? activeClass : inactiveClass
              }`}
            >
              <span
                className="material-symbols-outlined"
                style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
              >
                {item.icon}
              </span>
              <span className="text-sm font-sans">{item.label}</span>
            </button>
          )
        })}
      </nav>

      {/* ── Bottom section ────────────────────────────────────── */}
      <div className="mt-auto pt-4 border-t border-slate-700/50 space-y-1">
        {visibleBottom.map((item) => (
          <button
            key={item.label}
            onClick={() => handleNav(item)}
            className={`w-full flex items-center gap-3 px-4 py-2 transition-all duration-300 cursor-pointer ${
              item.screen === current
                ? "text-[#FFD700]"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <span className="material-symbols-outlined text-xl">{item.icon}</span>
            <span className="text-sm font-sans">{item.label}</span>
          </button>
        ))}

        {/* Support — no screen target yet */}
        <button className="w-full flex items-center gap-3 px-4 py-2 text-slate-400 hover:text-white transition-all cursor-pointer">
          <span className="material-symbols-outlined text-xl">contact_support</span>
          <span className="text-sm font-sans">Support</span>
        </button>
      </div>
    </aside>
  )
}
