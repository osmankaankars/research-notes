"""Transparent inventory/review simulation. No LLMs or human participants.

Currency is arbitrary model units. Read docs/PROTOCOL.md and METHODS.md before
interpreting outputs. Policies see only the supplied historical observations.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from statistics import mean, stdev
from typing import Sequence
import numpy as np

PROFILES = ('cash_buffer', 'service_buffer', 'trend_response', 'plan_anchored')
REGIMES = ('stationary', 'upshift', 'downshift', 'pulse')

@dataclass(frozen=True)
class Config:
    lead: int = 1
    price: float = 35.0
    unit_cost: float = 20.0
    holding: float = 0.4
    initial_cash: float = 20000.0
    reserve: float = 2000.0
    order_cap: int = 400
    position_cap: int = 1200
    salvage_fraction: float = 0.5
    review_budget: int = 4
    review_gap: int = 6
    target_duration: int = 4
    def __post_init__(self):
        for key in ('lead','order_cap','position_cap','review_gap','target_duration'):
            if not isinstance(getattr(self,key),int) or getattr(self,key)<1:
                raise ValueError(key+' must be a positive integer')
        if not isinstance(self.review_budget,int) or self.review_budget<0:
            raise ValueError('invalid review budget')
        vals=(self.price,self.unit_cost,self.holding,self.initial_cash,self.reserve,self.salvage_fraction)
        if not all(math.isfinite(x) and x>=0 for x in vals) or self.unit_cost<=0:
            raise ValueError('invalid economic parameter')
        if self.salvage_fraction>1:raise ValueError('salvage fraction exceeds cost')

def target(mu:float,sd:float,lead:int,z:float)->int:
    if any(not math.isfinite(x) or x<0 for x in (mu,sd,z)) or lead<1:
        raise ValueError('invalid target inputs')
    return math.ceil(mu*(lead+1)+z*sd*math.sqrt(lead+1))

def moments(history:Sequence[int])->tuple[float,float]:
    if not history:raise ValueError('empty history')
    return float(mean(history)),float(stdev(history)) if len(history)>1 else 0.0

def profile_target(profile:str,history:Sequence[int],train:Sequence[int],lead:int)->int:
    if profile not in PROFILES and profile!='baseline':raise ValueError('unknown profile')
    mu,sd=moments(history[-12:])
    z=1.28
    if profile=='cash_buffer':z=0.0
    elif profile=='service_buffer':z=2.326
    elif profile=='trend_response':mu=float(mean(history[-3:]))
    elif profile=='plan_anchored':mu,sd=moments(train)
    return target(mu,sd,lead,z)

def review_trigger(history:Sequence[int])->bool:
    if len(history)<12:return False
    long=float(mean(history[-12:]));short=float(mean(history[-3:]))
    return abs(short-long)/max(long,1.0)>0.25

def order_quantity(desired:int,position:int,cash:float,c:Config)->int:
    affordable=max(0,math.floor((cash-c.reserve)/c.unit_cost+1e-12))
    return int(max(0,min(desired-position,c.order_cap,c.position_cap-position,affordable)))

def _validate_observations(values:Sequence[int],label:str)->list[int]:
    if not values:raise ValueError(label+' is empty')
    out=[]
    for v in values:
        if not math.isfinite(float(v)) or v<0 or float(v)!=int(v):
            raise ValueError(label+' must contain nonnegative integer observations')
        out.append(int(v))
    return out

def prepare(train:Sequence[int],demand:Sequence[int],c:Config)->dict:
    train=_validate_observations(train,'train');demand=_validate_observations(demand,'demand')
    history=list(train);plans=[]
    for observation in demand:
        plans.append({'targets':{p:profile_target(p,history,train,c.lead)
                                 for p in ('baseline',)+PROFILES},
                      'trigger':review_trigger(history)})
        history.append(observation)  # append only AFTER that period's policy inputs
    mu,sd=moments(train)
    return {'train':train,'demand':demand,'plans':plans,
            'initial_stock':min(c.position_cap,target(mu,sd,c.lead,1.28))}

def simulate(train:Sequence[int],demand:Sequence[int],c:Config,
             profile:str='baseline',delay:int=0,fee:float=25.0,
             *, prepared:dict|None=None, keep_trace:bool=True)->tuple[dict,list[dict]]:
    if profile not in ('baseline',)+PROFILES:raise ValueError('unknown profile')
    if not isinstance(delay,int) or delay<0:raise ValueError('invalid delay')
    if not math.isfinite(fee) or fee<0:raise ValueError('invalid fee')
    p=prepared if prepared is not None else prepare(train,demand,c)
    values=p['demand'];plans=p['plans'];initial=p['initial_stock']
    stock=initial;cash=c.initial_cash
    arrivals=[0]*(len(values)+c.lead+1)
    pipeline_total=0;reviews=[];last_request=-c.review_gap
    active_target=None;active_until=-1;review_count=0
    totals={'orders':0,'sold':0,'demand_total':0,'lost':0,'holding_cost':0.0,
            'review_cost':0.0,'inventory_total':0,'request_target_changes':0}
    rows=[]
    for t,d in enumerate(values):
        arrived=arrivals[t];stock+=arrived;pipeline_total-=arrived
        opening_stock=stock;cash_open=cash
        delivered=-1
        due=[q for q in reviews if q['due']==t]
        for q in due:
            active_target=q['target'];active_until=t+c.target_duration
            delivered=q['request_t']
        reviews=[q for q in reviews if q['due']>t]
        baseline=plans[t]['targets']['baseline']
        requested=(profile!='baseline' and plans[t]['trigger']
                   and review_count<c.review_budget and t-last_request>=c.review_gap)
        charge=0.0;request_target=-1
        if requested:
            review_count+=1;last_request=t;charge=fee;cash-=charge
            request_target=plans[t]['targets'][profile]
            totals['request_target_changes']+=int(request_target!=baseline)
            if delay==0:
                active_target=request_target;active_until=t+c.target_duration;delivered=t
            else:reviews.append({'target':request_target,'request_t':t,'due':t+delay})
        desired=active_target if active_target is not None and t<active_until else baseline
        desired=int(desired)
        position=stock+pipeline_total
        q=order_quantity(desired,position,cash,c)
        cash-=q*c.unit_cost;arrivals[t+c.lead]+=q;pipeline_total+=q
        sold=min(stock,d);stock-=sold;lost=d-sold
        revenue=c.price*sold;holding=c.holding*stock
        cash+=revenue-holding
        totals['orders']+=q;totals['sold']+=sold;totals['lost']+=lost
        totals['demand_total']+=d;totals['holding_cost']+=holding
        totals['review_cost']+=charge;totals['inventory_total']+=stock
        if keep_trace:
            rows.append({'t':t,'arrivals':arrived,'opening_stock':opening_stock,
              'demand':d,'baseline_target':baseline,'selected_target':desired,
              'signal':int(plans[t]['trigger']),'review_requested':int(requested),
              'request_target':request_target,'delivered_request_t':delivered,
              'review_fee':charge,'order':q,'inventory_position_after_order':position+q,
              'sold':sold,'lost':lost,'on_hand_end':stock,'pipeline_end':pipeline_total,
              'cash_open':cash_open,'sales_revenue':revenue,'purchase_cost':q*c.unit_cost,
              'holding_cost':holding,'cash_end':cash})
    terminal=c.salvage_fraction*c.unit_cost*(stock+pipeline_total)
    capital=c.initial_cash+c.unit_cost*initial
    outcome={**totals,'initial_stock':initial,'end_stock':stock,'end_pipeline':pipeline_total,
      'end_cash':cash,'terminal_credit':terminal,'net_surplus':cash+terminal-capital,
      'cash_surplus_before_terminal':cash-capital,'mean_inventory':totals['inventory_total']/len(values),
      'fill_rate':(totals['sold']/totals['demand_total']) if totals['demand_total'] else None,
      'review_count':review_count,'periods':len(values)}
    return outcome,rows

def generate_paths(seed:int)->dict:
    rng=np.random.default_rng(seed)
    shocks=rng.standard_normal(80)
    def realise(mus,z):
        return np.maximum(0,np.rint(np.asarray(mus)*(1.0+0.25*z))).astype(int).tolist()
    result={'train':realise(np.full(20,100.0),shocks[:20])}
    for r in REGIMES:
        mus=np.full(60,100.0)
        if r=='upshift':mus[20:]=150.0
        elif r=='downshift':mus[20:]=60.0
        elif r=='pulse':mus[20:28]=160.0
        result[r]=realise(mus,shocks[20:])
    return result
