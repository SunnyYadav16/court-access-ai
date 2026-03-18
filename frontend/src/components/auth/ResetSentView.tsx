/**
 * components/auth/ResetSentView.tsx
 *
 * Read-only confirmation view after sending a password reset email.
 * No password inputs — Firebase handles the reset on its own hosted page.
 */

import useAuthStore from "@/store/authStore";

/**
 * Confirmation view shown after a password reset email is sent.
 *
 * Displays a success badge, heading, explanatory text, an informational note
 * about the 24-hour link expiry, and a control to return to the sign-in view.
 *
 * Clicking the "Back to sign in" control switches the authentication modal to the "login" view.
 *
 * @returns The React element for the reset-sent confirmation UI.
 */
export default function ResetSentView() {
  const { setAuthModalView } = useAuthStore();

  return (
    <div className="text-center">
      <div
        className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4"
        style={{ background: "#DCFCE7", border: "1px solid #86efac" }}
      >
        <span className="text-2xl">✓</span>
      </div>

      <h2
        className="text-xl font-bold mb-2"
        style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
      >
        Check your email
      </h2>
      <p
        className="text-sm leading-relaxed mb-4"
        style={{ color: "#8494A7" }}
      >
        We've sent a password reset link to your email address. Click the link
        to set a new password.
      </p>

      <div
        className="rounded-md p-3 mb-6 text-left"
        style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}
      >
        <p
          className="text-xs leading-relaxed"
          style={{ color: "#1e40af" }}
        >
          <strong>The link expires in 24 hours.</strong> If you don't see the
          email, check your spam folder.
        </p>
      </div>

      <button
        onClick={() => setAuthModalView("login")}
        className="text-xs font-medium flex items-center gap-1 mx-auto cursor-pointer"
        style={{ color: "#2563eb", background: "none", border: "none" }}
      >
        ← Back to sign in
      </button>
    </div>
  );
}
