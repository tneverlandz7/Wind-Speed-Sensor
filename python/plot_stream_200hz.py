#!/usr/bin/env python3
"""Plot 200Hz STM32 velocity estimates versus manually annotated reference.
These plots are qualitative unless reference pressure timestamps are synchronized.
"""
import argparse
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def plot(df,path,title):
    if len(df)<2:return False
    fig,ax=plt.subplots(figsize=(7,3.4))
    x=df.host_elapsed_s.to_numpy(dtype=float)
    ax.plot(x,df.wind_mps.astype(float),label='STM32 estimate (200Hz output)',lw=1.0)
    ax.plot(x,df.ref_mps.astype(float),label='Reference, manually annotated',lw=1.5,alpha=0.8)
    ax.set(xlabel='Host elapsed time (s)',ylabel='Airspeed (m/s)',title=title)
    ax.grid(True,alpha=.25)
    ax.legend(loc='best',fontsize=8)
    fig.tight_layout();fig.savefig(path);plt.close(fig)
    return True


def run(file,out):
    out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(file)
    needed={'kind','host_elapsed_s','wind_mps','phase','ref_mps'}
    if not needed.issubset(df.columns):raise ValueError('Missing columns: '+str(needed-set(df.columns)))
    s=df[df.kind=='STREAM'].copy()
    s=s[pd.to_numeric(s.wind_mps,errors='coerce').notna()]
    if not len(s):raise ValueError('No 200Hz STREAM rows. Use g/j after starting tools/logger_200hz.py')
    s.to_csv(out/'stream_numeric_200hz.csv',index=False)
    for phase in ('step','ramp'):
        part=s[s.phase==phase]
        if plot(part,out/f'fig_{phase}_200hz_ANNOTATED.pdf',f'{phase.title()} response: annotated reference (NOT synchronized)'):
            print('Wrote',out/f'fig_{phase}_200hz_ANNOTATED.pdf')
    plot(s,out/'fig_stream_all_200hz_ANNOTATED.pdf','200 Hz STM32 output and manual pressure annotations')
    rate=(len(s)-1)/(float(s.host_elapsed_s.iloc[-1])-float(s.host_elapsed_s.iloc[0]))
    print('200Hz rows:',len(s),'approx host receive throughput:',round(rate,2),'rows/s')
    print('WARNING: do NOT calculate official dynamic MSE/rise time from manual annotations; use synchronized Dwyer/Pitot reference.')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=Path('outputs/lab_200hz'))
    a=ap.parse_args()
    run(a.input,a.out)
