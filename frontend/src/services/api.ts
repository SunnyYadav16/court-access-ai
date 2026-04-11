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
  items: DocumentStatus[];
  total: number;
  page: number;
  page_size: number;
}

export interface FormListParams {
  q?: string;
  division?: string;
  language?: "es" | "pt";
  status?: "active" | "archived";
  page?: number;
  page_size?: number;
}

export interface FormAppearanceResponse {
  appearance_id: string;
  form_id: string;
  division: string;
  section_heading: string;
}

export interface FormVersionResponse {
  version_id: string;
  form_id: string;
  version: number;
  content_hash: string;
  file_type: string;
  file_path_original: string;
  file_path_es: string | null;
  file_path_pt: string | null;
  signed_url_original: string | null;
  signed_url_es: string | null;
  signed_url_pt: string | null;
  file_type_es: string | null;
  file_type_pt: string | null;
  created_at: string;
}

export interface FormResponse {
  form_id: string;
  form_name: string;
  form_slug: string;
  source_url: string;
  file_type: string;
  status: "active" | "archived";
  content_hash: string;
  current_version: number;
  needs_human_review: boolean;
  preprocessing_flags: unknown[] | null;
  created_at: string;
  last_scraped_at: string | null;
  versions: FormVersionResponse[];
  appearances: FormAppearanceResponse[];
}

export interface FormListResponse {
  items: FormResponse[];
  total: number;
  page: number;
  page_size: number;
  filters_applied: Record<string, string>;
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
  get: (formId: string): Promise<FormResponse> =>
    api.get<FormResponse>(`/forms/${formId}`).then((r) => r.data),

  /** List all court divisions. */
  divisions: (): Promise<string[]> =>
    api.get<string[]>("/forms/divisions").then((r) => r.data),

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

// ══════════════════════════════════════════════════════════════════════════════
// Realtime endpoints
// ══════════════════════════════════════════════════════════════════════════════

export interface RoomCreateRequest {
  target_language: "es" | "pt";
  court_division?: string | null;
  courtroom?: string | null;
  case_docket?: string | null;
  partner_name: string;
  consent_acknowledged: boolean;
}

export interface RoomCreateResponse {
  session_id: string;
  rt_request_id: string;
  room_code: string;
  room_code_expires_at: string;
  join_url: string;
}

export interface RoomPreviewResponse {
  phase: "waiting" | "joining" | "active" | "ended";
  target_language: string;
  court_division: string | null;
  courtroom: string | null;
  partner_name: string;
  room_code_expires_at: string;
}

export interface RoomStatusResponse {
  phase: "waiting" | "joining" | "active" | "ended";
  room_code: string;
  room_code_expires_at: string;
  partner_joined_at: string | null;
}

export const realtimeApi = {
  /** Create a new two-party interpretation room. Returns room code + join URL. */
  createRoom: (body: RoomCreateRequest): Promise<RoomCreateResponse> =>
    api.post<RoomCreateResponse>("/sessions/rooms", body).then((r) => r.data),

  /** Public room preview for the guest join page — no auth required. */
  getRoomPreview: (roomCode: string): Promise<RoomPreviewResponse> =>
    api.get<RoomPreviewResponse>(`/sessions/rooms/${roomCode}/preview`).then((r) => r.data),

  /** Poll room status — used by the lobby screen to detect when the partner joins. */
  getRoomStatus: (roomCode: string): Promise<RoomStatusResponse> =>
    api.get<RoomStatusResponse>(`/sessions/rooms/${roomCode}/status`).then((r) => r.data),

  /** End a room session (creator only). Idempotent — 204 if already ended. */
  endRoom: (sessionId: string): Promise<void> =>
    api.post(`/sessions/rooms/${sessionId}/end`).then(() => undefined),
};

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

// ══════════════════════════════════════════════════════════════════════════════
// Admin endpoints
// ══════════════════════════════════════════════════════════════════════════════

export interface AdminStats {
  active_sessions_total: number;
  active_sessions_realtime: number;
  active_sessions_document: number;
  todays_translations_total: number;
  todays_translations_docs: number;
  todays_translations_realtime: number;
  avg_nmt_confidence: number | null;
  last_scrape_at: string | null;
  recent_audit_events: AdminAuditEvent[];
}

export interface AdminAuditEvent {
  audit_id: string;
  action_type: string;
  created_at: string;
  details: Record<string, unknown> | null;
}

export interface AdminUserRow {
  user_id: string;
  name: string;
  email: string;
  role: string;
  last_login_at: string | null;
  session_count: number;
  is_active: boolean;
  created_at: string;
}

export interface TriggerScraperResponse {
  dag_run_id: string;
  triggered_at: string;
}

export const adminApi = {
  getStats: (): Promise<AdminStats> =>
    api.get<AdminStats>("/admin/stats").then((r) => r.data),

  listUsers: (page = 1, pageSize = 50): Promise<AdminUserRow[]> =>
    api.get<AdminUserRow[]>("/admin/users", { params: { page, page_size: pageSize } }).then((r) => r.data),

  setUserRole: (userId: string, roleName: string): Promise<UserInfo> =>
    api.post<UserInfo>(`/admin/users/${userId}/role`, { role_name: roleName }).then((r) => r.data),

  listRoleRequests: (pendingOnly = true): Promise<RoleRequestSummary[]> =>
    api.get<RoleRequestSummary[]>("/admin/role-requests", { params: { pending_only: pendingOnly } }).then((r) => r.data),

  approveRoleRequest: (requestId: string): Promise<void> =>
    api.post(`/admin/role-requests/${requestId}/approve`, {}).then(() => undefined),

  rejectRoleRequest: (requestId: string): Promise<void> =>
    api.post(`/admin/role-requests/${requestId}/reject`, {}).then(() => undefined),

  triggerScraper: (): Promise<TriggerScraperResponse> =>
    api.post<TriggerScraperResponse>("/forms/scraper/trigger", { force: false }).then((r) => r.data),
};

// Re-export RoleRequestSummary for consumers that need it
export interface RoleRequestSummary {
  request_id: string;
  user_id: string;
  requested_role_id: number;
  status: string;
  requested_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export default api;
