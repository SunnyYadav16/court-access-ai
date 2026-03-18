/**
 * components/auth/SignupForm.tsx
 *
 * Signup form rendered inside AuthModal.
 * Google/Microsoft OAuth + email/password registration with:
 *   - Dynamic password strength indicator
 *   - Terms acceptance
 *   - Client-side validation
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

export default function SignupForm() {
  const {
    isLoading,
    error,
    signInWithGoogle,
    signInWithMicrosoft,
    createAccount,
    setAuthModalView,
    clearError,
  } = useAuthStore();

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Password strength checks
  const checks = {
    minLength: password.length >= 8,
    hasUppercase: /[A-Z]/.test(password),
    hasNumber: /[0-9]/.test(password),
    hasSpecial: /[!@#$%^&*(),.?":{}|<>]/.test(password),
  };
  const strength = Object.values(checks).filter(Boolean).length;

  const strengthColors = Array.from({ length: 4 }, (_, i) =>
    i < strength ? "#16a34a" : "#E2E6EC"
  );

  const validate = (): boolean => {
    const errs: Record<string, string> = {};

    if (!firstName.trim()) errs.firstName = "First name is required.";
    if (!lastName.trim()) errs.lastName = "Last name is required.";
    if (!email.trim()) errs.email = "Email is required.";
    else if (!/\S+@\S+\.\S+/.test(email))
      errs.email = "Please enter a valid email address.";
    if (!password) errs.password = "Password is required.";
    else if (strength < 4)
      errs.password = "Password must meet all requirements.";
    if (password !== confirmPassword)
      errs.confirmPassword = "Passwords do not match.";
    if (!termsAccepted) errs.terms = "You must accept the terms to continue.";

    setValidationErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const displayName = `${firstName.trim()} ${lastName.trim()}`;
    await createAccount(email, password, displayName);
  };

  return (
    <div>
      <h2
        className="text-xl font-bold mb-1"
        style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
      >
        Create your account
      </h2>
      <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
        Get access to court translation and interpretation services
      </p>

      {/* Error display */}
      {error && (
        <div
          className="rounded-md p-3 mb-4 text-xs leading-relaxed"
          style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#b91c1c" }}
        >
          {error}
        </div>
      )}

      {/* OAuth Buttons */}
      <button
        onClick={() => { clearError(); signInWithGoogle(); }}
        disabled={isLoading}
        className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-2 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ borderColor: "#E2E6EC", color: "#1A2332", background: "#fff" }}
      >
        <GoogleIcon /> Sign up with Google
      </button>
      <button
        onClick={() => { clearError(); signInWithMicrosoft(); }}
        disabled={isLoading}
        className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md border text-sm font-medium mb-3 cursor-pointer hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ borderColor: "#E2E6EC", color: "#1A2332", background: "#fff" }}
      >
        <MicrosoftIcon /> Sign up with Microsoft
      </button>

      {/* Divider */}
      <div className="flex items-center gap-3 my-4">
        <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
        <span className="text-[11px]" style={{ color: "#8494A7" }}>
          or create account with email
        </span>
        <div className="flex-1 h-px" style={{ background: "#E2E6EC" }} />
      </div>

      <form onSubmit={handleSubmit}>
        {/* Name fields */}
        <div className="flex gap-3 mb-3">
          <div className="flex-1">
            <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
              First name
            </label>
            <Input
              placeholder="Maria"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              disabled={isLoading}
              style={validationErrors.firstName ? { borderColor: "#ef4444" } : {}}
            />
            {validationErrors.firstName && (
              <p className="text-[10px] mt-0.5" style={{ color: "#ef4444" }}>
                {validationErrors.firstName}
              </p>
            )}
          </div>
          <div className="flex-1">
            <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
              Last name
            </label>
            <Input
              placeholder="Santos"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              disabled={isLoading}
              style={validationErrors.lastName ? { borderColor: "#ef4444" } : {}}
            />
            {validationErrors.lastName && (
              <p className="text-[10px] mt-0.5" style={{ color: "#ef4444" }}>
                {validationErrors.lastName}
              </p>
            )}
          </div>
        </div>

        {/* Email */}
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
            style={validationErrors.email ? { borderColor: "#ef4444" } : {}}
          />
          {validationErrors.email && (
            <p className="text-[10px] mt-0.5" style={{ color: "#ef4444" }}>
              {validationErrors.email}
            </p>
          )}
        </div>

        {/* Password */}
        <div className="mb-1">
          <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
            Password
          </label>
          <div className="relative">
            <Input
              placeholder="Create a strong password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              style={validationErrors.password ? { borderColor: "#ef4444" } : {}}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs cursor-pointer"
              style={{ color: "#8494A7", background: "none", border: "none" }}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        {/* Password strength indicator */}
        <div className="mb-3">
          <div className="flex gap-1 mb-1">
            {strengthColors.map((c, i) => (
              <div
                key={i}
                className="flex-1 h-1 rounded-full transition-colors"
                style={{ background: c }}
              />
            ))}
          </div>
          <div className="flex gap-3 text-[10px] flex-wrap">
            <span style={{ color: checks.minLength ? "#16a34a" : "#8494A7" }}>
              {checks.minLength ? "✓" : "○"} 8+ chars
            </span>
            <span style={{ color: checks.hasUppercase ? "#16a34a" : "#8494A7" }}>
              {checks.hasUppercase ? "✓" : "○"} Uppercase
            </span>
            <span style={{ color: checks.hasNumber ? "#16a34a" : "#8494A7" }}>
              {checks.hasNumber ? "✓" : "○"} Number
            </span>
            <span style={{ color: checks.hasSpecial ? "#16a34a" : "#8494A7" }}>
              {checks.hasSpecial ? "✓" : "○"} Special char
            </span>
          </div>
        </div>

        {/* Confirm password */}
        <div className="mb-4">
          <label className="text-xs font-semibold block mb-1" style={{ color: "#4A5568" }}>
            Confirm password
          </label>
          <Input
            placeholder="Confirm your password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            disabled={isLoading}
            style={validationErrors.confirmPassword ? { borderColor: "#ef4444" } : {}}
          />
          {validationErrors.confirmPassword && (
            <p className="text-[10px] mt-0.5" style={{ color: "#ef4444" }}>
              {validationErrors.confirmPassword}
            </p>
          )}
        </div>

        {/* Terms */}
        <div className="flex items-start gap-2 mb-5">
          <input
            type="checkbox"
            className="mt-0.5 accent-slate-800"
            checked={termsAccepted}
            onChange={(e) => setTermsAccepted(e.target.checked)}
            disabled={isLoading}
          />
          <span className="text-[11px] leading-relaxed" style={{ color: "#4A5568" }}>
            I agree to the{" "}
            <span className="cursor-pointer" style={{ color: "#2563eb" }}>
              Terms of Service
            </span>{" "}
            and{" "}
            <span className="cursor-pointer" style={{ color: "#2563eb" }}>
              Privacy Policy
            </span>
            . I understand all translations are machine-generated and not official
            court records.
          </span>
        </div>
        {validationErrors.terms && (
          <p className="text-[10px] mb-3 -mt-3" style={{ color: "#ef4444" }}>
            {validationErrors.terms}
          </p>
        )}

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
              Creating account…
            </span>
          ) : (
            "Create Account"
          )}
        </Button>
      </form>

      <p className="text-center text-xs mt-4" style={{ color: "#8494A7" }}>
        Already have an account?{" "}
        <button
          onClick={() => setAuthModalView("login")}
          className="font-semibold cursor-pointer"
          style={{ color: "#2563eb", background: "none", border: "none" }}
        >
          Sign in
        </button>
      </p>
    </div>
  );
}
