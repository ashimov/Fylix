import { request } from "./client";

export type BlocklistKind = "ips" | "domains" | "emails";

export interface BlocklistEntry {
  value: string;
  reason: string | null;
  added_at: string;
  expires_at: string | null;
}

export function listBlocklist(kind: BlocklistKind): Promise<BlocklistEntry[]> {
  return request<BlocklistEntry[]>(`/api/admin/blocklist/${kind}`);
}

export function addBlocklist(
  kind: BlocklistKind,
  body: { value: string; reason?: string | null; expires_at?: string | null },
): Promise<void> {
  return request<void>(`/api/admin/blocklist/${kind}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function removeBlocklist(kind: BlocklistKind, value: string): Promise<void> {
  return request<void>(
    `/api/admin/blocklist/${kind}/${encodeURIComponent(value)}`,
    { method: "DELETE" },
  );
}
