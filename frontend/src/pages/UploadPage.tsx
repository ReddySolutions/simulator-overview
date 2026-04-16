import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { createProject, uploadFile } from "../api/client";

interface StagedFile {
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
}

const ACCEPTED_TYPES = new Set(["video/mp4", "application/pdf"]);

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<StagedFile[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);

  const hasMp4 = files.some((f) => f.file.type === "video/mp4");
  const hasPdf = files.some((f) => f.file.type === "application/pdf");
  const isValid = hasMp4 && hasPdf;
  const allDone = files.length > 0 && files.every((f) => f.status === "done");

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const newFiles: StagedFile[] = [];
      const rejected: string[] = [];

      for (const file of incoming) {
        if (!ACCEPTED_TYPES.has(file.type)) {
          rejected.push(file.name);
        } else {
          newFiles.push({ file, status: "pending" });
        }
      }

      if (rejected.length > 0) {
        setError(
          `Rejected (only MP4 and PDF allowed): ${rejected.join(", ")}`,
        );
      } else {
        setError(null);
      }

      if (newFiles.length > 0) {
        setFiles((prev) => [...prev, ...newFiles]);
      }
    },
    [],
  );

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles],
  );

  const handleUpload = useCallback(async () => {
    if (!isValid || uploading) return;
    setUploading(true);
    setError(null);

    try {
      // Create project
      const project = await createProject("Untitled Project");
      const pid = project.project_id;
      setProjectId(pid);

      // Upload each file sequentially with progress tracking
      for (let i = 0; i < files.length; i++) {
        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, status: "uploading" } : f)),
        );
        try {
          await uploadFile(pid, files[i].file);
          setFiles((prev) =>
            prev.map((f, idx) => (idx === i ? { ...f, status: "done" } : f)),
          );
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Upload failed";
          setFiles((prev) =>
            prev.map((f, idx) =>
              idx === i ? { ...f, status: "error", error: msg } : f,
            ),
          );
          setError(`Failed to upload ${files[i].file.name}: ${msg}`);
          setUploading(false);
          return;
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create project";
      setError(msg);
    }

    setUploading(false);
  }, [files, isValid, uploading]);

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-semibold mb-6">Upload Files</h2>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-colors ${
          dragOver
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".mp4,.pdf"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <svg
          className="mx-auto h-12 w-12 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
          />
        </svg>
        <p className="mt-3 text-sm text-gray-600">
          Drag and drop MP4 and PDF files here, or click to browse
        </p>
        <p className="mt-1 text-xs text-gray-400">
          MP4 videos (max 40 MB) and PDF documents
        </p>
      </div>

      {/* Error message */}
      {error && (
        <div className="mt-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
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

      {/* Validation warning */}
      {files.length > 0 && !isValid && (
        <div className="mt-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-700 flex items-center gap-2">
          <svg className="h-4 w-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z"
              clipRule="evenodd"
            />
          </svg>
          Add at least one MP4 and one PDF
          {!hasMp4 && !hasPdf && " — both are missing"}
          {hasMp4 && !hasPdf && " — add a PDF document"}
          {!hasMp4 && hasPdf && " — add an MP4 video"}
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <ul className="mt-4 divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
          {files.map((sf, i) => (
            <li
              key={`${sf.file.name}-${i}`}
              className="flex items-center gap-3 px-4 py-3"
            >
              {/* Type icon */}
              {sf.file.type === "video/mp4" ? (
                <svg
                  className="h-5 w-5 text-purple-500 shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z"
                  />
                </svg>
              ) : (
                <svg
                  className="h-5 w-5 text-red-500 shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
                  />
                </svg>
              )}

              {/* File info */}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">
                  {sf.file.name}
                </p>
                <p className="text-xs text-gray-500">
                  {formatBytes(sf.file.size)}
                </p>
              </div>

              {/* Status indicator */}
              {sf.status === "uploading" && (
                <span className="text-xs text-blue-600 font-medium">
                  Uploading...
                </span>
              )}
              {sf.status === "done" && (
                <svg
                  className="h-5 w-5 text-green-500 shrink-0"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
              {sf.status === "error" && (
                <span className="text-xs text-red-600 font-medium" title={sf.error}>
                  Failed
                </span>
              )}

              {/* Remove button (only when not uploading/done) */}
              {sf.status === "pending" && (
                <button
                  type="button"
                  onClick={() => removeFile(i)}
                  className="text-gray-400 hover:text-red-500 transition-colors"
                >
                  <svg
                    className="h-5 w-5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Actions */}
      <div className="mt-6 flex gap-3">
        {!allDone && (
          <button
            type="button"
            disabled={!isValid || uploading}
            onClick={handleUpload}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {uploading ? "Uploading..." : "Upload Files"}
          </button>
        )}

        {allDone && projectId && (
          <button
            type="button"
            onClick={() => navigate(`/progress/${projectId}`)}
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500 transition-colors"
          >
            Start Analysis
          </button>
        )}
      </div>
    </div>
  );
}
