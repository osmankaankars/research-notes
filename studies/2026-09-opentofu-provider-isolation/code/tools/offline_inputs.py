#!/usr/bin/env python3
"""Integrity checks for a pre-collected, pinned OpenTofu source/module bundle.

The digest must come through a trusted transfer channel. A digest invented by the
same untrusted sender is not a signature or a provenance guarantee. These helpers
never retrieve dependencies, change source versions, or implement a sandbox.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

CORE = 'b4305e5a5dd2fb79a27897ae30784a181d3a26cb'
RANDOM = 'bc2ddb552b4676d16997987a9bf2875c7b98d342'
SCHEMA = 'providercell-offline-inputs-v1'

class InputError(RuntimeError):
    pass

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def inventory(root: Path) -> dict[str,str]:
    """Regular files only; never follow links during bundle verification."""
    if root.is_symlink() or not root.is_dir():
        raise InputError('input root must be an existing real directory')
    found={}
    def fail_walk(error): raise InputError('unreadable input directory') from error
    for base, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        for n in dirs+files:
            p=Path(base)/n
            if p.is_symlink(): raise InputError('symlinked bundle member is unsupported: '+str(p.relative_to(root)))
        for n in files:
            p=Path(base)/n; rel=p.relative_to(root).as_posix()
            if rel=='INPUTS.json': continue
            if not p.is_file(): raise InputError('non-regular bundle member')
            found[rel]=digest(p)
    return dict(sorted(found.items()))

def seal(root: Path, pins: dict[str,str], fixture_input_digest: str) -> str:
    if pins!={'core':CORE,'random':RANDOM}: raise InputError('unexpected upstream pins')
    if not re.fullmatch('[0-9a-f]{64}',fixture_input_digest): raise InputError('invalid fixture input digest')
    dest=root/'INPUTS.json'
    if dest.exists(): raise InputError('refusing to overwrite a sealed bundle')
    data={'schema':SCHEMA,'core_commit':CORE,'random_commit':RANDOM,
          'fixture_input_go_mod_sha256':fixture_input_digest,
          'minimum_go':'1.26.6','files':inventory(root),
          'scope':'BUILD INPUTS ONLY. Podman/runtime image must be verified separately.'}
    with dest.open('x') as f:
        f.write(json.dumps(data,sort_keys=True,indent=2)+'\n')
    return digest(dest)

def verify(root: Path, expected_manifest_sha256: str) -> dict:
    if not re.fullmatch('[0-9a-f]{64}',expected_manifest_sha256): raise InputError('a trusted manifest SHA-256 is required')
    manifest=root/'INPUTS.json'
    if root.is_symlink() or manifest.is_symlink() or not manifest.is_file(): raise InputError('missing or symlinked input manifest')
    if digest(manifest)!=expected_manifest_sha256: raise InputError('input manifest digest mismatch')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise InputError('duplicate manifest key')
            d[k]=v
        return d
    try: m=json.loads(manifest.read_text(),object_pairs_hook=pairs)
    except (ValueError,UnicodeError) as e: raise InputError('invalid input manifest') from e
    if not isinstance(m,dict) or m.get('schema')!=SCHEMA: raise InputError('unsupported input bundle schema')
    if m.get('core_commit')!=CORE or m.get('random_commit')!=RANDOM: raise InputError('upstream revision mismatch')
    for p in ('sources','fixture-lock','modcache'):
        if not (root/p).is_dir(): raise InputError('incomplete inputs: '+p)
    for p in ('sources/opentofu.bundle','sources/random.bundle','fixture-lock/go.mod','fixture-lock/go.sum'):
        if not (root/p).is_file(): raise InputError('incomplete build inputs: '+p)
    if not isinstance(m.get('fixture_input_go_mod_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',m['fixture_input_go_mod_sha256']): raise InputError('invalid fixture input digest')
    if inventory(root)!=m.get('files'): raise InputError('input inventory mismatch: missing, changed or extra file')
    return m

def offline_environment(module_cache: Path) -> dict[str,str]:
    return {'GOTOOLCHAIN':'local','GOPROXY':'off','GOSUMDB':'off','GONOPROXY':'none',
            'GONOSUMDB':'none','GOVCS':'*:off','GOMODCACHE':str(module_cache.resolve()),
            'GOWORK':'off','GIT_ALLOW_PROTOCOL':'file'}


def copy_cache(source: Path, dest: Path):
    if dest.exists(): raise InputError('module cache destination already exists')
    shutil.copytree(source,dest,symlinks=False)
