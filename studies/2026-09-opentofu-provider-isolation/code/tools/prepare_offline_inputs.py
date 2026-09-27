#!/usr/bin/env python3
"""Collect the pinned sources and Go module cache on an Internet-connected host.

No provider program, cloud command, container, or GitHub workflow is executed.
This preparatory step is not usable without a legitimate source-download route.
The result contains build inputs, not Podman, an OCI image, or an isolation result.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import build
import offline_inputs as offline

ROOT=Path(__file__).resolve().parents[1]


def input_plan():
    return {'core':{'repository':'opentofu/opentofu','commit':offline.CORE},
            'random':{'repository':'hashicorp/terraform-provider-random','commit':offline.RANDOM},
            'minimum_go':'1.26.6','fixture_sdk':'v2.38.1',
            'executes_providers':False,'contains_podman_runtime':False}


def lock_hashes(root:Path):
    return {name:offline.digest(root/name) for name in ('go.mod','go.sum')}


def require_unchanged_locks(root:Path, before:dict):
    if lock_hashes(root)!=before:
        raise RuntimeError('upstream dependency lock changed during collection')


def main(out:Path):
    if sys.platform!='linux':raise RuntimeError('collect on Linux for the declared build profile')
    if out.is_relative_to(ROOT) and not out.is_relative_to(ROOT/'.build'):
        raise RuntimeError('nested output must be under .build')
    if out.exists():raise RuntimeError('output exists; refusing to overwrite input evidence')
    env=build.base_environment(out)
    version=build.installed_compiler_version()
    m=re.search(r'go(\d+)\.(\d+)\.(\d+)',version)
    if not m or tuple(map(int,m.groups()))<(1,26,6):raise RuntimeError('Go >=1.26.6 must already be installed')
    out.mkdir(parents=True,mode=0o700)
    for name in ('home','tmp','work','sources','fixture-lock','modcache','reports'):
        (out/name).mkdir(mode=0o700)
    build.disable_telemetry(env)
    env.update({'GOMODCACHE':str(out/'modcache'),'GOCACHE':str(out/'work/gocache'),
                'GOPROXY':'https://proxy.golang.org','GOSUMDB':'sum.golang.org','GOVCS':'*:off',
                'GIT_ALLOW_PROTOCOL':'https','GOFLAGS':'-mod=readonly'})
    seq=0
    def run(args,cwd=None,extra=None):
        nonlocal seq
        seq+=1
        with (out/'reports'/f'{seq:02d}.log').open('w') as f:
            subprocess.run(args,cwd=cwd,env={**env,**(extra or {})},stdout=f,
                           stderr=subprocess.STDOUT,check=True,timeout=1800)
    try:
        for key in ('core','random'):
            item=input_plan()[key]; source=out/'work'/key
            run(['git','-c','core.hooksPath=/dev/null','init',str(source)])
            run(['git','-C',str(source),'-c','credential.helper=','remote','add','origin',
                 'https://github.com/'+item['repository']+'.git'])
            # No shallow/partial objects: the offline bundle must be self-contained.
            run(['git','-C',str(source),'-c','credential.helper=','fetch','--no-tags','origin',item['commit']])
            run(['git','-C',str(source),'-c','core.hooksPath=/dev/null','checkout','--detach',item['commit']])
            got=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],env=env,text=True).strip()
            if got!=item['commit']:raise RuntimeError('source commit mismatch')
            before=lock_hashes(source)
            run(['go','mod','download'],source)
            targets=['./cmd/tofu','./internal/plugins'] if key=='core' else ['.']
            run(['go','list','-mod=readonly','-deps','-test',*targets],source)
            run(['go','mod','verify'],source)
            require_unchanged_locks(source,before)
            filename='opentofu.bundle' if key=='core' else 'random.bundle'
            run(['git','-C',str(source),'bundle','create',str(out/'sources'/filename),'HEAD'])
            run(['git','-C',str(source),'bundle','verify',str(out/'sources'/filename)])
            (out/'reports'/f'{key}-lock-hashes.json').write_text(json.dumps(before,sort_keys=True,indent=2)+'\n')
        impl=out/'work/implementation'
        shutil.copytree(ROOT,impl,ignore=shutil.ignore_patterns('.git','.build','__pycache__','verification'))
        fixture=impl/'fixture/provider'
        fixture_input=offline.digest(fixture/'go.mod')
        # Only our research fixture needs a new lock. Pinned upstream locks may not change.
        run(['go','mod','tidy'],fixture,extra={'GOFLAGS':''})
        run(['go','mod','download'],fixture)
        run(['go','list','-mod=readonly','-deps','-test','.'],fixture)
        run(['go','mod','verify'],fixture)
        for name in ('go.mod','go.sum'):
            shutil.copyfile(fixture/name,out/'fixture-lock'/name)
        (out/'reports/preparation.json').write_text(json.dumps({'status':'COLLECTED_NOT_BUILT',
            'toolchain':version,'plan':input_plan(),'checksum_service':'sum.golang.org',
            'new_fixture_lock':True,'providers_executed':False,'runtime_verified':False},indent=2)+'\n')
        # These are this command's newly-created scratch directories only.
        for name in ('work','home','tmp'):shutil.rmtree(out/name)
        pin=offline.seal(out,{'core':offline.CORE,'random':offline.RANDOM},fixture_input)
        offline.verify(out,pin)
        print(json.dumps({'status':'SEALED_BUILD_INPUTS_NOT_RUNTIME','inputs':str(out),
                         'inputs_sha256':pin,'requires_separate_podman_runtime':True},indent=2))
    except Exception as exc:
        (out/'PREPARATION_FAILED.json').write_text(json.dumps({'status':'INCOMPLETE_DO_NOT_BUILD',
            'error_type':type(exc).__name__,'error':str(exc),'last_log':f'reports/{seq:02d}.log',
            'no_sealed_bundle_produced':True},indent=2)+'\n')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--show-plan',action='store_true')
    args=parser.parse_args()
    if args.show_plan:print(json.dumps(input_plan(),indent=2))
    elif args.out is None:parser.error('--out is required unless --show-plan is used')
    else:
        try:main(args.out.resolve())
        except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
            raise SystemExit('PREPARATION STOPPED: '+str(exc))
