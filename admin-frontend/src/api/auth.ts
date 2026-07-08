import { request } from "./client";
import type { AdminPublic, LoginRequest, LoginResponse } from "./types";

export function login(body: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/api/admin/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function logout(): Promise<void> {
  return request<void>("/api/admin/logout", { method: "POST" });
}

export function me(): Promise<AdminPublic> {
  return request<AdminPublic>("/api/admin/me");
}
