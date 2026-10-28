"""Compare logged Nucleo 200 Hz STREAM against externally recorded Dwyer/Pitot ground truth.

Requires accurately aligned time axes. --ref-time-offset-s is an explicitly
measured shift from reference clock to logger's host_elapsed_s (not guessed).
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def stats(reference, prediction, reference_sigma=None):
    residual=np.asarray(prediction)-np.asarray(reference)
    bias=float(np.mean(residual))
    var=float(np.mean((residual-bias)**2))
    output={'n':len(residual),'MSE_m2_s2':float(np.mean(residual**2)),
            'RMSE_m_s':float(np.sqrt(np.mean(residual**2))),
            'MAE_m_s':float(np.mean(np.abs(residual))),
            'bias_m_s':bias,'residual_sigma_m_s':float(np.sqrt(var))}
    if reference_sigma is not None:
        refvar=float(np.mean(np.asarray(reference_sigma)**2))
        sensorvar=max(0.0,var-refvar)
        output['mean_reference_variance_m2_s2']=refvar
        output['RMSE_adjusted_m_s']=float(np.sqrt(bias*bias+sensorvar))
        output['RMSE_adjusted_assumptions']='Independent errors and approximately unbiased reference'
    return output


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sensor',type=Path,required=True,help='CSV logged by logger_200hz.py')
    p.add_argument('--reference',type=Path,required=True,help='CSV from official Dwyer/Pitot recorder')
    p.add_argument('--ref-time-col',default='time_s')
    p.add_argument('--ref-speed-col',default='speed_mps')
    p.add_argument('--ref-sigma-col',default=None,help='Optional 1-sigma reference speed uncertainty in m/s')
    p.add_argument('--ref-time-offset-s',type=float,required=True,
                   help='Shift reference timestamp into sensor host_elapsed_s (must be measured/aligned)')
    p.add_argument('--out',type=Path,default=Path('outputs/official_comparison'))
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    s=pd.read_csv(a.sensor)
    r=pd.read_csv(a.reference)
    for name in ('kind','host_elapsed_s','wind_mps','phase'):
        if name not in s.columns:raise ValueError(f'Sensor CSV missing {name}')
    for name in (a.ref_time_col,a.ref_speed_col):
        if name not in r.columns:raise ValueError(f'Reference CSV missing {name}')
    if a.ref_sigma_col and a.ref_sigma_col not in r.columns:
        raise ValueError(f'Reference CSV missing {a.ref_sigma_col}')
    s=s[s.kind=='STREAM'].copy()
    s['host_elapsed_s']=pd.to_numeric(s.host_elapsed_s,errors='coerce')
    s['wind_mps']=pd.to_numeric(s.wind_mps,errors='coerce')
    s=s.dropna(subset=['host_elapsed_s','wind_mps']).sort_values('host_elapsed_s')
    ref=pd.DataFrame({'t':pd.to_numeric(r[a.ref_time_col],errors='coerce')+a.ref_time_offset_s,
                      'speed':pd.to_numeric(r[a.ref_speed_col],errors='coerce')})
    if a.ref_sigma_col:
        ref['sigma']=pd.to_numeric(r[a.ref_sigma_col],errors='coerce')
    ref=ref.dropna().groupby('t',as_index=False).mean().sort_values('t')
    if len(s)<2 or len(ref)<2:raise ValueError('Need at least two valid rows from both data sources')
    t=s.host_elapsed_s.to_numpy(dtype=float)
    valid=(t>=ref.t.iloc[0])&(t<=ref.t.iloc[-1])
    paired=s.loc[valid].copy()
    if len(paired)<2:
        raise ValueError('No overlapping timestamps! Align clocks with a real shared trigger and --ref-time-offset-s')
    tt=paired.host_elapsed_s.to_numpy(dtype=float)
    paired['reference_mps']=np.interp(tt,ref.t.to_numpy(),ref.speed.to_numpy())
    paired['error_mps']=paired.wind_mps-paired.reference_mps
    ref_sigma=None
    if a.ref_sigma_col:
        paired['reference_sigma_mps']=np.interp(tt,ref.t.to_numpy(),ref.sigma.to_numpy())
        ref_sigma=paired.reference_sigma_mps
    result={'note':'This comparison only valid if reference/device timestamps were independently aligned and reference values were measured, not inferred from manual knob annotations.',
            'ref_time_offset_s':a.ref_time_offset_s,
            'overall':stats(paired.reference_mps,paired.wind_mps,ref_sigma),
            'by_phase':{}}
    for phase,chunk in paired.groupby('phase'):
        if len(chunk)>2:
            sg=chunk.reference_sigma_mps if a.ref_sigma_col else None
            result['by_phase'][str(phase)]=stats(chunk.reference_mps,chunk.wind_mps,sg)
    paired.to_csv(a.out/'paired_200hz.csv',index=False)
    (a.out/'official_metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for chartname,data in [('all',paired)]+[(str(n),g) for n,g in paired.groupby('phase') if len(g)>5]:
        fig,ax=plt.subplots(figsize=(7.2,3.5))
        ax.plot(data.host_elapsed_s,data.reference_mps,label='Synchronized Pitot ground truth',lw=1.3)
        ax.plot(data.host_elapsed_s,data.wind_mps,label='STM32 estimate',lw=.9)
        ax.set(xlabel='Elapsed time (s)',ylabel='Airspeed (m/s)',title=f'Synchronized 200 Hz comparison: {chartname}')
        ax.grid(True,alpha=.25);ax.legend();fig.tight_layout()
        fig.savefig(a.out/f'fig_{chartname}_official.pdf');plt.close(fig)
    print(json.dumps(result['overall'],indent=2))
    print('Saved matched stream, metrics and PDF plots:',a.out)


if __name__=='__main__':
    main()
