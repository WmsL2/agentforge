export type WorkspaceRole = "owner" | "admin" | "member";

export interface WorkspaceRead {
  id: string;
  name: string;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface WorkspaceList {
  items: WorkspaceRead[];
}

export interface WorkspaceCreate {
  name: string;
}

export interface WorkspaceUpdate {
  name?: string | null;
}

export interface WorkspaceMemberRead {
  workspace_id: string;
  user_id: string;
  role: WorkspaceRole;
  created_at: string;
  updated_at: string | null;
}

export interface WorkspaceMemberCreate {
  user_id: string;
  role?: WorkspaceRole;
}

export interface WorkspaceMemberUpdate {
  role: WorkspaceRole;
}
