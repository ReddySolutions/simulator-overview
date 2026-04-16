import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router";
import { getProject } from "../api/client";
import type { Project, WalkthroughOutput } from "../types";
import RoutingDiagram from "../components/RoutingDiagram";
import SubDiagram from "../components/SubDiagram";

type Tab = "routing" | "simulation" | "questions";

const TABS: { id: Tab; label: string }[] = [
  { id: "routing", label: "Routing Diagram" },
  { id: "simulation", label: "Simulation" },
  { id: "questions", label: "Open Questions" },
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

export default function WalkthroughPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("routing");
  const [selectedScreenId, setSelectedScreenId] = useState<string | null>(null);

  const fetchProject = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const data = await getProject(id);
      setProject(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load project");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchProject();
  }, [fetchProject]);

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto">
        {/* Hero skeleton */}
        <div className="rounded-lg border border-gray-200 bg-white p-6 mb-6 animate-pulse">
          <div className="h-7 bg-gray-200 rounded w-1/3 mb-3" />
          <div className="h-4 bg-gray-100 rounded w-1/2 mb-6" />
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((n) => (
              <div key={n} className="h-20 bg-gray-100 rounded" />
            ))}
          </div>
        </div>
        {/* Tab skeleton */}
        <div className="h-10 bg-gray-100 rounded w-2/3 mb-4" />
        <div className="h-64 bg-gray-100 rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-6xl mx-auto">
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <svg className="h-4 w-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={fetchProject}
            className="text-red-700 underline hover:text-red-800 text-xs"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!project) return null;

  const output: WalkthroughOutput | null = project.walkthrough_output;
  const stats = output?.stats;
  const warnings = output?.warnings ?? [];
  const sourceCount = project.videos.length + project.pdfs.length;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Warnings banner */}
      {warnings.length > 0 && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 px-4 py-3">
          <div className="flex items-start gap-2">
            <svg
              className="h-5 w-5 text-red-500 mt-0.5 shrink-0"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                clipRule="evenodd"
              />
            </svg>
            <div>
              <h3 className="text-sm font-semibold text-red-800">
                {warnings.length} unresolved critical{" "}
                {warnings.length === 1 ? "gap" : "gaps"}
              </h3>
              <ul className="mt-1 text-sm text-red-700 space-y-1">
                {warnings.map((w) => (
                  <li key={w.gap_id}>
                    {w.description}
                    {w.screen_id && (
                      <span className="text-red-500 ml-1">
                        (Screen: {output?.screens[w.screen_id]?.title ?? w.screen_id.slice(0, 8)})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Hero section */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
        <p className="mt-1 text-sm text-gray-500">
          Generated from {sourceCount} source{" "}
          {sourceCount === 1 ? "file" : "files"} ({project.videos.length}{" "}
          {project.videos.length === 1 ? "video" : "videos"},{" "}
          {project.pdfs.length} {project.pdfs.length === 1 ? "PDF" : "PDFs"})
          &middot; {formatDate(project.updated_at)}
        </p>

        {/* Stats cards */}
        {stats && (
          <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Screens" value={stats.total_screens} />
            <StatCard label="Branch Points" value={stats.total_branches} />
            <StatCard label="Decision Paths" value={stats.total_paths} />
            <StatCard
              label="Open Questions"
              value={stats.open_questions}
              highlight={stats.open_questions > 0}
            />
          </div>
        )}
      </div>

      {/* Navigation tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex gap-6" aria-label="Tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
              }`}
            >
              {tab.label}
              {tab.id === "questions" && stats && stats.open_questions > 0 && (
                <span className="ml-2 inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                  {stats.open_questions}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === "routing" && output && (
        selectedScreenId ? (
          <SubDiagram
            trees={output.decision_trees}
            screens={output.screens}
            initialScreenId={selectedScreenId}
            onBack={() => setSelectedScreenId(null)}
          />
        ) : (
          <RoutingDiagram
            trees={output.decision_trees}
            screens={output.screens}
            onSelectScreen={setSelectedScreenId}
          />
        )
      )}
      {activeTab === "simulation" && (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-400">
          <p>Simulation Navigator will be rendered here.</p>
        </div>
      )}
      {activeTab === "questions" && (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-400">
          <p>Open Questions will be rendered here.</p>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        highlight
          ? "border-amber-200 bg-amber-50"
          : "border-gray-200 bg-gray-50"
      }`}
    >
      <p
        className={`text-2xl font-bold ${
          highlight ? "text-amber-700" : "text-gray-900"
        }`}
      >
        {value}
      </p>
      <p
        className={`text-sm ${
          highlight ? "text-amber-600" : "text-gray-500"
        }`}
      >
        {label}
      </p>
    </div>
  );
}
