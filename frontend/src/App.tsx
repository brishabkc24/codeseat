import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { Home } from "./pages/Home";
import { StudentRoom } from "./pages/StudentRoom";
import { TeacherRoom } from "./pages/TeacherRoom";

function NotFound() {
  return (
    <>
      <TopBar />
      <main className="closed">
        <h1>There is no page here</h1>
        <p>The address may be mistyped. Classes are joined from the start page.</p>
        <Link className="btn" to="/">
          Back to the start
        </Link>
      </main>
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/join/:code" element={<Home />} />
        <Route path="/class/:code" element={<StudentRoom />} />
        <Route path="/teach/:code" element={<TeacherRoom />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
