//go:build !linux

package cell

import (
	"context"
	"errors"
	"io"
	"os"
)

var errUnsupported = errors.New("provider isolation requires Linux; no unrestricted fallback")

func openRegular(string, bool) (*os.File, error)     { return nil, errUnsupported }
func (c *Controller) TransportRoot() (string, error) { return "", errUnsupported }

type Runner struct{}

func NewRunner(LaunchSpec, []string, string, string) (*Runner, error) { return nil, errUnsupported }
func (*Runner) Start(context.Context) error                           { return errUnsupported }
func (*Runner) Wait(context.Context) error                            { return errUnsupported }
func (*Runner) Kill(context.Context) error                            { return errUnsupported }
func (*Runner) Diagnose(context.Context) string                       { return errUnsupported.Error() }
func (*Runner) Stdout() io.ReadCloser                                 { return nil }
func (*Runner) Stderr() io.ReadCloser                                 { return nil }
func (*Runner) Name() string                                          { return "unsupported-isolated-provider" }
func (*Runner) ID() string                                            { return "" }
func (*Runner) PluginToHost(string, string) (string, string, error)   { return "", "", errUnsupported }
func (*Runner) HostToPlugin(string, string) (string, string, error)   { return "", "", errUnsupported }
