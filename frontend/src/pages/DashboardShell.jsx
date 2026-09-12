import React from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import Overview from "./Dashboard.jsx";
import Model from "./Model.jsx";
import Segments from "./Segments.jsx";
import Monitoring from "./Monitoring.jsx";

/* Overview, model, segments and monitoring are all read-only views of the same
   data, so they live as tabs under one heading rather than four nav entries.
   Each keeps its own URL, so a tab is still linkable. */
const TABS = [
  { id: "overview", label: "Overview", Body: Overview,
    h1: "Lead conversion and the live call queue",
    p: "Where the leads are, who is converting, and what the floor should be calling right now. Refreshed every 5 minutes." },
  { id: "model", label: "Model", Body: Model,
    h1: "The active model, and what it was measured against",
    p: "What it beat, what it scores on data it never saw, and every training run on record." },
  { id: "segments", label: "Segments", Body: Segments,
    h1: "Who are these leads, and which ones get called?",
    p: "The queue says who to call first; this says what kind of lead they are — and which groups the queue keeps picking." },
  { id: "monitoring", label: "Monitoring", Body: Monitoring,
    h1: "Is the model still telling the truth?",
    p: "The ways a working model quietly stops being right: probabilities drifting, scores shifting, the decay biting harder." },
];

export default function DashboardShell() {
  const { section } = useParams();
  const navigate = useNavigate();
  const tab = TABS.find((t) => t.id === (section || "overview"));
  if (!tab) return <Navigate to="/dashboard" replace />;

  return (
    <>
      <div className="phead">
        <span className="eyebrow">Dashboard</span>
        <h1>{tab.h1}</h1>
        <p>{tab.p}</p>
      </div>

      <div className="tabs" role="tablist" aria-label="Dashboard sections">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={t.id === tab.id}
                  className={t.id === tab.id ? "tab on" : "tab"}
                  onClick={() => navigate(t.id === "overview" ? "/dashboard" : `/dashboard/${t.id}`)}>
            {t.label}
          </button>
        ))}
      </div>

      <tab.Body />
    </>
  );
}
