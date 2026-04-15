import { useParams } from "react-router";

export default function WalkthroughPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">Walkthrough</h2>
      <p className="text-gray-500">Interactive simulation for project {id}.</p>
    </div>
  );
}
