import { useState } from "react"
import courtaccessLogo from "@/assets/courtaccess-logo.png"
import { ScreenId, SCREENS } from "@/lib/constants"
import { useAuth } from "@/hooks/useAuth"
import { getInitials } from "@/lib/utils"
import ProfileDropdown from "./ProfileDropdown"

interface TopBarProps {
  onNav: (s: ScreenId) => void
}

export default function TopBar({ onNav }: TopBarProps) {
  const { backendUser, role } = useAuth()
  const [showDropdown, setShowDropdown] = useState(false)

  const initials = getInitials(backendUser?.name, backendUser?.email)

  const homeScreen = () => {
    if (role === "public") return SCREENS.HOME_PUBLIC
    if (role === "court_official") return SCREENS.HOME_OFFICIAL
    if (role === "interpreter") return SCREENS.HOME_INTERPRETER
    return SCREENS.HOME_ADMIN
  }

  return (
    <div className="relative">
      <div className="h-14 px-6 flex items-center justify-between"
        style={{ background: "#0B1D3A", color: "#fff" }}>
        <div className="flex items-center gap-2 cursor-pointer"
          onClick={() => onNav(homeScreen())}>
          <img src={courtaccessLogo} alt="CourtAccess AI" className="h-9 w-auto block" />
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded tracking-wide"
            style={{ background: "rgba(200,150,62,0.25)", color: "#C8963E" }}>BETA</span>
        </div>
        <div className="flex items-center">
          <button
            onClick={() => setShowDropdown(!showDropdown)}
            className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold cursor-pointer hover:opacity-90 transition-opacity"
            style={{ background: "#C8963E" }}
            aria-label="Open profile menu"
          >
            {initials}
          </button>
        </div>
      </div>

      {showDropdown && (
        <ProfileDropdown
          onClose={() => setShowDropdown(false)}
          onNav={onNav}
        />
      )}
    </div>
  )
}
