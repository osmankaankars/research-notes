# Implementation and experimental method

## Identity before launch

The overlay is pinned to OpenTofu commit
`b4305e5a5dd2fb79a27897ae30784a181d3a26cb`. It checks upstream blob identities
before modifying source. Resolved configuration addresses, instance keys and
phases travel from graph nodes through the provider manager to a deferred
factory. A policy resolution failure prevents launch rather than selecting the
ordinary host launcher.

The policy binds provider source, executable SHA-256 and exact configuration
identity. An administrator controls the policy. The provider does not select its own
binding. Image and executable digests bind bytes, not the trustworthiness of
those bytes.

## Execution boundary

The Linux runner stages a verified executable, then creates and starts a rootless
Podman container with private runtime namespaces, a root filesystem that cannot be written to, no
external network, dropped capabilities, no new privileges and a separate scratch
directory for each invocation.
Only the assigned credential files, environment values loaded from configured
files, and Unix service connections are supplied. Host environment inheritance is disabled. Image
entrypoint, command and environment defaults are overridden.

The existing go-plugin protocol and automatic mTLS are preserved. The runner
translates Unix socket addresses and pins sockets using file descriptors. Cleanup
is scoped to the invocation it created and checks container absence before
removing its lease. Host/core crashes and independent runtime auditing are
outside the demonstrated cleanup claim.

Schema discovery uses a separate invocation. Configuration validation may receive
sensitive values and therefore receives a binding for that instance. Development
overrides, unmanaged reattachment, provisioners and unsupported launch contexts
are refused in enforced mode. This is deliberately not a transparent wrapper for
all Terraform/OpenTofu distributions or provider features.

## Fixed workflow and comparators

The unmodified upstream random provider was built from v3.7.2 source at
`bc2ddb552b4676d16997987a9bf2875c7b98d342`. The research provider uses Terraform
Plugin SDK v2.38.1. The graph contains three resources:

```text
random_id.anchor -> cell_record.red -> cell_record.blue
```

The research provider reports a bounded set of boolean checks against explicitly
named synthetic values. Its assigned credential must authenticate a successful
local API operation. Each alias uses a different service/credential pair.

The same definition is run with the default core, a core that filters the
environment, the whole job inside one container, and the core that isolates
provider configurations. The single job container intentionally shares the lab
directories and artificial credentials inside it, but does not mount the
operator's real home. This is one specified configuration, not a universal claim
about every possible job sandbox.

Every comparator runs init, validation, apply, a plan using `-detailed-exitcode` and
destroy. Random resource identifiers change between arrangements; the graph and
asserted relationships do not. Results are compared as recorded observations,
not independent samples of an error rate.

## Reproducibility limits

Upstream source revisions and produced binary hashes are recorded. The local
mirror used providers built from source. Vendor signatures on release binaries
were not verified.
The research provider's dependency lock was generated during the original build;
its hash is recorded, but the complete generated lock is not in the evidence
export. Thus this release targets behavioural reproduction, not a guarantee of
rebuilds with identical bytes or a sealed offline dependency distribution.

No claim is made about production cloud egress, normal AWS/Azure/GitHub provider
operation, performance overhead or full malware resistance. The current network
profile intentionally permits local connections only. The trusted core/HCL/policy and runtime can
still grant unsafe authority, and intentionally passed secrets remain disclosed.
