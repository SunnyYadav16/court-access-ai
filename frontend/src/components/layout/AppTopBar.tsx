/**
 * components/layout/AppTopBar.tsx
 *
 * Shared top navigation bar for all authenticated screens.
 * Fixed at the top of the viewport, z-50, height h-16.
 * Shows the brand name and a Sign Out button.
 */

import { useAuth } from "@/hooks/useAuth"

export default function AppTopBar() {
  const { signOut, backendUser } = useAuth()

  return (
    <nav className="bg-[#0D1B2A] fixed top-0 left-0 w-full z-50 flex justify-between items-center px-6 py-3 shadow-xl h-16 border-b border-white/5">
      {/* Brand */}
      <div className="flex items-center gap-2">
        <span className="text-xl font-sans font-black text-[#FFD700] tracking-[0.15em]">
          COURT ACCESS AI
        </span>
      </div>

      {/* Right side: user name + sign out */}
      <div className="flex items-center gap-6">
        {backendUser?.name && (
          <span className="text-sm text-slate-400 hidden md:block">
            {backendUser.name}
          </span>
        )}
        <button
          onClick={signOut}
          className="px-4 py-1.5 bg-[#FFD700] text-[#0D1B2A] text-xs font-bold rounded-md hover:scale-95 active:scale-90 transition-all cursor-pointer"
        >
          Sign Out
        </button>
      </div>
    </nav>
  )
}
