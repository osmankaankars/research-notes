"""Standalone article graphics from verified outputs. Never image-generated data."""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
R=Path(__file__).resolve().parent
F=R/'figures';F.mkdir(exist_ok=True)
s=pd.read_csv(R/'results/primary_summary.csv')
profiles=['cash_buffer','service_buffer','trend_response','plan_anchored']
labels={'cash_buffer':'Cash buffer','service_buffer':'Service buffer','trend_response':'Trend response','plan_anchored':'Plan anchored'}
regimes=['stationary','upshift','downshift','pulse']
reglabels=['Stable demand','Sustained rise','Sustained fall','Temporary spike']

def finish(fig,name):
    fig.savefig(F/(name+'.png'),dpi=250)
    fig.savefig(F/(name+'.svg'))
    plt.close(fig)

fig,ax=plt.subplots(figsize=(12.4,6.8))
fig.subplots_adjust(left=.21,right=.94,bottom=.22,top=.73)
for j,(reg,marker) in enumerate(zip(regimes,['o','s','^','D'])):
    d=s[(s.regime==reg)&(s.lead=='both')&(s.review_delay==0)].set_index('profile').loc[profiles]
    y=np.arange(4)+(j-1.5)*.145
    x=d.relative_mean_change_pct.to_numpy()
    lo=x-d.relative_mc95_low.to_numpy();hi=d.relative_mc95_high.to_numpy()-x
    ax.errorbar(x,y,xerr=np.vstack([lo,hi]),fmt=marker,markersize=6,capsize=3,linestyle='none',label=reglabels[j])
ax.axvline(0,linestyle='--',linewidth=1.1,alpha=.65)
ax.set_yticks(np.arange(4),[labels[p] for p in profiles],fontsize=12)
ax.invert_yaxis();ax.set_xlim(-3.65,.42)
ax.xaxis.set_major_formatter(FuncFormatter(lambda x,p:f'{x:+.1f}%' if x else '0'))
ax.tick_params(axis='x',labelsize=11);ax.set_xlabel('Change in mean net surplus vs the same automated baseline',fontsize=11,labelpad=12)
ax.spines[['top','right']].set_visible(False);ax.grid(axis='x',alpha=.17)
fig.text(.075,.943,'Four review policies, different consequences',fontsize=21,weight='bold')
fig.text(.075,.89,'Scripted-policy simulation | Immediate review | Fee: 25 model units per request',fontsize=11)
fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.54,.843),ncol=4,frameon=False,fontsize=10.4)
fig.text(.075,.093,'Points: paired scenario means. Bars: 95% seed-cluster bootstrap intervals within the specified simulator.',fontsize=9.3)
fig.text(.075,.054,'120 random seeds × 4 demand regimes × 2 lead times. Equal lead-time weighting. No human participants or new LLM runs.',fontsize=9.3)
finish(fig,'01_review_by_regime')

fig,ax=plt.subplots(figsize=(12.4,6.4))
fig.subplots_adjust(left=.105,right=.77,bottom=.23,top=.79)
for p,m in zip(profiles,['o','s','^','D']):
    d=s[(s.regime=='all_equal_weight')&(s.lead=='both')&(s.profile==p)].sort_values('review_delay')
    x=d.review_delay.to_numpy();y=d.relative_mean_change_pct.to_numpy()
    ax.errorbar(x,y,yerr=np.vstack([y-d.relative_mc95_low.to_numpy(),d.relative_mc95_high.to_numpy()-y]),
                fmt=m+'-',linewidth=1.8,markersize=6,capsize=3)
    ax.text(4.15,y[-1],labels[p],fontsize=11,va='center')
ax.axhline(0,linestyle='--',linewidth=1.0,alpha=.65)
ax.set_xlim(-.2,4.1);ax.set_ylim(-2.2,.1)
ax.set_xticks([0,2,4],['0 periods','2 periods','4 periods'],fontsize=11)
ax.yaxis.set_major_formatter(FuncFormatter(lambda x,p:f'{x:+.1f}%' if x else '0'))
ax.set_ylabel('Change in mean net surplus',fontsize=11,labelpad=12)
ax.set_xlabel('Delay before a revised inventory target takes effect',fontsize=11,labelpad=12)
ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.17)
fig.text(.075,.943,'Review timing changes the result',fontsize=21,weight='bold')
fig.text(.075,.89,'Equal-weight mix of the four demand regimes and both lead times | Fee: 25 model units',fontsize=11)
fig.text(.075,.102,'The baseline keeps ordering while a review is pending. Revised targets stay active for four periods.',fontsize=9.4)
fig.text(.075,.063,'Bars: 95% seed-cluster bootstrap intervals. Delays are assumed, not measured human response times.',fontsize=9.4)
finish(fig,'02_review_delay')

print('Exported two evidence-based article figures in PNG and SVG.')
