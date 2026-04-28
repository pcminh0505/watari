const BASE = import.meta.env.VITE_API_BASE_URL ?? "https://watari-api.fly.dev";
const KEY = import.meta.env.VITE_API_KEY ?? "";

function getHeaders(): HeadersInit {
  return KEY ? { "X-API-Key": KEY } : {};
}

export async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: getHeaders() });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiFetchPaged<T>(
  path: string
): Promise<{ data: T[]; total: number }> {
  const res = await fetch(`${BASE}${path}`, { headers: getHeaders() });
  if (!res.ok) throw new Error(`API ${res.status}`);
  const total = parseInt(res.headers.get("X-Total-Count") ?? "0", 10);
  return { data: (await res.json()) as T[], total };
}
