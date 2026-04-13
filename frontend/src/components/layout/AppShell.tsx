/**
 * components/layout/AppShell.tsx
 *
 * Layout wrapper for all authenticated screens.
 * Composes the fixed TopBar + fixed Sidebar + scrollable content area.
 *
 * Screens rendered inside AppShell should NOT render their own nav — only
 * their <main> content area.
 */

import type { ReactNode } from "react"
import type { ScreenId, UserRole } from "@/lib/constants"
import AppTopBar from "./AppTopBar"
import AppSidebar from "./AppSidebar"

interface AppShellProps {
  children: ReactNode
  current: ScreenId
  onNav: (s: ScreenId) => void
  role: UserRole | null
}

export default function AppShell({ children, current, onNav, role }: AppShellProps) {
  return (
    <div className="min-h-screen bg-background text-on-surface font-body">
      <AppTopBar />
      <AppSidebar current={current} onNav={onNav} role={role} />

      {/* Main content — offset for fixed sidebar (w-64 = 16rem) and topbar (h-16 = 4rem) */}
      <main className="lg:ml-64 pt-16 min-h-screen">
        {children}
      </main>
    </div>
  )
}
