import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { deleteProject, listProjects } from "../api/client";
import type { ProjectSummary } from "../types";

const STATUS_CONFIG: Record<
  string,
  { badge: string; label: string; route: (id: string) => string }
> = {
  uploading: {
    badge: "bg-gray-100 text-gray-600",
    label: "Uploading",
    route: (id) => `/upload?resume=${id}`,
  },
  analyzing: {
    badge: "bg-blue-100 text-blue-700",
    label: "Analyzing",
    route: (id) => `/progress/${id}`,
  },
  clarifying: {
    badge: "bg-amber-100 text-amber-700",
    label: "Clarifying",
    route: (id) => `/clarify/${id}`,
  },
  generating: {
    badge: "bg-purple-100 text-purple-700",
    label: "Generating",
    route: (id) => `/progress/${id}`,
  },
  complete: {
    badge: "bg-green-100 text-green-700",
    label: "Complete",
    route: (id) => `/walkthrough/${id}`,
  },
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: d.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

export default function ProjectListPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const fetchProjects = useCallback(async () => {
    try {
      const data = await listProjects();
      setProjects(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load projects");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleDelete = useCallback(
    async (projectId: string, name: string) => {
      if (!confirm(`Delete project "${name}"? This cannot be undone.`)) return;
      setDeleting(projectId);
      try {
        await deleteProject(projectId);
        setProjects((prev) =>
          prev.filter((p) => p.project_id !== projectId),
        );
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to delete project",
        );
      } finally {
        setDeleting(null);
      }
    },
    [],
  );

  const handleCardClick = useCallback(
    (project: ProjectSummary) => {
      const config = STATUS_CONFIG[project.status];
      if (config) {
        navigate(config.route(project.project_id));
      }
    },
    [navigate],
  );

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h2 className="text-2xl font-semibold">Projects</h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="rounded-lg border border-gray-200 p-5 animate-pulse"
            >
              <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
              <div className="h-4 bg-gray-100 rounded w-1/3 mb-4" />
              <div className="h-3 bg-gray-100 rounded w-1/2" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-2xl font-semibold">Projects</h2>
        <Link
          to="/upload"
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 transition-colors"
        >
          New Project
        </Link>
      </div>

      {error && (
        <div className="mb-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <svg
            className="h-4 w-4 shrink-0"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-red-700 underline hover:text-red-800 text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {projects.length === 0 ? (
        <div className="text-center py-16">
          <svg
            className="mx-auto h-12 w-12 text-gray-300"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"
            />
          </svg>
          <p className="mt-4 text-lg font-medium text-gray-500">
            No projects yet
          </p>
          <p className="mt-1 text-sm text-gray-400">
            Upload MP4 and PDF files to get started.
          </p>
          <Link
            to="/upload"
            className="mt-6 inline-block rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 transition-colors"
          >
            Create your first project
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => {
            const config = STATUS_CONFIG[project.status] ?? {
              badge: "bg-gray-100 text-gray-600",
              label: project.status,
              route: () => "/",
            };
            const isDeleting = deleting === project.project_id;

            return (
              <div
                key={project.project_id}
                role="button"
                tabIndex={0}
                onClick={() => !isDeleting && handleCardClick(project)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !isDeleting) handleCardClick(project);
                }}
                className={`rounded-lg border border-gray-200 p-5 hover:border-gray-300 hover:shadow-sm transition-all cursor-pointer ${
                  isDeleting ? "opacity-50 pointer-events-none" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold text-gray-900 truncate">
                    {project.name}
                  </h3>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(project.project_id, project.name);
                    }}
                    disabled={isDeleting}
                    className="text-gray-400 hover:text-red-500 transition-colors shrink-0"
                    title="Delete project"
                  >
                    <svg
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                      />
                    </svg>
                  </button>
                </div>

                <div className="mt-2">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${config.badge}`}
                  >
                    {config.label}
                  </span>
                </div>

                <p className="mt-3 text-xs text-gray-400">
                  Updated {formatDate(project.updated_at)}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
