# Provider-Scoped Isolation for OpenTofu

**Osman Kaan Kars**

A configuration- and lifecycle-aware provider launcher that keeps one OpenTofu
resource graph while assigning each external provider process its own execution
boundary. **Working local integration prototype, not a production security product.**

## Result

In the recorded four-arrangement lab, the scoped integration prevented both
research-provider configurations from obtaining a named unrelated environment
value and an unassigned file's expected content. Their assigned API operations
and resource dependencies continued to work.

| Execution arrangement | Unrelated environment visible | Unassigned file content obtained | Assigned operations and dependency chain |
|---|---|---|---|
| Default OpenTofu | Yes | Yes | Completed |
| Environment filtering only | No | Yes | Completed |
| Whole-job container | Yes | Yes | Completed |
| Provider-scoped isolation | No | No | Completed |

Each arrangement completed `init`, `validate`, `apply`, a no-change `plan`, and
`destroy`. This is one completed lab, not a statistical success rate.

**Read:** [Article](ARTICLE.md) · [Results and limits](RESULTS.md) ·
[Implementation notes](METHODS.md) · [Source references](SOURCES.md).

## Inspect the implementation

`code/cell/` contains policy binding, executable staging, the rootless Podman
runner and private socket handling. `code/integration/` installs a blob-checked
source overlay at the pinned OpenTofu revision. `code/fixture/` and
`code/fixtureapi/` contain the controlled provider and its local service.
`code/tools/` builds the three core variants and runs the comparison.

The policy is selected by trusted core code before external-provider execution.
Schema discovery is separated from credential-bearing validation and configured
instances. Unsupported launches fail closed. The existing provider RPC and
automatic mutual TLS are retained.

## Reproduce

Use a disposable **Linux x86-64** machine with a working non-root Podman/cgroups-v2
session, Git, Python 3.10+ and Go **1.26.6**. The recorded run used Podman 4.9.3.
These are reproduction targets, not recommendations to deploy old versions in
production. Source and module downloads require Internet access; the lab APIs
are local. Do not run the default or whole-job comparison in an environment
containing real credentials. No cloud account is needed.

From this study directory:

```sh
cd code
podman --remote=false info --format '{{.Host.Security.Rootless}}:{{.Host.CgroupsVersion}}'
# Required: true:v2
python3 tools/build.py --out "$PWD/.build/reproduction"
python3 tools/run_lab.py --build "$PWD/.build/reproduction" \
  --out "$PWD/.build/results" --runtime /usr/bin/podman
```

The build and output directories must not already exist. A successful lab writes
`.build/results/summary.json` with `COMPLETED_LOCAL_PROTOCOL_LAB`. The earlier
build manifest intentionally remains a build-stage record. Read the generated
logs if a step fails; do not remove checks to obtain a green result.

For source-only component checks, without running the lab:

```sh
go test -race -count=1 ./...
python3 -m unittest discover -s integration/tests -v
python3 -m unittest discover -s tools/tests -v
```

Those commands are not substitutes for the real OpenTofu integration run.

## Scope

The strict profile uses no external network and only explicitly assigned local
Unix services. Real cloud compatibility and production hardening are not
established. The core, HCL, policy, kernel and runtime are trusted. Authority
intentionally given to a provider, or values explicitly passed to it through
HCL/RPC, are outside the protection claim.

The publication retains the recorded runtime implementation. Private account
provisioning scripts and development scratch logs are not needed to inspect or
reproduce the Linux lab and are omitted. The public evidence is a selected,
labelled subset of the preserved original record, not a new execution.

See [attribution and rights](NOTICE.md). Provider isolation is prior art; this
study does not claim a new CVE or the first provider sandbox.
