# Methods: Approval Is Not a Receipt

**Osman Kaan Kars | 19 September 2026**

A completed controlled software experiment. No human participants, new language-model inference, paid APIs, real payments or production ERP connections are involved.

## 1. Question and contribution

We examine an external purchase operation whose outcome is unknown when the originating business request changes. The study makes three conventional executor scopes explicit, varies supplier guarantees, and distinguishes verified completion from safe unresolved liability. Its contribution is a reproducible case pack, retained evidence and a capability-specific comparison. It does not introduce idempotency, durable workflows, compensation, stateful authorization or a new AI architecture.

CAV-Bench already evaluates commit validity, historical effects and truthful recovery. Our comparison with that project is a documented contract/coverage crosswalk, not an executed head-to-head or a reproduction of its published scores. See [RELATED_WORK.md](RELATED_WORK.md).

## 2. Implemented system and trust boundary

The core is Python standard-library software. Two suppliers, A and B, each maintain an independent SQLite database with an append-only CREATE/CANCEL effect ledger. The client separately persists request revisions, dispatches, reservations, attempts and received results. Supplier outcomes are obtained through a common interface, either directly or through actual loopback HTTP in separate processes.

The test controller receives the currently available request and documented supplier contract. It does not receive the scenario family, future event schedule, private expected result or supplier database path. Fault injection is environment-owned. This is a cooperating-component test, not a sandbox against an adapter that deliberately inspects Python internals or local files.

The evaluator independently reads supplier effects and recorded authority events. It ignores an adapter's asserted score. It uses the adapter's success statement only to check whether that statement is supported. Hashes bind identity and payload but are not a cryptographic authentication mechanism against a malicious provider. The local fixture supplies the authoritative provider boundary.

Four identifiers have separate roles: `intent_id` identifies the business request across changes; `revision_id` identifies one authorized replacement version; `operation_id` identifies an immutable external payload at one supplier; `attempt_id` identifies one transmission. Equal payloads belonging to different authorized intents are legitimate separate work.

## 3. Authority and supplier contracts

Authority is evaluated at **local durable dispatch commitment**, when the exact payload, applicable revision and resource reservation are written atomically. This is not a claim of remote atomicity or serializability at an external provider. A revision after a valid dispatch does not retrospectively invalidate that dispatch.

In these fixtures a replacement revision explicitly means the new quantity/supplier replaces the previous requirement and permits cancellation of the earlier order. It is not an additive order. This authorization convention is fixed, not inferred by a model. Real cancellation rights, fees and irreversible shipment states are outside scope.

Unknown outcomes keep their possible liability reserved. Confirmed purchases also keep the active resource commitment reserved; cancellation or definitive no-effect evidence can release it. Budget increases are explicit scenario events, not silently supplied extra resources.

| Contract | Deduplication and status | Closure assumption |
|---|---|---|
| DURABLE | Stable operation keys with no expiry; a final lookup or same-key retry can establish the effect | Definitive no-effect and confirmed cancellation install a provider-side fence against later creation of that operation |
| EXPIRING | Keys expire at `tick >= expires_at`; retry after expiry can create a second effect; status visibility may be delayed | Independent final status/closure remains available in the specified schedules; confirmed closure fences late creation |
| OPAQUE | No reliable deduplication or final lookup; unknown responses do not reveal hidden ledger versions | No dependable cancellation confirmation or final no-effect proof |

These are **explicit mock-provider capabilities**, not claims about Stripe, SAP or any live supplier. In particular, EXPIRING is not simply a short-lived idempotency key with no other protection. The retained final lookup and closure guarantees materially support its successful recovery.

A plain absent result is always UNKNOWN. FINAL_NO_EFFECT is issued only after a durable fence that rejects a later original delivery. Likewise CANCEL_PENDING is not confirmed cancellation. The opaque contract may stay unresolved through the observation horizon.

## 4. Compared executor scopes

All configurations use the same deterministic proposal rule and visible inputs. No method is selected by scenario name.

- **Request-only:** diagnostic weak control. It relies on request-time checks, permits fresh operations on retry and lacks aggregate liability coordination. This is intentionally incomplete, not a best-practice competitor.
- **Operation-scoped:** intermediate ablation. It has current dispatch checks, shared-budget reservations, durable single-operation identities and status reconciliation. It does not coordinate distinct operations belonging to replacement revisions.
- **Intent-scoped:** strong conventional reference. It also preserves prior operation liabilities across revisions and suppliers, resolves the old operation, obtains confirmed authorized cancellation or final no-effect evidence, then submits an admissible replacement.

There is no proposed fourth executor called a novel improvement. The strong reference is established engineering practice instantiated in this fixture. Results establish the effect of the included capabilities under this controller, not superiority over CAV-Bench, Provenact or all existing workflows.

The controller uses simple bounded polling. It is not optimized for minimum calls. This is particularly relevant to OPAQUE, where repeated status queries cannot create missing evidence. Queries, cancellation requests and retries all count as work.

## 5. Case allocation, timing and freeze

There are 24 development cases and 120 fixed evaluation cases, ten in each family:

| Family | Condition |
|---|---|
| F01 | Normal order |
| F02 | Irrelevant state changes |
| F03 | Revision between observation and local dispatch |
| F04 | Two intents competing for shared funds |
| F05 | Supplier accepts but response is lost |
| F06 | Request is not accepted and response is lost |
| F07 | Non-final or delayed lookup visibility |
| F08 | Idempotency retention expires |
| F09 | Client restart around dispatch or receipt persistence |
| F10 | Replacement quantity/supplier while outcome is unknown |
| F11 | Unconfirmed cancellation or delayed original delivery |
| F12 | Two independently authorized identical purchases |

The allocation includes 43 DURABLE, 44 EXPIRING and 33 OPAQUE cases. Ten slots per family vary contracts, event order, visibility, cancellation delay and parameters; they are not ten random draws from an industry population. F04 includes five eventual budget increases and five cases whose funds stay insufficient. The allocation is not a factorial estimate of a provider's causal effect because not every family/slot supports every contract.

Evaluation quantities are `100 + 7*slot`, unit price is `2000 + 50*(slot % 4)` integer minor units, and replacement quantity is `floor(0.6*original)`. All fixtures have a 16-tick horizon. Expiring retention is two or three ticks; visibility and late-delivery schedules are explicit in the JSON input. A tick is logical time, not seconds, a business day or model latency.

Faults are attached to semantic anchors such as first dispatch or create attempt. The environment changes the state after the controller's observation where the scenario requires it. Runtime performance does not determine whether a hazard is injected.

Core source, tests and exact inputs were hashed locally before the completed scored evaluation. The freeze is `protocol/frozen_manifest.json`; this is not public preregistration. Its SHA-256 is `bf7e45deb2cfacbca41eddcb43c0430c80e6f373bedfc6345635838f4eefd4e2`. The frozen source and cases have not changed after outcomes were obtained. Audits, transport-subset selection, diagnostics, charts and prose are subsequent analysis.

## 6. What was executed

The main evaluation ran 120 cases once per deterministic executor, producing **360 complete scored episodes**. Identical deterministic episodes were not rerun to inflate an experimental sample size.

The HTTP confirmation ran **26 of those cases across all three executors, 78 episodes**. Its mechanical subset is slots 0 and 2 of every family, plus slot 1 in F10 and F11. This subset was selected after direct evaluation for transport confirmation, not as a held-out validation set. Both suppliers run in distinct subprocesses and exchange actual local HTTP requests. The server closes a connection without sending a response either before acceptance or after the SQLite transaction commits. Other integration tests terminate an actual client process at two persistence boundaries and restart the provider process.

All 78 HTTP outcomes match their corresponding direct-run logical outcomes exactly. Startup times and transport runtimes differ and are not used as comparative latency results.

An initial direct attempt hit the tool runtime limit after 209 complete episodes. It was not the scored dataset; the unchanged full matrix was rerun in a clean directory. The initial serial HTTP confirmation also hit a runtime limit. Complete records were validated and missing episodes resumed in isolated directories without changing source or inputs. Interrupted attempts and full reruns are not additional independent evidence. The run manifests and execution logs disclose these interruptions; partial work was not selected or excluded by performance.

A separate **two-world diagnostic** was constructed after the main evaluation. Both opaque cases expose exactly the same 100-to-60 revision, observations, actions and reports. One supplier ledger contains 100 units; the other contains none. The strong reference stays unresolved in both, retaining 200,000 minor units of possible liability. Public-history bytes match exactly. These two diagnostics are outside the 120-case comparison and establish no new impossibility theorem or model result.

## 7. Independent scoring and coverage

`completed_correctly` requires the final physical goal, supported receipts, no forbidden historical effect, no duplicate effect and a justified success report. Looking correct at the end is insufficient if an invalid effect occurred earlier and was later cancelled.

`invalid_effects` counts physical commits that violate recorded dispatch authority, shared budget or intent exclusivity, plus duplicates and payload discrepancies. A blocked proposal is not a committed violation. The report distinguishes event counts from cases containing any such event.

`duplicate_effects` covers repeated operation effects or overlapping effects for the same intent revision. A new operation for a replacement revision can create a **conflicting commitment without repeating the same operation**. These are invalid historical effects but not necessarily same-operation duplicates.

`false_success_claim` includes unsupported completion claims: even a coincidentally correct physical state does not justify claiming verified success without evidence. The label does not imply deliberate deception. Public prose uses 'unsupported completion claims'.

`safe_unresolved` retains unknown liabilities and truthfully reports pending recovery, with no invalid physical effect. `safe_blocked` represents non-completion requiring a decision, such as insufficient budget, without unknown external effects. Neither counts as verified completion. Calls and held-liability duration are reported separately, rather than combined into a score that could hide an unauthorized effect.

The primary `fault_exercised` boolean records whether **any** environment fault occurred. A post-run component audit in `results/audit/hazard_coverage.csv` identifies compound stages that were not reached. Of the 360 direct episodes, 60 are clean controls, 278 reached all enumerated hazard components and 22 did not. In particular, a method that never attempts cancellation cannot claim to have recovered from cancellation-response loss. Such episodes remain in the failure accounting and are not labelled successful stress recoveries. This clarification changes no core code or primary outcome.

These are finite fixture counts. No confidence intervals, p-values or production failure probabilities are reported. The HTTP confirmations are overlapping cases, not an additional generalization sample.

## 8. Results and cost of caution

| Executor | Verified completion | Invalid-effect cases | Repeated-effect cases | Safe unresolved | Budget blocked | Unsupported success |
|---|---:|---:|---:|---:|---:|---:|
| Request-only | 30/120 | 70/120 | 35/120 | 0 | 0 | 90/120 |
| Operation-scoped | 83/120 | 15/120 | 0/120 | 12 | 5 | 20/120 |
| Intent-scoped | 97/120 | 0/120 | 0/120 | 18 | 5 | 0/120 |

The intent-scoped reference produces 14 additional verified completions relative to operation-scoped execution, prevents 15 invalid effects in 15 cases, and leaves six more cases explicitly unresolved rather than misreporting progress. It uses 651 supplier calls across 120 cases versus 497: 154 additional calls, with means 5.425 versus 4.1417. This is a joint change in architecture and behavior, not proof that adding more calls causes reliability.

Within the strong reference, DURABLE completes 41/43 with two budget blocks; EXPIRING completes 42/44 with two budget blocks; OPAQUE completes 14/33, leaves 18 unresolved and one budget-blocked. No observed invalid effects in the fixed suite is not a universal safety guarantee.

The example `eval-F10-00` makes the cross-revision error tangible. Under operation-scoped execution, A accepts 100 units and B subsequently accepts 60, leaving 160 live units even though each operation ID is unique. The strong reference observes A's confirmed status, obtains confirmed fenced cancellation, then creates B's 60 units. The two execution traces are retained.

## 9. Verification and limitations

There are 69 software/integration tests. They include real concurrent shared-budget transactions, parameter mismatch, expiry duplicates, persistence, future-prefix invariance, identical opaque observations, forged success reports, legitimate duplicate-looking purchases, cancellation uncertainty, actual HTTP disconnects and abrupt process exits. These are validation checks, not 69 additional business experiments.

`audit/verify_results.py` independently inspects raw SQLite tables for all 360 direct and 78 HTTP episodes. It checks ledger/event exports, physical goals, liability accounting, tool counts, summary arithmetic and direct/HTTP parity without invoking the benchmark evaluator. `results/audit/verification.json` records that audit. This is a separate arithmetic path performed in the same project, not external peer review.

The fixtures omit real logistics, shipping irreversibility, malicious providers, distributed multi-writer client databases, cancellation fees, inventory economics, external market feedback and human judgment. Authorization and cancellation permissions are prescribed. The provider closure fences are stronger than a generic acknowledgement. Real deployments must verify their actual contracts instead of inferring these guarantees from this experiment.

CAV-Bench documentation and its pinned source interface were inspected. Its full archive could not be retrieved in usable form through the available route; its test suite was **not run** and no numerical replication or superiority claim is made. No real open-source ERP application or current AI model was integrated. The experiment supports a capability-aware execution comparison, not a frontier-model ranking or human-performance estimate.

Reproduction instructions are in [README.md](README.md). Core execution is standard-library-only; the supplied figures require Matplotlib only if regenerated. Python 3.13.5 was used for the completed runs.
