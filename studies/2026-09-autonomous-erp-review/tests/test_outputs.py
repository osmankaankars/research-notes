"""Checks completed runs; skips rather than invents results before execution."""
import unittest,csv,gzip,json,hashlib,math
from pathlib import Path
from statistics import mean,stdev
import pandas as pd
from simulation import Config,simulate,prepare
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless((ROOT/'results/all_trajectories.csv').exists(),'Run experiment first')
class OutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df=pd.read_csv(ROOT/'results/all_trajectories.csv')
        cls.inputs={(x['seed'],x['regime']):x for x in map(json.loads,(ROOT/'data/demand_paths.jsonl').read_text().splitlines())}
    def test_trajectory_keys(self):
        self.assertEqual(len(self.df),35520)
        self.assertFalse(self.df.duplicated(['seed','regime','lead','profile','review_delay','review_fee']).any())
    def test_counts_not_independent_trials(self):
        self.assertEqual(self.df.seed.nunique(),120)
        self.assertEqual(len(self.df[['seed','regime','lead']].drop_duplicates()),960)
        self.assertEqual(len(self.inputs),480)
    def test_fees_are_charged(self):
        self.assertTrue(((self.df.review_count*self.df.review_fee-self.df.review_cost).abs()<1e-8).all())
        self.assertTrue((self.df.review_count<=4).all())
    def test_schedules_have_equal_request_counts(self):
        r=self.df[self.df.profile!='baseline'].groupby(['seed','regime','lead']).review_count.nunique()
        self.assertTrue((r==1).all())
    def test_seed_regime_prefixes(self):
        for seed in range(41000,41120):
            reference=self.inputs[(seed,'stationary')]
            for regime in ('upshift','downshift','pulse'):
                x=self.inputs[(seed,regime)]
                self.assertEqual(x['train'],reference['train'])
                self.assertEqual(x['demand'][:20],reference['demand'][:20])
    def test_input_hash_and_protocol_lock(self):
        expected=json.loads((ROOT/'execution/run_metadata.json').read_text())['input_sha256']
        self.assertEqual(hashlib.sha256((ROOT/'data/demand_paths.jsonl').read_bytes()).hexdigest(),expected)
        recorded=(ROOT/'execution/protocol_before_run.sha256').read_text().split()[0]
        self.assertEqual(hashlib.sha256((ROOT/'docs/PROTOCOL.md').read_bytes()).hexdigest(),recorded)
    def test_no_false_human_or_model_count(self):
        x=json.loads((ROOT/'execution/run_metadata.json').read_text())
        self.assertEqual(x['human_participants'],0)
        self.assertEqual(x['new_llm_calls'],0)
    def test_primary_and_all_ledger_independently(self):
        runs=steps=0
        with gzip.open(ROOT/'results/primary_trajectories.jsonl.gz','rt') as f:
            for line in f:
                x=json.loads(line);run=x['outcome'];rows=x['steps'];runs+=1
                oldstock=run['initial_stock'];cash=20000.;pipe=0;totalorders=totalsales=0
                schedule={};reviewtimes=[]
                for r in rows:
                    steps+=1;t=r['t'];arrived=schedule.get(t,0)
                    self.assertEqual(r['arrivals'],arrived)
                    self.assertEqual(r['opening_stock'],oldstock+arrived)
                    self.assertEqual(r['sold'],min(oldstock+arrived,r['demand']))
                    stock=oldstock+arrived-r['sold'];pipe=pipe-arrived+r['order']
                    self.assertEqual(stock,r['on_hand_end']);self.assertEqual(pipe,r['pipeline_end'])
                    schedule[t+x['lead']]=schedule.get(t+x['lead'],0)+r['order']
                    if r['review_requested']:reviewtimes.append(t)
                    cash=cash+35*r['sold']-20*r['order']-0.4*stock-r['review_fee']
                    self.assertAlmostEqual(cash,r['cash_end'],places=6)
                    self.assertEqual(r['review_fee'],x['review_fee']*r['review_requested'])
                    self.assertLessEqual(r['order'],400)
                    self.assertLessEqual(r['inventory_position_after_order'],1200)
                    if r['order']>0:
                        self.assertGreaterEqual(r['cash_open']-r['review_fee']-20*r['order']+1e-8,2000)
                    oldstock=stock;totalorders+=r['order'];totalsales+=r['sold']
                self.assertTrue(all(b-a>=6 for a,b in zip(reviewtimes,reviewtimes[1:])))
                self.assertEqual(run['review_count'],len(reviewtimes))
                self.assertEqual(totalorders,run['orders']);self.assertEqual(totalsales,run['sold'])
                self.assertAlmostEqual(cash+10*(oldstock+pipe)-20000-20*run['initial_stock'],run['net_surplus'],places=6)
        self.assertEqual(runs,12480);self.assertEqual(steps,748800)
    def test_replay_sample(self):
        sample=self.df.iloc[::1776]
        for row in sample.itertuples():
            x=self.inputs[(row.seed,row.regime)];c=Config(lead=row.lead)
            result,_=simulate(x['train'],x['demand'],c,row.profile,row.review_delay,row.review_fee)
            self.assertAlmostEqual(result['net_surplus'],row.net_surplus,places=6)
    def test_summary_independent_group_means(self):
        summary=pd.read_csv(ROOT/'results/primary_summary.csv')
        for r in summary[summary.lead=='both'].itertuples():
            d=self.df[(self.df.profile==r.profile)&(self.df.review_fee==25)&(self.df.review_delay==r.review_delay)]
            if r.regime!='all_equal_weight':d=d[d.regime==r.regime]
            change=mean(d.net_surplus)-mean(d.baseline_surplus)
            self.assertAlmostEqual(change,r.mean_delta_surplus,places=6)
            self.assertAlmostEqual(100*change/mean(d.baseline_surplus),r.relative_mean_change_pct,places=6)
    def test_revision_targets_recomputed_without_helpers(self):
        count=0
        with gzip.open(ROOT/'results/primary_trajectories.jsonl.gz','rt') as f:
            for line in f:
                x=json.loads(line)
                if x['seed']!=41000:break
                history=self.inputs[(x['seed'],x['regime'])]['train'][:];train=history[:]
                active=None;expiry=-1;pending={};L=x['lead']
                for r in x['steps']:
                    t=r['t'];mu=mean(history[-12:]);sd=stdev(history[-12:])
                    base=math.ceil(mu*(L+1)+1.28*sd*math.sqrt(L+1))
                    self.assertEqual(r['baseline_target'],base)
                    if t in pending:active=pending[t];expiry=t+4
                    if r['review_requested']:
                        prof=x['profile'];z=1.28
                        if prof=='cash_buffer':z=0
                        elif prof=='service_buffer':z=2.326
                        elif prof=='trend_response':mu=mean(history[-3:])
                        elif prof=='plan_anchored':mu=mean(train);sd=stdev(train)
                        revision=math.ceil(mu*(L+1)+z*sd*math.sqrt(L+1))
                        self.assertEqual(revision,r['request_target'])
                        if x['review_delay']==0:active=revision;expiry=t+4
                        else:pending[t+x['review_delay']]=revision
                    expected=active if active is not None and t<expiry else base
                    self.assertEqual(expected,r['selected_target'])
                    history.append(r['demand']);count+=1
        self.assertEqual(count,8*13*60)

if __name__=='__main__':unittest.main()
