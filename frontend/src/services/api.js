/**
 * services/api.js
 *
 * Axios HTTP client for the CourtAccess AI API.
 *
 * Base URL: /api (proxied to http://localhost:8000 in dev via vite.config.js)
 *
 * Features:
 *   - Auto-attaches Bearer token from localStorage
 *   - 401 interceptor auto-refreshes the access token once, then logs out
 *   - Resource-specific helper modules at bottom of file
 */

import axios from "axios";

// ── Client ──────────────────────────────────────────────────────────────────

const api = axios.create({
    baseURL: "/api",
    timeout: 30_000,
    headers: { "Content-Type": "application/json" },
});

// ── Request interceptor — attach access token ────────────────────────────────

api.interceptors.request.use((config) => {
    const token = localStorage.getItem("access_token");
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// ── Response interceptor — auto-refresh on 401 ──────────────────────────────

let _isRefreshing = false;
let _refreshQueue = [];

function _processQueue(error, token = null) {
    _refreshQueue.forEach((prom) => (error ? prom.reject(error) : prom.resolve(token)));
    _refreshQueue = [];
}

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const original = error.config;
        if (error.response?.status !== 401 || original._retry) {
            return Promise.reject(error);
        }

        original._retry = true;

        if (_isRefreshing) {
            return new Promise((resolve, reject) => {
                _refreshQueue.push({ resolve, reject });
            }).then((token) => {
                original.headers.Authorization = `Bearer ${token}`;
                return api(original);
            });
        }

        _isRefreshing = true;
        const refreshToken = localStorage.getItem("refresh_token");

        try {
            const { data } = await axios.post("/api/auth/refresh", { refresh_token: refreshToken });
            const newAccess = data.access_token;
            localStorage.setItem("access_token", newAccess);
            localStorage.setItem("refresh_token", data.refresh_token);
            api.defaults.headers.common.Authorization = `Bearer ${newAccess}`;
            _processQueue(null, newAccess);
            original.headers.Authorization = `Bearer ${newAccess}`;
            return api(original);
        } catch (refreshError) {
            _processQueue(refreshError);
            // Clear tokens and force re-login
            localStorage.removeItem("access_token");
            localStorage.removeItem("refresh_token");
            window.dispatchEvent(new Event("auth:logout"));
            return Promise.reject(refreshError);
        } finally {
            _isRefreshing = false;
        }
    }
);

// ══════════════════════════════════════════════════════════════════════════════
// Auth endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const authApi = {
    /** Register a new user account. */
    register: (data) => api.post("/auth/register", data).then((r) => r.data),

    /** Exchange credentials for a JWT token pair. */
    login: (data) => api.post("/auth/login", data).then((r) => r.data),

    /** Refresh the access token using a refresh token. */
    refresh: (refreshToken) =>
        api.post("/auth/refresh", { refresh_token: refreshToken }).then((r) => r.data),

    /** Return the current user's profile. */
    me: () => api.get("/auth/me").then((r) => r.data),

    /** Invalidate the refresh token. */
    logout: (refreshToken) =>
        api.post("/auth/logout", { refresh_token: refreshToken }).then((r) => r.data),
};

// ══════════════════════════════════════════════════════════════════════════════
// Document endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const documentsApi = {
    /**
     * Upload a PDF file for translation.
     * @param {File} file — PDF File object
     * @param {string[]} targetLanguages — e.g. ["es", "pt"]
     * @param {string?} notes — optional submitter notes
     * @param {Function?} onProgress — upload progress callback (0–100)
     */
    upload: (file, targetLanguages = ["es", "pt"], notes = null, onProgress) => {
        const form = new FormData();
        form.append("file", file);
        form.append("target_languages", targetLanguages.join(","));
        if (notes) form.append("notes", notes);
        return api
            .post("/documents/upload", form, {
                headers: { "Content-Type": "multipart/form-data" },
                onUploadProgress: (e) => onProgress?.(Math.round((e.loaded * 100) / e.total)),
            })
            .then((r) => r.data);
    },

    /** Get translation status for a document. */
    status: (documentId) => api.get(`/documents/${documentId}`).then((r) => r.data),

    /** List the current user's documents. */
    list: (page = 1, pageSize = 20) =>
        api.get("/documents/", { params: { page, page_size: pageSize } }).then((r) => r.data),

    /** Delete a document and its translations. */
    delete: (documentId) => api.delete(`/documents/${documentId}`).then((r) => r.data),
};

// ══════════════════════════════════════════════════════════════════════════════
// Forms (catalog) endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const formsApi = {
    /**
     * Search and list court forms.
     * @param {{ q?, division?, language?, status?, page?, page_size? }} params
     */
    list: (params = {}) => api.get("/forms/", { params }).then((r) => r.data),

    /** Get a single form by ID. */
    get: (formId) => api.get(`/forms/${formId}`).then((r) => r.data),

    /** List all court divisions. */
    divisions: () => api.get("/forms/divisions").then((r) => r.data),

    /**
     * Submit a human review decision.
     * requires court_official or admin role.
     */
    review: (formId, approved, reviewerNotes = null) =>
        api
            .patch(`/forms/${formId}/review`, { approved, reviewer_notes: reviewerNotes })
            .then((r) => r.data),
};

// ══════════════════════════════════════════════════════════════════════════════
// Session endpoints
// ══════════════════════════════════════════════════════════════════════════════

export const sessionsApi = {
    /** Create a new real-time interpretation session. */
    create: (targetLanguage = "es", sourceLanguage = "en") =>
        api.post("/sessions/", { target_language: targetLanguage, source_language: sourceLanguage }).then((r) => r.data),

    /** Get session metadata. */
    get: (sessionId) => api.get(`/sessions/${sessionId}`).then((r) => r.data),

    /** End an active session. */
    end: (sessionId) => api.post(`/sessions/${sessionId}/end`).then((r) => r.data),
};

export default api;
