import { request } from "./client";

export interface AnalyticsResponse {
  kpi: {
    active_transfers: number;
    traffic_today_gb: number;
    traffic_week_gb: number;
    infected_count: number;
    rate_limit_blocks_today: number;
  };
  daily_transfers: { date: string; count: number; bytes: number }[];
  top_countries: { country: string; count: number }[];
  top_mime: { mime: string; count: number }[];
  top_ips: { ip: string; count: number }[];
  top_sender_domains: { domain: string; count: number }[];
  infected_timeline: { date: string; count: number }[];
}

export function getAnalytics(days = 30): Promise<AnalyticsResponse> {
  return request<AnalyticsResponse>(`/api/admin/analytics?days=${days}`);
}
