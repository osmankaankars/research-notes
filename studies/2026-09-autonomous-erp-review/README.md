# Autonomous ERP: review-policy simulation

**Osman Kaan Kars | September 2026**

[Read the article](ARTICLE.md) · [Methods](METHODS.md) · [Results](results/article_results.csv)

## Research question

When the same replenishment controller is modified by different review objectives,
how do the intervention cost and response delay affect service and net surplus?

The experiment compares an adaptive inventory policy with four scripted alternatives:
cash buffer, service buffer, trend response and plan anchored. Demand is synthetic.
There are no human participants and no new LLM inference calls. This is not an ERP
product benchmark or a test of Jev or Mercury.

## Design

| Item | Specification |
|---|---|
| Independent simulation clusters | 120 random seeds |
| Demand paths | 480, spanning four demand regimes |
| Scenario settings | 960, including two supply lead times |
| Evaluation horizon | 60 operating periods per scenario |
| Controllers | One baseline and four scripted review policies |
| Response delays | 0, 2 and 4 periods |
| Review fees | 0, 25 and 100 model units per request |
| Maximum review requests | Four per trajectory |
| Total trajectories | 35,520 |
| Retained primary period records | 748,800 |

Multiple regimes and supply lead times share the same seed-level random shocks.
The trajectory count is not a count of independent companies or human decisions.

## Main comparison

Immediate response, review fee 25, and equal weighting of demand regimes and lead times:

| Review policy | Mean net-surplus change | Mean fill-rate change |
|---|---:|---:|
| Cash buffer | -1.70% | -1.58 percentage points |
| Service buffer | -0.13% | +0.25 percentage points |
| Trend response | -0.69% | -0.47 percentage points |
| Plan anchored | -1.44% | -0.99 percentage points |

These are relative changes against the matched simulated baseline, not corporate ROI.
Full precision and seed-cluster uncertainty intervals are in
[article_results.csv](results/article_results.csv) and
[primary_summary.csv](results/primary_summary.csv).

## Verify the included results

The recorded environment uses Python 3.13.5. Run the following from this study directory:

```sh
python -m venv .venv
```

Activate the environment with `source .venv/bin/activate` on macOS/Linux or
`.venv\Scripts\Activate.ps1` in Windows PowerShell, then run:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The included test suite checks decision timing, future-data isolation, review budgets,
stock and cash accounting, the input hash and the frozen protocol. Output checks inspect
all 748,800 retained primary period records. The latest captured output is in
[execution/tests.txt](execution/tests.txt).

## Regenerate

```sh
python run_experiment.py
python -m unittest discover -s tests -v
python make_figures.py
```

Regeneration overwrites files in this study's `data/`, `results/`, `execution/` and
`figures/` directories. The small `article_results.csv` table is the zero-delay,
combined-regime and combined-lead subset of `primary_summary.csv`; it is supplied
as a convenience export. The experiment itself runs offline and requires no API key.
Installing dependencies may access a package index.

## Evidence and implementation

| Path | Purpose |
|---|---|
| [simulation.py](simulation.py) | State transitions, review rules and demand generator |
| [run_experiment.py](run_experiment.py) | Paired runs, aggregates and bootstrap intervals |
| [make_figures.py](make_figures.py) | PNG and SVG figure generation |
| [tests/](tests/) | Engine checks and independent output checks |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | Original locally frozen specification, preserved without edits |
| [data/demand_paths.jsonl](data/demand_paths.jsonl) | Synthetic training and evaluation demand |
| [results/all_trajectories.csv](results/all_trajectories.csv) | Every run's outcome and matched baseline |
| [results/primary_trajectories.jsonl.gz](results/primary_trajectories.jsonl.gz) | Complete primary traces in compressed JSONL |
| [results/sensitivity_summary.csv](results/sensitivity_summary.csv) | Fee and delay sensitivity comparisons |
| [execution/run_metadata.json](execution/run_metadata.json) | Parameters, counts and recorded execution environment |
| [execution/files.sha256](execution/files.sha256) | Integrity manifest for research code, inputs and outputs |
| [CITATION.cff](CITATION.cff) | Citation metadata |

## Limits

The baseline is an illustrative adaptive heuristic, not an optimised planning policy.
The four reviewers are decision rules, not validated models of human behaviour. Fees,
delays and terminal inventory value are assumptions. The simulation has a single
inventory system and exogenous, fully observed demand. It does not measure human
judgment, model speed, production savings or vendor performance.

[Full assumptions and equations](METHODS.md) · [Repository rights](../../RIGHTS.md)
