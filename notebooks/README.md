# Notebooks

The exploration layer. The deliverable is the running pipeline in `src/` and the
dashboard's **How it works** page; these notebooks are where each of those decisions was
measured.

`01_eda` is a few figures and then the findings read off them. A **column sheet** puts each
column on one row — where the leads are with conversion drawn through them, share missing,
separation from the target, and that separation expressed in conversion points — so
everything about a column lines up horizontally. A **matrix** then covers every pair. A
**shift sheet** repeats the first sheet's row order for a different question: how far each
column's distribution moves between the training period and the holdout, measured against
the floor that sampling noise alone produces at this sample size, and how much of the
change in conversion each column's mix explains. Features are grouped by
family throughout, and inside each family the strongest separator from the target comes
first. The rest of the series follows the pipeline.

Each notebook opens with a one-line-per-section table — the question it asks and the answer
it reaches — so the series can be skimmed from those and read properly only where it
matters.

| Notebook | Question |
|---|---|
| `01_eda.ipynb` | A sheet of every column (shape, holes, signal, worth), the pairwise matrix, and how far each column's distribution moves month by month — and the findings they yield |
| `02_record_generation.ipynb` | What process wrote a row, and what does that decide about the two timestamps at inference? |
| `03_model_selection.ipynb` | Why is the split temporal and three-way — and, on top of that, which model, and what did it have to beat? |
| `04_serving_and_decay.ipynb` | How does a score stay current without re-running the model forever? |
| `05_interpretation.ipynb` | Why this lead — and what can the ranking still not tell you? |

`pe_style.py` holds the shared palette, figure defaults, the column taxonomy (`PROFILE`,
mirroring `api.PROFILE_COLUMNS`), the EDA figures (`column_sheet()`, `dataset_map()`,
`shift_over_time()`, `lift_stability()`) and a few drawing primitives, so the series reads
as one document rather than five. The figures return the numbers behind them as
DataFrames, which is what the findings cells read — so the prose and the pictures cannot
drift apart.

## Running them

Every notebook reads **Postgres**, not the CSV — `pe.v_leads_curated`, the same
deduplicated view the pipeline and dashboard read — and imports the pipeline's own
`features` / `metrics` / `interpret` modules, so the numbers come from the code that
actually runs.

```bash
docker compose up -d postgres     # then load-data once, if the table is empty
pip install -r requirements.txt
jupyter lab notebooks/
```

`pe_style` defaults to `localhost:5433`, which is where compose publishes Postgres on the
host; set `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_PASSWORD` to override.

Run them in order the first time: `03` fits the model and writes
`artifacts/notebook_model.joblib`, which `04` and `05` load instead of refitting. Figures
are also written to `charts/` as PNGs.
