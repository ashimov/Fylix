import { defineStore } from "pinia";
import { ref } from "vue";

import { ApiError } from "@/api/client";
import { login as apiLogin, logout as apiLogout, me as apiMe } from "@/api/auth";
import type { AdminPublic, LoginRequest } from "@/api/types";

export const useSession = defineStore("session", () => {
  const admin = ref<AdminPublic | null>(null);
  const hydrated = ref(false);
  const error = ref<string | null>(null);

  async function refresh(): Promise<void> {
    try {
      admin.value = await apiMe();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        admin.value = null;
      } else {
        throw e;
      }
    } finally {
      hydrated.value = true;
    }
  }

  async function login(req: LoginRequest): Promise<void> {
    error.value = null;
    try {
      const resp = await apiLogin(req);
      admin.value = resp.admin;
      hydrated.value = true;
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) error.value = "invalid_credentials";
        else if (e.status === 403) error.value = "disabled";
        else if (e.status === 423) error.value = "locked";
        else if (e.status === 400) error.value = "totp_not_enrolled";
        else error.value = `${e.status}`;
      } else {
        error.value = "network";
      }
      throw e;
    }
  }

  async function logout(): Promise<void> {
    await apiLogout();
    admin.value = null;
  }

  return { admin, hydrated, error, refresh, login, logout };
});
