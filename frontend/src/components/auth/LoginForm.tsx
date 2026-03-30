/**
 * components/auth/LoginForm.tsx
 *
 * Login form rendered inside AuthModal.
 * Supports Google, Microsoft OAuth and email/password sign-in.
 * No Apple sign-in.
 */

import { useState, type FormEvent } from "react";
import useAuthStore from "@/store/authStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18">
    <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908C16.618 14.013 17.64 11.705 17.64 9.2z" fill="#4285F4"/>
    <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
    <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
    <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
  </svg>
);

const MicrosoftIcon = () => (
  <svg width="18" height="18" viewBox="0 0 21 21">
    <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
    <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
    <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
  </svg>
);

export default function LoginForm() {
  const {
    isLoading,
    error,
    pendingVerificationEmail,
    signInWithGoogle,
    signInWithMicrosoft,
    signInWithEmail,
    setAuthModalView,
    clearError,
  } = useAuthStore();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [validationError, setValidationError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setValidationError("");

    if (!email.trim()) {
      setValidationError("Email is required.");
      return;
    }
    if (!/\S+@\S+\.\S+/.test(email)) {
      setValidationError("Please enter a valid email address.");
      return;
    }
    if (!password) {
      setValidationError("Password is required.");
      return;
    }

    await signInWithEmail(email, password);
  };

  const displayError = validationError || error;

  return (
    <div>
      <h2
        className="text-xl font-bold mb-1"
        style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
      >
        Welcome back
      </h2>
      <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
        Sign in to access court translation services
      </p>

      {/* Verification pending banner */}
      {pendingVerificationEmail && (
        <div
          className="rounded-md p-3 mb-4 text-xs leading-relaxed"
          style={{ background: "#EFF6FF", border: "1px solid #BFDBFE", color: "#1e40af" }}
        >
          <strong>Verification email sent to {pendingVerificationEmail}.</strong>{" "}
          Please verify your email before signing in.
        </div>
      )}

      {/* Error display */}
      {displayError && (
        <div
          className="rounded-md p-3 mb-4 text-xs leading-relaxed"
          style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#b91c1c" }}
        >
          {displayError}
        </div>
      )}

      {/* OAuth Buttons */}
      <button
        onClick={() => { clearError(); signInWithGoogle(); }}
        disabled={isLoading}
        className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-2 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ borderColor: "#E2E6EC", color: "#1A2332", background: "#fff" }}
      >
        <GoogleIcon /> Continue with Google
      </button>
      <button
        onClick={() => { clearError(); signInWithMicrosoft(); }}
        disabled={isLoading}
        className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-3 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ borderColor: "#E2E6EC", color: "#1A2332", background: "#fff" }}
      >
        <MicrosoftIcon /> Continue with Microsoft
      </button>

      {/* Divider */}
      <div className="flex items-center gap-3 my-4">
        <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
        <span className="text-[11px]" style={{ color: "#8494A7" }}>or sign in with email</span>
        <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
      </div>

      {/* Email/password form */}
      <form onSubmit={handleSubmit}>
        <div className="mb-3">
          <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
            Email address
          </label>
          <Input
            placeholder="name@example.com"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading}
          />
        </div>
        <div className="mb-4">
          <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
            Password
          </label>
          <Input
            placeholder="••••••••"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isLoading}
          />
        </div>

        <div className="flex justify-between items-center mb-5">
          <label
            className="flex items-center gap-2 text-xs cursor-pointer"
            style={{ color: "#4A5568" }}
          >
            <input type="checkbox" className="accent-slate-800" /> Remember me
          </label>
          <button
            type="button"
            onClick={() => setAuthModalView("forgot")}
            className="text-xs font-medium cursor-pointer"
            style={{ color: "#2563eb", background: "none", border: "none" }}
          >
            Forgot password?
          </button>
        </div>

        <Button
          type="submit"
          className="w-full cursor-pointer"
          style={{ background: "#0B1D3A" }}
          disabled={isLoading}
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Signing in…
            </span>
          ) : (
            "Sign In"
          )}
        </Button>
      </form>

      <p className="text-center text-xs mt-4" style={{ color: "#8494A7" }}>
        Don't have an account?{" "}
        <button
          onClick={() => setAuthModalView("signup")}
          className="font-semibold cursor-pointer"
          style={{ color: "#2563eb", background: "none", border: "none" }}
        >
          Create account
        </button>
      </p>
    </div>
  );
}
