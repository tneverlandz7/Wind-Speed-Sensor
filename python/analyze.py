"""Fit ADC->wind model from POINT rows, validate, plot time series and errors.
Data needs the format produced by logger.py. No mock data is used for real metrics.
"""
import argparse,json,math,re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams.update({'font.size':9,'figure.dpi':140,'savefig.dpi':250,'axes.grid':True,'grid.alpha':0.25,'pdf.fonttype':42})

def extract_points(df):
    rows=[]
    for _,r in df[df.kind=='DEVICE'].iterrows():
        line=str(r.raw_line)
        if not line.startswith('POINT,'):continue
        d={}
        for frag in line.split(',')[1:]:
            if '=' in frag:
                k,v=frag.split('=',1)
                try:d[k]=float(v)
                except ValueError:pass
        if 'REF_MPS' in d and 'DELTA_ADC' in d:
            d['group']=r.phase if r.phase in ('cal','val') else 'unknown'
            d['time_s']=r.host_elapsed_s
            d['pressure_pa']=r.pressure_pa
            rows.append(d)
    return pd.DataFrame(rows)

def baseline(df):
    vals=[]
    for line in df[df.kind=='DEVICE'].raw_line.dropna():
        if str(line).startswith('ZERO,'):
            m=re.search(r'ADC=([-\d.]+)',str(line));
            if m:vals.append(float(m.group(1)))
    if vals:return vals[-1]
    calm=df[(df.kind=='LIVE') & (df.pressure_pa.fillna(0)==0)]
    if len(calm):return float(calm.raw_adc.median())
    raise ValueError('No ZERO message or no-wind baseline. Run z in still air.')

def density(temp):return 101325.0/(287.05*(np.asarray(temp,dtype=float)+273.15))

def predict(delta,rho,beta,sign):
    return beta*np.sqrt(np.maximum(0.0,sign*np.asarray(delta,dtype=float)/np.asarray(rho,dtype=float)))

def score(ref,pred):
    err=np.asarray(pred)-np.asarray(ref)
    return {'n':int(len(err)),'MSE_m2_s2':float(np.mean(err*err)),'RMSE_m_s':float(np.sqrt(np.mean(err*err))), 'MAE_m_s':float(np.mean(np.abs(err))), 'bias_m_s':float(np.mean(err))}

def plot_one(x,series,path,title,xlabel='Time (s)',ylabel='Airspeed (m/s)',ylim=None):
    fig,ax=plt.subplots(figsize=(7.1,3.1))
    for y,label in series:ax.plot(x,y,label=label,linewidth=1.7)
    ax.set(title=title,xlabel=xlabel,ylabel=ylabel)
    if ylim:ax.set_ylim(*ylim)
    ax.legend(loc='best');fig.tight_layout();fig.savefig(path);plt.close(fig)

def main(file,out):
    out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(file)
    needed={'kind','raw_line','host_elapsed_s','pressure_pa','raw_adc','temperature_c','phase'}
    if not needed.issubset(set(df.columns)):raise ValueError('Input is not a logger.py CSV; missing '+str(needed-set(df.columns)))
    z=baseline(df)
    points=extract_points(df)
    if points.empty:raise ValueError('No POINT rows found; finish at least two p <Pa> captures.')
    points['rho']=density(points.TEMP_C)
    cal=points[points.group=='cal'].copy()
    val=points[points.group=='val'].copy()
    if len(cal)<2:raise ValueError('Need >=2 valid calibration POINT rows before fitting')
    sign=1 if cal.loc[cal.DELTA_ADC.abs().idxmax(),'DELTA_ADC']>=0 else -1
    x=np.sqrt(np.maximum(0,sign*cal.DELTA_ADC.values/cal.rho.values))
    if (x>0).sum()<2:raise ValueError('ADC sign or baseline incorrect; fewer than 2 positive calibrations')
    beta=float(np.dot(x,cal.REF_MPS)/np.dot(x,x))
    if not np.isfinite(beta) or beta<=0:raise ValueError('Fitting failed')
    points['predicted_mps']=predict(points.DELTA_ADC,points.rho,beta,sign)
    points['error_mps']=points.predicted_mps-points.REF_MPS
    points.to_csv(out/'points_with_predictions.csv',index=False)
    cal=points[points.group=='cal'];val=points[points.group=='val']
    metrics={'file':str(file),'zero_adc':z,'model':'v=beta*sqrt(max(0,sign*DeltaADC/rho))','beta':beta,'sign':sign,'calibration':score(cal.REF_MPS,cal.predicted_mps),'validation':score(val.REF_MPS,val.predicted_mps) if len(val) else None,'reference_assumption':'v=10 sqrt(deltaP/60); requires tunnel pressure-speed curve verification','uncertainty':'Reference pressure uncertainty and timestamp latency NOT corrected'}
    (out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    with (out/'metrics.txt').open('w') as f:
        f.write('Model beta = %.7g; sign = %+d\n'%(beta,sign))
        f.write('Calibration: '+str(metrics['calibration'])+'\n')
        f.write('Validation: '+str(metrics['validation'])+'\n')
    # Figure 1: calibration mapping
    fig,ax=plt.subplots(figsize=(6.6,3.5))
    for group,marker in [('cal','o'),('val','x')]:
        rows=points[points.group==group]
        if len(rows):ax.scatter(sign*rows.DELTA_ADC,rows.REF_MPS,marker=marker,s=42,label=f'{group}: reference')
    xs=np.linspace(0,max(1,float((sign*cal.DELTA_ADC).max()))*1.08,250)
    rho=float(np.nanmedian(cal.rho))
    ax.plot(xs,beta*np.sqrt(xs/rho),label='Fitted model')
    ax.set(xlabel='Signed ADC difference (counts)',ylabel='Reference airspeed (m/s)',title='Wind tunnel calibration')
    ax.legend();fig.tight_layout();fig.savefig(out/'fig_calibration.pdf');plt.close(fig)
    # Figure 2: validation errors
    fig,ax=plt.subplots(figsize=(6.6,3.1))
    if len(val):
        ax.scatter(val.REF_MPS,val.error_mps,label='Validation',s=45)
    else:ax.text(.5,.5,'No validation POINT data yet',transform=ax.transAxes,ha='center')
    ax.axhline(0,color='black',linewidth=1);ax.set(xlabel='Reference airspeed (m/s)',ylabel='Prediction error (m/s)',title='Independent validation residuals')
    fig.tight_layout();fig.savefig(out/'fig_validation_error.pdf');plt.close(fig)
    # Full time-series: live predictor trained offline, reference from pressure annotations
    live=df[df.kind=='LIVE'].copy()
    live=live[pd.to_numeric(live.raw_adc,errors='coerce').notna() & pd.to_numeric(live.temperature_c,errors='coerce').notna()].copy()
    if len(live):
        live['predicted_offline_mps']=predict(live.raw_adc-z,density(live.temperature_c),beta,sign)
        live['reference_mps']=10*np.sqrt(np.maximum(0,live.pressure_pa.fillna(0).astype(float))/60.0)
        live['time_s']=live.host_elapsed_s.astype(float)
        live.to_csv(out/'timeseries_predictions.csv',index=False)
        plot_one(live.time_s,[(live.reference_mps,'Reference (manually annotated)'),(live.predicted_offline_mps,'Estimated')],out/'fig_timeseries_all.pdf','Recorded time-series (check reference synchronization)')
        for phase in ('step','ramp'):
            part=live[live.phase==phase]
            if len(part)<3:continue
            plot_one(part.time_s,[(part.reference_mps,'Reference (annotated)'),(part.predicted_offline_mps,'Estimated')],out/f'fig_{phase}.pdf',f'{phase.capitalize()} response (reference timestamp approximate)')
    print('Outputs written to:',out)
    print('Model beta:',beta,'sign:',sign)
    print('Calibration metrics:',metrics['calibration'])
    print('Validation metrics:',metrics['validation'] or 'NOT AVAILABLE - collect independent v points')
    print('IMPORTANT: annotations are not synchronous pressure sensor readings. Do not report accurate latency/rise time without timing alignment.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',default='outputs/analysis')
    args=p.parse_args();main(Path(args.input),Path(args.out))
