import { useParams } from "react-router";

export default function ProgressPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">Analysis Progress</h2>
      <p className="text-gray-500">Analyzing project {id}...</p>
    </div>
  );
}
