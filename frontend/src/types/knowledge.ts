/** Wire schemas from backend/app/schemas/knowledge.py. UUIDs and dates are strings. */
export type KnowledgeDocumentParseStatus = "ready" | "failed";
export type KnowledgeIndexJobStatus = "pending" | "running" | "succeeded" | "failed";
export type KnowledgeIndexStatus = "not_indexed" | KnowledgeIndexJobStatus;
export type KnowledgeAskStatus = "answered" | "no_evidence";

export interface KnowledgeBaseCreate {
  name: string;
  description?: string | null;
}

export interface KnowledgeBaseUpdate {
  name?: string;
  description?: string | null;
}

export interface KnowledgeBaseRead {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface KnowledgeBaseList {
  items: KnowledgeBaseRead[];
  total: number;
}

export interface KnowledgeDocumentRead {
  id: string;
  workspace_id: string;
  knowledge_base_id: string;
  created_by_user_id: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  parse_status: KnowledgeDocumentParseStatus;
  parse_error_code: string | null;
  page_count: number | null;
  parse_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
}

export interface KnowledgeDocumentList {
  items: KnowledgeDocumentRead[];
  total: number;
}

export interface KnowledgeDocumentContent {
  document_id: string;
  content: string;
  page_count: number | null;
  parse_metadata: Record<string, unknown>;
}

export interface KnowledgeIndexJobRead {
  id: string;
  document_id: string;
  status: KnowledgeIndexJobStatus;
  embedding_model: string;
  embedding_dimensions: number;
  index_generation_id: string;
  chunking_config_version: string;
  attempt_count: number;
  error_code: string | null;
  created_at: string;
}

export interface KnowledgeIndexStatusRead {
  document_id: string;
  job_id: string | null;
  status: KnowledgeIndexStatus;
  active_generation_id: string | null;
  chunk_count: number;
  embedding_model: string | null;
  index_version: string | null;
  error_code: string | null;
}

export interface KnowledgeSearchRequest {
  /** Backend validates 1–2000 characters. */
  query: string;
  /** Integer 1–20; default 5. */
  top_k?: number;
  /** -1 to 1, or null. */
  min_score?: number | null;
}

export interface KnowledgeSearchItemRead {
  chunk_id: string;
  document_id: string;
  knowledge_base_id: string;
  filename: string;
  chunk_index: number;
  content: string;
  start_offset: number;
  end_offset: number;
  page_start: number | null;
  page_end: number | null;
  similarity_score: number;
}

export interface KnowledgeSearchResponse {
  query: string;
  results: KnowledgeSearchItemRead[];
  total: number;
  embedding_model: string;
}

export interface KnowledgeAskRequest {
  /** Backend validates 1–2000 characters; no session or model configuration. */
  question: string;
}

export interface KnowledgeAgentSourceRead {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_start: number | null;
  page_end: number | null;
  similarity_score: number;
}

export interface KnowledgeAskResponse {
  answer: string;
  status: KnowledgeAskStatus;
  sources: KnowledgeAgentSourceRead[];
}
