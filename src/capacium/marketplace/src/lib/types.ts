export type Kind =
  | "skill"
  | "bundle"
  | "tool"
  | "prompt"
  | "template"
  | "workflow"
  | "mcp-server"
  | "connector-pack";

export type TrustLevel = "discovered" | "audited" | "verified" | "signed";

export interface TrustScore {
  overall: number;
  schema: number;
  security: number;
  maintenance: number;
  community: number;
  docs: number;
}

export interface DepVersion {
  [dep: string]: string;
}

export interface CapabilityResult {
  name: string;
  owner: string;
  kind: Kind;
  version: string;
  description: string;
  frameworks: string[];
  fingerprint?: string;
  trust?: TrustLevel;
  trust_score?: TrustScore;
  dependencies?: DepVersion;
  installs?: number;
  updated_at?: string;
  created_at?: string;
  categories?: string[];
  shortcuts?: Record<string, string>;
}

export interface CapabilityDetail extends CapabilityResult {
  versions?: { version: string; published_at: string }[];
}

export interface SearchResponse {
  results: CapabilityResult[];
  total: number;
  page: number;
  per_page: number;
}

export interface Stats {
  capabilities: number;
  publishers: number;
  frameworks: number;
}

export interface Category {
  name: string;
  slug: string;
  count?: number;
}

export interface Publisher {
  owner: string;
  capabilities: CapabilityResult[];
  aggregate_trust?: number;
}
