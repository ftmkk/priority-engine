import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, clockLabel, num, pct } from "../api.js";
import { Card, useApi } from "../components.jsx";
import {
  ABTestTemplateChart, AtKTable, GainsChart, QueueTierChart, TargetBalanceChart, UrgencyChart,
} from "../charts.jsx";
import { GlobalImportance } from "../leadexplain.jsx";
import { PipelineDiagram, RegimeDiagram, SplitDiagram } from "../diagrams.jsx";

/* Eight slides, one argument: who to call, why that order, and where it stops
   being true. The long version — every measurement, and the readings the data
   ruled out — lives in `notebooks/`. This deck is the part a sales lead needs:
   one claim per slide, one picture, one consequence. */

const Note = ({ kind = "decision", children }) => (
  <div className={`box ${kind}`}>
    <span className="box-tag">
      {kind === "limit" ? "Limit" : kind === "finding" ? "Finding" : "So"}
    </span>
    <p>{children}</p>
  </div>
);
const Split = ({ children }) => <div className="slide-split">{children}</div>;
const Lead = ({ children }) => <p className="slide-lead">{children}</p>;
const Fig = ({ title, children }) => (
  <div className="slide-fig">{title && <span className="eyebrow">{title}</span>}{children}</div>
);

/* --------------------------------------------------------------- 1 */
function Problem() {
  const { data: s } = useApi(api.summary, []);
  return (
    <>
      <h2>{s ? num(s.kpi.leads) : "50,000"} people left the checkout. You can call a few hundred.</h2>
      <Split>
        <div>
          <Lead>
            Every one of them got as far as a price and walked away. About{" "}
            <b>{s ? pct(s.kpi.conversion, 1) : "9.2%"}</b> come back and buy anyway. The
            floor’s capacity doesn’t move, so the only question worth answering is the
            order of the call list.
          </Lead>
          <Note kind="finding">
            “Nobody buys” is right nine times out of ten. Accuracy cannot be the target.
          </Note>
          <Note>
            This is ranking under a fixed capacity. The number that counts is how many
            buyers land in the first 500 calls — not how often the model is right.
          </Note>
        </div>
        <Fig title="Who buys"><TargetBalanceChart height={240} /></Fig>
      </Split>
    </>
  );
}

/* --------------------------------------------------------------- 2 */
function Record() {
  const { data: s } = useApi(api.summary, []);
  return (
    <>
      <h2>Each row is a photo, not a film.</h2>
      <Split>
        <div>
          <Lead>
            A row is written by a scheduled job: the quote as it stood at that moment,
            with the lead’s age frozen into it. We know it is frozen because 180 leads
            were written twice, minutes apart, and only the timestamp moved.
          </Lead>
          <Note>
            A lead’s real age is the age in the photo <b>plus</b> the time since the photo
            was taken. That one line is what lets the queue re-rank itself all day without
            the model running again.
          </Note>
          <Note kind="finding">
            Age matters, and it is steep: roughly 11% conversion in the first hour against
            5% in the sixth. The column stops at six hours because that is where the data
            was cut off — so that is where our claims stop too.
          </Note>
        </div>
        <Fig title="Conversion by how long ago they left">
          <UrgencyChart which="abandonment" base={s?.kpi.conversion} height={250} />
        </Fig>
      </Split>
    </>
  );
}

/* --------------------------------------------------------------- 3 */
function Drift() {
  return (
    <>
      <h2>The market moved while we were measuring it.</h2>
      <Lead>
        Conversion sat near 9.5% from April to July, then fell to 7.4% and stayed there. A
        random train/test split blends the two periods together: the model tests
        beautifully and then meets next week.
      </Lead>
      <SplitDiagram />
      <Note>
        Cut by time, twice: the middle window picks the algorithm, the newest is read once
        after that choice is locked. And since no amount of retraining recovers a level
        that genuinely moved, calibration is re-checked on every run.
      </Note>
    </>
  );
}

/* --------------------------------------------------------------- 4 */
function Result() {
  const { data: m } = useApi(api.model, []);
  const k = m?.metrics?.at_k?.find((r) => r.k === 500) || m?.metrics?.at_k?.[1];
  return (
    <>
      <h2>{k ? `${k.lift.toFixed(1)}×` : "About 3×"} more buyers, out of the same number of calls.</h2>
      <Split>
        <div>
          <Lead>
            Worked top-down, the first {k ? num(k.k) : 500} calls on the ranked list
            convert at <b>{k ? pct(k.precision, 1) : "≈21%"}</b> against a{" "}
            {m ? pct(m.base_rate_test, 1) : "7.4%"} base rate. Same team, same hours, same
            leads — different order.
          </Lead>
          <Note kind="finding">
            The bar was not zero: a four-line rule of thumb already ranks far better than
            chance. The model’s worth is the gap above <em>that</em>, earned by stacking
            weak signals rather than finding one magic column.
          </Note>
        </div>
        <Fig title="Buyers reached as you work down the queue">
          <GainsChart height={230} />
        </Fig>
      </Split>
      <AtKTable />
    </>
  );
}

/* --------------------------------------------------------------- 5 */
function Serving() {
  const { data: c } = useApi(api.clock, []);
  return (
    <>
      <h2>A score has a shelf life.</h2>
      <Lead>
        Nothing about a lead changes after capture except how old it is. For six hours we
        ask the model again with the clock moved on; after that it has nothing new to say,
        so its last defensible answer is carried forward and faded.
      </Lead>
      <RegimeDiagram />
      <Note>
        The queue ends at {c ? c.horizon_hours : 24} hours — carried that far, even the
        best lead left is under 1%, a tenth of the base rate. The fade is a <b>ranking
        device, not a probability</b>: it is measured across leads rather than by watching
        one lead cool, so treat it as the optimistic end of how fast interest dies.
      </Note>
    </>
  );
}

/* --------------------------------------------------------------- 6 */
function Why() {
  return (
    <>
      <h2>Every number in the queue opens up.</h2>
      <Split>
        <div>
          <Lead>
            Click any lead and the score comes apart: what pushed it up, what pulled it
            down, and how it would move if one fact about the lead were different. Nothing
            on the call list is a number a rep has to take on faith.
          </Lead>
          <Note>
            The order is expected value — probability × margin — so a slightly colder lead
            on a bigger policy can outrank a warmer one. That is deliberate, and it is
            visible on the lead’s own panel.
          </Note>
        </div>
        <Fig title="What the model leans on"><GlobalImportance height={250} /></Fig>
      </Split>
    </>
  );
}

/* --------------------------------------------------------------- 7 */
function Running() {
  const { data: c } = useApi(api.clock, []);
  return (
    <>
      <h2>How it runs, and what it will not tell you.</h2>
      <PipelineDiagram />
      <Split>
        <div>
          <Lead>
            The CSV is read once, at start-up. After that everything lives in Postgres: a
            job re-scores ageing leads every five minutes, the queue’s order is worked out
            the moment someone asks for it, and every score records the model behind it.
          </Lead>
          <Note kind="limit">
            It ranks <b>who is likely to buy</b>, not who buys <em>because</em> we called.
            Telling those apart needs a holdout of leads we deliberately do not call.
          </Note>
        </div>
        <div>
          <Fig title="Live queue"><QueueTierChart height={200} /></Fig>
          <Note kind="limit">
            The dataset is a fixed five-month export, so “now” is pinned to{" "}
            <b>{c ? clockLabel(c.at) : "its newest row"}</b> — the badge in the header says
            so on every page. One config line; on live data nothing else changes.
          </Note>
        </div>
      </Split>
    </>
  );
}

/* --------------------------------------------------------------- 8 */
function Rollout() {
  return (
    <>
      <h2>The gains chart is a backtest. Comparing models for real means an A/B test.</h2>
      <Lead>
        Everything on the previous slides is measured against a holdout the model never
        trained on — but every lead in that holdout was still, in the end, worked the old way.
        It says the ranking would have been right. It cannot say reps calling from that
        ranking actually sell more, because nobody has yet called from it. Answering that
        needs a live experiment, run like this:
      </Lead>
      <Split>
        <div>
          <Note kind="finding">
            <b>1. Split live traffic, not historical rows.</b> Each new lead is randomly
            assigned, at the lead level, to one arm: <b>control</b> (today's order), a{" "}
            <b>heuristic</b> baseline, and the <b>model</b> queue. Random assignment is what
            lets a gap in outcomes be pinned on the arm rather than on which reps or which
            leads happened to land where.
          </Note>
          <Note>
            <b>2. Pick one primary metric up front.</b> Conversion rate within the arm's call
            window — not lift, not precision@k, not anything computed after peeking at the
            data. Secondary metrics (revenue per lead, time-to-contact) get reported but don't
            decide the winner.
          </Note>
          <Note>
            <b>3. Size the sample before starting.</b> Given the base rate (≈7–9%) and the
            smallest lift worth acting on, a power calculation (e.g. two-proportion z-test,
            80% power, α = 0.05) sets the leads-per-arm target and the run length — not "run it
            till it looks good."
          </Note>
        </div>
        <div>
          <Note>
            <b>4. Read it once, at the pre-registered stopping point.</b> Compare realized
            conversion per arm with a two-proportion z-test (or chi-square), report the
            difference with a 95% CI, and require the interval to exclude zero before calling
            a winner. Checking daily and stopping the moment a gap looks good is how noise gets
            sold as lift.
          </Note>
          <Note kind="limit">
            <b>5. Re-run, don't reuse.</b> A win says the ranking beats the alternative for{" "}
            <em>this</em> offer, market regime, and rep pool, right now — not permanently. It
            answers the causal question <b>Serving</b> and <b>Result</b> can't, but it expires
            the same way a backtest does.
          </Note>
          <Fig title="Template — illustrative numbers, no experiment run yet">
            <ABTestTemplateChart height={210} />
          </Fig>
        </div>
      </Split>
    </>
  );
}

const SLIDES = [
  { id: "problem", tab: "The problem",   Body: Problem },
  { id: "record",  tab: "The data",      Body: Record },
  { id: "drift",   tab: "The trap",      Body: Drift },
  { id: "result",  tab: "The result",    Body: Result },
  { id: "serving", tab: "Staying live",  Body: Serving },
  { id: "why",     tab: "Why this lead", Body: Why },
  { id: "running", tab: "In production", Body: Running },
  { id: "rollout", tab: "Proving it live", Body: Rollout },
];

export default function About() {
  const [i, setI] = useState(0);
  const slide = useRef(null);
  const go = useCallback((n) => {
    setI(Math.max(0, Math.min(SLIDES.length - 1, n)));
    window.scrollTo({ top: 0 });
  }, []);

  // The slide box scrolls internally, so a new slide has to be rewound too —
  // otherwise you arrive halfway down it, wherever the last one was left.
  useEffect(() => { slide.current?.scrollTo({ top: 0 }); }, [i]);

  /* Size the slide to whatever the viewport has left, so the page itself never
     scrolls — only the slide does. Nothing about the surrounding chrome is
     assumed: the slide is collapsed to nothing, the card's bottom edge is read
     at that moment (which accounts for the header above, the tab bar however
     many rows it wrapped onto, and the Previous/Next row below), and the slide
     takes the remainder. `minHeight` has to be cleared for the probe or the CSS
     floor would keep the box open and the measurement would include it. */
  useEffect(() => {
    const fit = () => {
      const el = slide.current;
      if (!el) return;
      const card = el.closest(".card");
      const main = el.closest("main");
      el.style.minHeight = "0px";
      el.style.height = "0px";
      const below = card.getBoundingClientRect().bottom + window.scrollY
        + (parseFloat(getComputedStyle(main).paddingBottom) || 0);
      el.style.height = `${Math.max(200, window.innerHeight - below)}px`;
    };
    fit();
    // A plain resize listener misses the case that actually matters: the tab bar
    // rewrapping onto another row changes the chrome height without the window
    // changing size. Observing the page container catches both.
    const ro = new ResizeObserver(fit);
    ro.observe(document.documentElement);
    const main = slide.current?.closest("main");
    if (main) ro.observe(main);
    window.addEventListener("resize", fit);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.matches("input, select, textarea")) return;
      if (e.key === "ArrowRight") go(i + 1);
      if (e.key === "ArrowLeft") go(i - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [i, go]);

  const S = SLIDES[i];
  return (
    <>
      <div className="phead tight">
        <span className="eyebrow">The case</span>
        <h1>Why this works</h1>
        <p>
          Eight slides: how the call list is built, and where it stops being true. The
          measurements behind each one live in <code>notebooks/</code>.
        </p>
      </div>

      <div className="tabs" role="tablist" aria-label="Slides">
        {SLIDES.map((s, n) => (
          <button key={s.id} role="tab" aria-selected={n === i}
                  className={n === i ? "tab on" : "tab"} onClick={() => go(n)}>
            <span className="tab-n">{n + 1}</span>{s.tab}
          </button>
        ))}
      </div>

      <Card>
        <div className="slide" ref={slide}><S.Body /></div>
        <div className="deck-nav">
          <button className="btn" onClick={() => go(i - 1)} disabled={i === 0}>← Previous</button>
          <div className="dots" aria-hidden="true">
            {SLIDES.map((s, n) => <span key={s.id} className={n === i ? "dot-on" : "dot-off"} />)}
          </div>
          <span className="num deck-count">{i + 1} / {SLIDES.length}</span>
          <button className="btn primary" onClick={() => go(i + 1)}
                  disabled={i === SLIDES.length - 1}>Next →</button>
        </div>
      </Card>
    </>
  );
}
