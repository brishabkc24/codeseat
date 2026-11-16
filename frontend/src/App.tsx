import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { SessionProvider } from "./lib/session";
import { Admin } from "./pages/Admin";
import { Classes } from "./pages/Classes";
import { Home } from "./pages/Home";
import { SignUp } from "./pages/SignUp";
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
      <SessionProvider>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/join/:code" element={<Home />} />
          <Route path="/signup" element={<SignUp />} />
          <Route path="/class/:code" element={<StudentRoom />} />
          <Route path="/teach" element={<Classes />} />
          <Route path="/teach/:code" element={<TeacherRoom />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </SessionProvider>
    </BrowserRouter>
  );
}
