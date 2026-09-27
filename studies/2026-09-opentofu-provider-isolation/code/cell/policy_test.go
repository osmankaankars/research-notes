package cell

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const source = "registry.opentofu.org/example/cell"
const address = "provider[\"registry.opentofu.org/example/cell\"].red"

func testPolicy(t *testing.T) (*Controller, string, string) {
	t.Helper()
	d := t.TempDir()
	os.Chmod(d, 0700)
	bin := filepath.Join(d, "provider")
	os.WriteFile(bin, []byte("fixture executable, not a real provider"), 0500)
	h := sha256.Sum256([]byte("fixture executable, not a real provider"))
	secret := filepath.Join(d, "secret")
	os.WriteFile(secret, []byte("artificial-red-canary"), 0600)
	p := Policy{Version: 1, Runtime: "/usr/bin/podman", StateDir: filepath.Join(d, "state"),
		Artifacts: map[string]Artifact{source: {SHA256: hex.EncodeToString(h[:]), Image: "localhost/cell@sha256:" + strings.Repeat("a", 64)}},
		Bindings:  []Binding{{Source: source, Configuration: address, EnvironmentFiles: map[string]string{"FIXTURE_TOKEN": secret}, Files: map[string]string{"token": secret}}}}
	raw, _ := json.Marshal(p)
	path := filepath.Join(d, "policy.json")
	os.WriteFile(path, raw, 0600)
	c, e := Load(path)
	if e != nil {
		t.Fatal(e)
	}
	return c, bin, path
}
func TestScopeResolvedBeforeCredentials(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, e := c.Resolve(Scope{Source: source, Configuration: address, Phase: Configured}, bin)
	if e != nil || s.Scope.Configuration != address || len(s.Binding.Files) != 1 {
		t.Fatalf("%+v %v", s, e)
	}
	_, e = c.Resolve(Scope{Source: source, Configuration: address + "-other", Phase: Configured}, bin)
	if e == nil {
		t.Fatal("unknown alias authorized")
	}
}
func TestSchemaHasNoCredentialsAndRequiresEmptyIdentity(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, e := c.Resolve(Scope{Source: source, Phase: Schema}, bin)
	if e != nil || len(s.Binding.Files) != 0 || len(s.Binding.EnvironmentFiles) != 0 || len(s.Binding.Services) != 0 {
		t.Fatal(s, e)
	}
	if _, e = c.Resolve(Scope{Source: source, Configuration: address, Phase: Schema}, bin); e == nil {
		t.Fatal("schema identity accepted")
	}
}
func TestUnknownPhaseFails(t *testing.T) {
	c, bin, _ := testPolicy(t)
	for _, p := range []Phase{"", "provider-chosen", "reattach"} {
		if _, e := c.Resolve(Scope{Source: source, Configuration: address, Phase: p}, bin); e == nil {
			t.Fatal(p)
		}
	}
}
func TestUnknownFieldsAndDuplicateKeysRejected(t *testing.T) {
	_, _, p := testPolicy(t)
	raw, _ := os.ReadFile(p)
	for _, bad := range []string{strings.Replace(string(raw), `"version":1`, `"version":1,"version":1`, 1), strings.Replace(string(raw), `"version":1`, `"version":1,"unrestricted":true`, 1)} {
		os.WriteFile(p, []byte(bad), 0600)
		if _, e := Load(p); e == nil {
			t.Fatal("accepted ambiguous policy")
		}
	}
}
func TestPolicyWritableByOthersRejected(t *testing.T) {
	_, _, p := testPolicy(t)
	os.Chmod(p, 0666)
	if _, e := Load(p); e == nil {
		t.Fatal("insecure policy accepted")
	}
}
func TestDuplicateBindingRejected(t *testing.T) {
	_, _, p := testPolicy(t)
	raw, _ := os.ReadFile(p)
	var v Policy
	json.Unmarshal(raw, &v)
	v.Bindings = append(v.Bindings, v.Bindings[0])
	raw, _ = json.Marshal(v)
	os.WriteFile(p, raw, 0600)
	if _, e := Load(p); e == nil {
		t.Fatal("duplicate")
	}
}
func TestDigestVerificationUsesCopiedBytes(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, e := c.Resolve(Scope{Source: source, Configuration: address, Phase: Configured}, bin)
	if e != nil {
		t.Fatal(e)
	}
	dst := filepath.Join(t.TempDir(), "provider")
	if e = CopyVerified(s.Executable, dst, s.Artifact.SHA256); e != nil {
		t.Fatal(e)
	}
	os.Chmod(bin, 0600)
	os.WriteFile(bin, []byte("changed after policy resolution"), 0500)
	if e = CopyVerified(s.Executable, filepath.Join(t.TempDir(), "provider"), s.Artifact.SHA256); e == nil {
		t.Fatal("changed executable accepted")
	}
}
func TestSymlinkExecutableRejected(t *testing.T) {
	c, bin, _ := testPolicy(t)
	link := filepath.Join(t.TempDir(), "link")
	os.Symlink(bin, link)
	s, e := c.Resolve(Scope{Source: source, Configuration: address, Phase: Configured}, link)
	if e != nil {
		t.Fatal(e)
	}
	if e = CopyVerified(s.Executable, filepath.Join(t.TempDir(), "out"), s.Artifact.SHA256); e == nil {
		t.Fatal("symlink followed")
	}
}
func TestSecretPathCannotEscapeMount(t *testing.T) {
	_, _, p := testPolicy(t)
	raw, _ := os.ReadFile(p)
	var v Policy
	json.Unmarshal(raw, &v)
	v.Bindings[0].Files = map[string]string{"../escape": "/tmp/a"}
	raw, _ = json.Marshal(v)
	os.WriteFile(p, raw, 0600)
	if _, e := Load(p); e == nil {
		t.Fatal("mount path escape")
	}
}
func TestBootstrapStrictAllowlist(t *testing.T) {
	v, e := FilterBootstrap([]string{"TF_PLUGIN_MAGIC_COOKIE=ok", "PLUGIN_PROTOCOL_VERSIONS=5,6", "PLUGIN_CLIENT_CERT=public-cert"}, "TF_PLUGIN_MAGIC_COOKIE")
	if e != nil || len(v) != 3 {
		t.Fatal(v, e)
	}
	for _, bad := range []string{"AWS_SECRET_ACCESS_KEY=not-for-provider", "PLUGIN_UNKNOWN=1", "LD_PRELOAD=/tmp/x", "TF_PLUGIN_MAGIC_COOKIE=another"} {
		a := []string{"TF_PLUGIN_MAGIC_COOKIE=ok", bad}
		if _, e := FilterBootstrap(a, "TF_PLUGIN_MAGIC_COOKIE"); e == nil {
			t.Fatal("unexpected bootstrap accepted", bad)
		}
	}
}

func TestTransportRootPrivateAndNoExistingSymlink(t *testing.T) {
	c, _, _ := testPolicy(t)
	p, err := c.TransportRoot()
	if err != nil {
		t.Fatal(err)
	}
	if fi, err := os.Stat(p); err != nil || fi.Mode().Perm() != 0700 {
		t.Fatal("private transport root not created")
	}
	if err := os.Remove(p); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(t.TempDir(), p); err != nil {
		t.Fatal(err)
	}
	if _, err := c.TransportRoot(); err == nil {
		t.Fatal("symlink transport accepted")
	}
}
