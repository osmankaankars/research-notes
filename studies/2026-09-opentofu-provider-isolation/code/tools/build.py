#!/usr/bin/env python3
"""Build pinned original/env-only/scoped OpenTofu and two actual providers.

This is an offline-inspectable reproduction script, not evidence of a successful
build. It refuses insufficient compiler versions rather than altering go.mod.
Only anonymous read access to public repositories/module servers is used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import offline_inputs as offline

ROOT=Path(__file__).resolve().parents[1]
CORE='b4305e5a5dd2fb79a27897ae30784a181d3a26cb'
RANDOM='bc2ddb552b4676d16997987a9bf2875c7b98d342'

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def base_environment(out:Path):
 return {'PATH':os.environ['PATH'],'HOME':str(out/'home'),'TMPDIR':str(out/'tmp'),
         'LANG':'C.UTF-8','GOTOOLCHAIN':'local','CGO_ENABLED':'0','GOSUMDB':'sum.golang.org',
         'GOPROXY':'https://proxy.golang.org','GOWORK':'off',
         'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}

def disable_telemetry(env):
 # GOTELEMETRY is a read-only go-env output, not an effective env override.
 # Use the documented command inside this invocation's private HOME instead.
 Path(env['HOME']).mkdir(parents=True,exist_ok=True)
 Path(env['TMPDIR']).mkdir(parents=True,exist_ok=True)
 subprocess.run(['go','telemetry','off'],env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)

def installed_compiler_version():
 # Even `go version` can create local telemetry files. Do not point its HOME
 # at the future build output before the exclusive directory creation.
 with tempfile.TemporaryDirectory(prefix='providercell-compiler-') as tmp:
  env=base_environment(Path(tmp))
  disable_telemetry(env)
  return subprocess.check_output(['go','version'],text=True,env=env,timeout=30).strip()

def check_offline_arguments(inputs, manifest_pin):
 if (inputs is None)!=(manifest_pin is None):
  raise ValueError('--offline-inputs and --inputs-sha256 must be supplied together')

def clone_offline(name,commit,dest,inputs,run,env):
 names={'opentofu/opentofu':'opentofu.bundle','hashicorp/terraform-provider-random':'random.bundle'}
 if name not in names:raise RuntimeError('unsupported offline source repository')
 bundle=inputs/'sources'/names[name]
 # No hooks or external transport. The bundle imports original Git objects, not
 # an unversioned source tree relabeled as the pinned upstream revision.
 local={**env,'GIT_ALLOW_PROTOCOL':'file'}
 run(['git','-c','core.hooksPath=/dev/null','clone','--no-checkout',str(bundle),str(dest)],extra={'GIT_ALLOW_PROTOCOL':'file'})
 got=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True,env=local).strip()
 if got!=commit:raise RuntimeError('offline source commit mismatch')
 run(['git','-C',str(dest),'-c','core.hooksPath=/dev/null','checkout','--detach',commit],extra={'GIT_ALLOW_PROTOCOL':'file'})
 run(['git','-C',str(dest),'fsck','--strict'],extra={'GIT_ALLOW_PROTOCOL':'file'})
 clean=subprocess.check_output(['git','-C',str(dest),'status','--porcelain'],text=True,env=local)
 if clean:raise RuntimeError('offline source checkout is not clean')

def main(out:Path, inputs:Path|None=None, manifest_pin:str|None=None):
 check_offline_arguments(inputs,manifest_pin)
 input_manifest=None
 if inputs is not None:
  input_manifest=offline.verify(inputs,manifest_pin)
  if input_manifest['fixture_input_go_mod_sha256']!=digest(ROOT/'fixture/provider/go.mod'):
   raise RuntimeError('offline fixture lock belongs to different source inputs')
 # Select the installed compiler, never download a toolchain during preflight.
 version=installed_compiler_version()
 m=re.search(r'go(\d+)\.(\d+)\.(\d+)',version)
 if not m or tuple(map(int,m.groups()))<(1,26,6):raise RuntimeError('Go >= 1.26.6 is required; the upstream requirement will not be weakened')
 if sys.platform!='linux':raise RuntimeError('Linux build required for this profile')
 if out.is_relative_to(ROOT) and not out.is_relative_to(ROOT/'.build'):
  raise RuntimeError('nested build output must be under .build to avoid copying itself')
 if out.exists():raise RuntimeError('build output already exists; never overwrite evidence')
 out.mkdir(parents=True,mode=0o700)
 for n in ('home','tmp','bin','logs','src'): (out/n).mkdir(mode=0o700)
 env=base_environment(out)
 disable_telemetry(env)
 if inputs is not None:
  offline.copy_cache(inputs/'modcache',out/'modcache')
  env.update(offline.offline_environment(out/'modcache'))
  # Online checksums were verified during collection. Offline mode checks the
  # sealed cache and go.sum without contacting the public checksum service.
  (out/'inputs-used.json').write_text(json.dumps({'manifest_sha256':manifest_pin,
       'core_commit':CORE,'random_commit':RANDOM,'mode':'offline'},indent=2)+'\n')
 seq=0
 def run(args,cwd=None,extra=None):
  nonlocal seq
  seq+=1
  with (out/'logs'/f'{seq:02d}.log').open('w') as log:
   subprocess.run(args,cwd=cwd,env={**env,**(extra or {})},stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
 def clone(name,commit,dest):
  if inputs is not None:
   return clone_offline(name,commit,dest,inputs,run,env)
  run(['git','init',str(dest)])
  run(['git','-C',str(dest),'-c','credential.helper=','remote','add','origin','https://github.com/'+name+'.git'])
  run(['git','-C',str(dest),'-c','credential.helper=','fetch','--depth=1','origin',commit])
  run(['git','-C',str(dest),'checkout','--detach',commit])
  got=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True,env=env).strip()
  if got!=commit:raise RuntimeError('commit mismatch')
 core=out/'src/opentofu';clone('opentofu/opentofu',CORE,core)
 run(['go','mod','download'],core);run(['go','mod','verify'],core)
 run(['go','build','-mod=readonly','-trimpath','-o',str(out/'bin/tofu-original'),'./cmd/tofu'],core)
 envonly=out/'src/opentofu-env'
 run(['git','-C',str(core),'worktree','add','--detach',str(envonly),CORE])
 p=envonly/'internal/command/meta_providers.go';s=p.read_text()
 anchor='Cmd:              exec.Command(execFile),'
 if s.count(anchor)!=1:raise RuntimeError('environment-only baseline source changed')
 p.write_text(s.replace(anchor,anchor+'\n\t\t\tSkipHostEnv: true,',1))
 run(['gofmt','-w',str(p)])
 run(['go','build','-mod=readonly','-trimpath','-o',str(out/'bin/tofu-env-only'),'./cmd/tofu'],envonly)
 run([sys.executable,str(ROOT/'integration/install.py'),str(core),'--apply'])
 run(['go','test','-mod=readonly','./internal/providerisolation'],core)
 run(['go','test','-mod=readonly','-run','^TestProviderIsolationBinding$','./internal/plugins'],core)
 run(['go','build','-mod=readonly','-trimpath','-o',str(out/'bin/tofu-scoped'),'./cmd/tofu'],core)
 random=out/'src/random';clone('hashicorp/terraform-provider-random',RANDOM,random)
 run(['go','mod','download'],random);run(['go','mod','verify'],random)
 run(['go','build','-mod=readonly','-trimpath','-o',str(out/'bin/terraform-provider-random_v3.7.2'),'.'],random)
 # Work on a private copy: generation of the fixture's dependency lock does not
 # rewrite this delivered source or a previously checked-in lock.
 impl=out/'src/implementation';shutil.copytree(ROOT,impl,ignore=shutil.ignore_patterns('.git','.build','__pycache__','verification'))
 fixture=impl/'fixture/provider'
 if inputs is not None:
  shutil.copyfile(inputs/'fixture-lock/go.mod',fixture/'go.mod')
  shutil.copyfile(inputs/'fixture-lock/go.sum',fixture/'go.sum')
 else:
  run(['go','mod','tidy'],fixture)
 run(['go','mod','download'],fixture);run(['go','mod','verify'],fixture)
 run(['go','build','-mod=readonly','-trimpath','-o',str(out/'bin/terraform-provider-cell_v0.1.0'),'.'],fixture)
 run(['go','build','-trimpath','-o',str(out/'bin/fixture-api'),'./cmd/fixture-api'],impl)
 run(['go','build','-trimpath','-o',str(out/'bin/cellctl'),'./cmd/cellctl'],impl)
 manifest={'status':'COMPILED_NOT_RUNTIME_VERIFIED','opentofu_commit':CORE,'random_commit':RANDOM,'fixture_sdk':'v2.38.1','go':version,'input_mode':'offline' if inputs else 'online','inputs_manifest_sha256':manifest_pin,'binaries':{p.name:digest(p) for p in (out/'bin').iterdir()},'isolation_verified':False,'fixture_go_sum_sha256':digest(fixture/'go.sum')}
 (out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps(manifest,indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--out',type=Path,required=True)
 p.add_argument('--offline-inputs',type=Path,help='Verified local inputs from prepare_offline_inputs.py; no network fallback')
 p.add_argument('--inputs-sha256',help='Expected INPUTS.json SHA-256 from the trusted preparation run')
 a=p.parse_args()
 try:main(a.out.resolve(),a.offline_inputs.absolute() if a.offline_inputs else None,a.inputs_sha256)
 except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as e:raise SystemExit('BUILD STOPPED: '+str(e))
