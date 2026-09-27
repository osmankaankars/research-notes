// Package cell binds a trusted provider identity to a fail-closed OCI launch.
// It is not an evaluator, a malware detector, or an alternative Terraform core.
package cell

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type Phase string

const (
	Schema     Phase = "schema"
	Validation Phase = "validation"
	Configured Phase = "configured"
)

type Scope struct {
	Source        string `json:"source"`
	Configuration string `json:"configuration"`
	InstanceKey   string `json:"instance_key"`
	Phase         Phase  `json:"phase"`
}
type scopeKey struct{}

func WithScope(ctx context.Context, s Scope) context.Context {
	return context.WithValue(ctx, scopeKey{}, s)
}
func FromContext(ctx context.Context) (Scope, bool) {
	s, ok := ctx.Value(scopeKey{}).(Scope)
	return s, ok
}
func Enabled() bool { _, ok := os.LookupEnv("TOFU_PROVIDER_ISOLATION_POLICY"); return ok }

type Artifact struct {
	SHA256 string `json:"sha256"`
	Image  string `json:"image"`
}
type Binding struct {
	Source           string            `json:"source"`
	Configuration    string            `json:"configuration"`
	InstanceKey      string            `json:"instance_key"`
	EnvironmentFiles map[string]string `json:"environment_files,omitempty"`
	Files            map[string]string `json:"files,omitempty"`
	// Services is a map of local names to administrator-owned Unix socket paths.
	// No arbitrary TCP destination, host network or container-engine socket is allowed.
	Services map[string]string `json:"services,omitempty"`
}
type Policy struct {
	Version   int                 `json:"version"`
	Runtime   string              `json:"runtime"`
	StateDir  string              `json:"state_dir"`
	Artifacts map[string]Artifact `json:"artifacts"`
	Bindings  []Binding           `json:"bindings"`
}
type Controller struct {
	policy   Policy
	bindings map[string]Binding
}
type LaunchSpec struct {
	Scope      Scope
	Artifact   Artifact
	Binding    Binding
	Executable string
	Runtime    string
	StateDir   string
}

var digestRE = regexp.MustCompile(`^[0-9a-f]{64}$`)
var imageRE = regexp.MustCompile(`^(sha256:[0-9a-f]{64}|[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[0-9a-f]{64})$`)
var nameRE = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]{0,63}$`)

func bindingKey(source, config, key string) string {
	v, _ := json.Marshal([3]string{source, config, key})
	return string(v)
}

// Load takes a single immutable in-memory snapshot. Provider processes never choose
// the policy or receive the policy file. It must be owned by the launching user.
func Load(path string) (*Controller, error) {
	if !filepath.IsAbs(path) {
		return nil, errors.New("policy_path_must_be_absolute")
	}
	f, e := openRegular(path, true)
	if e != nil {
		return nil, fmt.Errorf("policy_untrusted: %w", e)
	}
	defer f.Close()
	raw, e := io.ReadAll(io.LimitReader(f, 1<<20+1))
	if e != nil {
		return nil, e
	}
	if len(raw) > 1<<20 {
		return nil, errors.New("policy_too_large")
	}
	if e = uniqueJSON(raw); e != nil {
		return nil, e
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	var p Policy
	if e = d.Decode(&p); e != nil {
		return nil, errors.New("invalid_policy_schema")
	}
	if e = p.validate(); e != nil {
		return nil, e
	}
	c := &Controller{policy: p, bindings: map[string]Binding{}}
	for _, b := range p.Bindings {
		k := bindingKey(b.Source, b.Configuration, b.InstanceKey)
		if _, ok := c.bindings[k]; ok {
			return nil, errors.New("duplicate_binding")
		}
		c.bindings[k] = b
	}
	return c, nil
}
func (p Policy) validate() error {
	if p.Version != 1 {
		return errors.New("unsupported_policy_version")
	}
	if !filepath.IsAbs(p.Runtime) || filepath.Clean(p.Runtime) != p.Runtime {
		return errors.New("runtime_path_must_be_absolute")
	}
	if !filepath.IsAbs(p.StateDir) || filepath.Clean(p.StateDir) != p.StateDir {
		return errors.New("state_directory_must_be_absolute")
	}
	if len(p.Artifacts) == 0 || len(p.Artifacts) > 64 {
		return errors.New("invalid_artifact_count")
	}
	for source, a := range p.Artifacts {
		if source == "" || strings.ContainsAny(source, "\x00\n\r") || !digestRE.MatchString(a.SHA256) || !imageRE.MatchString(a.Image) {
			return errors.New("artifact_requires_source_digest_and_digest_pinned_image")
		}
	}
	if len(p.Bindings) > 1024 {
		return errors.New("too_many_bindings")
	}
	for _, b := range p.Bindings {
		if _, ok := p.Artifacts[b.Source]; !ok || b.Configuration == "" || strings.ContainsAny(b.Configuration+b.InstanceKey, "\x00\n\r") {
			return errors.New("invalid_binding_identity")
		}
		for kind, m := range map[string]map[string]string{"env": b.EnvironmentFiles, "file": b.Files, "service": b.Services} {
			if len(m) > 32 {
				return errors.New("too_many_capabilities")
			}
			for k, v := range m {
				if !nameRE.MatchString(k) || !filepath.IsAbs(v) || filepath.Clean(v) != v || strings.ContainsAny(v, "\x00\n\r,") {
					return errors.New("invalid_capability_name_or_path")
				}
				if kind == "env" && (strings.HasPrefix(k, "CELL_") || strings.HasPrefix(k, "PLUGIN_") || strings.HasPrefix(k, "TF_PLUGIN_") || strings.HasPrefix(k, "LD_") || k == "PATH" || k == "HOME" || k == "TMPDIR" || k == "CONTAINER_HOST" || k == "DOCKER_HOST") {
					return errors.New("reserved_environment_name")
				}
				if kind == "service" && (strings.Contains(strings.ToLower(v), "docker.sock") || strings.Contains(strings.ToLower(v), "podman.sock")) {
					return errors.New("container_control_socket_forbidden")
				}
			}
		}
	}
	return nil
}
func cloneMap(m map[string]string) map[string]string {
	r := make(map[string]string, len(m))
	for k, v := range m {
		r[k] = v
	}
	return r
}
func (c *Controller) Resolve(s Scope, executable string) (LaunchSpec, error) {
	a, ok := c.policy.Artifacts[s.Source]
	if !ok {
		return LaunchSpec{}, errors.New("provider_source_not_allowed")
	}
	if !filepath.IsAbs(executable) {
		return LaunchSpec{}, errors.New("provider_path_not_absolute")
	}
	b := Binding{Source: s.Source}
	switch s.Phase {
	case Schema:
		if s.Configuration != "" || s.InstanceKey != "" {
			return LaunchSpec{}, errors.New("schema_cannot_carry_instance_authority")
		}
	case Validation, Configured:
		var found bool
		b, found = c.bindings[bindingKey(s.Source, s.Configuration, s.InstanceKey)]
		if !found {
			return LaunchSpec{}, errors.New("provider_instance_not_bound")
		}
	default:
		return LaunchSpec{}, errors.New("unknown_launch_phase")
	}
	b.Files = cloneMap(b.Files)
	b.Services = cloneMap(b.Services)
	b.EnvironmentFiles = cloneMap(b.EnvironmentFiles)
	return LaunchSpec{Scope: s, Artifact: a, Binding: b, Executable: executable, Runtime: c.policy.Runtime, StateDir: c.policy.StateDir}, nil
}

// FilterBootstrap rejects rather than silently forwards unrecognized environment.
// The certificate is PUBLIC bootstrap material; the client private key stays in core.
func FilterBootstrap(env []string, magicCookieKey string) (map[string]string, error) {
	allowed := map[string]bool{magicCookieKey: true, "PLUGIN_MIN_PORT": true, "PLUGIN_MAX_PORT": true, "PLUGIN_PROTOCOL_VERSIONS": true, "PLUGIN_CLIENT_CERT": true, "PLUGIN_UNIX_SOCKET_DIR": true, "PLUGIN_UNIX_SOCKET_GROUP": true, "PLUGIN_MULTIPLEX_GRPC": true}
	out := map[string]string{}
	for _, entry := range env {
		k, v, ok := strings.Cut(entry, "=")
		if !ok || !allowed[k] || k == "" || strings.ContainsRune(v, 0) {
			return nil, errors.New("unexpected_plugin_bootstrap_variable")
		}
		if _, ok := out[k]; ok {
			return nil, errors.New("duplicate_plugin_bootstrap_variable")
		}
		out[k] = v
	}
	if out[magicCookieKey] == "" {
		return nil, errors.New("missing_plugin_magic_cookie")
	}
	return out, nil
}

// encoding/json permits duplicate object members. An authority policy must not.
func uniqueJSON(raw []byte) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	var walk func(int) error
	walk = func(depth int) error {
		if depth > 24 {
			return errors.New("policy_nesting_too_deep")
		}
		tok, e := d.Token()
		if e != nil {
			return errors.New("invalid_policy_json")
		}
		if delim, ok := tok.(json.Delim); ok {
			switch delim {
			case '{':
				seen := map[string]bool{}
				for d.More() {
					key, e := d.Token()
					if e != nil {
						return e
					}
					k, ok := key.(string)
					if !ok || seen[k] {
						return errors.New("duplicate_policy_key")
					}
					seen[k] = true
					if e = walk(depth + 1); e != nil {
						return e
					}
				}
				_, e = d.Token()
				return e
			case '[':
				for d.More() {
					if e = walk(depth + 1); e != nil {
						return e
					}
				}
				_, e = d.Token()
				return e
			default:
				return errors.New("invalid_policy_json")
			}
		}
		return nil
	}
	if e := walk(0); e != nil {
		return e
	}
	if _, e := d.Token(); e != io.EOF {
		return errors.New("trailing_policy_json")
	}
	return nil
}
