//go:build linux

package cell

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Runner has the method set required by go-plugin v1.7.0 runner.Runner.
// No third-party process starts in the constructor. Podman is the trusted OCI
// runtime, never a daemon socket mounted into the provider.
type Runner struct {
	spec              LaunchSpec
	stage, rpc, id    string
	args, env         []string
	mu                sync.Mutex
	cmd               *exec.Cmd
	stdout, stderr    *os.File
	stdoutW, stderrW  *os.File
	started           bool
	stopping          bool
	creationAttempted bool
	containerRemoved  bool
	closed            bool
	done              chan struct{}
	waitErr           error
	cleanupOnce       sync.Once
	cleanupErr        error
	pinnedSockets     []*os.File
}

func ownedDirectory(path string) error {
	s, e := os.Lstat(path)
	if e != nil {
		return errors.New("private_directory_missing")
	}
	st, ok := s.Sys().(*syscall.Stat_t)
	if !s.IsDir() || s.Mode()&os.ModeSymlink != 0 || s.Mode().Perm()&0077 != 0 || !ok || int(st.Uid) != os.Geteuid() {
		return errors.New("private_owned_directory_required")
	}
	return nil
}
func safeMountPath(p string) bool {
	return filepath.IsAbs(p) && filepath.Clean(p) == p && !strings.ContainsAny(p, "\x00\n\r,: ")
}
func sortedKeys(m map[string]string) []string {
	k := make([]string, 0, len(m))
	for key := range m {
		k = append(k, key)
	}
	sort.Strings(k)
	return k
}
func runtimeEnv() []string {
	// Deliberately excludes engine remote connections, proxy credentials and cloud
	// credentials. Only the local rootless runtime's OS environment is inherited.
	e := []string{"PATH=/usr/bin:/bin", "LANG=C.UTF-8"}
	for _, k := range []string{"HOME", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"} {
		if v := os.Getenv(k); v != "" {
			e = append(e, k+"="+v)
		}
	}
	return e
}
func NewRunner(s LaunchSpec, bootstrap []string, socketDir, magicKey string) (result *Runner, err error) {
	if s.Scope.Phase != Schema && s.Scope.Phase != Validation && s.Scope.Phase != Configured {
		return nil, errors.New("unknown_launch_phase")
	}
	if !safeMountPath(s.StateDir) || !safeMountPath(socketDir) {
		return nil, errors.New("unsupported_mount_path")
	}
	if err = ownedDirectory(socketDir); err != nil {
		return nil, err
	}
	if err = os.MkdirAll(s.StateDir, 0700); err != nil {
		return nil, err
	}
	if err = ownedDirectory(s.StateDir); err != nil {
		return nil, err
	}
	env, e := FilterBootstrap(bootstrap, magicKey)
	if e != nil {
		return nil, e
	}
	env["PLUGIN_UNIX_SOCKET_DIR"] = "/rpc"
	delete(env, "PLUGIN_UNIX_SOCKET_GROUP") // Keep host UID mapping, not a shared group.
	env["HOME"] = "/work"
	env["TMPDIR"] = "/tmp"
	credentials := map[string]string{}
	var nonce [16]byte
	if _, err = rand.Read(nonce[:]); err != nil {
		return nil, err
	}
	r := &Runner{spec: s, rpc: socketDir, id: "tofu-cell-" + hex.EncodeToString(nonce[:]), done: make(chan struct{})}
	env["CELL_INVOCATION_ID"] = r.id
	env["CELL_LAUNCH_PHASE"] = string(s.Scope.Phase)
	env["CELL_CONFIGURATION"] = s.Scope.Configuration
	r.stage, err = os.MkdirTemp(s.StateDir, "invocation-")
	if err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			_ = r.ClosePrepared()
		}
	}()
	binary := filepath.Join(r.stage, "provider")
	if err = CopyVerified(s.Executable, binary, s.Artifact.SHA256); err != nil {
		return nil, err
	}
	args := []string{"--remote=false", "create", "--rm", "--name", r.id, "--pull=never", "--network=none", "--pid=private", "--ipc=private", "--uts=private", "--userns=keep-id", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=128", "--timeout=300", "--cgroupns=private", "--memory=512m", "--cpus=1", "--log-driver=none", "--workdir=/work", "--entrypoint=[]", "--unsetenv-all", "--env-host=false", "--http-proxy=false", "--image-volume=ignore", "--systemd=false", "--no-hosts", "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777", "--tmpfs=/work:rw,noexec,nosuid,nodev,size=16m,mode=1777", "--volume", binary + ":/provider/provider:ro,nosuid,nodev", "--volume", socketDir + ":/rpc:rw,nosuid,nodev,noexec"}
	if s.Scope.Phase == Schema && (len(s.Binding.Files) > 0 || len(s.Binding.EnvironmentFiles) > 0 || len(s.Binding.Services) > 0) {
		return nil, errors.New("discovery_cannot_receive_capabilities")
	}
	for _, k := range sortedKeys(s.Binding.EnvironmentFiles) {
		b, e := readSecret(s.Binding.EnvironmentFiles[k])
		if e != nil {
			return nil, e
		}
		if strings.ContainsAny(string(b), "\x00\r\n") {
			return nil, errors.New("environment_credential_must_be_single_line_use_file_for_multiline")
		}
		if _, exists := env[k]; exists {
			return nil, errors.New("credential_overwrites_bootstrap")
		}
		credentials[k] = string(b)
	}
	for _, k := range sortedKeys(s.Binding.Files) {
		b, e := readSecret(s.Binding.Files[k])
		if e != nil {
			return nil, e
		}
		dst := filepath.Join(r.stage, "credential-"+k)
		if err = os.WriteFile(dst, b, 0400); err != nil {
			return nil, err
		}
		args = append(args, "--volume", dst+":/credentials/"+k+":ro,nosuid,nodev,noexec")
	}
	for _, k := range sortedKeys(s.Binding.Services) {
		p := s.Binding.Services[k]
		if !safeMountPath(p) {
			return nil, errors.New("unsupported_service_path")
		}
		st, e := os.Lstat(p)
		if e != nil || st.Mode()&os.ModeSocket == 0 || st.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("service_must_be_unix_socket")
		}
		sys, ok := st.Sys().(*syscall.Stat_t)
		if !ok || int(sys.Uid) != os.Geteuid() {
			return nil, errors.New("service_owner_mismatch")
		}
		args = append(args, "--volume", p+":/services/"+k+".sock:ro,nosuid,nodev,noexec")
	}
	r.env = runtimeEnv()
	// Bootstrap contains no account credentials. AutoMTLS sends only the public
	// client certificate; its private key never enters this process or argv.
	for _, k := range sortedKeys(env) {
		args = append(args, "--env", k+"="+env[k])
	}
	if len(credentials) > 0 {
		var values strings.Builder
		for _, k := range sortedKeys(credentials) {
			values.WriteString(k + "=" + credentials[k] + "\n")
		}
		p := filepath.Join(r.stage, "environment")
		if err = os.WriteFile(p, []byte(values.String()), 0600); err != nil {
			return nil, err
		}
		args = append(args, "--env-file", p)
	}
	args = append(args, s.Artifact.Image, "/provider/provider")
	r.args = args
	r.stdout, r.stdoutW, err = os.Pipe()
	if err != nil {
		return nil, err
	}
	r.stderr, r.stderrW, err = os.Pipe()
	if err != nil {
		return nil, err
	}
	if err = r.journal("prepared"); err != nil {
		return nil, err
	}
	return r, nil
}

// Args does not include credential values. CommandEnv is for the trusted integration
// and tests only; it must never be logged or included in exported evidence.
func (r *Runner) Args() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.args...)
}
func (r *Runner) CommandEnv() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.env...)
}
func (r *Runner) Name() string          { return "isolated-provider:" + r.spec.Scope.Source }
func (r *Runner) ID() string            { return r.id }
func (r *Runner) Stdout() io.ReadCloser { return r.stdout }
func (r *Runner) Stderr() io.ReadCloser { return r.stderr }
func (r *Runner) Diagnose(context.Context) string {
	return "Provider isolation failed; inspect trusted runtime locally. No unrestricted fallback was attempted."
}
func (r *Runner) Start(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed || r.stopping {
		return errors.New("runner_already_closed")
	}
	if r.started {
		return errors.New("runner_already_started")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if os.Geteuid() == 0 {
		return errors.New("rootless_runtime_required")
	}
	checkCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	check := exec.CommandContext(checkCtx, r.spec.Runtime, "--remote=false", "info", "--format={{.Host.Security.Rootless}}:{{.Host.CgroupsVersion}}")
	check.Env = runtimeEnv()
	output, e := check.Output()
	if e != nil || strings.TrimSpace(string(output)) != "true:v2" {
		return errors.New("local_rootless_podman_unavailable")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	// Start's context controls startup only, per go-plugin's Runner contract.
	// Wait and Kill are responsible for the lifetime after launch.
	if e = r.journal("launch_requested"); e != nil {
		return e
	}
	// Create separately so cancellation cannot remove a not-yet-created name
	// and then race with a later provider start. The container exists before its
	// payload is permitted to run. Failed creation is still owned for cleanup.
	r.creationAttempted = true
	create := exec.CommandContext(ctx, r.spec.Runtime, r.args...)
	create.Env = r.env
	cid, createErr := create.Output()
	if createErr != nil {
		return errors.New("isolated_container_creation_failed")
	}
	parsed, parseErr := hex.DecodeString(strings.TrimSpace(string(cid)))
	if parseErr != nil || len(parsed) != 32 {
		return errors.New("invalid_runtime_container_id")
	}
	if err := r.journal("container_created"); err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	r.cmd = exec.Command(r.spec.Runtime, "--remote=false", "start", "--attach", r.id)
	r.cmd.Env = r.env
	r.cmd.Stdout = r.stdoutW
	r.cmd.Stderr = r.stderrW
	if e = r.cmd.Start(); e != nil {
		return errors.New("isolated_provider_start_failed")
	}
	r.started = true
	go func() {
		err := r.cmd.Wait()
		r.stdoutW.Close()
		r.stderrW.Close()
		r.mu.Lock()
		r.waitErr = errors.Join(err, r.journal("runtime_exited"))
		r.mu.Unlock()
		close(r.done)
	}()
	return nil
}
func (r *Runner) Wait(ctx context.Context) error {
	r.mu.Lock()
	started := r.started
	r.mu.Unlock()
	if !started {
		return errors.New("runner_not_started")
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-r.done:
		r.mu.Lock()
		err := r.waitErr
		r.mu.Unlock()
		return err
	}
}
func (r *Runner) Kill(ctx context.Context) error {
	r.cleanupOnce.Do(func() {
		r.mu.Lock()
		r.stopping = true
		attempted, started, cmd := r.creationAttempted, r.started, r.cmd
		r.mu.Unlock()
		if attempted {
			cctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
			defer cancel()
			rm := exec.CommandContext(cctx, r.spec.Runtime, "--remote=false", "rm", "--force", "--ignore", "--time=0", r.id)
			rm.Env = runtimeEnv()
			if e := rm.Run(); e != nil {
				r.cleanupErr = errors.New("container_cleanup_not_confirmed")
				return
			}
			if started {
				select {
				case <-r.done:
				case <-time.After(3 * time.Second):
					if cmd != nil && cmd.Process != nil {
						_ = cmd.Process.Kill()
					}
					select {
					case <-r.done:
					case <-time.After(3 * time.Second):
						r.cleanupErr = errors.New("runtime_process_cleanup_not_confirmed")
						return
					}
				}
			}
			probe := exec.CommandContext(cctx, r.spec.Runtime, "--remote=false", "container", "exists", r.id)
			probe.Env = runtimeEnv()
			probeErr := probe.Run()
			var exitErr *exec.ExitError
			if !errors.As(probeErr, &exitErr) || exitErr.ExitCode() != 1 {
				r.cleanupErr = errors.New("container_absence_not_confirmed")
				return
			}
			r.mu.Lock()
			r.containerRemoved = true
			r.mu.Unlock()
		}
		r.cleanupErr = r.ClosePrepared()
	})
	return r.cleanupErr
}
func (r *Runner) ClosePrepared() error {
	r.mu.Lock()
	if r.closed {
		r.mu.Unlock()
		return nil
	}
	if r.creationAttempted && !r.containerRemoved {
		r.mu.Unlock()
		return errors.New("cannot_remove_unresolved_container_lease")
	}
	if r.started {
		select {
		case <-r.done:
		default:
			r.mu.Unlock()
			return errors.New("cannot_remove_live_lease")
		}
	}
	r.closed = true
	pinned := r.pinnedSockets
	r.pinnedSockets = nil
	for i := range r.env {
		r.env[i] = ""
	}
	r.env = nil
	r.mu.Unlock()
	for _, f := range pinned {
		_ = f.Close()
	}
	for _, f := range []*os.File{r.stdout, r.stdoutW, r.stderr, r.stderrW} {
		if f != nil {
			_ = f.Close()
		}
	}
	if r.stage != "" {
		err := os.RemoveAll(r.stage)
		event := "lease_removed"
		if err != nil {
			event = "lease_cleanup_failed"
		}
		return errors.Join(err, r.journal(event))
	}
	return nil
}

func (r *Runner) PluginToHost(network, address string) (string, string, error) {
	if network != "unix" || filepath.Dir(address) != "/rpc" || filepath.Clean(address) != address {
		return "", "", errors.New("plugin_endpoint_outside_private_transport")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed || len(r.pinnedSockets) >= 32 {
		return "", "", errors.New("private_transport_closed_or_limit_reached")
	}
	host := filepath.Join(r.rpc, filepath.Base(address))
	// Lstat followed by Dial has a race: an untrusted process can replace the
	// checked socket with a symlink before the host connects. Pin the inode using
	// Linux O_PATH and connect through our own descriptor, not the mutable name.
	const oPath = 0x200000 // Linux UAPI O_PATH, unavailable in older syscall exports.
	fd, err := syscall.Open(host, oPath|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return "", "", errors.New("private_socket_required")
	}
	f := os.NewFile(uintptr(fd), host)
	st, err := f.Stat()
	if err != nil || st.Mode()&os.ModeSocket == 0 {
		f.Close()
		return "", "", errors.New("private_socket_required")
	}
	owner, ok := st.Sys().(*syscall.Stat_t)
	if !ok || int(owner.Uid) != os.Geteuid() {
		f.Close()
		return "", "", errors.New("private_socket_owner_mismatch")
	}
	r.pinnedSockets = append(r.pinnedSockets, f)
	return "unix", fmt.Sprintf("/proc/self/fd/%d", fd), nil
}

func (r *Runner) HostToPlugin(network, address string) (string, string, error) {
	if network != "unix" || filepath.Dir(address) != r.rpc || filepath.Clean(address) != address {
		return "", "", errors.New("host_endpoint_outside_private_transport")
	}
	return "unix", filepath.Join("/rpc", filepath.Base(address)), nil
}

// VerifyMethodSet keeps the third-party structural interface visible without
// pulling external modules into this standalone component test suite.
var _ interface {
	Start(context.Context) error
	Wait(context.Context) error
	Kill(context.Context) error
	Stdout() io.ReadCloser
	Stderr() io.ReadCloser
	Name() string
	ID() string
	Diagnose(context.Context) string
	PluginToHost(string, string) (string, string, error)
	HostToPlugin(string, string) (string, string, error)
} = (*Runner)(nil)

// TransportRoot is a core-owned parent for invocation-specific RPC directories.
// It is never mounted wholesale into a provider.
func (c *Controller) TransportRoot() (string, error) {
	if !safeMountPath(c.policy.StateDir) {
		return "", errors.New("unsupported_mount_path")
	}
	if err := os.MkdirAll(c.policy.StateDir, 0700); err != nil {
		return "", err
	}
	if err := ownedDirectory(c.policy.StateDir); err != nil {
		return "", err
	}
	path := filepath.Join(c.policy.StateDir, "transport")
	if err := os.Mkdir(path, 0700); err != nil && !os.IsExist(err) {
		return "", err
	}
	if err := ownedDirectory(path); err != nil {
		return "", err
	}
	return path, nil
}
