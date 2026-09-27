# One Infrastructure Run Is Not One Trust Boundary

*Keeping OpenTofu's dependency graph without giving every provider the same access.*

**Osman Kaan Kars | 27 September 2026**

An infrastructure workflow may need several providers to cooperate. That does not mean those providers need access to the same credentials, files or process environment.

That distinction is the reason I built a provider-scoped isolation prototype for OpenTofu. The objective was practical: keep the infrastructure workflow working while removing unrelated access from individual provider processes.

## Why I chose this problem

On 22 September, Aikido published research describing Graphalgo-linked malware distributed through Terraform providers and Go modules. The report, updated on 24 September, made provider execution a particularly timely supply-chain concern. This was Aikido's discovery, not mine, and I did not run those malicious packages. [1]

The architectural issue is broader than any one campaign. A provider is an executable program, not just configuration. Terraform's documentation describes providers as separate processes communicating with the core over RPC. A process boundary alone does not specify which credentials or files that program is allowed to see. [2]

My question was therefore not whether another scanner could recognise a malicious package. It was whether an infrastructure engine could give each provider configuration a narrower execution environment without breaking the dependencies between resources.

## The boundary belongs to the provider configuration

Putting the whole job in a container can protect what is outside that job. It does not automatically separate the providers inside it. Similarly, filtering environment variables does not remove access to files that remain visible to the process.

I implemented the boundary at the provider-configuration level. Two aliases of the same provider can receive different credential files and service connections, even though they execute the same provider binary.

The OpenTofu integration carries the resolved configuration identity and execution phase to the launcher. A trusted policy binds that identity to the provider executable and the capabilities it receives. The launcher uses rootless Podman; it does not fall back to unrestricted host execution when isolation setup fails.

Timing matters as much as identity. In the reviewed OpenTofu code, obtaining a provider's schema starts its executable. Protection cannot begin only when a resource is created. The integration separates schema discovery, configuration validation and configured execution rather than treating every invocation as equivalent. [3]

The existing provider RPC protocol remains in place. I used the existing go-plugin runner and environment-control interfaces rather than introducing a replacement infrastructure engine. [4]

## Keep the useful work, remove the unrelated access

I compared four execution arrangements using the same small infrastructure definition: ordinary OpenTofu, environment filtering alone, whole-job containerisation, and the provider-scoped integration.

The workflow used a source-built copy of the published `hashicorp/random` provider and two configurations of a controlled research provider. The first research resource consumed the random provider's output. The second consumed the first resource's identifier. Each research configuration had its own artificial credential and local Unix-socket service. [5]

The controlled provider checked a named unrelated file and an unrelated environment variable. It also had to complete its assigned API operation. A provider that could do nothing was not counted as a successful defence.

In the default arrangement, both unrelated values were accessible. Environment filtering removed the environment value but left the file readable. The whole-job container still exposed the shared lab values placed inside that job.

With provider-scoped isolation, neither research configuration obtained the unrelated environment value or the expected contents of the unassigned file. Both retained access to their assigned credential and completed their own API operation. The dependency chain remained intact. [5]

This was not just a provider-startup demonstration. All four arrangements completed validation, created three resources, produced a subsequent plan with no changes, and destroyed the three resources. [5]

## What the result is useful for

The result gives platform engineers a concrete integration to inspect and reproduce. It separates two things that are easy to conflate: passing a required resource identifier through the dependency graph, and exposing the execution environment in which another provider operates.

It also offers a more precise review question than asking whether an entire job is sandboxed: **which provider configuration receives this capability, at which stage, and what remains visible that its work does not require?**

Provider isolation itself is not a new invention. OpenTofu issue #1138 already proposed containerised or remote provider execution. The contribution here is an implemented configuration- and lifecycle-bound integration, demonstrated while a normal resource dependency chain continues to work. [6]

## What I am not claiming

This is a local integration prototype, not a production-hardened security product. The recorded experiment measures two specific synthetic access checks. It does not establish resistance to all credential-theft techniques, kernel escapes or malicious provider behaviour.

The current strict profile disables external networking and explicitly exposes local Unix services. AWS, Azure and GitHub API compatibility has not been demonstrated. A provider can still misuse authority deliberately assigned to it; isolating two instances of the same malicious package does not make either instance trustworthy.

Those limits leave a useful result: **resource cooperation does not have to mean shared ambient access.** The code, execution requirements and recorded comparison are available for engineers who want to examine that boundary in detail.

[Source code, results and reproduction instructions](https://github.com/osmankaankars/research-notes/tree/main/studies/2026-09-opentofu-provider-isolation).

## References

[1] Oliver Smith, Aikido, [Graphalgo campaign expands to Terraform providers and Go modules](https://www.aikido.dev/blog/graphalgo-terraform-go-modules), 22 September 2026, updated 24 September. [Publisher's German edition](https://de.aikido.dev/blog/graphalgo-terraform-go-modules).

[2] HashiCorp, [How Terraform works with plugins](https://developer.hashicorp.com/terraform/plugin/how-terraform-works).

[3] OpenTofu, [provider lifecycle at the reviewed revision](https://github.com/opentofu/opentofu/blob/b4305e5a5dd2fb79a27897ae30784a181d3a26cb/internal/plugins/provider.go).

[4] HashiCorp, [go-plugin v1.7.0 client interfaces](https://github.com/hashicorp/go-plugin/blob/v1.7.0/client.go).

[5] This study, [recorded results and measurement limits](https://github.com/osmankaankars/research-notes/blob/main/studies/2026-09-opentofu-provider-isolation/RESULTS.md), run 36317604974. The public evidence folder contains selected recorded JSON and labelled CLI excerpts.

[6] OpenTofu, [issue #1138: remotely deploying providers](https://github.com/opentofu/opentofu/issues/1138).
