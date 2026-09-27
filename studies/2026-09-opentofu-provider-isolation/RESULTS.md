# Recorded results

## Execution

Run **36317604974**, completed **27 September 2026**, used source commit
`b487dbb261fd3a7c489aee5479e7db1b0b3997ae`. The original downloaded evidence
archive had SHA-256:

```text
636db0429ecadf5058210eee31f595fa16327c46c98821de93efdf9b2beb039f
```

The environment was Linux x86-64, Go 1.26.6, rootless Podman 4.9.3 and cgroups v2.
The controlled resources used artificial credentials and local APIs reached through Unix sockets.
No real cloud keys or malware packages were used.

## Observed comparison

| Arrangement | Unrelated environment visible | Unassigned file content obtained | Assigned API works | Dependency chain works |
|---|---|---|---|---|
| Default | Yes | Yes | Yes | Yes |
| Environment filtering only | No | Yes | Yes | Yes |
| Whole job in one container | Yes | Yes | Yes | Yes |
| Isolation by provider configuration | No | No | Yes | Yes |

Both `red` and `blue` configurations recorded the listed result in every
arrangement. They executed the same research provider binary with distinct
credential and service bindings. Each arrangement validated, created three
resources, produced a plan with no changes, and destroyed three resources.

The scoped dependency outputs were:

```text
random_id.anchor = e25018ef84225d3c
red_upstream     = e25018ef84225d3c
red_id           = red-7736c4229da32c9b89f8ed44ac638042
blue_upstream    = red-7736c4229da32c9b89f8ed44ac638042
blue_id          = blue-cc6f8b54a4dc0e3d847d053533f46e1a
```

## Evidence available here

[evidence/results.json](evidence/results.json) is the unchanged aggregate lab
result, including the original build manifest and boolean checks for each
configuration. [evidence/cli-excerpts.txt](evidence/cli-excerpts.txt) selects validation,
apply, plan and destroy messages from the original logs and includes the scoped
output. ANSI formatting was removed from the excerpts. Source filenames and
original file hashes are listed alongside them.

[evidence/runtime.json](evidence/runtime.json) and
[evidence/execution.json](evidence/execution.json) are unchanged records.
[evidence/provenance.json](evidence/provenance.json) describes the selection.
[evidence/SHA256SUMS](evidence/SHA256SUMS) covers the published evidence files.
The original full archive was checked separately before publication. This folder
is not a claim to contain that entire archive.

## Interpretation boundaries

- `unassigned_file_readable: false` means the expected canary content was not
  obtained. The measurement does not export an errno; it does not establish a
  particular `EACCES` or `EPERM` response.
- `self_process_information_available` checks `/proc/self/stat`, not the privacy
  of the parent process or every access path between processes.
- `credential_file_present_at_start` in a resource result is sampled by a check
  function called during configuration. It is not independent evidence that a
  schema process had no credentials at its first instruction.
- The unchanged build manifest says `COMPILED_NOT_RUNTIME_VERIFIED`. It was
  produced before the successful lab. The outer summary, not a rewritten build
  record, reports the later runtime result.
- One fixed workflow is not a performance benchmark, repeated statistical study,
  compatibility result covering all providers, or comprehensive evaluation of malicious code.

The implementation removed the two unrelated accesses being measured while the
assigned operations continued to work. This does not establish resistance to
kernel or runtime escapes, every method of stealing credentials, or
misuse of authority deliberately granted to a provider.
