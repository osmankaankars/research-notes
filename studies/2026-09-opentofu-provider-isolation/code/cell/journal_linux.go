//go:build linux

package cell

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

// No provider-supplied logs, credential values or capability file contents are
// included. This is a core-side lifecycle journal, not proof a sandbox worked.
func (r *Runner) journal(event string) error {
	path := filepath.Join(r.spec.StateDir, "events.jsonl")
	fd, err := syscall.Open(path, syscall.O_WRONLY|syscall.O_APPEND|syscall.O_CREAT|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return errors.New("isolation_journal_unavailable")
	}
	f := os.NewFile(uintptr(fd), path)
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return err
	}
	owner, ok := st.Sys().(*syscall.Stat_t)
	if !st.Mode().IsRegular() || st.Mode().Perm()&0077 != 0 || !ok || int(owner.Uid) != os.Geteuid() {
		return errors.New("isolation_journal_not_private")
	}
	if err := syscall.Flock(fd, syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(fd, syscall.LOCK_UN)
	raw, err := json.Marshal(struct {
		Time       string `json:"time"`
		Event      string `json:"event"`
		Invocation string `json:"invocation"`
		Scope      Scope  `json:"scope"`
		Digest     string `json:"binary_sha256"`
	}{time.Now().UTC().Format(time.RFC3339Nano), event, r.id, r.spec.Scope, r.spec.Artifact.SHA256})
	if err != nil {
		return err
	}
	if _, err = f.Write(append(raw, '\n')); err != nil {
		return err
	}
	return f.Sync()
}
