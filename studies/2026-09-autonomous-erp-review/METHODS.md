# Methods: four scripted review profiles

**Completed computational experiment, 19 September 2026.** Zero human participants;
zero new LLM inference calls. This is an independent, newly implemented inventory
simulation, not a human-participant experiment or an ERP product test.

## 1. Scope and inputs
The inputs are synthetic observations generated on 19 September 2026. They are
not customer records, observed September 2026 demand or downloaded benchmark
trajectories. This is an independent inventory simulation with a common automated
baseline and four scripted review policies. It does not evaluate an ERP product,
Jev, Mercury, human performance or a newly executed language model.

External publications provide context and are cited in [ARTICLE.md](ARTICLE.md).
The experimental code, original inputs, numerical outputs and retained primary
traces are included in this study directory.

## 2. Design and unit of analysis
120 seeds, 41000 to 41119, each produce 20 historical and 60 evaluation shocks from
NumPy's default_rng standard normal distribution. Four mean-demand patterns share
those shocks. Each pattern is evaluated at lead times 1 and 4. Thus there are 480
synthetic demand paths and 960 scenario settings. The shared shock vector makes the
seed the independent simulation cluster, rather than the regime, lead time, period or controller.

There are five controller types: an automated baseline and four scripted review
profiles. Reviewed variants are crossed with delay {0,2,4} and fee {0,25,100}; each
scenario has one baseline plus 36 reviewed variants. Total: 35,520 trajectories.
The baseline and fee-25 variants comprise 12,480 primary trajectories and 748,800
retained per-period records. Other fee variants are sensitivity analyses.

The protocol was written and hashed locally before generating outcomes. It was not
publicly preregistered, no field study was performed, and no outcome-informed policy
tuning was conducted. `docs/PROTOCOL.md` is the immutable specification.

## 3. Demand and information
Demand is integer-valued: max(0, round(mu*(1+0.25*Z))), Z~N(0,1).
Training mu=100. Evaluation mu is 100 throughout for stationary demand; 150 from
zero-based period 20 onward for upshift; 60 from period 20 onward for downshift;
or 160 during periods 20 to 27 for a temporary pulse, returning to 100 thereafter.
All previously realised demand is observed, including demand lost during stockouts.
A controller does not see the regime name, forthcoming demand, future outcomes or
competitor data. Scenarios are not revealed to its decision functions.

All arrays are retained in `data/demand_paths.jsonl`. No bootstrap creates new
observed companies. Larger row counts do not increase the number of seed clusters.

## 4. Controller and profiles
Let m12,s12 be the rolling last-12 mean and sample standard deviation; L is lead time.
The baseline target stock position is ceil(m12*(L+1)+1.28*s12*sqrt(L+1)).
Initial inventory uses the training moments, capped at 1,200; initial pipeline is empty.
This is a transparent illustrative heuristic, not an optimised or economically
optimal baseline. It differs from the published InventoryBench policy.

| Scripted profile | Target at a review request | What it represents |
|---|---|---|
| Cash buffer | ceil(m12*(L+1)) | Removing the safety-stock allowance |
| Service buffer | ceil(m12*(L+1)+2.326*s12*sqrt(L+1)) | A larger safety allowance |
| Trend response | ceil(m3*(L+1)+1.28*s12*sqrt(L+1)) | Reacting to the last three observations |
| Plan anchored | ceil(mTrain*(L+1)+1.28*sTrain*sqrt(L+1)) | Reverting to the initial demand estimate |

These are four policies, NOT four participants, personality evaluations, validated
human-behaviour models or autonomous LLM agents. Role interpretations do not measure
how actual cash managers, service planners or experts decide.

## 5. Trigger, budget and latency
A common request signal is abs(m3-m12)/max(m12,1)>0.25, using only history available
before current-period demand. There are at most four requests with a six-period
cooldown. Because demand is uncensored and exogenous, all four profiles have the
same request schedule under a given demand path. The fee is charged on requesting.

The profile computes a stock target at request time. The target becomes usable
immediately or after two/four periods, and persists for four periods after delivery.
The baseline continues ordering while waiting. Current inventory, cash and caps are
checked again on application; stale order quantities are not blindly added to stock.
A late request can cost money even when its target arrives after the horizon.

Fees are 0/25/100 model units per request. They are arbitrary accounting assumptions,
not human salaries, measured effort, model tokens or observed response times.
No panel, voting, consensus, psychological diversity or same-budget random-review
allocation was tested.

## 6. State transitions and accounting
At the start of period t, receive orders due at t and any due review target. Compute
past-only signals, optionally pay a review fee, and choose a target. Inventory
position = on-hand + outstanding pipeline. Order max(0,target-position) subject to
400 units per period, 1,200 total position and available cash above a 2,000 reserve.
The reserve constrains purchasing, not subsequent holding fees or solvency.

Initial cash is 20,000. Purchase price is 20/unit, selling price 35/unit and holding
cost 0.4/ending on-hand unit/period. Orders are paid immediately and arrive at t+L.
They cannot satisfy demand at t. Realised demand then sells min(stock,demand) units;
unmet demand is lost, not backlogged. Charge holding cost and update the history.

Per-period cash increment = 35*sales - 20*order - 0.4*ending_stock - review_fee.
Ending pipeline units are counted until they arrive. All stock and cash movements
are recalculated along each altered trajectory, not spliced into a recorded outcome.

Net surplus = ending_cash + terminal_credit - initial_cash - 20*initial_stock.
Terminal credit = 10*(ending_stock + ending_pipeline), i.e. 50% of acquisition cost.
Both terminal credit and cash surplus before that credit are exported separately.
The terminal assumption can influence rankings; it is not an observed market value.
Changing decisions does not change exogenous demand: this is not a competitive market.

Fill rate = total units sold/total demand within each trajectory. Reported fill changes
average these per-trajectory rates, not a ratio after pooling all demand volumes.
There are no claims about invoice timing, shipment-level on-time delivery, fraud,
regulatory compliance, labour productivity, real currency savings or SAP accuracy.

## 7. Comparisons and uncertainty
Compare each reviewed run to its matched baseline (same seed, regime, lead, initial
resources). Relative mean change = 100*(mean(policy surplus)-mean(baseline surplus)) /
mean(baseline surplus). Baseline surplus is positive for the generated cohort.
Regimes and lead times receive equal weight in aggregate. These weights are not asserted market shares.
The exported `scenario_harm_pct` is a descriptive case fraction, not a deployment risk.

Primary intervals resample the 120 seed clusters 2,000 times using rng seed 20260919.
Pairings across policies, lead times and demand regimes are preserved. These percentile
intervals quantify Monte Carlo sampling uncertainty under this artificial generator.
They do not measure human variability or model misspecification, and are not evidence
of external validity. No universal best policy, p-value or field effect is asserted.

Fees are also compared at zero and 100; delays remain 0,2,4. The existing coefficients,
trigger, cash limits, holding cost and salvage rate were not optimised to make a
profile win. We did not study uncertain lead times, endogenous pricing, multi-SKU
substitution, macroeconomic shifts, malicious inputs or changing corporate objectives.
Those omissions materially limit applicability.

## 8. Verification and reproducibility
39 new automated checks pass: 28 engine/unit checks and 11 output/ledger checks.
The output check independently recomputes stock flows, arrival schedules, cash and
terminal accounting across all 748,800 retained primary period records. A separate
past-only arithmetic check recomputes target revisions for all 104 primary trajectories
of seed 41000. Twenty trajectory summaries are rerun; aggregate means are recomputed
with standard-library arithmetic. Future-prefix invariance and review latency/expiry
are tested. Inputs and the pre-run protocol hash are checked. The test output is retained
in `execution/tests.txt`.

Python 3.13.5, NumPy 2.3.5, pandas 2.2.3 were used for the experiment. Plotting uses
Matplotlib 3.10.8. All experiment runs are offline. Runtime,
counts and input SHA-256 are in `execution/run_metadata.json`.

## 9. Permissible conclusion
Under the exact policies, costs and generator tested, review need not improve the
baseline and may trade net surplus for service. The experiment cannot estimate human
review benefit, human mistakes, the value of contextual knowledge, or LLM performance.
The positive human results discussed in the article belong to Baek et al. (2026).
They are not observations collected by this computational study.
