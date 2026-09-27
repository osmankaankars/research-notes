# Sources and prior work

External sources explain architecture and motivation. They are not measurements
from this experiment.

1. Oliver Smith, Aikido: Graphalgo campaign expands to Terraform providers and Go
   modules. Published 22 September 2026; updated 24 September.
   https://www.aikido.dev/blog/graphalgo-terraform-go-modules
   Publisher's accessible German edition:
   https://de.aikido.dev/blog/graphalgo-terraform-go-modules
2. HashiCorp, How Terraform works with plugins:
   https://developer.hashicorp.com/terraform/plugin/how-terraform-works
3. OpenTofu reviewed source:
   https://github.com/opentofu/opentofu/tree/b4305e5a5dd2fb79a27897ae30784a181d3a26cb
   Relevant files: internal/plugins/provider.go,
   internal/command/meta_providers.go, internal/tofu/node_provider.go,
   internal/providers/provider.go and internal/command/plugins.go.
4. HashiCorp go-plugin v1.7.0 runner, bootstrap and transport interfaces:
   https://github.com/hashicorp/go-plugin/blob/v1.7.0/client.go
   https://github.com/hashicorp/go-plugin/blob/v1.7.0/runner/runner.go
5. Prior OpenTofu provider deployment/isolation proposal, issue #1138:
   https://github.com/opentofu/opentofu/issues/1138
6. Random provider v3.7.2 source:
   https://github.com/hashicorp/terraform-provider-random/tree/bc2ddb552b4676d16997987a9bf2875c7b98d342
7. Terraform Plugin SDK v2.38.1:
   https://github.com/hashicorp/terraform-plugin-sdk/tree/cada9f39b0a039e7f6b07ebe21466f20b48bba7d
8. Podman runtime semantics:
   https://docs.podman.io/en/latest/markdown/podman-run.1.html
   https://docs.podman.io/en/latest/markdown/podman-container-exists.1.html

Container isolation, provider RPC, short-lived credentials and custom plugin
runners are existing techniques. This study claims an implemented integration
and the limited result in RESULTS.md, not their invention or a new vulnerability.
