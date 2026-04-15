import { useParams } from "react-router";

export default function ClarificationPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">Clarification Questions</h2>
      <p className="text-gray-500">Answer questions for project {id} to resolve gaps.</p>
    </div>
  );
}
