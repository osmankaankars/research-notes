# Four simulated review profiles: locked computational protocol

Date: 19 September 2026. Version: 1.0.
Status at creation: specified before intervention outcomes were generated.
This is a local pre-analysis specification, NOT a public preregistration.

## Scope amendment
The earlier four-arm LLM/human protocol is NOT completed by this study. This new
experiment compares four explicit, scripted review policies against a common
scripted inventory controller. There are no people, recruited participants,
LLM calls or empirically validated models of human behaviour. Role names describe
objectives, not measurements of a CFO, planner or any population.

## Question
With identical demand information, initial resources and a bounded review budget,
how do different review objectives and review delays affect a replenishment policy?

## Inputs and accounting
- 120 seeds (41000 through 41119), each generating 20 historical observations and
  60 evaluation periods. Demand = max(0, round(mu * (1 + 0.25 * standard_normal))).
- Four predeclared regimes: constant mu=100; mu=150 from period index 20 onward;
  mu=60 from index 20 onward; mu=160 on indices 20..27, otherwise 100.
- The same standard-normal shocks are paired across regimes and lead times.
  Each seed is one simulation cluster, not eight independent observations.
- Lead time L=1 or L=4 periods; no competition, lost deliveries, uncertain lead
  time, backorders or human errors. Demand is fully observed, even if unsatisfied.
- Price 35, purchase cost 20, holding cost 0.4 per ending on-hand unit per period.
  Monetary amounts are model units, NOT euros or measured business savings.
- Initial cash 20,000, protected cash reserve 2,000, order cap 400 units/period.
  Maximum on-hand+in-transit stock position after purchase = 1,200 units.
- Initial on-hand stock is the baseline target from the training observations.
  Initial inventory is valued at cost as contributed capital. No initial pipeline.
- At each period: receive due stock; deliver due review target; observe past-only
  signals; optionally request review; choose target and order; realise demand;
  sell available stock; charge holding cost; log state and observe demand.
- Orders paid immediately, arrive at beginning t+L, never in the order's period.
  Stock and purchase quantities are nonnegative integers. Lost sales do not queue.
- Terminal value: 50% of acquisition cost for remaining on-hand and in-transit
  inventory. Report cash P&L and terminal credit separately. Net surplus = final
  cash + terminal credit - initial cash - initial inventory acquisition value.

## Baseline
Rolling last-12 mean mu and sample standard deviation sd. Target inventory position
S = ceil(mu*(L+1) + 1.28*sd*sqrt(L+1)). This is an illustrative heuristic, NOT a
claimed optimal OR policy. Order max(0,S-inventory_position), subject to common caps.

## Four profiles (only one active in a run)
R1 cash_buffer: same last-12 mean, safety coefficient z=0.
R2 service_buffer: same last-12 mean, z=2.326.
R3 trend_response: last-3 mean, last-12 sd, z=1.28.
R4 plan_anchored: initial training mean and sd, z=1.28.
All use the same present and historical information; no regime labels or future
observations are passed to decision functions. None is asserted to model humans.

## Shared review mechanism
Trigger when abs(last-3 mean - last-12 mean)/max(last-12 mean,1) > 0.25.
At most four requests per 60-period run; at least six periods between requests.
Common trigger only depends on observed demand, so profiles face the same schedule.
A review computes a target from information at request time. It arrives after
0, 2 or 4 periods and remains in force for four periods after arrival. The baseline
continues while waiting; a stale target is rechecked against present inventory and
resource caps. This tests lagged target revision, not a queue blocking all work.
Fee 25 model units/request in primary runs, 0 and 100 in sensitivities. Costs debit
cash immediately. Target delivery is free after request; last-period requests may
cost without delivering a benefit. Fees/lag are assumptions, not measured latency.

## Design and outputs
960 scenario settings = 120 seed clusters x 4 regimes x 2 lead times.
Per setting: one baseline, plus 4 profiles x 3 delays x 3 fees = 37 trajectories.
Total 35,520 trajectories, of which 12,480 are the baseline and fee-25 primary set.
The 120 seed clusters, not trajectories or time steps, underpin uncertainty.
Preserve all inputs, outcomes, the full primary-step log in gzip, and all results.
No optimisation or tuning on evaluation outcomes, no changes to profile parameters
in response to results. Any repair to implementation is documented.
Primary comparisons: per-profile paired change in net surplus vs baseline by
regime (pool both lead times equally), at delay=0/fee=25. Also inspect lead-specific
results and delay curves. Report fill rate, mean inventory, fees and terminal stock.
Bootstrap 2,000 resamples of the 120 seed clusters, preserving the full paired
regime/lead/profile structure. Intervals describe Monte Carlo uncertainty under
this artificial generator, not external validity or a human population.

## Verification
Test exact accounting, resource limits, past-only decisions, lead-time semantics,
review schedules, review fees, delayed delivery/expiry, deterministic reruns and
input rejection. Compare exported totals to independently recomputed daily ledgers.
No success claim is made about a simulator never executed.
