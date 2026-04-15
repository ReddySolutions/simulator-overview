import { Link, Outlet, useParams } from "react-router";

export default function Layout() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-4 flex items-center gap-4">
          <Link to="/" className="text-xl font-bold tracking-tight">
            Walkthrough
          </Link>

          {id && (
            <>
              <span className="text-gray-300">/</span>
              <span className="text-sm text-gray-500">Project {id.slice(0, 8)}</span>
            </>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
