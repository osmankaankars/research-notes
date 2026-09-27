package fixtureapi

import (
	"context"
	"net"
	"net/http"
	"path/filepath"
	"testing"
)

func TestUnixServiceDoesOwnWorkAndRejectsOtherScope(t *testing.T) {
	l, err := net.Listen("unix", filepath.Join(t.TempDir(), "api.sock"))
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: NewHandler("red", []byte("artificial-red-token"))}
	go server.Serve(l)
	t.Cleanup(func() { server.Close() })
	c := NewClient(l.Addr().String(), []byte("artificial-red-token"))
	obj, err := c.Create(context.Background(), "upstream-identifier-only")
	if err != nil || obj.Upstream != "upstream-identifier-only" {
		t.Fatal(obj, err)
	}
	got, err := c.Read(context.Background(), obj.ID)
	if err != nil || got != obj {
		t.Fatal(got, err)
	}
	other := NewClient(l.Addr().String(), []byte("artificial-blue-token"))
	if _, err := other.Read(context.Background(), obj.ID); err == nil {
		t.Fatal("other credential accepted")
	}
	if err := c.Delete(context.Background(), obj.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Read(context.Background(), obj.ID); err != ErrNotFound {
		t.Fatal(err)
	}
}
