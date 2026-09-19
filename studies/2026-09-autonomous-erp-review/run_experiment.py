"""Run all predeclared scripted-policy experiments. No network access or API calls."""
from pathlib import Path
import csv,gzip,json,hashlib,platform,time
from dataclasses import asdict
import numpy as np
import pandas as pd
from simulation import Config,PROFILES,REGIMES,prepare,simulate,generate_paths

ROOT=Path(__file__).resolve().parent

def write_json(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def main():
    start=time.perf_counter()
    for d in ('data','results','execution'):(ROOT/d).mkdir(exist_ok=True)
    inputs=[];results=[]
    for seed in range(41000,41120):
        paths=generate_paths(seed)
        for regime in REGIMES:
            inputs.append({'seed':seed,'regime':regime,'train':paths['train'],'demand':paths[regime]})
    raw=''.join(json.dumps(r,sort_keys=True,separators=(',',':'))+'\n' for r in inputs).encode()
    (ROOT/'data/demand_paths.jsonl').write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    full_primary_steps=0
    # mtime=0 makes the gzip container reproducible; payload is deterministic.
    with (ROOT/'results/primary_trajectories.jsonl.gz').open('wb') as fo:
      with gzip.GzipFile(fileobj=fo,mode='wb',mtime=0,compresslevel=5) as gz:
       for k,row in enumerate(inputs):
        for lead in (1,4):
            c=Config(lead=lead);p=prepare(row['train'],row['demand'],c)
            variants=[('baseline',0,0)]+[(profile,delay,fee) for profile in PROFILES
                                          for delay in (0,2,4) for fee in (0,25,100)]
            for profile,delay,fee in variants:
                primary=profile=='baseline' or fee==25
                out,trace=simulate(row['train'],row['demand'],c,profile,delay,fee,prepared=p,keep_trace=primary)
                ident={'seed':row['seed'],'regime':row['regime'],'lead':lead,
                       'profile':profile,'review_delay':delay,'review_fee':fee}
                results.append({**ident,**out})
                if primary:
                    payload={**ident,'outcome':out,'steps':trace}
                    gz.write((json.dumps(payload,separators=(',',':'),allow_nan=False)+'\n').encode())
                    full_primary_steps+=len(trace)
        if (k+1)%120==0:print(f'Processed {k+1}/{len(inputs)} demand paths',flush=True)
    df=pd.DataFrame(results)
    assert len(df)==35520 and len(inputs)==480
    keys=['seed','regime','lead']
    base=df[df.profile=='baseline'][keys+['net_surplus','fill_rate','mean_inventory']].rename(columns={
         'net_surplus':'baseline_surplus','fill_rate':'baseline_fill','mean_inventory':'baseline_inventory'})
    paired=df.merge(base,on=keys,validate='many_to_one')
    paired['delta_surplus']=paired.net_surplus-paired.baseline_surplus
    paired['delta_fill_pp']=(paired.fill_rate-paired.baseline_fill)*100
    paired.to_csv(ROOT/'results/all_trajectories.csv',index=False,float_format='%.10f')
    core=paired[(paired.profile!='baseline') & (paired.review_fee==25)]
    rng=np.random.default_rng(20260919)
    boot_ix=rng.integers(0,120,size=(2000,120))
    summaries=[]
    # Group by seed first: regimes and lead times are paired within a cluster.
    for regime in list(REGIMES)+['all_equal_weight']:
      for leadset in ['both','1','4']:
       part=core if regime=='all_equal_weight' else core[core.regime==regime]
       if leadset!='both':part=part[part.lead==int(leadset)]
       for (profile,delay),g in part.groupby(['profile','review_delay'],sort=True):
        cluster=g.groupby('seed',sort=True).agg(delta=('delta_surplus','mean'),base=('baseline_surplus','mean'),
               surplus=('net_surplus','mean'),fill=('fill_rate','mean'),delta_fill=('delta_fill_pp','mean'),
               inventory=('mean_inventory','mean'),nreview=('review_count','mean'),cost=('review_cost','mean'))
        if len(cluster)!=120:raise AssertionError('Incomplete seed clusters')
        delta=cluster.delta.to_numpy();den=cluster.base.mean()
        boot=delta[boot_ix].mean(axis=1)
        percent_boot=100*boot/cluster.base.to_numpy()[boot_ix].mean(axis=1)
        lo,hi=np.quantile(boot,[.025,.975]);plo,phi=np.quantile(percent_boot,[.025,.975])
        summaries.append({'regime':regime,'lead':leadset,'profile':profile,'review_delay':int(delay),'review_fee':25,
          'seed_clusters':120,'scenario_rows':len(g),'mean_baseline_surplus':den,
          'mean_policy_surplus':cluster.surplus.mean(),'mean_delta_surplus':delta.mean(),
          'delta_mc95_low':lo,'delta_mc95_high':hi,'relative_mean_change_pct':100*delta.mean()/den,
          'relative_mc95_low':plo,'relative_mc95_high':phi,'mean_fill_pct':cluster.fill.mean()*100,
          'mean_delta_fill_pp':cluster.delta_fill.mean(),'mean_inventory':cluster.inventory.mean(),
          'mean_reviews':cluster.nreview.mean(),'mean_review_cost':cluster.cost.mean(),
          'scenario_harm_pct':100*(g.delta_surplus<0).mean()})
    summary=pd.DataFrame(summaries)
    summary.to_csv(ROOT/'results/primary_summary.csv',index=False,float_format='%.8f')
    sensitivity=paired[paired.profile!='baseline'].groupby(['regime','lead','profile','review_delay','review_fee'],sort=True).agg(
        mean_delta_surplus=('delta_surplus','mean'),mean_surplus=('net_surplus','mean'),mean_baseline=('baseline_surplus','mean'),
        fill_pct=('fill_rate',lambda x:100*x.mean()),mean_reviews=('review_count','mean')).reset_index()
    sensitivity['relative_mean_change_pct']=100*sensitivity.mean_delta_surplus/sensitivity.mean_baseline
    sensitivity.to_csv(ROOT/'results/sensitivity_summary.csv',index=False,float_format='%.8f')
    cfg=asdict(Config());cfg['lead']=[1,4]
    write_json(ROOT/'execution/run_metadata.json',{'study':'scripted-profile intervention simulation','date':'2026-09-19',
       'human_participants':0,'new_llm_calls':0,'seed_clusters':120,'demand_paths':480,'scenario_settings':960,
       'total_trajectories':len(df),'primary_trajectories':12480,'primary_period_records':full_primary_steps,
       'input_sha256':digest,'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
       'config':cfg,'wall_seconds':round(time.perf_counter()-start,3)})
    print(summary[(summary.regime=='all_equal_weight')&(summary.lead=='both')][['profile','review_delay','relative_mean_change_pct','scenario_harm_pct']].to_string(index=False))
    print('Completed',len(df),'trajectories;',full_primary_steps,'retained period records',flush=True)

if __name__=='__main__':main()
