const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api"
).replace(/\/$/, "");

let csrfToken: string | null = null;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly data: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.method && !["GET", "HEAD", "OPTIONS"].includes(options.method.toUpperCase())) {
    if (!csrfToken) await refreshCsrfToken();
    if (csrfToken) headers.set("X-CSRFToken", csrfToken);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 204) return undefined as T;

  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      typeof data === "object" && data !== null && "detail" in data
        ? String(data.detail)
        : "The request could not be completed.";
    throw new ApiError(message, response.status, data);
  }
  return data as T;
}

async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: { Accept: "application/pdf, text/markdown" },
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const message =
      typeof data === "object" && data !== null && "detail" in data
        ? String(data.detail)
        : "The export could not be downloaded.";
    throw new ApiError(message, response.status, data);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const extension = path.endsWith(".pdf") ? ".pdf" : ".md";
  const filename = disposition.match(/filename="([A-Za-z0-9._-]+)"/)?.[1]
    ?? `engineering-specification${extension}`;
  return { blob: await response.blob(), filename };
}

export async function refreshCsrfToken(): Promise<void> {
  csrfToken = null;
  const response = await fetch(`${API_BASE_URL}/auth/csrf/`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new ApiError("Could not establish a secure session.", response.status, null);
  const data: { csrfToken: string } = await response.json();
  csrfToken = data.csrfToken;
}

export const api = {
  get: <T>(path: string, options: Pick<RequestInit, "signal"> = {}) =>
    request<T>(path, options),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  download,
};
