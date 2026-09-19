"""Render standalone evidence figures from audited CSVs. Plotting is optional."""
from pathlib import Path
import csv
from decimal import Decimal, ROUND_HALF_UP
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'figures'
OUT.mkdir(exist_ok=True)


def save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=240)
    fig.savefig(OUT/(name+'.svg'))
    plt.close(fig)


def main():
    cap=list(csv.DictReader((ROOT/'results/audit/capability_outcomes.csv').open()))
    order={'DURABLE':0,'EXPIRING':1,'OPAQUE':2}
    cap.sort(key=lambda r:order[r['capability']])
    ys=list(range(3));n=[int(r['cases']) for r in cap]
    a=[100*int(r['completed'])/int(r['cases']) for r in cap]
    b=[100*int(r['unresolved'])/int(r['cases']) for r in cap]
    c=[100*int(r['budget_blocked'])/int(r['cases']) for r in cap]
    fig,ax=plt.subplots(figsize=(12.4,6.7))
    fig.subplots_adjust(left=.16,right=.96,top=.76,bottom=.30)
    fig.text(.06,.94,'Approval Is Not a Receipt',fontsize=12)
    fig.text(.06,.875,'Safety does not guarantee completion',fontsize=23,fontweight='bold')
    fig.text(.06,.817,'Strong intent-scoped reference | 120 fixed scenarios | No model inference',fontsize=11)
    ax.barh(ys,a,height=.50,label='Verified completion')
    ax.barh(ys,b,left=a,height=.50,label='Unresolved external outcome')
    ax.barh(ys,c,left=[x+y for x,y in zip(a,b)],height=.50,label='Insufficient shared budget')
    for i,r in enumerate(cap):
        ax.text(a[i]/2,i,f"{r['completed']}/{r['cases']}",ha='center',va='center',fontsize=12,fontweight='bold')
        if b[i]: ax.text(a[i]+b[i]/2,i,f"{r['unresolved']}/{r['cases']}",ha='center',va='center',fontsize=12,fontweight='bold')
        ax.annotate(f"{r['budget_blocked']}/{r['cases']}",(100-c[i]/2,i-.25),xytext=(100-c[i]/2,i-.42),ha='center',va='center',fontsize=9)
    ax.set_yticks(ys,[f"{r['capability']}\n{r['cases']} scenarios" for r in cap],fontsize=11)
    ax.set_ylim(2.55,-.65);ax.set_xlim(0,100)
    ax.set_xticks([0,25,50,75,100],['0%','25%','50%','75%','100%'])
    ax.set_xlabel('Share of cases within each specified supplier contract',fontsize=11)
    ax.spines[['top','right']].set_visible(False)
    fig.legend(*ax.get_legend_handles_labels(),loc='lower left',bbox_to_anchor=(.06,.17),ncol=3,frameon=False,fontsize=9.5)
    fig.text(.06,.11,'DURABLE / EXPIRING fixtures include definitive status or explicit closure and cancellation fences.',fontsize=9.5)
    fig.text(.06,.067,'OPAQUE offers no reliable final lookup. Pending work is not counted as successful. Synthetic fixture counts only.',fontsize=9.5)
    save(fig,'01_capability_and_completion')

    rows=list(csv.DictReader((ROOT/'results/audit/executor_tradeoffs.csv').open()))
    labels={'request_only':('Request-only','Diagnostic weak control'),
            'operation_scoped':('Operation-scoped','Intermediate ablation'),
            'intent_scoped':('Intent-scoped','Strong conventional reference')}
    fig,ax=plt.subplots(figsize=(12.4,6.8))
    fig.subplots_adjust(left=.10,right=.96,top=.77,bottom=.24)
    fig.text(.06,.94,'Approval Is Not a Receipt',fontsize=12)
    fig.text(.06,.875,'Track the business request, not only each API call',fontsize=22,fontweight='bold')
    fig.text(.06,.817,'Same 120 cases per strategy | Actual committed effects, not rejected proposals',fontsize=11)
    for r,marker in zip(rows,['s','^','o']):
        x=float(r['mean_calls']);y=int(r['invalid_case_count'])
        ax.scatter([x],[y],s=140,marker=marker)
        title,scope=labels[r['strategy']]
        offset=(18,-10) if y>30 else (18,20)
        ax.annotate(f"{title}: {y}/120 cases\n{scope}\n{Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} calls per case",(x,y),xytext=offset,textcoords='offset points',fontsize=10,va='top' if y>30 else 'bottom')
    ax.set_xlim(0,7.4);ax.set_ylim(-5,85)
    ax.set_yticks([0,15,30,45,60,75])
    ax.set_xlabel('Mean supplier calls per case, including unresolved and unsuccessful cases',fontsize=10.5)
    ax.set_ylabel('Cases with at least one invalid committed effect',fontsize=10.5)
    ax.spines[['top','right']].set_visible(False)
    fig.text(.06,.125,'Invalid effects include conflicting revisions, repeat effects, and authority/budget violations.',fontsize=9.5)
    fig.text(.06,.083,'Operation-scoped: zero repeated-operation duplicates, but 15 cases with conflicting commitments.',fontsize=9.5)
    fig.text(.06,.041,'Calls are recovery effort, not latency or a causal explanation. Strong reference completed 97/120; 23 stayed open.',fontsize=9.5)
    save(fig,'02_effects_and_recovery_effort')
    print('Two PNG and SVG evidence figures rendered from audited result tables.')

if __name__=='__main__':main()
