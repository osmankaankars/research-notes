# Research Notes

**Osman Kaan Kars**

Independent articles, technical notes and reproducible studies on AI, cybersecurity,
SAP and enterprise systems. Each study keeps its writing, methods, code and evidence
together. Experimental findings are distinguished from interpretation.

## Studies

| Date | Study | Focus |
|---|---|---|
| 27 September 2026 | [Provider-Scoped Isolation for OpenTofu](studies/2026-09-opentofu-provider-isolation/README.md) | Per-configuration execution boundaries, provider supply-chain risk and preserved resource dependencies |
| September 2026 | [Approval Is Not a Receipt](studies/2026-09-approval-is-not-a-receipt/ARTICLE.md) | Request revisions, uncertain external effects, supplier guarantees and safe recovery |

## Latest study

[Provider-Scoped Isolation for OpenTofu: code and reproduction](studies/2026-09-opentofu-provider-isolation/README.md)

A working local integration prototype comparing default execution, environment
filtering, whole-job containerisation and provider-scoped isolation. The scoped
run removed two tested unrelated accesses while assigned API operations and the
resource dependency chain continued to work. It is not a production security
product or a demonstration of live-cloud compatibility.

## Organisation

Each directory under `studies/` is self-contained. `ARTICLE.md` is the reader-facing
piece; `README.md` describes the experiment and how to reproduce it. Data, results,
figures and tests remain with the study they support.

[Rights and attribution](RIGHTS.md)
