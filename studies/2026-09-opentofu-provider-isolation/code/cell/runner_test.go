package cell

import (
	"context"
	"io"
	"net"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

func prepared(t *testing.T) (*Runner, string) {
	t.Helper()
	c, bin, _ := testPolicy(t)
	spec, e := c.Resolve(Scope{Source: source, Configuration: address, Phase: Configured}, bin)
	if e != nil {
		t.Fatal(e)
	}
	rpc := filepath.Join(t.TempDir(), "rpc")
	os.Mkdir(rpc, 0700)
	r, e := NewRunner(spec, []string{"TF_PLUGIN_MAGIC_COOKIE=ok", "PLUGIN_UNIX_SOCKET_DIR=" + rpc, "PLUGIN_PROTOCOL_VERSIONS=5,6", "PLUGIN_CLIENT_CERT=public\ncert"}, rpc, "TF_PLUGIN_MAGIC_COOKIE")
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { r.ClosePrepared() })
	return r, rpc
}
func TestOCIPlanHasBoundariesAndNoSecretArguments(t *testing.T) {
	r, _ := prepared(t)
	args := strings.Join(r.Args(), " ")
	for _, want := range []string{"--network=none", "--pid=private", "--userns=keep-id", "--cap-drop=ALL", "--read-only", "--security-opt=no-new-privileges", "--pull=never", "--entrypoint=[]"} {
		if !strings.Contains(args, want) {
			t.Fatal(want, args)
		}
	}
	if strings.Contains(args, "artificial-red-canary") {
		t.Fatal("secret in argv")
	}
	for _, arg := range r.Args() {
		if strings.Contains(arg, ":/proc") || strings.Contains(arg, ":/root") || strings.Contains(arg, ":/home") {
			t.Fatal(arg)
		}
	}
}
func TestBootstrapRelocatedAndHostEnvNotInherited(t *testing.T) {
	t.Setenv("AWS_SECRET_ACCESS_KEY", "host-unrelated")
	r, _ := prepared(t)
	env := r.CommandEnv()
	if hasEnv(env, "HOME=/work") {
		t.Fatal("container HOME overwrote runtime HOME")
	}
	if hasEnv(env, "FIXTURE_TOKEN=artificial-red-canary") {
		t.Fatal("credential exposed to runtime environment")
	}
	b, err := os.ReadFile(filepath.Join(r.stage, "environment"))
	if err != nil || !strings.Contains(string(b), "FIXTURE_TOKEN=artificial-red-canary") {
		t.Fatal("missing isolated env file", err)
	}
	for _, v := range env {
		if strings.Contains(v, "host-unrelated") {
			t.Fatal("inherited host secret")
		}
	}
}
func hasEnv(e []string, v string) bool {
	for _, x := range e {
		if x == v {
			return true
		}
	}
	return false
}
func TestTranslatorOnlyAcceptsOwnedInvocationSocket(t *testing.T) {
	r, rpc := prepared(t)
	socket := filepath.Join(rpc, "plugin.sock")
	l, e := net.Listen("unix", socket)
	if e != nil {
		t.Fatal(e)
	}
	defer l.Close()
	n, a, e := r.PluginToHost("unix", "/rpc/plugin.sock")
	if e != nil || n != "unix" || !strings.HasPrefix(a, "/proc/self/fd/") {
		t.Fatal(n, a, e)
	}
	for _, p := range []string{"/etc/passwd", "/rpc/../other.sock", "/rpc/sub/socket", "relative"} {
		if _, _, e = r.PluginToHost("unix", p); e == nil {
			t.Fatal("unsafe endpoint", p)
		}
	}
	if _, _, e = r.PluginToHost("tcp", "127.0.0.1:80"); e == nil {
		t.Fatal("tcp accepted")
	}
	os.Symlink(socket, filepath.Join(rpc, "alias"))
	if _, _, e = r.PluginToHost("unix", "/rpc/alias"); e == nil {
		t.Fatal("symlink socket accepted")
	}
}
func TestSchemaInvocationIsSecretless(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, e := c.Resolve(Scope{Source: source, Phase: Schema}, bin)
	if e != nil {
		t.Fatal(e)
	}
	rpc := t.TempDir()
	os.Chmod(rpc, 0700)
	r, e := NewRunner(s, []string{"TF_PLUGIN_MAGIC_COOKIE=x"}, rpc, "TF_PLUGIN_MAGIC_COOKIE")
	if e != nil {
		t.Fatal(e)
	}
	defer r.ClosePrepared()
	for _, e := range r.CommandEnv() {
		if strings.HasPrefix(e, "FIXTURE_TOKEN=") {
			t.Fatal("discovery got credentials")
		}
	}
	if strings.Contains(strings.Join(r.Args(), " "), "/credentials/token") {
		t.Fatal("discovery got file")
	}
}
func TestUnavailableRuntimeNeverExecutesProvider(t *testing.T) {
	r, _ := prepared(t)
	r.spec.Runtime = filepath.Join(t.TempDir(), "runtime-does-not-exist")
	e := r.Start(context.Background())
	if e == nil {
		t.Fatal("unexpected live runtime")
	}
	if r.started {
		t.Fatal("marked as started after failure")
	}
}
func TestNoCrossInvocationStageReuse(t *testing.T) {
	a, _ := prepared(t)
	b, _ := prepared(t)
	if a.ID() == b.ID() || a.stage == b.stage {
		t.Fatal("reuse")
	}
}
func TestScopeContextDoesNotMutate(t *testing.T) {
	a := WithScope(context.Background(), Scope{Configuration: "a"})
	b := WithScope(a, Scope{Configuration: "b"})
	sa, _ := FromContext(a)
	sb, _ := FromContext(b)
	if sa.Configuration != "a" || sb.Configuration != "b" {
		t.Fatal("crossing scope")
	}
}

func TestJournalContainsScopeNotSecretAndRejectsSymlink(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, _ := c.Resolve(Scope{Source: source, Configuration: address, Phase: Configured}, bin)
	rpc := t.TempDir()
	os.Chmod(rpc, 0700)
	r, err := NewRunner(s, []string{"MAGIC=fixed", "PLUGIN_UNIX_SOCKET_DIR=" + rpc}, rpc, "MAGIC")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(s.StateDir, "events.jsonl"))
	if err != nil || !strings.Contains(string(raw), "prepared") || strings.Contains(string(raw), "artificial-red-canary") {
		t.Fatal(string(raw), err)
	}
	if err := r.ClosePrepared(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(r.stage); !os.IsNotExist(err) {
		t.Fatal("stage remains")
	}
	target := filepath.Join(s.StateDir, "events.jsonl")
	os.Remove(target)
	other := filepath.Join(t.TempDir(), "untouched")
	os.WriteFile(other, []byte("unchanged"), 0600)
	os.Symlink(other, target)
	if _, err := NewRunner(s, []string{"MAGIC=fixed"}, rpc, "MAGIC"); err == nil {
		t.Fatal("journal symlink followed")
	}
	raw, _ = os.ReadFile(other)
	if string(raw) != "unchanged" {
		t.Fatal("other file changed")
	}
}

func TestImageDefaultsCannotReplaceExecutableOrInjectEnvironment(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, _ := c.Resolve(Scope{Source: source, Phase: Schema}, bin)
	rpc := t.TempDir()
	os.Chmod(rpc, 0700)
	r, err := NewRunner(s, []string{"MAGIC=fixed"}, rpc, "MAGIC")
	if err != nil {
		t.Fatal(err)
	}
	defer r.ClosePrepared()
	args := r.Args()
	for _, flag := range []string{"--entrypoint=[]", "--unsetenv-all", "--image-volume=ignore", "--env-host=false", "--http-proxy=false"} {
		if !slices.Contains(args, flag) {
			t.Fatal("missing override", flag)
		}
	}
	if args[len(args)-1] != "/provider/provider" || args[len(args)-2] != s.Artifact.Image {
		t.Fatal("image CMD was not overridden")
	}
}

func TestClosedLeaseCannotStartAgain(t *testing.T) {
	c, bin, _ := testPolicy(t)
	s, _ := c.Resolve(Scope{Source: source, Phase: Schema}, bin)
	rpc := t.TempDir()
	os.Chmod(rpc, 0700)
	r, err := NewRunner(s, []string{"MAGIC=fixed"}, rpc, "MAGIC")
	if err != nil {
		t.Fatal(err)
	}
	if err = r.ClosePrepared(); err != nil {
		t.Fatal(err)
	}
	if err = r.Start(context.Background()); err == nil || err.Error() != "runner_already_closed" {
		t.Fatal("closed lease was not rejected", err)
	}
}

func TestTransportCannotBeRedirectedAfterValidation(t *testing.T) {
	r, rpc := prepared(t)
	first := filepath.Join(rpc, "first.sock")
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: first, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	l.SetUnlinkOnClose(false)
	defer l.Close()
	delivered := make(chan string, 1)
	go func() {
		c, err := l.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		c.Write([]byte("original"))
		delivered <- "original"
	}()
	_, pinned, err := r.PluginToHost("unix", "/rpc/first.sock")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(pinned, "/proc/self/fd/") {
		t.Fatal("path remains mutable after validation", pinned)
	}
	if err = os.Rename(first, filepath.Join(rpc, "old.sock")); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink("/run/nonexistent-control.sock", first); err != nil {
		t.Fatal(err)
	}
	c, err := net.DialTimeout("unix", pinned, time.Second)
	if err != nil {
		t.Fatal("pinned inode could not be reached", err)
	}
	defer c.Close()
	c.SetReadDeadline(time.Now().Add(time.Second))
	b := make([]byte, 8)
	if _, err = io.ReadFull(c, b); err != nil || string(b) != "original" {
		t.Fatal(string(b), err)
	}
	<-delivered
}

func TestContainerIsPreparedBeforePayloadStartup(t *testing.T) {
	r, _ := prepared(t)
	args := r.Args()
	if len(args) < 2 || args[1] != "create" {
		t.Fatal("payload must not run during container creation", args[:2])
	}
}

func TestPreparedContainerLeaseRequiresConfirmedRemoval(t *testing.T) {
	r, _ := prepared(t)
	// Synthetic lifecycle state only. No OCI runtime is run in this test.
	r.creationAttempted = true
	if err := r.ClosePrepared(); err == nil {
		t.Fatal("discarded lease while runtime ownership unresolved")
	}
	r.containerRemoved = true
	if err := r.ClosePrepared(); err != nil {
		t.Fatal(err)
	}
}
