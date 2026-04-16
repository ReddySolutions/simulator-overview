import { useCallback, useState } from "react";
import { useNavigate } from "react-router";
import {
  deleteProject,
  reopenClarification,
} from "../api/client";

interface ProjectControlsProps {
  projectId: string;
  projectName: string;
}

export default function ProjectControls({
  projectId,
  projectName,
}: ProjectControlsProps) {
  const navigate = useNavigate();
  const [reopening, setReopening] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleReopen = useCallback(async () => {
    setReopening(true);
    setError(null);
    try {
      await reopenClarification(projectId);
      navigate(`/clarify/${projectId}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reopen clarification",
      );
      setReopening(false);
    }
  }, [projectId, navigate]);

  const handleDelete = useCallback(async () => {
    setDeleting(true);
    setError(null);
    try {
      await deleteProject(projectId);
      navigate("/");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete project",
      );
      setDeleting(false);
      setConfirmDelete(false);
    }
  }, [projectId, navigate]);

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Reopen Clarification */}
      <button
        type="button"
        disabled={reopening}
        onClick={handleReopen}
        className="rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {reopening ? "Reopening..." : "Reopen Clarification"}
      </button>

      {/* Delete with confirmation */}
      {confirmDelete ? (
        <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 ring-1 ring-inset ring-red-200">
          <span className="text-sm text-red-700">
            Delete &ldquo;{projectName}&rdquo;?
          </span>
          <button
            type="button"
            disabled={deleting}
            onClick={handleDelete}
            className="rounded-md bg-red-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {deleting ? "Deleting..." : "Confirm"}
          </button>
          <button
            type="button"
            disabled={deleting}
            onClick={() => setConfirmDelete(false)}
            className="text-xs text-red-600 hover:text-red-800 underline"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          className="rounded-md bg-white px-3 py-2 text-sm font-semibold text-red-600 shadow-sm ring-1 ring-inset ring-red-200 hover:bg-red-50 transition-colors"
        >
          Delete Project
        </button>
      )}

      {/* Error message */}
      {error && (
        <span className="text-sm text-red-600">{error}</span>
      )}
    </div>
  );
}
