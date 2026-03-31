/**
 * services/api.ts
 *
 * Axios HTTP client for the CourtAccess AI API.
 *
 * Base URL: /api (proxied to http://localhost:8000 in dev via vite.config.js)
 *
 * Features:
 *   - Auto-attaches Firebase ID token as Bearer token on every request
 *   - 401 response triggers forced sign-out via auth:logout event
 *   - Resource-specific helper modules at bottom of file
 */

import axios, { AxiosError, AxiosProgressEvent } from "axios";
import { auth } from "@/config/firebase";

// ── Types ───────────────────────────────────────────────────────────────────

export interface UserInfo {
  user_id: string;
  email: string;
  name: string;
  role: string;
  firebase_uid: string | null;
  auth_provider: string;
  email_verified: boolean;
  mfa_enabled: boolean;
  role_approved_by: string | null;
  role_approved_at: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface RoleSelectionResponse {
  message: string;
  selected_role: string;
}

export interface DocumentUploadResponse {
  session_id: string;        // polling key
  request_id: string;
  status: string;            // always "processing"
  gcs_input_path: string;
  target_language: string;   // "es" | "pt"
  created_at: string;
  estimated_completion_seconds: number;
}

export interface DocumentStatus {
  session_id: string;
  status: string;            // "pending"|"processing"|"translated"|"error"|"rejected"
  target_language: string;
  created_at: string;
  completed_at: string | null;
  signed_url: string | null;
  signed_url_expires_at: string | null;
  gcs_output_path: string | null;
  avg_confidence_score: number | null;
  llama_corrections_count: number;
  processing_time_seconds: number | null;
  error_message: string | null;
}

export interface PipelineStep {
  step_name: string;
  status: string;       // "running"|"success"|"failed"|"skipped"
  detail: string;
  metadata: Record<string, unknown>;
  updated_at: string;
}

export interface DocumentListResponse {
  documents: DocumentStatus[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface FormListParams {
  q?: string;
  division?: string;
  language?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export interface Form {
  form_id: string;
  name: string;
  division: string;
  available_languages: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface FormListResponse {
  forms: Form[];
  total: number;
  page: number;
  page_size: number;
}

export interface FormDetail extends Form {
  description?: string;
  reviewer_notes?: string;
  file_urls: Record<string, string>;
}

export interface Division {
  division_id: string;
  name: string;
  description?: string;
}

export interface ReviewResponse {
  message: string;
  form_id: string;
  status: string;
}

export interface SessionCreateResponse {
  session_id: string;
  target_language: string;
  source_language: string;
  status: string;
  created_at: string;
}

export interface Session {
  session_id: string;
  target_language: string;
  source_language: string;
  status: string;
  created_at: string;
  ended_at?: string;
}

export interface SessionEndResponse {
  message: string;
  session_id: string;
  status: string;
}

// ── Client ──────────────────────────────────────────────────────────────────

const api = axios.create({
  baseURL: "/api",
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// ── Request interceptor — attach Firebase ID token ───────────────────────────

api.interceptors.request.use(async (config) => {
  const user = auth.currentUser;
  if (user) {
    // getIdToken() returns cached token or auto-refreshes if near expiry
    const token = await user.getIdToken();
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor — force sign-out on 401 ────────────────────────────

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Token is invalid — force sign out
      window.dispatchEvent(new Event("auth:logout"));
    }
    return Promise.reject(error);
  }
);

// ══════════════════════════════════════════════════════════════════════════════
// Auth endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const authApi = {
  /** Get current user info from backend */
  me: (): Promise<UserInfo> =>
    api.get<UserInfo>("/auth/me").then((r) => r.data),

  /** Submit role selection */
  selectRole: (selectedRole: string): Promise<RoleSelectionResponse> =>
    api.post<RoleSelectionResponse>("/auth/select-role", { selected_role: selectedRole }).then((r) => r.data),
};

// ══════════════════════════════════════════════════════════════════════════════
// Document endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const documentsApi = {
  /**
   * Upload a PDF file for translation.
   * @param file — PDF File object
   * @param targetLanguage — "es" or "pt" (single language per pipeline run)
   * @param notes — optional submitter notes
   * @param onProgress — upload progress callback (0–100)
   */
  upload: (
    file: File,
    targetLanguage: string = "es",
    notes: string | null = null,
    onProgress?: (progress: number) => void
  ): Promise<DocumentUploadResponse> => {
    const form = new FormData();
    form.append("file", file);
    form.append("target_language", targetLanguage);  // matches Form field name in backend
    if (notes) form.append("notes", notes);
    return api
      .post<DocumentUploadResponse>("/documents/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (e: AxiosProgressEvent) => {
          if (e.total) {
            onProgress?.(Math.round((e.loaded * 100) / e.total));
          }
        },
      })
      .then((r) => r.data);
  },

  /** Get translation status for a session. */
  status: (sessionId: string): Promise<DocumentStatus> =>
    api.get<DocumentStatus>(`/documents/${sessionId}`).then((r) => r.data),

  /** Get individual pipeline step progress — drives the live progress screen. */
  steps: (sessionId: string): Promise<PipelineStep[]> =>
    api.get<PipelineStep[]>(`/documents/${sessionId}/steps`).then((r) => r.data),

  /**
   * Re-translate an already-uploaded document into a second language.
   * The backend re-uses the original GCS input file and creates a new request_id.
   */
  retranslate: (sessionId: string, targetLanguage: string): Promise<DocumentUploadResponse> =>
    api
      .post<DocumentUploadResponse>(`/documents/${sessionId}/retranslate`, { target_language: targetLanguage })
      .then((r) => r.data),

  /** List the current user's documents. */
  list: (page: number = 1, pageSize: number = 20): Promise<DocumentListResponse> =>
    api.get<DocumentListResponse>("/documents/", { params: { page, page_size: pageSize } }).then((r) => r.data),

  /** Delete a document and its associated pipeline data. */
  delete: (sessionId: string): Promise<void> =>
    api.delete(`/documents/${sessionId}`).then(() => undefined),
};

// ══════════════════════════════════════════════════════════════════════════════
// Forms (catalog) endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const formsApi = {
  /**
   * Search and list court forms.
   * @param params — Search and filter parameters
   */
  list: (params: FormListParams = {}): Promise<FormListResponse> =>
    api.get<FormListResponse>("/forms/", { params }).then((r) => r.data),

  /** Get a single form by ID. */
  get: (formId: string): Promise<FormDetail> =>
    api.get<FormDetail>(`/forms/${formId}`).then((r) => r.data),

  /** List all court divisions. */
  divisions: (): Promise<Division[]> =>
    api.get<Division[]>("/forms/divisions").then((r) => r.data),

  /**
   * Submit a human review decision.
   * requires court_official or admin role.
   */
  review: (
    formId: string,
    approved: boolean,
    reviewerNotes: string | null = null
  ): Promise<ReviewResponse> =>
    api
      .patch<ReviewResponse>(`/forms/${formId}/review`, { approved, reviewer_notes: reviewerNotes })
      .then((r) => r.data),
};

// ══════════════════════════════════════════════════════════════════════════════
// Session endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const sessionsApi = {
  /** Create a new real-time interpretation session. */
  create: (
    targetLanguage: string = "es",
    sourceLanguage: string = "en"
  ): Promise<SessionCreateResponse> =>
    api.post<SessionCreateResponse>("/sessions/", { target_language: targetLanguage, source_language: sourceLanguage }).then((r) => r.data),

  /** Get session metadata. */
  get: (sessionId: string): Promise<Session> =>
    api.get<Session>(`/sessions/${sessionId}`).then((r) => r.data),

  /** End an active session. */
  end: (sessionId: string): Promise<SessionEndResponse> =>
    api.post<SessionEndResponse>(`/sessions/${sessionId}/end`).then((r) => r.data),
};

export default api;
