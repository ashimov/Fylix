import { request } from "./client";

export interface AuditRow {
  id: number;
  ts: string;
  event_type: string;
  severity: string;
  ip: string | null;
  country: string | null;
  transfer_id: string | null;
  admin_id: string | null;
  details: Record<string, unknown> | null;
}

export interface AuditListResponse {
  items: AuditRow[];
  next_cursor: string | null;
}

export function listAudit(params: Record<string, string | number | undefined> = {}): Promise<AuditListResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const suffix = qs.toString();
  return request<AuditListResponse>(`/api/admin/audit${suffix ? "?" + suffix : ""}`);
}

export interface AdminActionRow {
  id: number;
  ts: string;
  admin_id: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  ip: string | null;
  details: Record<string, unknown> | null;
}

export interface AdminActionListResponse {
  items: AdminActionRow[];
  next_cursor: string | null;
}

export function listAdminActions(params: Record<string, string | number | undefined> = {}): Promise<AdminActionListResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const suffix = qs.toString();
  return request<AdminActionListResponse>(`/api/admin/admin-actions${suffix ? "?" + suffix : ""}`);
}
