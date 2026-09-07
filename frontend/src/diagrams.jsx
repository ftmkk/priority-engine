import React from "react";

/* Hand-authored inline SVG. Structure uses currentColor so it follows the theme;
   --blue marks the path under discussion and --orange the extrapolated regime. */

const Fig = ({ label, caption, viewBox, children }) => (
  <figure className="fig">
    <svg viewBox={viewBox} role="img" aria-label={label} className="figsvg">
      {children}
    </svg>
    <figcaption>{caption}</figcaption>
  </figure>
);

const Arrow = ({ id }) => (
  <defs>
    <marker id={id} viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
    </marker>
  </defs>
);

/* ------------------------------------------------------------------ */
/* 1. Where the data lives and who reads it                            */
/* ------------------------------------------------------------------ */
export function PipelineDiagram() {
  const box = { fill: "var(--surface-2)", stroke: "currentColor", strokeWidth: 1, rx: 6 };
  const lbl = { fontSize: 11.5, fill: "currentColor", fontFamily: "IBM Plex Sans, sans-serif" };
  const mono = { fontSize: 10, fill: "var(--ink-3)", fontFamily: "IBM Plex Mono, monospace" };
  const edge = { stroke: "currentColor", strokeWidth: 1.4, fill: "none",
                 markerEnd: "url(#pipe-arrow)", opacity: 0.55 };
  const eLbl = { ...mono, fontSize: 9, fill: "var(--ink-3)" };

  // jobs sit above the spine, each acting on Postgres; the spine is the data path
  const jobs = [
    ["training job", "monthly + on boot", 244, 388, "reads mature labels · writes a version"],
    ["scoring job", "every 5 min", 412, 556, "reads due leads · appends scores"],
  ];

  return (
    <Fig
      viewBox="0 0 890 350"
      label="The CSV is loaded into Postgres once; three jobs act on Postgres, and the call queue is derived when it is read."
      caption="The CSV is touched exactly once, at boot. After that every job reads and writes Postgres — nothing reaches back to the file. The ordering of the queue is derived on read rather than stored, so it moves with the clock without the model running again."
    >
      <Arrow id="pipe-arrow" />

      {/* jobs */}
      {jobs.map(([title, when, x0, x1, what]) => {
        const mid = (x0 + x1) / 2;
        const accent = title === "scoring job";
        return (
          <g key={title}>
            <rect x={x0} y="28" width={x1 - x0} height="52" {...box}
                  stroke={accent ? "var(--blue)" : "currentColor"}
                  strokeWidth={accent ? 1.75 : 1} />
            <text x={mid} y="48" textAnchor="middle" {...lbl} fontSize="11">{title}</text>
            <text x={mid} y="65" textAnchor="middle" {...mono} fontSize="9.5">{when}</text>
            <path d={`M ${mid} 84 L ${mid} 148`} {...edge} />
            <text x={mid} y="106" textAnchor="middle" {...eLbl}>{what.split(" · ")[0]}</text>
            <text x={mid} y="118" textAnchor="middle" {...eLbl}>{what.split(" · ")[1]}</text>
          </g>
        );
      })}

      {/* source — read once, then never again */}
      <rect x="18" y="196" width="118" height="46" {...box} strokeDasharray="4 3" />
      <text x="77" y="216" textAnchor="middle" {...lbl}>leads.csv</text>
      <text x="77" y="231" textAnchor="middle" {...mono} fontSize="9.5">50,180 rows</text>
      <path d="M 140 219 L 222 219" {...edge} />
      <text x="181" y="211" textAnchor="middle" {...eLbl}>loaded once, at boot</text>

      {/* postgres */}
      <rect x="226" y="152" width="348" height="176" {...box} fill="var(--surface)" />
      <text x="400" y="172" textAnchor="middle" {...lbl} fontWeight="600">Postgres</text>
      <line x1="226" y1="181" x2="574" y2="181" stroke="currentColor"
            strokeWidth="1" opacity="0.22" />
      {[
        ["leads", "raw, lossless", 240, 194],
        ["v_leads_curated", "deduped per lead", 240, 240],
        ["job_runs", "every run recorded", 240, 286],
        ["model_versions", "registry, one active", 404, 194],
        ["predictions", "raw scores, append-only", 404, 240],
        ["monitoring_snapshots", "score drift", 404, 286],
      ].map(([name, note, x, y]) => (
        <g key={name}>
          <rect x={x} y={y - 12} width="156" height="34" rx="4"
                fill="var(--surface-2)" stroke="currentColor" strokeWidth="0.75" />
          <text x={x + 9} y={y + 1} {...mono} fill="currentColor" fontSize="9.5">{name}</text>
          <text x={x + 9} y={y + 14} {...mono} fontSize="8.5">{note}</text>
        </g>
      ))}

      {/* derived queue */}
      <path d="M 578 218 L 618 218" {...edge} />
      <rect x="622" y="164" width="252" height="102" rx="6"
            fill="var(--pale)" stroke="var(--blue)" strokeWidth="1.75" />
      <text x="748" y="188" textAnchor="middle" {...lbl} fontWeight="600">
        v_current_priority
      </text>
      <text x="748" y="208" textAnchor="middle" {...mono} fontSize="9.5">
        decay past the boundary
      </text>
      <text x="748" y="223" textAnchor="middle" {...mono} fontSize="9.5">
        × margin → rank, tier
      </text>
      <text x="748" y="246" textAnchor="middle" {...mono} fontSize="10"
            fill="var(--blue)">derived on every read</text>

      {/* consumers */}
      <path d="M 748 270 L 748 288" {...edge} />
      <rect x="622" y="292" width="252" height="44" {...box} />
      <text x="748" y="311" textAnchor="middle" {...lbl} fontSize="11">
        FastAPI → React panel
      </text>
      <text x="748" y="326" textAnchor="middle" {...mono} fontSize="9.5">
        GET /api/queue
      </text>

      {/* the file is never read again */}
      <path d="M 77 246 L 77 306 L 214 306" fill="none" stroke="var(--ink-3)"
            strokeWidth="1" strokeDasharray="3 4" opacity="0.45" />
      <text x="82" y="322" {...mono} fontSize="8.5">no job reads it again</text>
    </Fig>
  );
}

/* ------------------------------------------------------------------ */
/* 2. The two scoring regimes — the centrepiece                        */
/* ------------------------------------------------------------------ */
export function RegimeDiagram() {
  const L = 60, R = 748, T = 44, B = 236;         // plot frame
  const XB = 336;                                  // 360-minute boundary
  const XC = 604;                                  // decay cap
  const lbl = { fontSize: 11.5, fill: "currentColor", fontFamily: "IBM Plex Sans, sans-serif" };
  const mono = { fontSize: 10, fill: "var(--ink-3)", fontFamily: "IBM Plex Mono, monospace" };

  return (
    <Fig
      viewBox="0 0 780 300"
      label="Inside the model's trained range the score is re-inferred; past the boundary its last answer decays in SQL, and only the time beyond the boundary is decayed."
      caption="The split sits exactly at the edge of the model's evidence. Inside, we ask the model again with the lead's clock advanced. Outside, its last answer becomes an anchor that decays in SQL — counting only the time past the boundary, because the model already priced everything before it."
    >
      <Arrow id="regime-arrow" />

      {/* regions */}
      <rect x={L} y={T} width={XB - L} height={B - T} fill="var(--pale)" opacity="0.55" />
      <rect x={XB} y={T} width={R - XB} height={B - T} fill="var(--surface-2)" opacity="0.5" />

      <text x={(L + XB) / 2} y={T - 20} textAnchor="middle" {...lbl} fontWeight="600"
            fill="var(--blue)">model was trained here</text>
      <text x={(L + XB) / 2} y={T - 6} textAnchor="middle" {...mono}>
        re-infer · exact
      </text>
      <text x={(XB + R) / 2} y={T - 20} textAnchor="middle" {...lbl} fontWeight="600">
        no evidence out here
      </text>
      <text x={(XB + R) / 2} y={T - 6} textAnchor="middle" {...mono}>
        decay the anchor in SQL
      </text>

      {/* boundary */}
      <line x1={XB} y1={T} x2={XB} y2={B + 8} stroke="var(--blue)" strokeWidth="2" />
      <line x1={XC} y1={T} x2={XC} y2={B + 8} stroke="var(--orange)"
            strokeWidth="1.5" strokeDasharray="5 4" />
      <line x1={R} y1={T} x2={R} y2={B + 8} stroke="currentColor"
            strokeWidth="1.5" strokeDasharray="5 4" opacity="0.6" />

      {/* value curve: same downward trend, two mechanisms */}
      <path d={`M ${L} 72 C 150 88, 250 118, ${XB} 146`}
            fill="none" stroke="var(--blue)" strokeWidth="2.5" strokeLinecap="round" />
      <path d={`M ${XB} 146 C 420 186, 520 212, ${XC} 220`}
            fill="none" stroke="var(--orange)" strokeWidth="2.5" strokeLinecap="round" />
      <path d={`M ${XC} 220 L ${R} 220`}
            fill="none" stroke="var(--orange)" strokeWidth="2.5"
            strokeDasharray="4 4" strokeLinecap="round" />

      {/* re-inference ticks inside the window */}
      {[0, 1, 2, 3, 4, 5, 6].map((i) => {
        const x = L + (i * (XB - L)) / 6;
        const y = 72 + i * (146 - 72) / 6;
        return <circle key={i} cx={x} cy={y} r="3.4" fill="var(--blue)"
                       stroke="var(--surface)" strokeWidth="1.5" />;
      })}
      <text x={L + 10} y="196" {...mono} fill="var(--blue)" fontSize="10.5">
        one inference per run, every 5 min
      </text>
      <text x={L + 10} y="210" {...mono} fontSize="9.5">
        the lead's clock is advanced, then the model is asked again
      </text>

      {/* anchor */}
      <circle cx={XB} cy="146" r="6" fill="var(--surface)"
              stroke="var(--blue)" strokeWidth="2.5" />
      <text x={XB + 12} y="132" {...lbl} fontWeight="600" fill="var(--blue)">anchor</text>
      <text x={XB + 12} y="147" {...mono}>last answer the model can defend</text>

      {/* decay annotation */}
      <text x={XB + 34} y="196" {...mono} fill="var(--orange)">
        odds × 0.778 ^ (hours past boundary)
      </text>

      {/* axis */}
      <line x1={L} y1={B} x2={R} y2={B} stroke="currentColor" strokeWidth="1.25" />
      {[
        [L, "0", "captured"],
        [XB, "360 min", "boundary"],
        [XC, "30 h", "decay capped"],
        [R, "48 h", "leaves queue"],
      ].map(([x, t, sub]) => (
        <g key={t}>
          <line x1={x} y1={B} x2={x} y2={B + 6} stroke="currentColor" strokeWidth="1.25" />
          <text x={x} y={B + 20} textAnchor="middle" {...mono} fill="currentColor"
                fontSize="10.5">{t}</text>
          <text x={x} y={B + 33} textAnchor="middle" {...mono} fontSize="9">{sub}</text>
        </g>
      ))}
      <text x={(L + R) / 2} y={B + 54} textAnchor="middle" {...mono} fontSize="10">
        total abandonment age  (age at capture + time elapsed since)
      </text>

      {/* y label */}
      <text x="40" y="150" {...mono} fontSize="10"
            transform="rotate(-90 40 150)" textAnchor="middle">P(purchase)</text>
    </Fig>
  );
}

/* ------------------------------------------------------------------ */
/* 3. What reaches the model, and what bypasses it                     */
/* ------------------------------------------------------------------ */
export function FeatureRoutingDiagram() {
  const lbl = { fontSize: 11.5, fill: "currentColor", fontFamily: "IBM Plex Sans, sans-serif" };
  const mono = { fontSize: 9.5, fill: "var(--ink-3)", fontFamily: "IBM Plex Mono, monospace" };
  const edge = { stroke: "currentColor", strokeWidth: 1.4, fill: "none",
                 markerEnd: "url(#feat-arrow)", opacity: 0.55 };

  const groups = [
    ["Behaviour", ["visited_offer_page", "offer_views_last_7d", "sessions_last_7d",
                   "has_previous_purchase", "incoming_call_last_24h"], 34, "3.5×"],
    ["Urgency", ["minutes_since_abandonment", "days_to_policy_expiry",
                 "is_expired", "expiry × abandonment"], 148, "2.1×"],
    ["Offer & context", ["price_pct_in_product", "discount_percent",
                         "channel · payment_type", "insurance_company",
                         "device · partner"], 244, "1.2×"],
  ];

  return (
    <Fig
      viewBox="0 0 780 450"
      label="Three feature groups feed the model, three columns are excluded, and expected margin bypasses the model to join at the ranking step."
      caption="Expected margin never reaches the model — it is a fixed band of price, so as an input it adds only collinearity. It enters one step later, as the business weight that turns a probability into an ordering."
    >
      <Arrow id="feat-arrow" />

      {groups.map(([title, cols, y, lift]) => (
        <g key={title}>
          <rect x="14" y={y} width="214" height={cols.length * 15 + 30} rx="6"
                fill="var(--surface-2)" stroke="currentColor" strokeWidth="1" />
          <text x="26" y={y + 19} {...lbl} fontWeight="600">{title}</text>
          <text x="216" y={y + 19} textAnchor="end" {...mono} fill="var(--blue)"
                fontSize="10.5">{lift}</text>
          {cols.map((c, i) => (
            <text key={c} x="26" y={y + 36 + i * 15} {...mono}>{c}</text>
          ))}
          <path d={`M 232 ${y + (cols.length * 15 + 30) / 2} L 292 ${y + (cols.length * 15 + 30) / 2}`}
                {...edge} />
        </g>
      ))}
      <text x="120" y="26" textAnchor="middle" {...mono} fontSize="9">
        lift = best bin ÷ worst bin
      </text>

      {/* model */}
      <rect x="296" y="118" width="152" height="130" rx="6"
            fill="var(--surface)" stroke="var(--blue)" strokeWidth="1.75" />
      <text x="372" y="150" textAnchor="middle" {...lbl} fontWeight="600">model</text>
      <text x="372" y="169" textAnchor="middle" {...mono}>logreg vs gbdt</text>
      <text x="372" y="184" textAnchor="middle" {...mono}>temporal holdout</text>
      <text x="372" y="199" textAnchor="middle" {...mono}>class-weighted</text>
      <text x="372" y="214" textAnchor="middle" {...mono}>isotonic calibration</text>
      <text x="372" y="236" textAnchor="middle" {...mono} fontSize="10"
            fill="var(--blue)">P(purchase)</text>

      <path d="M 452 183 L 512 183" {...edge} />

      {/* ranking */}
      <rect x="516" y="130" width="176" height="106" rx="6"
            fill="var(--pale)" stroke="var(--blue)" strokeWidth="1.5" />
      <text x="604" y="156" textAnchor="middle" {...lbl} fontWeight="600">ranking</text>
      <text x="604" y="178" textAnchor="middle" {...mono} fontSize="10">
        decayed P × margin
      </text>
      <text x="604" y="196" textAnchor="middle" {...mono} fontSize="10">
        → rank, tier
      </text>
      <text x="604" y="220" textAnchor="middle" {...mono} fontSize="9.5"
            fill="var(--blue)">the call list</text>

      {/* margin bypasses the model */}
      <rect x="14" y="378" width="214" height="48" rx="6"
            fill="var(--surface-2)" stroke="var(--orange)" strokeWidth="1.5"
            strokeDasharray="5 3" />
      <text x="26" y="398" {...lbl} fontWeight="600">expected_margin</text>
      <text x="26" y="415" {...mono}>a fixed % band of price · corr 0.99</text>
      <path d="M 232 402 C 340 402, 420 300, 508 208"
            fill="none" stroke="var(--orange)" strokeWidth="1.75"
            markerEnd="url(#feat-arrow)" />
      <text x="352" y="380" textAnchor="middle" {...mono} fill="var(--orange)"
            fontSize="10">skips the model — enters as the weight</text>

      {/* excluded */}
      <rect x="516" y="282" width="176" height="118" rx="6"
            fill="none" stroke="currentColor" strokeWidth="1"
            strokeDasharray="4 3" opacity="0.6" />
      <text x="604" y="302" textAnchor="middle" {...lbl} fontSize="10.5"
            opacity="0.8">excluded, on purpose</text>
      {[
        ["price_comparisons_7d", "corr 0.002 — no signal"],
        ["city", "11 levels, no pattern"],
        ["hour, day_of_week", "flat within noise"],
      ].map(([c, why], i) => (
        <g key={c}>
          <text x="530" y={324 + i * 26} {...mono} fontSize="9"
                fill="currentColor">{c}</text>
          <text x="530" y={335 + i * 26} {...mono} fontSize="8.5">{why}</text>
        </g>
      ))}
    </Fig>
  );
}

/* ------------------------------------------------------------------ */
/* 4. Why the split is by time                                         */
/* ------------------------------------------------------------------ */
export function SplitDiagram() {
  const L = 56, R = 740, TOP = 40, BASE = 132;
  const XS = 552;                                   // train / holdout cut
  const lbl = { fontSize: 11.5, fill: "currentColor", fontFamily: "IBM Plex Sans, sans-serif" };
  const mono = { fontSize: 10, fill: "var(--ink-3)", fontFamily: "IBM Plex Mono, monospace" };
  const y = (rate) => BASE - (rate - 6.5) * 26;     // 6.5%..10% band

  return (
    <Fig
      viewBox="0 0 780 232"
      label="Conversion holds near 9.5 percent for four months then falls to 7.4 percent, so the holdout is the most recent slice rather than a random sample."
      caption="A random split would let the model learn from the drop and be tested on the period before it. Holding out the newest slice reproduces what production actually faces: fit the past, predict the future."
    >
      <Arrow id="split-arrow" />

      <rect x={L} y={TOP} width={XS - L} height={BASE - TOP + 26}
            fill="var(--surface-2)" opacity="0.6" rx="4" />
      <rect x={XS} y={TOP} width={R - XS} height={BASE - TOP + 26}
            fill="var(--pale)" opacity="0.8" rx="4" />

      <text x={(L + XS) / 2} y={TOP - 14} textAnchor="middle" {...lbl} fontWeight="600">
        train — 40,620 rows
      </text>
      <text x={(XS + R) / 2} y={TOP - 14} textAnchor="middle" {...lbl} fontWeight="600"
            fill="var(--blue)">holdout — 9,380</text>

      {/* conversion line */}
      <path d={`M ${L + 10} ${y(9.8)} L 180 ${y(9.5)} L 300 ${y(9.6)} L 420 ${y(9.4)}
                L ${XS} ${y(9.3)} L 620 ${y(7.6)} L ${R - 10} ${y(7.4)}`}
            fill="none" stroke="var(--blue)" strokeWidth="2.5" strokeLinejoin="round" />
      <circle cx={XS} cy={y(9.3)} r="4" fill="var(--blue)" />
      <circle cx={R - 10} cy={y(7.4)} r="4" fill="var(--blue)" />

      <text x={L + 16} y={y(9.8) - 12} {...mono} fill="currentColor">9.5% base rate</text>
      <text x={R - 16} y={y(7.4) + 20} textAnchor="end" {...mono} fill="currentColor">
        7.4%
      </text>

      {/* the cut */}
      <line x1={XS} y1={TOP - 4} x2={XS} y2={BASE + 34} stroke="var(--blue)"
            strokeWidth="2" />
      <text x={XS + 8} y={BASE + 30} {...mono} fontSize="9.5" fill="var(--blue)">
        cut by time, not at random
      </text>

      {/* axis */}
      <line x1={L} y1={BASE + 26} x2={R} y2={BASE + 26} stroke="currentColor"
            strokeWidth="1.25" />
      {[[L, "Apr"], [190, "May"], [320, "Jun"], [450, "Jul"], [610, "Aug"]].map(([x, m]) => (
        <g key={m}>
          <line x1={x} y1={BASE + 26} x2={x} y2={BASE + 32} stroke="currentColor"
                strokeWidth="1.25" />
          <text x={x} y={BASE + 46} textAnchor="middle" {...mono}>{m}</text>
        </g>
      ))}
      <text x={R} y={BASE + 66} textAnchor="end" {...mono} fontSize="9">
        label maturity: the newest 7 days are excluded — their outcome isn't known yet
      </text>
    </Fig>
  );
}
