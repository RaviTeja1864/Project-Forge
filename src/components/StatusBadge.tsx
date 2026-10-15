import type { WorkspaceStatus } from "../types";

const labels: Record<WorkspaceStatus, string> = {
  planning: "Planning",
  in_progress: "In progress",
  completed: "Completed",
};

export function StatusBadge({ status }: { status: WorkspaceStatus }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>;
}
