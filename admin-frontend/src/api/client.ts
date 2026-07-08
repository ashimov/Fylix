const BASE = "";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (MUTATING.has(method)) {
    const csrf = readCookie("csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const resp = await fetch(BASE + path, {
    ...init,
    method,
    headers,
    credentials: "include",
  });
  if (resp.status === 401 && !path.endsWith("/login")) {
    // Bounce to login if session expired/missing
    if (!window.location.pathname.startsWith("/admin/login")) {
      window.location.assign("/admin/login");
    }
  }
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new ApiError(resp.status, body || resp.statusText);
  }
  const ct = resp.headers.get("content-type") ?? "";
  if (resp.status === 204 || !ct.includes("application/json")) {
    return undefined as unknown as T;
  }
  return (await resp.json()) as T;
}
