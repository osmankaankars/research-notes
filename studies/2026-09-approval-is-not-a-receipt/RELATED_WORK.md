# Related work and contribution boundary

**Reviewed 19 September 2026.** This is a scoped primary-source comparison, not a comprehensive systematic review or proof of unique novelty. No external project's published scores are relabelled as our measurements.

## CAV-Bench

Nixalkumar Patel, *Commit-Time Action Validity Benchmark*, source pinned to `0e818a00517384241357b08354596ed7462872bf`.

- [Methodology](https://github.com/Harimay23/cav-bench/blob/0e818a00517384241357b08354596ed7462872bf/docs/methodology.md)
- [Tool facade](https://github.com/Harimay23/cav-bench/blob/0e818a00517384241357b08354596ed7462872bf/src/cavbench/runtime/tools.py)
- [Package and Apache-2.0 terms](https://github.com/Harimay23/cav-bench/blob/0e818a00517384241357b08354596ed7462872bf/pyproject.toml)

The methodology already separates final-state outcomes from commit-valid history, combines intent, authority, temporal validity, execution integrity and recovery, and does not trust an adapter's success label. Its five baseline profiles are deterministic, not live-model results. The inspected tool facade supports logical operation identity, idempotency keys, expected resource versions, status checks and escalation.

| This study's condition | Relationship to inspected CAV-Bench contract |
|---|---|
| Normal actions, changed state, bounded authority | Existing related coverage; not a new failure class claimed here |
| Lost replies, idempotency and reconciliation | Existing related execution/recovery coverage |
| Invalid effect later cancelled | Existing historical-ledger evaluation principle |
| Genuine separate intents with identical parameters | Related intent and effect-identity concern |
| Replacement revision during unresolved original effect | Our explicit two-supplier fixture, examined with retained liabilities and replacement semantics |
| Expiring deduplication versus durable closure evidence | Explicit provider contract variation in our fixture; not assumed a default capability of the inspected tool facade |
| Unresolvable, observationally identical accepted/nonaccepted worlds | Supplemental diagnostic of the assumed information boundary |
| Abrupt client exit and actual closed HTTP connection | Additional implementation-level confirmation in our local fixture |

This is **not** evidence that CAV-Bench cannot represent those extensions, or that its current full-lifecycle strategy would fail them. No direct adapter compatibility or upstream runtime reproduction has been established. The archive retrieval attempts failed in this environment; the pinned methodology and facade were read through GitHub. Upstream code has not been copied into our runtime and no upstream numerical results are compared with our denominator. Apache-2.0 attribution remains with its author and repository.

## Provenact

Yuxiang Peng and Xiaodi Wu, [*Stateful Governance for Concurrent Agentic Systems*](https://arxiv.org/html/2608.02764v1), arXiv:2608.02764v1, August 2026.

Provenact concerns stateful authorization across concurrent actions and delayed approvals. Its discussion of effects outside the local transaction identifies durable intent, operation identity and reconciliation as necessary issues. Our local dispatch boundary does not substitute for its policy-state serialization model. This study examines one explicit external-effects workflow, with mock-provider guarantees, and does not claim to implement or outperform Provenact.

## Established distributed-systems practice

Malcolm Featonby, [*Making retries safe with idempotent APIs*](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/), Amazon Builders' Library. Caller-supplied intent identifiers, atomic side-effect/key recording, late requests and parameter changes are prior art. The strong executor is built from these kinds of conventional practices, not presented as a newly invented algorithm.

Stripe, [*Idempotent requests*](https://docs.stripe.com/api/idempotent_requests), accessed 19 September 2026. Parameter matching and finite key retention show why an operation key is not an unlimited deduplication guarantee. Our supplier contract is synthetic; its permanent closure/cancellation fences must not be attributed to Stripe.

## Fast agent context

Diogo Almeida, [*Introducing System One Models and Jev*](https://typesafe.ai/blog/introducing-system-one-models-and-jev), TypeSafe, September 2026.

WindTunnel, [Jev + Mercury 2.5 implementation notes](https://github.com/nekuda-ai/WindTunnel/blob/5ca8644e23826ebb30108e7bad240b61043bfe67/experiments/jev/README.md). Its documented split puts action selection in Jev and argument/field generation in Mercury. Its actual model results belong to its authors. We made no Jev, Mercury or other model calls and do not estimate their speed, prices or relative safety.

FreshCtx's public [README](https://github.com/Hyperwise-LLC/freshctx) describes pre-action validation of declared evidence dependencies. It is additional contextual prior work, not an evaluated competitor here. Evidence freshness does not by itself prove an external write occurred.

## What this study adds, and what it does not

The delivered artifact is a specific revision-under-uncertainty case pack, three conventional executor scopes, independently inspectable provider effects, recovery/held-liability accounting, explicit provider capability boundaries, and HTTP/process-failure confirmation. It exposes how zero repeated-operation duplicates can coexist with conflicting replacements, and why truthful pending work must remain separate from completed work.

It does not claim to be the first treatment of these principles, a new exactly-once protocol, a validated production coordinator, a human study, or a new model benchmark. A strong existing implementation may perform just as well. The contribution is the explicit test and its evidence, not a guaranteed invention or a fabricated superiority result.
