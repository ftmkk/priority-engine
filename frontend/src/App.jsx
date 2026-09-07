import React from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api.js";
import { useApi } from "./components.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Queue from "./pages/Queue.jsx";
import Model from "./pages/Model.jsx";
import Monitoring from "./pages/Monitoring.jsx";
import About from "./pages/About.jsx";

const TABS = [
  ["/dashboard", "Dashboard"],
  ["/queue", "Call queue"],
  ["/model", "Model"],
  ["/monitoring", "Monitoring"],
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
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "on" : "")}>
              {label}
            </NavLink>
          ))}
        </nav>
        {health && (
          <div className="topmeta">
            <span className="dot" />
            <span className="num">{health.active_model || "no model"}</span>
          </div>
        )}
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/model" element={<Model />} />
          <Route path="/monitoring" element={<Monitoring />} />
          <Route path="/about" element={<About />} />
        </Routes>
      </main>
    </>
  );
}
