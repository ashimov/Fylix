import { request } from "./client";

export interface AdminRow {
  id: string;
  email: string;
  role: string;
  disabled: boolean;
  totp_enrolled: boolean;
  last_login_at: string | null;
  created_at: string;
  failed_attempts: number;
  locked_until: string | null;
}

export interface AdminCreateRequest {
  email: string;
  password: string;
  role: "admin" | "viewer";
}

export interface AdminCreateResponse {
  admin: AdminRow;
  totp_uri: string;
}

export interface ResetTotpResponse {
  totp_uri: string;
}

export function listAdmins(): Promise<AdminRow[]> {
  return request<AdminRow[]>("/api/admin/admins");
}

export function createAdmin(body: AdminCreateRequest): Promise<AdminCreateResponse> {
  return request<AdminCreateResponse>("/api/admin/admins", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateAdmin(
  id: string,
  body: { role?: "admin" | "viewer"; disabled?: boolean },
): Promise<AdminRow> {
  return request<AdminRow>(`/api/admin/admins/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function resetTotp(id: string): Promise<ResetTotpResponse> {
  return request<ResetTotpResponse>(`/api/admin/admins/${id}/reset-totp`, {
    method: "POST",
  });
}

export function deleteAdmin(id: string): Promise<void> {
  return request<void>(`/api/admin/admins/${id}`, { method: "DELETE" });
}
