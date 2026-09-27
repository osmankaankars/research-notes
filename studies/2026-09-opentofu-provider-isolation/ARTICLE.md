# One Infrastructure Run Is Not One Trust Boundary

*Keeping OpenTofu's dependency graph without giving every provider the same access.*

**Osman Kaan Kars | 27 September 2026**

An infrastructure workflow may need several providers to cooperate. Each provider still needs a defined set of credentials, files and environment variables for its own work.

I built an OpenTofu prototype to isolate those permissions by provider configuration. I wanted to keep the workflow running while removing access that individual provider processes did not need.

## Why I chose this problem

Aikido's report on 22 September, updated on 24 September, prompted this work. It described malware linked to Graphalgo being distributed through Terraform providers and Go modules. The discovery belongs to Aikido. I did not run those malicious packages. [1]

A provider runs executable code. Terraform's documentation describes providers as separate processes communicating with the core over RPC. Running in a separate process does not, by itself, restrict which credentials or files a provider can read. [2]

I wanted to see whether OpenTofu could restrict each provider configuration's execution environment without breaking the dependencies between resources. Detecting malicious packages was outside the scope of this work.

## The boundary belongs to the provider configuration

Putting the whole job in a container can protect what is outside that job. It does not automatically separate the providers inside it. Similarly, filtering environment variables does not remove access to files that remain visible to the process.

I gave each provider configuration its own execution environment. Two aliases of the same provider can receive different credential files and service connections, even though they execute the same provider binary.

The OpenTofu integration carries the resolved configuration identity and execution phase to the launcher. A trusted policy binds that identity to the provider executable and the capabilities it receives. The launcher uses rootless Podman. If isolation setup fails, it stops rather than running the provider unrestricted on the host.

The reviewed OpenTofu code starts the provider executable even when requesting its schema. Isolation therefore has to begin before resource creation. The integration handles schema discovery, configuration validation and configured execution separately. [3]

The integration keeps the existing provider RPC protocol and uses the runner and environment controls already available in go-plugin. It does not replace the infrastructure engine. [4]

## What I tested

I ran the same small infrastructure definition in four ways: ordinary OpenTofu, environment filtering alone, the whole job inside one container, and separate environments for each provider configuration.

The workflow used a copy of the published `hashicorp/random` provider built from source, together with two configurations of a controlled research provider. The first research resource consumed the random provider's output. The second consumed the first resource's identifier. Each research configuration had its own artificial credential and local service reached through a Unix socket. [5]

The controlled provider checked a named unrelated file and an unrelated environment variable. It also had to complete its assigned API operation. A provider that could do nothing was not counted as a successful defence.

In the default arrangement, both unrelated values were accessible. Environment filtering removed the environment value but left the file readable. Putting the whole job in one container still left the shared lab values accessible inside it.

When the provider configurations ran in separate environments, neither obtained the unrelated environment value or the expected contents of the unassigned file. Both retained access to their assigned credential and completed their own API operation. The dependency chain remained intact. [5]

I checked the resource lifecycle as well as provider startup. All four arrangements completed validation, created three resources, produced a subsequent plan with no changes, and destroyed the three resources. [5]

## What the result is useful for

Platform engineers can inspect the integration and reproduce the comparison. In this workflow, a provider could receive the resource identifier it needed through the dependency graph without sharing another provider's execution environment.

When reviewing an infrastructure job, I would check which provider configuration receives each permission, when it receives it, and whether it can still see files or credentials unrelated to its work.

OpenTofu issue #1138 already proposed running providers in containers or remotely. My contribution is an implementation that assigns access according to each provider's configuration and execution phase. In the recorded lab, it preserved the resource dependency chain while removing the two unrelated accesses being measured. [6] [5]

## Scope and limits

This is a local integration prototype. It has not been hardened for production use. The recorded experiment measures two specific synthetic access checks. It does not establish resistance to all techniques for stealing credentials, kernel escapes or malicious provider behaviour.

The current strict profile disables external networking and explicitly exposes local Unix services. AWS, Azure and GitHub API compatibility has not been demonstrated. A provider can still misuse authority deliberately assigned to it. Isolating two instances of the same malicious package does not make either instance trustworthy.

The demonstrated result is narrower: this workflow retained its resource dependencies after the two unrelated accesses were removed. The code, execution requirements and recorded comparison are available for engineers who want to inspect the implementation.

[Source code, results and reproduction instructions](https://github.com/osmankaankars/research-notes/tree/main/studies/2026-09-opentofu-provider-isolation).

## References

[1] Oliver Smith, Aikido, [Graphalgo campaign expands to Terraform providers and Go modules](https://www.aikido.dev/blog/graphalgo-terraform-go-modules), 22 September 2026, updated 24 September. [Publisher's German edition](https://de.aikido.dev/blog/graphalgo-terraform-go-modules).

[2] HashiCorp, [How Terraform works with plugins](https://developer.hashicorp.com/terraform/plugin/how-terraform-works).

[3] OpenTofu, [provider lifecycle at the reviewed revision](https://github.com/opentofu/opentofu/blob/b4305e5a5dd2fb79a27897ae30784a181d3a26cb/internal/plugins/provider.go).

[4] HashiCorp, [go-plugin v1.7.0 client interfaces](https://github.com/hashicorp/go-plugin/blob/v1.7.0/client.go).

[5] This study, [recorded results and measurement limits](https://github.com/osmankaankars/research-notes/blob/main/studies/2026-09-opentofu-provider-isolation/RESULTS.md), run 36317604974. The public evidence folder contains selected recorded JSON and labelled CLI excerpts.

[6] OpenTofu, [issue #1138: remotely deploying providers](https://github.com/opentofu/opentofu/issues/1138).
