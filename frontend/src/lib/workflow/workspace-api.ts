import { apiClient, type RequestOptions } from "@/lib/api-client";
import type {
  WorkspaceCreate,
  WorkspaceList,
  WorkspaceMemberCreate,
  WorkspaceMemberRead,
  WorkspaceMemberUpdate,
  WorkspaceRead,
  WorkspaceUpdate,
} from "@/types";

const workspacePath = (workspaceId: string) => `/workspaces/${encodeURIComponent(workspaceId)}`;

export const workspaceApi = {
  listWorkspaces: (options?: RequestOptions) =>
    options
      ? apiClient.get<WorkspaceList>("/workspaces", options)
      : apiClient.get<WorkspaceList>("/workspaces"),
  createWorkspace: (payload: WorkspaceCreate) =>
    apiClient.post<WorkspaceRead>("/workspaces", payload),
  getWorkspace: (workspaceId: string) => apiClient.get<WorkspaceRead>(workspacePath(workspaceId)),
  updateWorkspace: (workspaceId: string, payload: WorkspaceUpdate) =>
    apiClient.patch<WorkspaceRead>(workspacePath(workspaceId), payload),
  deleteWorkspace: (workspaceId: string) => apiClient.delete<null>(workspacePath(workspaceId)),
  listMembers: (workspaceId: string, options?: RequestOptions) =>
    options
      ? apiClient.get<WorkspaceMemberRead[]>(`${workspacePath(workspaceId)}/members`, options)
      : apiClient.get<WorkspaceMemberRead[]>(`${workspacePath(workspaceId)}/members`),
  addMember: (workspaceId: string, payload: WorkspaceMemberCreate) =>
    apiClient.post<WorkspaceMemberRead>(`${workspacePath(workspaceId)}/members`, payload),
  updateMember: (workspaceId: string, userId: string, payload: WorkspaceMemberUpdate) =>
    apiClient.patch<WorkspaceMemberRead>(
      `${workspacePath(workspaceId)}/members/${encodeURIComponent(userId)}`,
      payload,
    ),
  removeMember: (workspaceId: string, userId: string) =>
    apiClient.delete<null>(`${workspacePath(workspaceId)}/members/${encodeURIComponent(userId)}`),
};
