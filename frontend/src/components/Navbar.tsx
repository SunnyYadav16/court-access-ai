/**
 * components/Navbar.tsx
 *
 * Sticky navigation bar for CourtAccess AI.
 * Renders different nav links depending on authentication state.
 */

import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

/**
 * Top navigation bar that displays links and authentication actions.
 *
 * Renders the site logo, primary navigation links, and a right-aligned auth area. When a user is authenticated it includes "Live Interpret" and "My Documents"; when the user's role is "admin" or "court_official" it includes an "Admin" link. For authenticated users the auth area shows a dashboard link (using the user's name or email if available) and a logout button; clicking logout signs the user out and navigates to "/login".
 *
 * @returns The navbar as a JSX element.
 */
export default function Navbar() {
  const { authState, backendUser, signOut } = useAuth();
  const navigate = useNavigate();
  const isAuthenticated = authState === "authenticated";

  const handleLogout = async () => {
    await signOut();
    navigate("/login");
  };

  return (
    <header className="navbar" role="banner">
      <div className="navbar__inner">
        {/* Logo */}
        <NavLink to="/" className="navbar__logo" aria-label="CourtAccess AI home">
          ⚖️ Court<span>Access</span> AI
        </NavLink>

        {/* Nav links */}
        <nav aria-label="Main navigation">
          <ul className="navbar__links">
            <li>
              <NavLink to="/forms" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                Court Forms
              </NavLink>
            </li>

            {isAuthenticated && (
              <>
                <li>
                  <NavLink to="/sessions/new" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                    Live Interpret
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/documents" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                    My Documents
                  </NavLink>
                </li>
              </>
            )}

            {backendUser?.role === "admin" || backendUser?.role === "court_official" ? (
              <li>
                <NavLink to="/admin" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                  Admin
                </NavLink>
              </li>
            ) : null}
          </ul>
        </nav>

        {/* Auth actions */}
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {isAuthenticated ? (
            <>
              <NavLink to="/dashboard" className="btn btn-ghost btn--sm">
                {backendUser?.name ?? backendUser?.email ?? "Dashboard"}
              </NavLink>
              <button id="btn-logout" className="btn btn-secondary btn--sm" onClick={handleLogout}>
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="btn btn-ghost btn--sm" id="btn-login-nav">
                Log in
              </NavLink>
              <NavLink to="/register" className="btn btn-primary btn--sm" id="btn-register-nav">
                Register
              </NavLink>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
