#!/usr/bin/env python3
"""Execute the real four-arm OpenTofu lab after a verified build.

No live cloud credentials, no TCP listeners, no registry publication. Produces
no success record unless actual CLI operations and dependency checks succeed.
Recorded execution and its limits are documented in ../RESULTS.md.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE='registry.opentofu.org/example/cell'
NORMAL='registry.opentofu.org/hashicorp/random'

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_private(p:Path,text:str):p.write_text(text);p.chmod(0o600)

def require_image_id(value:str):
 value=value.strip()
 if not re.fullmatch(r"sha256:[0-9a-f]{64}",value):raise RuntimeError("image did not resolve to immutable ID")
 return value

def require_container_absent(returncode:int):
 # Podman's container-exists contract: 0 exists, 1 absent, 125 error.
 if returncode!=1:raise RuntimeError('container absence was not confirmed')
def main(build:Path,out:Path,runtime:str):
 if os.geteuid()==0:raise RuntimeError('requires a genuine rootless user')
 manifest=json.loads((build/'build-manifest.json').read_text())
 if manifest['status']!='COMPILED_NOT_RUNTIME_VERIFIED':raise RuntimeError('unexpected build record')
 for name,h in manifest['binaries'].items():
  if digest(build/'bin'/name)!=h:raise RuntimeError('binary changed after build')
 if out.exists():raise RuntimeError('results already exist; no overwriting')
 out.mkdir(parents=True,mode=0o700)
 lab=Path(tempfile.mkdtemp(prefix='provider-cell-lab-',dir='/tmp'));lab.chmod(0o700)
 env={'PATH':os.environ['PATH'],'LANG':'C.UTF-8'}
 for k in ('HOME','XDG_RUNTIME_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
  if k in os.environ:env[k]=os.environ[k]
 procs=[];handles=[];image=None;results={};counter=0
 def run(args,cwd=None,extra=None,capture=False):
  nonlocal counter
  counter+=1
  if capture:return subprocess.check_output(args,cwd=cwd,env={**env,**(extra or {})},text=True,timeout=600)
  with (out/f'command-{counter:02d}.log').open('w') as log:
   subprocess.run(args,cwd=cwd,env={**env,**(extra or {})},stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
 def pd(*args,capture=False):return run([runtime,'--remote=false',*args],capture=capture)
 try:
  if pd('info','--format={{.Host.Security.Rootless}}:{{.Host.CgroupsVersion}}',capture=True).strip()!='true:v2':raise RuntimeError('rootless Podman and cgroups v2 required')
  write_private(lab/'unassigned.canary','LAB_UNASSIGNED_CANARY_V1')
  for scope in ('red','blue'):
   write_private(lab/(scope+'.token'),secrets.token_hex(24))
   log=(out/(scope+'-fixture.log')).open('w');handles.append(log)
   p=subprocess.Popen([str(build/'bin/fixture-api'),'--scope',scope,'--socket',str(lab/(scope+'.sock')),'--token-file',str(lab/(scope+'.token'))],env=env,stdout=log,stderr=log);procs.append(p)
  deadline=time.monotonic()+10
  while not all((lab/(s+'.sock')).exists() for s in ('red','blue')):
   if any(p.poll() is not None for p in procs) or time.monotonic()>deadline:raise RuntimeError('fixture startup failed')
   time.sleep(.05)
  context=lab/'image';(context/'empty').mkdir(parents=True)
  for d in ('provider','credentials','services','rpc','tmp','work','etc'):
   p=context/'empty'/d;p.mkdir();(p/'.keep').write_text('')
  (context/'Containerfile').write_text('FROM scratch\nCOPY empty/ /\n')
  iidfile=lab/'image.id'
  pd('build','--pull=never','--network=none','--iidfile',str(iidfile),str(context))
  image=require_image_id(iidfile.read_text())
  mirror=lab/'mirror'
  for source,version,binary in ((SOURCE,'0.1.0','terraform-provider-cell_v0.1.0'),(NORMAL,'3.7.2','terraform-provider-random_v3.7.2')):
   dest=mirror/source/version/'linux_amd64';dest.mkdir(parents=True)
   shutil.copy2(build/'bin'/binary,dest/binary)
  # Per-binding sockets and credentials are deliberately distinct even though
  # the cell.red and cell.blue instances execute the same provider binary.
  policy={'version':1,'runtime':runtime,'state_dir':str(lab/'leases'),'artifacts':{
   SOURCE:{'sha256':manifest['binaries']['terraform-provider-cell_v0.1.0'],'image':image},
   NORMAL:{'sha256':manifest['binaries']['terraform-provider-random_v3.7.2'],'image':image}},'bindings':[
   {'source':NORMAL,'configuration':'provider["'+NORMAL+'"]','instance_key':''},
   *[{'source':SOURCE,'configuration':'provider["'+SOURCE+'"].'+s,'instance_key':'','files':{'token':str(lab/(s+'.token'))},'services':{'api':str(lab/(s+'.sock'))}} for s in ('red','blue')]]}
  policyPath=lab/'policy.json';write_private(policyPath,json.dumps(policy))
  for scenario in ('default','environment_only','whole_job','instance_scoped'):
   work=lab/scenario;work.mkdir();shutil.copy2(ROOT/'examples/main.tf',work/'main.tf')
   vars={'unassigned_canary':str(lab/'unassigned.canary')}
   for s in ('red','blue'):
    vars[s+'_socket']='/services/api.sock' if scenario=='instance_scoped' else str(lab/(s+'.sock'))
    vars[s+'_token']='/credentials/token' if scenario=='instance_scoped' else str(lab/(s+'.token'))
   write_private(work/'terraform.tfvars.json',json.dumps(vars))
   cli=work/'tofurc';write_private(cli,'provider_installation {\n filesystem_mirror {\n path = '+json.dumps(str(mirror))+'\n }\n}\n')
   extras={'TF_CLI_CONFIG_FILE':str(cli),'TF_IN_AUTOMATION':'1','CELL_LAB_UNRELATED':'LAB_UNRELATED_ENV_CANARY'}
   binary=build/'bin'/({'environment_only':'tofu-env-only','instance_scoped':'tofu-scoped'}.get(scenario,'tofu-original'))
   if scenario=='instance_scoped':extras['TOFU_PROVIDER_ISOLATION_POLICY']=str(policyPath)
   def tofu(*args,capture=False):
    if scenario!='whole_job':return run([str(binary),*args],work,extras,capture)
    # A whole-job boundary deliberately shares the *lab's* directories and
    # artificial credentials, never the operator's home or real secrets.
    cmd=[runtime,'--remote=false','run','--rm','--pull=never','--network=none','--userns=keep-id','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--timeout=300','--unsetenv-all','--http-proxy=false','--env-host=false','--entrypoint=[]','--tmpfs=/tmp:rw,nosuid,nodev,mode=1777','--volume',str(lab)+':'+str(lab)+':rw','--volume',str(binary)+':/tofu:ro','--workdir',str(work)]
    cmd+=['--env','HOME=/tmp','--env','TMPDIR=/tmp']
    for k,v in extras.items():cmd+=['--env',k+'='+v]
    return run(cmd+[image,'/tofu',*args],capture=capture)
   tofu('init','-input=false');tofu('validate');tofu('apply','-input=false','-auto-approve')
   actual=json.loads(tofu('output','-json','dependency_result',capture=True))
   if not actual['red_id'].startswith('red-') or not actual['blue_id'].startswith('blue-'):raise RuntimeError('alias received the wrong fixture authority')
   if actual['red_upstream']!=actual['anchor'] or actual['blue_upstream']!=actual['red_id']:raise RuntimeError('legitimate graph dependency failed')
   for s in ('red','blue'):
    chk=actual[s+'_checks']
    if not chk.get('own_credential_readable') or not chk.get('own_api_operation_completed') or not chk.get('self_process_information_available'):raise RuntimeError('inoperative provider is not isolation success')
    expected_env=scenario in ('default','whole_job')
    expected_file=scenario!='instance_scoped'
    if chk.get('unrelated_environment_visible')!=expected_env or chk.get('unassigned_file_readable')!=expected_file:raise RuntimeError('unexpected canary outcome: '+scenario)
   tofu('plan','-input=false','-detailed-exitcode')
   tofu('destroy','-input=false','-auto-approve')
   results[scenario]=actual
   (out/(scenario+'.json')).write_text(json.dumps(actual,indent=2)+'\n')
  journal=lab/'leases/events.jsonl'
  if not journal.exists():raise RuntimeError('no core-side launch evidence')
  shutil.copy2(journal,out/'isolation-events.jsonl')
  events=[json.loads(line) for line in journal.read_text().splitlines()]
  prepared={e['invocation'] for e in events if e['event']=='prepared'}
  removed={e['invocation'] for e in events if e['event']=='lease_removed'}
  if not prepared or prepared!=removed:raise RuntimeError('provider lease cleanup was not confirmed')
  phases={e['scope']['phase'] for e in events if e['event']=='prepared'}
  if not {'schema','validation','configured'}<=phases:raise RuntimeError('missing lifecycle phase evidence')
  for cid in prepared:
   probe=subprocess.run([runtime,'--remote=false','container','exists',cid],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
   require_container_absent(probe.returncode)
  pending_summary={'status':'COMPLETED_LOCAL_PROTOCOL_LAB','cloud_compatibility_tested':False,'build_manifest':manifest,'results':results}
 except BaseException as e:
  (out/'failure.json').write_text(json.dumps({'status':'FAILED_NOT_SECURITY_SUCCESS','reason_type':type(e).__name__,'completed_scenarios':list(results)},indent=2)+'\n')
  raise
 finally:
  # Remove only invocation IDs from our own protected journal. Never prune the
  # host's global containers/images or delete a repository.
  journal=lab/'leases/events.jsonl'
  if journal.exists():
   ids=set()
   import re
   for line in journal.read_text().splitlines():
    try:
     cid=json.loads(line)['invocation']
     if re.fullmatch(r'tofu-cell-[0-9a-f]{32}',cid):ids.add(cid)
    except (ValueError,KeyError):pass
   for cid in ids:subprocess.run([runtime,'--remote=false','rm','--force','--ignore',cid],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=True)
  for p in procs:
   p.terminate()
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:p.kill();p.wait()
  for h in handles:h.close()
  # Tokens are generated here and never exported. This is deletion, not secure
  # erasure. Failure to clean up is surfaced by Python, not suppressed.
  shutil.rmtree(lab)
 # This line is unreachable if any operation or cleanup raised an error.
 (out/'summary.json').write_text(json.dumps(pending_summary,indent=2)+'\n')

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--runtime',default='/usr/bin/podman');a=p.parse_args()
 try:main(a.build.resolve(),a.out.resolve(),a.runtime)
 except (RuntimeError,OSError,subprocess.SubprocessError) as e:raise SystemExit('LAB STOPPED: '+str(e))
