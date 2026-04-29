import type {
  SearchResponse,
  CapabilityDetail,
  Stats,
  Category,
  Publisher,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/v1";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });

  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }

  return res.json();
}

export async function searchCapabilities(params: {
  q?: string;
  kind?: string;
  framework?: string;
  trust?: string;
  page?: number;
  per_page?: number;
  sort?: string;
}): Promise<SearchResponse> {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.kind) sp.set("kind", params.kind);
  if (params.framework) sp.set("framework", params.framework);
  if (params.trust) sp.set("trust", params.trust);
  if (params.page) sp.set("page", String(params.page));
  if (params.per_page) sp.set("per_page", String(params.per_page));
  if (params.sort) sp.set("sort", params.sort);
  const qs = sp.toString();
  return fetchAPI<SearchResponse>(`/search${qs ? `?${qs}` : ""}`);
}

export async function getCapability(
  owner: string,
  name: string
): Promise<CapabilityDetail> {
  return fetchAPI<CapabilityDetail>(
    `/capabilities/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
  );
}

export async function getStats(): Promise<Stats> {
  return fetchAPI<Stats>("/stats");
}

export async function getCategories(): Promise<Category[]> {
  return fetchAPI<Category[]>("/categories");
}

export async function getPublisher(owner: string): Promise<Publisher> {
  return fetchAPI<Publisher>(`/publishers/${encodeURIComponent(owner)}`);
}

export async function getRecentCapabilities(): Promise<SearchResponse> {
  return searchCapabilities({ sort: "recent", per_page: 12 });
}
