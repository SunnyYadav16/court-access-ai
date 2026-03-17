export const SCREENS = {
    // Public
    LANDING:            "landing",
  
    // Auth
    LOGIN:              "login",
    SIGNUP:             "signup",
    FORGOT:             "forgot",
    RESET:              "reset",
    VERIFY_EMAIL:       "verify_email",
    MFA:                "mfa",
  
    // Home (role-based)
    HOME_PUBLIC:        "home_public",
    HOME_OFFICIAL:      "home_official",
    HOME_INTERPRETER:   "home_interpreter",
    HOME_ADMIN:         "home_admin",
  
    // Realtime
    REALTIME_SETUP:     "realtime_setup",
    REALTIME_SESSION:   "realtime_session",
  
    // Documents
    DOC_UPLOAD:         "doc_upload",
    DOC_PROCESSING:     "doc_processing",
    DOC_RESULTS:        "doc_results",
  
    // Forms
    FORMS_LIBRARY:      "forms_library",
    FORM_DETAIL:        "form_detail",
  
    // Admin
    ADMIN_DASHBOARD:    "admin_dashboard",
    ADMIN_USERS:        "admin_users",
    ADMIN_FORMS:        "admin_forms",
    INTERPRETER_REVIEW: "interpreter_review",
  } as const
  
  export type ScreenId = typeof SCREENS[keyof typeof SCREENS]