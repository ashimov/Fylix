import { request } from "./client";

export interface TelegramConfig {
  bot_token_is_set: boolean;
  chat_id: string;
  alert_on_infected: boolean;
  alert_on_rate_limit_spike: boolean;
  alert_on_admin_login_fail_spike: boolean;
  alert_on_storage_high: boolean;
  alert_on_defender_event: boolean;
  rate_limit_spike_threshold: number;
}

export interface TelegramConfigUpdate {
  bot_token?: string;
  chat_id?: string;
  alert_on_infected?: boolean;
  alert_on_rate_limit_spike?: boolean;
  alert_on_admin_login_fail_spike?: boolean;
  alert_on_storage_high?: boolean;
  alert_on_defender_event?: boolean;
  rate_limit_spike_threshold?: number;
}

export function getTelegram(): Promise<TelegramConfig> {
  return request<TelegramConfig>("/api/admin/telegram");
}

export function patchTelegram(body: TelegramConfigUpdate): Promise<TelegramConfig> {
  return request<TelegramConfig>("/api/admin/telegram", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}
