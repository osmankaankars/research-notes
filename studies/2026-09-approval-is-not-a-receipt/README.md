# Approval Is Not a Receipt

**Osman Kaan Kars | 19 September 2026**

A controlled purchase-workflow study of changing requests, uncertain external effects and safe recovery. No model API, account, external host or paid service is needed to run the core experiment.

[Read the article](ARTICLE.md) · [Methods](METHODS.md) · [Related work](RELATED_WORK.md)

## What was measured

The same 120 fixed synthetic cases were run through three executor scopes. A separate 26-case subset was rerun through actual local HTTP supplier processes. The 78 corresponding logical outcomes match. Supplier databases and traces are included; the evaluator does not accept the controller's success label as evidence.

| Executor | Verified completion | Cases with an invalid effect | Safe unresolved | Budget blocked |
|---|---:|---:|---:|---:|
| Request-only, diagnostic | 30/120 | 70/120 | 0 | 0 |
| Operation-scoped, intermediate | 83/120 | 15/120 | 12 | 5 |
| Intent-scoped, conventional strong reference | 97/120 | 0/120 | 18 | 5 |

Zero observed invalid effects is conditional on these exact fixtures and supplier guarantees. Unresolved work is not a completed task. The strong reference is not a new algorithm. No human or AI-model performance was measured, and no production ERP system was tested.

## Run locally

Python 3.11 or newer. The measured environment used Python 3.13.5. Core runtime and tests use only the standard library. Commands are run from this directory.

```sh
python3 -m unittest discover -s tests -v
python3 -m receiptbench.runner --cases protocol/cases_eval.json --out results/my-direct-run
```

To repeat the transport confirmation, using subprocesses bound only to `127.0.0.1`:

```sh
python3 -m receiptbench.runner --cases protocol/http_confirmation_cases.json --out results/my-http-run --transport http
```

The output directory must not already exist. The runner verifies the frozen source/input hashes and will fail rather than silently run modified code as the original experiment. New experimental changes should use their own versioned cases, manifest and result directory. No external network is used by the runner. HTTP confirmation starts 156 supplier processes in sequence and can take several minutes depending on local process-startup time.

To check the supplied evidence independently:

```sh
python3 audit/verify_results.py
```

If this distribution includes compressed episode archives instead of expanded `episodes/` directories, first extract them as instructed in [results/EVIDENCE.md](results/EVIDENCE.md). Charts use audited CSVs; the included PNG/SVG images require no installation to view. Matplotlib is optional for regenerating them: `python3 -m pip install -r requirements-figures.txt`, then `python3 make_figures.py`. It is not required for the simulation or tests.

## Inspect the evidence

- [Primary summary](results/eval-direct/summary.csv), [individual cases](results/eval-direct/cases.csv), [family breakdown](results/eval-direct/by_family.csv).
- [HTTP confirmation manifest](results/eval-http/manifest.json).
- [Independent arithmetic audit](results/audit/verification.json), [hazard component reach](results/audit/hazard_coverage.csv), [paired executor differences](results/audit/paired_executor_differences.csv).
- [Two indistinguishable worlds](results/paired-unknown-worlds/summary.json), a supplemental diagnostic outside the main cohort.
- `protocol/` contains exact development/evaluation cases and the pre-evaluation source freeze.
- `execution/` retains the final validation log and the interrupted-attempt provenance. Only the completed, enumerated cases are scored.

Core case families cover normal actions, irrelevant changes, authority changes, budget competition, lost responses, delayed status, key expiry, client restart, request revision, cancellation uncertainty and two intentionally identical purchases.

## Research boundary

The finite cases are not industry incidence estimates. Both DURABLE and EXPIRING fixtures include explicit definitive status/closure and cancellation-fence guarantees. OPAQUE does not. The controller is deterministic, the fault schedules are synthetic, and the local services are controlled fixtures. CAV-Bench and Provenact are credited related work, not implementations whose published benchmark scores were reproduced or surpassed here.

Source code, traces, supplier ledgers and documentation are intended to make the result inspectable. Self-review and independent arithmetic checks are not external peer review.

## Article example

The 100-to-60 example is `eval-F10-00`. After extracting the episode archives, compare the `operation_scoped` and `intent_scoped` traces in `results/eval-direct/episodes/`. These are the measured records, not reconstructed illustrations.

[Repository rights and attribution](../../RIGHTS.md)
