import { useEffect, useRef } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getInitials } from "@/lib/utils"

interface ProfileDropdownProps {
  onClose: () => void
  onNav: (s: ScreenId) => void
}

export default function ProfileDropdown({ onClose, onNav }: ProfileDropdownProps) {
  const { backendUser, role, signOut } = useAuth()
  const dropdownRef = useRef<HTMLDivElement>(null)

  const initials = getInitials(backendUser?.name, backendUser?.email)
  const displayRole = role?.replace("_", " ").toUpperCase() ?? "PUBLIC"

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        onClose()
      }
    }

    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [onClose])

  // Close on Escape key
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose()
      }
    }

    document.addEventListener("keydown", handleEscape)
    return () => document.removeEventListener("keydown", handleEscape)
  }, [onClose])

  const handleNavToSettings = () => {
    onClose()
    onNav(SCREENS.SETTINGS)
  }

  const handleSignOut = () => {
    onClose()
    signOut()
  }

  return (
    <div
      ref={dropdownRef}
      className="absolute top-16 right-6 w-72 rounded-lg shadow-xl"
      style={{ background: "#fff", border: "1px solid #E2E6EC", zIndex: 50 }}
    >
      {/* User Info Header */}
      <div className="p-4 border-b" style={{ borderColor: "#E2E6EC" }}>
        <div className="flex items-center gap-3 mb-3">
          <div
            className="w-12 h-12 rounded-full flex items-center justify-center text-white text-sm font-bold"
            style={{ background: "#C8963E" }}
          >
            {initials}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm truncate" style={{ color: "#1A2332" }}>
              {backendUser?.name || "User"}
            </div>
            <div className="text-xs truncate" style={{ color: "#8494A7" }}>
              {backendUser?.email}
            </div>
          </div>
        </div>
        <div className="flex justify-start">
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide"
            style={{ background: "rgba(11, 29, 58, 0.08)", color: "#0B1D3A" }}>
            {displayRole}
          </span>
        </div>
      </div>

      {/* Menu Items */}
      <div className="py-1">
        <button
          onClick={handleNavToSettings}
          className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
        >
          <span className="text-base" style={{ color: "#4A5568" }}>⚙️</span>
          <span className="text-sm" style={{ color: "#1A2332" }}>Settings</span>
        </button>

        <button
          onClick={() => {
            onClose()
          }}
          className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
        >
          <span className="text-base" style={{ color: "#4A5568" }}>❓</span>
          <span className="text-sm" style={{ color: "#1A2332" }}>Help & Support</span>
        </button>

        <div className="my-1" style={{ borderTop: "1px solid #E2E6EC" }} />

        <button
          onClick={handleSignOut}
          className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-red-50 transition-colors text-left"
        >
          <span className="text-base" style={{ color: "#b91c1c" }}>🚪</span>
          <span className="text-sm font-medium" style={{ color: "#b91c1c" }}>Sign Out</span>
        </button>
      </div>
    </div>
  )
}
