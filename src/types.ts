export type User = {
  id: number;
  email: string;
  date_joined: string;
};

export type WorkspaceStatus = "planning" | "in_progress" | "completed";

export type Workspace = {
  id: string;
  name: string;
  description: string;
  status: WorkspaceStatus;
  created_at: string;
  updated_at: string;
  access_role: "owner" | "collaborator";
};

export type WorkspaceInput = Pick<Workspace, "name" | "description" | "status">;

export type WorkspaceCollaborator = {
  id: number;
  email: string;
  granted_by_email: string;
  granted_at: string;
  revoked_at: string | null;
  access_status: "active" | "revoked";
};

export type WorkspaceArtifactKind = "research" | "requirements" | "technology" | "design" | "specification";
export type WorkspaceArtifactStatus = "draft" | "approved";

export type WorkspaceArtifact = {
  id: string;
  kind: WorkspaceArtifactKind;
  status: WorkspaceArtifactStatus;
  is_outdated: boolean;
  version_number: number;
  lineage_root_id: string;
  revision_of_id: string | null;
  author_id: number | null;
  content: Record<string, unknown>;
  source_snapshot: Array<{
    id: string;
    external_source_id?: string;
    source_url: string;
    canonical_url?: string;
    source_title: string;
    publisher: string | null;
    publication_date: string | null;
    retrieved_at?: string;
    relevant_excerpt: string | null;
    source_type?: string;
  }>;
  source_problem_id: string | null;
  input_artifact_ids: string[];
  created_at: string;
  updated_at: string;
};

export type WorkspaceArtifactVersionComparison = {
  left_version: WorkspaceArtifact;
  right_version: WorkspaceArtifact;
  changed_fields: string[];
  changes: Array<{
    path: string;
    before: unknown;
    after: unknown;
    before_present?: boolean;
    after_present?: boolean;
  }>;
};

export type WorkspaceSpecificationInputs = {
  specification_id: string;
  is_outdated: boolean;
  input_artifacts: WorkspaceArtifact[];
  validation_findings: Array<{
    severity: "warning" | "error";
    code: string;
    path: string;
    message: string;
  }>;
};

export type OllamaStatus = {
  available: boolean;
  model: string;
  state: "available" | "model_missing" | "offline" | "timeout" | "invalid_response" | "misconfigured";
};

export type ProblemStatement = {
  id: string;
  title: string;
  description: string;
  sector: string;
  difficulty: "unspecified" | "beginner" | "intermediate" | "advanced";
  status: "published" | "archived";
  evidence_source_count: number;
  created_at: string;
  updated_at: string;
};

export type EvidenceSource = {
  id: string;
  source_url: string;
  source_title: string;
  publisher: string;
  publication_date: string | null;
  retrieved_at: string;
  relevant_excerpt: string;
  source_type: "report" | "article" | "dataset" | "official_release" | "other";
};

export type SimilarProblem = {
  problem: ProblemStatement;
  similarity_score: number;
  matching_signals: string[];
};

export type SimilarProblems = {
  threshold: number;
  count: number;
  results: SimilarProblem[];
};

export type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};
