/** All screen identifiers used by the router */
export const SCREENS = {
  // Public
  LANDING: "LANDING",

  // Auth
  LOGIN: "LOGIN",
  SIGNUP: "SIGNUP",
  FORGOT: "FORGOT",
  RESET: "RESET",
  VERIFY_EMAIL: "VERIFY_EMAIL",
  MFA: "MFA",

  // Home (role-based)
  HOME_PUBLIC: "HOME_PUBLIC",
  HOME_OFFICIAL: "HOME_OFFICIAL",
  HOME_INTERPRETER: "HOME_INTERPRETER",
  HOME_ADMIN: "HOME_ADMIN",

  // Realtime interpretation
  REALTIME_SETUP: "REALTIME_SETUP",
  REALTIME_SESSION: "REALTIME_SESSION",

  // Document translation
  DOC_UPLOAD: "DOC_UPLOAD",
  DOC_PROCESSING: "DOC_PROCESSING",
  DOC_RESULTS: "DOC_RESULTS",

  // Forms library
  FORMS_LIBRARY: "FORMS_LIBRARY",
  FORM_DETAIL: "FORM_DETAIL",

  // Admin
  ADMIN_DASHBOARD: "ADMIN_DASHBOARD",
  ADMIN_USERS: "ADMIN_USERS",
  ADMIN_FORMS: "ADMIN_FORMS",
  INTERPRETER_REVIEW: "INTERPRETER_REVIEW",
} as const;

/** Union type of all valid screen IDs */
export type ScreenId = (typeof SCREENS)[keyof typeof SCREENS];

// ══════════════════════════════════════════════════════════════════════════════
// Auth Types & Constants
// ══════════════════════════════════════════════════════════════════════════════

/** Auth state machine states */
export type AuthState =
  | "loading"
  | "unauthenticated"
  | "needs_email_verification"
  | "needs_role_selection"
  | "authenticated";

/** Auth modal view states (null = modal closed) */
export type AuthModalView =
  | "login"
  | "signup"
  | "forgot"
  | "reset_sent"
  | "verify_email"
  | null;

/** User roles */
export type UserRole = "public" | "court_official" | "interpreter" | "admin";

/** Firebase error code → user-friendly message mapping */
export const FIREBASE_ERROR_MESSAGES: Record<string, string> = {
  "auth/email-already-in-use":
    "An account with this email already exists. Please sign in and verify your email.",
  "auth/invalid-credential": "Invalid email or password. Please try again.",
  "auth/wrong-password": "Incorrect password. Please try again.",
  "auth/user-not-found": "No account found with this email address.",
  "auth/weak-password": "Password must be at least 8 characters.",
  "auth/invalid-email": "Please enter a valid email address.",
  "auth/too-many-requests": "Too many failed attempts. Please try again later.",
  "auth/network-request-failed":
    "Network error. Please check your connection.",
  "auth/popup-closed-by-user": "Sign-in popup was closed. Please try again.",
  "auth/popup-blocked":
    "Sign-in popup was blocked by your browser. Please allow popups and try again.",
  "auth/account-exists-with-different-credential":
    "An account already exists with this email using a different sign-in method.",
  "auth/requires-recent-login":
    "Please sign in again to complete this action.",
  "auth/user-disabled":
    "This account has been disabled. Please contact support.",
};

/**
 * Map a Firebase error code to a user-friendly message.
 *
 * @param code - The Firebase error code to translate (for example, `auth/user-not-found`).
 * @returns The corresponding friendly message, or `An unexpected error occurred. Please try again.` if the code is not recognized.
 */
export function getFirebaseErrorMessage(code: string): string {
  return (
    FIREBASE_ERROR_MESSAGES[code] ||
    "An unexpected error occurred. Please try again."
  );
}

/** Password validation rules */
export const PASSWORD_RULES = {
  minLength: 8,
  requireUppercase: true,
  requireNumber: true,
  requireSpecialChar: true,
} as const;
