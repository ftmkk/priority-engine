import React from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, clockLabel } from "./api.js";
import { ErrorBoundary, useApi } from "./components.jsx";
import DashboardShell from "./pages/DashboardShell.jsx";
import Queue from "./pages/Queue.jsx";
import About from "./pages/About.jsx";

// Four sections. Everything read-only lives under Dashboard as a tab.
const TABS = [
  ["/dashboard", "Dashboard"],
  ["/queue", "Call queue"],
  ["/about", "How it works"],
];

export default function App() {
  const { data: health } = useApi(api.health, []);

  return (
    <>
      <header className="top">
        <div className="brand">
          Lead <span>Priority</span> Engine
        </div>
        <nav>
          {TABS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to !== "/dashboard"}
                     className={({ isActive }) => (isActive ? "on" : "")}>
              {label}
            </NavLink>
          ))}
        </nav>
        {health && (
          <div className="topmeta">
            {health.clock?.pinned && (
              /* Say it rather than let the screen imply a live clock: on a fixed
                 export every age on the page is measured from this instant. */
              <span className="pill clockpin" title={
                health.clock.mode === "dataset"
                  ? "priority.current_time: dataset — the newest created_at in the data"
                  : "priority.current_time is set to a fixed instant"}>
                clock fixed · {clockLabel(health.clock.at)}
              </span>
            )}
            <span className="dot" />
            <span className="num">{health.active_model || "no model"}</span>
          </div>
        )}
      </header>
      <main>
        <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardShell />} />
          <Route path="/dashboard/:section" element={<DashboardShell />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/about" element={<About />} />
          {/* the old top-level URLs still resolve */}
          <Route path="/explain" element={<Navigate to="/queue" replace />} />
          <Route path="/model" element={<Navigate to="/dashboard/model" replace />} />
          <Route path="/segments" element={<Navigate to="/dashboard/segments" replace />} />
          <Route path="/monitoring" element={<Navigate to="/dashboard/monitoring" replace />} />
        </Routes>
        </ErrorBoundary>
      </main>
    </>
  );
}
