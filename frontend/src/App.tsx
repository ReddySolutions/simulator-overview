import { BrowserRouter, Routes, Route } from "react-router";
import Layout from "./components/Layout";
import ProjectListPage from "./pages/ProjectListPage";
import UploadPage from "./pages/UploadPage";
import ProgressPage from "./pages/ProgressPage";
import ClarificationPage from "./pages/ClarificationPage";
import WalkthroughPage from "./pages/WalkthroughPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<ProjectListPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="progress/:id" element={<ProgressPage />} />
          <Route path="clarify/:id" element={<ClarificationPage />} />
          <Route path="walkthrough/:id" element={<WalkthroughPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
