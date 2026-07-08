import { request } from "./client";

/**
 * Mutable admin settings surfaced via GET/PATCH /api/admin/settings.
 * Known keys are typed narrowly; the index signature keeps compatibility
 * with forward-compat keys the backend may add without a frontend release.
 */
export interface SettingsPayload {
  // Upload / transfer limits
  max_transfer_size_gb?: number;
  max_ttl_days?: number;
  max_recipients?: number;
  max_message_length?: number;
  // Rate limits (per IP)
  rate_hourly?: number;
  rate_daily?: number;
  rate_download_hourly?: number;
  // GeoIP gate
  geoip_enabled?: boolean;
  geoip_countries?: string[];
  // Retention
  audit_retention_days?: number;
  // Forward-compat: unknown future keys
  [key: string]: unknown;
}

export function getSettings(): Promise<SettingsPayload> {
  return request<SettingsPayload>("/api/admin/settings");
}

export function patchSettings(body: SettingsPayload): Promise<void> {
  return request<void>("/api/admin/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function getExtensions(): Promise<string[]> {
  return request<string[]>("/api/admin/extensions");
}

export function addExtension(extension: string): Promise<void> {
  return request<void>("/api/admin/extensions", {
    method: "POST",
    body: JSON.stringify({ extension }),
  });
}

export function removeExtension(extension: string): Promise<void> {
  return request<void>(
    `/api/admin/extensions/${encodeURIComponent(extension)}`,
    { method: "DELETE" },
  );
}
