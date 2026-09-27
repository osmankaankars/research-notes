// Local credential-scoped test fixture; never binds to a TCP interface.
package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"providercell.local/implementation/fixtureapi"
	"syscall"
	"time"
)

func main() {
	socket := flag.String("socket", "", "absolute Unix socket path")
	tokenFile := flag.String("token-file", "", "private synthetic credential file")
	scope := flag.String("scope", "", "fixture namespace")
	flag.Parse()
	if !filepath.IsAbs(*socket) || !filepath.IsAbs(*tokenFile) {
		fmt.Fprintln(os.Stderr, "absolute paths required")
		os.Exit(2)
	}
	fi, err := os.Lstat(*tokenFile)
	if err != nil || !fi.Mode().IsRegular() || fi.Mode().Perm()&0077 != 0 {
		fmt.Fprintln(os.Stderr, "private regular credential file required")
		os.Exit(2)
	}
	token, err := os.ReadFile(*tokenFile)
	if err != nil || len(token) < 8 || len(token) > 1024 {
		fmt.Fprintln(os.Stderr, "invalid fixture credential")
		os.Exit(2)
	}
	l, err := net.Listen("unix", *socket)
	if err != nil {
		fmt.Fprintln(os.Stderr, "fixture socket creation failed")
		os.Exit(2)
	}
	defer l.Close()
	defer os.Remove(*socket)
	if err = os.Chmod(*socket, 0600); err != nil {
		panic(err)
	}
	srv := &http.Server{Handler: fixtureapi.NewHandler(*scope, token), ReadHeaderTimeout: 2 * time.Second, ReadTimeout: 3 * time.Second, WriteTimeout: 3 * time.Second, MaxHeaderBytes: 8192}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		c, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		srv.Shutdown(c)
	}()
	fmt.Println("FIXTURE_READY")
	if err := srv.Serve(l); err != nil && err != http.ErrServerClosed {
		fmt.Fprintln(os.Stderr, "fixture serve failed")
		os.Exit(1)
	}
}
