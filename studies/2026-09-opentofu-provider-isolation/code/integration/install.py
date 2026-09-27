#!/usr/bin/env python3
"""Apply the provider-isolation source overlay to exactly OpenTofu v1.12.6.

No network, no build, no provider process, no repository push. This installer
preflights every original blob and every destination before writing anything.
It must be used only in a disposable checkout. Compilation is a separate gate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "b4305e5a5dd2fb79a27897ae30784a181d3a26cb"
IMPORT = 'providercell "github.com/opentofu/opentofu/internal/providerisolation"'
PINNED = {
 "internal/command/meta_providers.go": "aa90df4976cd77ab47ebd1dabe3bc2be7d8a74c4",
 "internal/command/plugins.go": "c6c0c00575693539f963bc17d66b1e6fb8a3df97",
 "internal/plugins/provider.go": "9e7512fc5d7b784e12cc197f4f18cf6b2c49381d",
 "internal/tofu/node_provider.go": "e131126ebccd316f35db3dec0087e90b29a88c76",
 "go.mod": "934ae7eff3732e76796eb234d272fd4e4e7d72ab",
}

def blob_id(raw: bytes) -> str:
 return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def once(text: str, old: str, new: str) -> str:
 if text.count(old) != 1:
  raise ValueError("Pinned source anchor absent or ambiguous: " + old[:100])
 return text.replace(old,new,1)

def imported(text: str) -> str:
 return once(text, 'import (\n', 'import (\n\t' + IMPORT + '\n')

VALIDATE_OLD = '''\t\tinstance, newDiags := evalCtx.Providers().NewProvider(ctx, n.Addr.Provider)
\t\tif !newDiags.HasErrors() { // We can't validate if we didn't successfully start the provider plugin
\t\t\tn.instances[addrs.NoKey] = instance
\t\t\tfor key, data := range instanceData {
\t\t\t\tdiags = diags.Append(n.ValidateProvider(ctx, evalCtx, instance, key, data))
\t\t\t}
\t\t}
\t\treturn diags.Append(newDiags)'''
VALIDATE_NEW = '''\t\t// Validation itself receives configuration values. Never reuse a
\t\t// process across instance keys that may have different authority.
\t\tfor key, data := range instanceData {
\t\t\tscopedCtx := providerIsolationContext(ctx, n.Addr, key, providercell.Validation)
\t\t\tinstance, newDiags := evalCtx.Providers().NewProvider(scopedCtx, n.Addr.Provider)
\t\t\tdiags = diags.Append(newDiags)
\t\t\tif !newDiags.HasErrors() {
\t\t\t\tn.instances[key] = instance
\t\t\t\tdiags = diags.Append(n.ValidateProvider(scopedCtx, evalCtx, instance, key, data))
\t\t\t}
\t\t}
\t\treturn diags'''

def transform(path: str, text: str) -> str:
 if path == "internal/command/meta_providers.go":
  text=imported(text)
  anchor='func (m *Meta) providerFactories() (map[addrs.Provider]providers.Factory, error) {\n'
  text=once(text,anchor,anchor+'''\tisolatedPolicy, isolationErr := loadProviderIsolationPolicy()
\tif isolationErr != nil { return nil, isolationErr }
\tif isolatedPolicy != nil && (len(m.ProviderDevOverrides) != 0 || len(m.UnmanagedProviders) != 0) {
\t\treturn nil, errors.New("provider isolation: development overrides and unmanaged reattachment are unsupported")
\t}
''')
  text=once(text,'\t\tfactory := providerFactory(cached)', '''\t\tfactory := providerFactory(cached)
\t\tif isolatedPolicy != nil { factory = isolatedProviderFactory(cached, isolatedPolicy) }''')
  anchor='func providerFactory(meta *providercache.CachedProvider) providers.Factory {\n'
  text=once(text,anchor,anchor+'''\tif providercell.Enabled() {
\t\treturn func() (providers.Interface, error) {
\t\t\treturn nil, errors.New("provider isolation: unscoped provider launcher is disabled")
\t\t}
\t}
''')
  return text
 if path == "internal/command/plugins.go":
  text=imported(text)
  anchor='func (m *Meta) provisionerFactories() map[string]provisioners.Factory {\n'
  return once(text,anchor,anchor+'''\tif providercell.Enabled() {
\t\t// Provisioners execute outside the provider protocol. Until separately
\t\t// isolated they are deliberately unavailable, including built-ins.
\t\treturn map[string]provisioners.Factory{}
\t}
''')
 if path == "internal/plugins/provider.go":
  text=once(text,'\treturn f()\n}', '''\tinstance, err := f()
\tif err != nil { return nil, err }
\tif _, protected := instance.(scopedProviderBinder); protected {
\t\treturn nil, fmt.Errorf("provider isolation: legacy launch entry has no authority scope")
\t}
\treturn instance, nil
}''')
  anchor='p.providerFactories.NewInstance(addr)'
  if text.count(anchor)!=3: raise ValueError('unexpected provider launch inventory')
  text=text.replace(anchor,'p.providerFactories.newForSchema(ctx, addr)',1)
  return text.replace(anchor,'p.providerFactories.newForContext(ctx, addr)')
 if path == "internal/tofu/node_provider.go":
  text=imported(text)
  text=once(text,VALIDATE_OLD, "\t\tif !providercell.Enabled() {\n" + VALIDATE_OLD + "\n\t\t}\n" + VALIDATE_NEW)
  return once(text,
    'evalCtx.Providers().NewConfiguredProvider(ctx, n.Addr.Provider, configVal)',
    'evalCtx.Providers().NewConfiguredProvider(providerIsolationContext(ctx, n.Addr, providerKey, providercell.Configured), n.Addr.Provider, configVal)')
 raise ValueError('No transformation for '+path)

GRAPH_HELPER='''// Copyright (c) 2026 Osman Kaan Kars
// SPDX-License-Identifier: MPL-2.0
package tofu
import (
 "context"
 "github.com/opentofu/opentofu/internal/addrs"
 providercell "github.com/opentofu/opentofu/internal/providerisolation"
)
func providerIsolationContext(ctx context.Context, addr addrs.AbsProviderConfig, key addrs.InstanceKey, phase providercell.Phase) context.Context {
 k:=""
 if key!=addrs.NoKey {k=key.String()}
 return providercell.WithScope(ctx,providercell.Scope{Source:addr.Provider.String(),Configuration:addr.String(),InstanceKey:k,Phase:phase})
}
'''

def generate(originals: dict[str,bytes]) -> dict[str,bytes]:
 if set(originals)!=set(PINNED): raise ValueError('incomplete original source inventory')
 for path,expected in PINNED.items():
  if blob_id(originals[path])!=expected: raise ValueError('Unreviewed or modified upstream file: '+path)
 output={p:transform(p,raw.decode()).encode() for p,raw in originals.items() if p!='go.mod'}
 for path in (ROOT/'cell').glob('*.go'):
  output['internal/providerisolation/'+path.name]=path.read_bytes()
 for parent in ('command','plugins'):
  for p in (ROOT/'integration/templates'/parent).glob('*.go.in'):
   output[f'internal/{parent}/'+p.name[:-3]]=p.read_bytes()
 output['internal/tofu/provider_isolation.go']=GRAPH_HELPER.encode()
 return output

def install(checkout: Path, write: bool=False) -> dict:
 checkout=checkout.resolve(strict=True)
 if not (checkout/'.git').exists(): raise ValueError('use a clean detached Git checkout')
 head=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
 if head!=COMMIT: raise ValueError('unsupported upstream commit')
 if subprocess.check_output(['git','-C',str(checkout),'status','--porcelain','--untracked-files=all'],text=True).strip():
  raise ValueError('checkout must be clean; do not overwrite existing work')
 originals={}
 for p in PINNED:
  path=checkout/p
  if path.is_symlink():raise ValueError('symlinked source rejected')
  originals[p]=path.read_bytes()
 output=generate(originals)
 for path in output:
  target=checkout/path
  if path not in PINNED and target.exists():raise ValueError('destination already exists: '+path)
  for parent in target.parents:
   if parent==checkout:break
   if parent.is_symlink():raise ValueError('symlinked destination parent')
 report={'upstream_commit':COMMIT,'mode':'preflight','files':{p:hashlib.sha256(b).hexdigest() for p,b in sorted(output.items())},'compiled':False,'runtime_tested':False}
 if write:
  # Stage and syntax-check *all* files before touching the checkout. Installation
  # failures roll back originals and remove only newly created files.
  with tempfile.TemporaryDirectory(prefix='provider-overlay-') as tmp:
   stage=Path(tmp)
   for p,raw in output.items():
    dest=stage/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    subprocess.run(['gofmt','-w',str(dest)],check=True,capture_output=True)
   written=[]
   try:
    for p in output:
     dest=checkout/p;dest.parent.mkdir(parents=True,exist_ok=True)
     dest.write_bytes((stage/p).read_bytes());written.append(p)
   except BaseException:
    for p in reversed(written):
     if p in originals:(checkout/p).write_bytes(originals[p])
     else:(checkout/p).unlink(missing_ok=True)
    raise
  report['mode']='applied_source_only'
  report['files']={p:hashlib.sha256((checkout/p).read_bytes()).hexdigest() for p in sorted(output)}
 return report

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('checkout',type=Path)
 parser.add_argument('--apply',action='store_true')
 args=parser.parse_args()
 try: print(json.dumps(install(args.checkout,args.apply),indent=2))
 except (ValueError,OSError,subprocess.CalledProcessError) as e:
  raise SystemExit('STOP: '+str(e))
