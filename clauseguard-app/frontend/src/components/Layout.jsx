import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { LayoutDashboard, FileText, FileCheck, ScrollText, User, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Disclaimer from "./Disclaimer";

const NAV_ITEMS = [
  { path: "/", label: "Tableau de bord", icon: LayoutDashboard },
  { path: "/contracts", label: "Contrats", icon: FileText },
  { path: "/reports", label: "Rapports", icon: FileCheck },
  { path: "/audit", label: "Journal d'audit", icon: ScrollText },
];

export default function Layout({ children }) {
  const location = useLocation();
  const params = useParams();
  const userName = localStorage.getItem("X-User-Id") || "Utilisateur";
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("sidebar-collapsed") === "true"
  );

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("sidebar-collapsed", String(next));
      return next;
    });
  };

  const isActive = (path) => {
    if (path === "/") return location.pathname === "/";
    if (path === "/contracts") {
      return location.pathname.startsWith("/contracts") || location.pathname.startsWith("/upload");
    }
    return location.pathname.startsWith(path);
  };

  const contractId = params.contractId;
  const pageTitle = (() => {
    if (location.pathname.startsWith("/review")) return "Revue des clauses";
    if (location.pathname.startsWith("/report")) return "Rapport d'analyse";
    if (location.pathname === "/upload") return "Téléverser un contrat";
    if (location.pathname.startsWith("/contracts")) return "Contrats";
    if (location.pathname.startsWith("/reports")) return "Rapports";
    if (location.pathname.startsWith("/audit")) return "Journal d'audit";
    return "Tableau de bord";
  })();

  return (
    <div className={`app-shell ${collapsed ? "collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <Link to="/" className="wordmark" style={{ display: "flex", alignItems: "center" }}>
            <img src="/clauseguard_logo.png" alt="ClauseGuard" height="32" />
            <span className="wordmark-full" style={{ color: "var(--color-primary)", fontWeight: 600, fontSize: "1.1rem", marginLeft: "8px" }}>ClauseGuard</span>
          </Link>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Déplier le menu" : "Replier le menu"}
            title={collapsed ? "Déplier le menu" : "Replier le menu"}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </button>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`nav-item ${isActive(item.path) ? "active" : ""}`}
                title={collapsed ? item.label : undefined}
              >
                <Icon />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          ClauseGuard — Assistant de pré-lecture contractuelle
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div>
            <span className="topbar-title">{pageTitle}</span>
            {contractId && (
              <span className="topbar-context">
                {" "}
                · Dossier <span className="mono">{contractId.slice(0, 8)}</span>
              </span>
            )}
          </div>
          <div className="topbar-user">
            <User />
            <span>{userName}</span>
          </div>
        </header>

        <main className="page">{children}</main>
        <Disclaimer />
      </div>
    </div>
  );
}
