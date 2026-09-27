// cellctl diagnoses prerequisites and parses policies; it does not claim that
// a successful preflight is a security audit or a completed isolation test.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"providercell.local/implementation/cell"
	"runtime"
	"strings"
	"time"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: cellctl doctor | check-policy --path /absolute/policy.json")
		os.Exit(2)
	}
	switch os.Args[1] {
	case "doctor":
		flags := flag.NewFlagSet("doctor", flag.ExitOnError)
		runtimePath := flags.String("runtime", "/usr/bin/podman", "trusted local Podman path")
		flags.Parse(os.Args[2:])
		report := map[string]any{"platform": runtime.GOOS, "euid": os.Geteuid(), "go_compiler_used": runtime.Version(), "provider_started": false, "isolation_verified": false}
		ready := runtime.GOOS == "linux" && os.Geteuid() != 0
		_, err := os.Stat(*runtimePath)
		report["runtime_present"] = err == nil
		if err != nil {
			ready = false
		}
		if ready {
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, *runtimePath, "--remote=false", "info", "--format={{.Host.Security.Rootless}}:{{.Host.CgroupsVersion}}")
			// Same minimal runtime environment, without cloud credentials or remote settings.
			cmd.Env = []string{"PATH=/usr/bin:/bin", "LANG=C.UTF-8"}
			for _, k := range []string{"HOME", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"} {
				if v := os.Getenv(k); v != "" {
					cmd.Env = append(cmd.Env, k+"="+v)
				}
			}
			b, e := cmd.Output()
			ready = e == nil && strings.TrimSpace(string(b)) == "true:v2"
		}
		report["prerequisites_passed"] = ready
		json.NewEncoder(os.Stdout).Encode(report)
		if !ready {
			os.Exit(2)
		}
	case "check-policy":
		flags := flag.NewFlagSet("check-policy", flag.ExitOnError)
		path := flags.String("path", "", "private policy path")
		flags.Parse(os.Args[2:])
		if _, err := cell.Load(*path); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		fmt.Println(`{"policy_parsed":true,"provider_started":false,"isolation_verified":false}`)
	default:
		fmt.Fprintln(os.Stderr, "unsupported command")
		os.Exit(2)
	}
}
