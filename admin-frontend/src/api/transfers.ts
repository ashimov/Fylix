import { request } from "./client";

export interface TransferRow {
  id: string;
  sender_email: string;
  sender_ip: string;
  sender_country: string | null;
  total_size: number;
  file_count: number;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface TransferListResponse {
  items: TransferRow[];
  next_cursor: string | null;
}

export interface FileDetail {
  id: string;
  filename: string;
  size_bytes: number;
  mime_type: string;
}
export interface RecipientDetail {
  email: string;
  email_sent_at: string | null;
  email_status: string | null;
}
export interface DownloadDetail {
  ip: string;
  country: string | null;
  ua: string | null;
  started_at: string;
  completed_at: string | null;
  bytes_sent: number | null;
  aborted: boolean;
}

export interface TransferDetailResponse {
  id: string;
  sender_email: string;
  sender_ip: string;
  sender_country: string | null;
  sender_city: string | null;
  message: string | null;
  status: string;
  total_size: number;
  file_count: number;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  deleted_at: string | null;
  infected_at: string | null;
  files: FileDetail[];
  recipients: RecipientDetail[];
  downloads: DownloadDetail[];
}

export function listTransfers(
  params: {
    status?: string;
    country?: string;
    size_min?: number;
    size_max?: number;
    q?: string;
    limit?: number;
    cursor?: string;
  } = {},
): Promise<TransferListResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const suffix = qs.toString();
  return request<TransferListResponse>(
    `/api/admin/transfers${suffix ? "?" + suffix : ""}`,
  );
}

export function getTransfer(id: string): Promise<TransferDetailResponse> {
  return request<TransferDetailResponse>(`/api/admin/transfers/${encodeURIComponent(id)}`);
}

export function deleteTransfer(id: string): Promise<void> {
  return request<void>(`/api/admin/transfers/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function revokeTransfer(id: string): Promise<void> {
  return request<void>(`/api/admin/transfers/${encodeURIComponent(id)}/revoke`, {
    method: "POST",
  });
}
