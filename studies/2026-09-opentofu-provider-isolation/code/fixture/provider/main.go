// Controlled protocol provider. It reads only explicitly named synthetic canary
// locations and never enumerates host credentials or sends data over the Internet.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/hashicorp/terraform-plugin-sdk/v2/diag"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/schema"
	"github.com/hashicorp/terraform-plugin-sdk/v2/plugin"
	"providercell.local/implementation/fixtureapi"
)

type configured struct {
	client *fixtureapi.Client
	checks map[string]bool
}

func readOwn(path string) ([]byte, error) {
	fi, err := os.Lstat(path)
	if err != nil || !fi.Mode().IsRegular() || fi.Mode().Perm()&0077 != 0 {
		return nil, errors.New("own fixture credential unavailable")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 1025))
	if err != nil || len(b) < 8 || len(b) > 1024 {
		return nil, errors.New("invalid artificial fixture credential")
	}
	return b, nil
}
func checks(unassigned string) map[string]bool {
	c := map[string]bool{"unrelated_environment_visible": os.Getenv("CELL_LAB_UNRELATED") != ""}
	if unassigned != "" && filepath.IsAbs(unassigned) && filepath.Base(unassigned) == "unassigned.canary" && strings.HasPrefix(filepath.Clean(unassigned), "/tmp/provider-cell-lab-") {
		f, err := os.Open(unassigned)
		if err == nil {
			b, _ := io.ReadAll(io.LimitReader(f, 256))
			f.Close()
			c["unassigned_file_readable"] = string(b) == "LAB_UNASSIGNED_CANARY_V1"
		} else {
			c["unassigned_file_readable"] = false
		}
	}
	_, ownErr := os.Stat("/credentials/token")
	c["credential_file_present_at_start"] = ownErr == nil
	_, err := os.ReadFile("/proc/self/stat")
	c["self_process_information_available"] = err == nil
	return c
}
func Provider() *schema.Provider {
	return &schema.Provider{
		Schema: map[string]*schema.Schema{
			"socket_path":            {Type: schema.TypeString, Required: true},
			"token_file":             {Type: schema.TypeString, Required: true},
			"unassigned_canary_path": {Type: schema.TypeString, Optional: true},
		},
		ResourcesMap: map[string]*schema.Resource{"cell_record": {
			CreateContext: create, ReadContext: read, DeleteContext: remove,
			Schema: map[string]*schema.Schema{
				"upstream":    {Type: schema.TypeString, Required: true, ForceNew: true},
				"checks_json": {Type: schema.TypeString, Computed: true},
			},
		}},
		ConfigureContextFunc: func(ctx context.Context, d *schema.ResourceData) (any, diag.Diagnostics) {
			token, err := readOwn(d.Get("token_file").(string))
			if err != nil {
				return nil, diag.Errorf("assigned fixture credential could not be read")
			}
			socket := d.Get("socket_path").(string)
			if !filepath.IsAbs(socket) {
				return nil, diag.Errorf("fixture requires an absolute Unix socket path")
			}
			c := checks(d.Get("unassigned_canary_path").(string))
			c["own_credential_readable"] = true
			return &configured{client: fixtureapi.NewClient(socket, token), checks: c}, nil
		},
	}
}
func create(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
	m, ok := meta.(*configured)
	if !ok {
		return diag.Errorf("provider not configured")
	}
	o, err := m.client.Create(ctx, d.Get("upstream").(string))
	if err != nil {
		return diag.Errorf("assigned fixture API operation failed")
	}
	d.SetId(o.ID)
	c := map[string]bool{}
	for k, v := range m.checks {
		c[k] = v
	}
	c["own_api_operation_completed"] = true
	raw, _ := json.Marshal(c)
	if err := d.Set("checks_json", string(raw)); err != nil {
		return diag.FromErr(err)
	}
	return nil
}
func read(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
	m, ok := meta.(*configured)
	if !ok {
		return diag.Errorf("provider not configured")
	}
	o, err := m.client.Read(ctx, d.Id())
	if errors.Is(err, fixtureapi.ErrNotFound) {
		d.SetId("")
		return nil
	}
	if err != nil {
		return diag.Errorf("fixture read failed")
	}
	if err = d.Set("upstream", o.Upstream); err != nil {
		return diag.FromErr(err)
	}
	return nil
}
func remove(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
	m, ok := meta.(*configured)
	if !ok {
		return diag.Errorf("provider not configured")
	}
	err := m.client.Delete(ctx, d.Id())
	if err != nil && !errors.Is(err, fixtureapi.ErrNotFound) {
		return diag.Errorf("fixture delete failed")
	}
	d.SetId("")
	return nil
}
func main() {
	// Before any handshake or ConfigureProvider call, record booleans only. Schema
	// execution is expected to have no unrelated credential environment.
	raw, _ := json.Marshal(map[string]any{"event": "fixture_process_started", "checks": checks(""), "phase": os.Getenv("CELL_LAUNCH_PHASE"), "invocation": os.Getenv("CELL_INVOCATION_ID")})
	fmt.Fprintln(os.Stderr, "CELL_FIXTURE "+string(raw))
	plugin.Serve(&plugin.ServeOpts{ProviderFunc: Provider})
}
