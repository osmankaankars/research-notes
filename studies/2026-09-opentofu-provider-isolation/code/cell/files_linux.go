//go:build linux

package cell

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"syscall"
)

// openRegular refuses a symlink in the leaf. The trusted administrator owns the
// containing paths; providers cannot reach them. Descriptor-based copying plus
// digest verification binds the executed bytes despite subsequent source changes.
func openRegular(path string, private bool) (*os.File, error) {
	fd, e := syscall.Open(path, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if e != nil {
		return nil, errors.New("file_open_refused")
	}
	f := os.NewFile(uintptr(fd), path)
	s, e := f.Stat()
	if e != nil || !s.Mode().IsRegular() {
		f.Close()
		return nil, errors.New("regular_file_required")
	}
	st, ok := s.Sys().(*syscall.Stat_t)
	if private && (!ok || int(st.Uid) != os.Geteuid() || s.Mode().Perm()&0077 != 0) {
		f.Close()
		return nil, errors.New("private_owned_file_required")
	}
	return f, nil
}
func CopyVerified(source, destination, want string) error {
	if !digestRE.MatchString(want) {
		return errors.New("invalid_executable_digest")
	}
	f, e := openRegular(source, false)
	if e != nil {
		return e
	}
	defer f.Close()
	out, e := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0500)
	if e != nil {
		return e
	}
	success := false
	defer func() {
		out.Close()
		if !success {
			os.Remove(destination)
		}
	}()
	h := sha256.New()
	n, e := io.Copy(io.MultiWriter(out, h), io.LimitReader(f, 512<<20+1))
	if e != nil {
		return e
	}
	if n > 512<<20 || hex.EncodeToString(h.Sum(nil)) != want {
		return errors.New("provider_digest_mismatch")
	}
	if e = out.Sync(); e != nil {
		return e
	}
	if e = out.Close(); e != nil {
		return e
	}
	success = true
	return nil
}
func readSecret(path string) ([]byte, error) {
	f, e := openRegular(path, true)
	if e != nil {
		return nil, errors.New("credential_file_refused")
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, 65537))
	if e != nil || len(b) > 65536 {
		return nil, errors.New("invalid_credential_size")
	}
	return b, nil
}
