import { Link, useLocation } from "react-router-dom";
import Disclaimer from "./Disclaimer";

export default function Layout({ children }) {
  const location = useLocation();
  return (
    <div className="layout">
      <header className="app-header">
        <Link to="/" className="logo">
          ClauseGuard
        </Link>
        <nav className="nav">
          <Link to="/" className={location.pathname === "/" ? "active" : ""}>
            Charger
          </Link>
        </nav>
      </header>
      <main className="main-content">{children}</main>
      <Disclaimer />
    </div>
  );
}
