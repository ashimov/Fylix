const BASE = ""; // same origin — nginx proxies /api, /t, /s to api container

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
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
