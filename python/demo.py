"""Generate fake, clearly labeled logs for a dry run. NEVER use as experimental results."""
import csv,math,random,datetime
from pathlib import Path
FIELDS=['host_iso','host_elapsed_s','device_ms','kind','phase','pressure_pa','ref_mps','temperature_c','raw_adc','delta_adc','wind_mps','command','raw_line']
random.seed(24)
BASE=8837000;T=25.6

def main(output):
    output.parent.mkdir(parents=True,exist_ok=True)
    t=0.0;device=0;delta=0.0
    with output.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader()
        def emit(kind,phase,pa,line='',raw=None,cmd=''):
            nonlocal t,device
            ref=10*math.sqrt(pa/60)
            w.writerow(dict(host_iso=(datetime.datetime(2026,10,27,tzinfo=datetime.timezone.utc)+datetime.timedelta(seconds=t)).isoformat(),host_elapsed_s=round(t,3),device_ms=device,kind=kind,phase=phase,pressure_pa=pa,ref_mps=ref,temperature_c=T if raw is not None else '',raw_adc=raw if raw is not None else '',delta_adc=raw-BASE if raw is not None else '',wind_mps='',command=cmd,raw_line=line))
        def segment(pa,phase,seconds=6,point=False):
            nonlocal t,device,delta
            emit('EVENT',phase,pa,cmd=f'pressure {pa}; phase {phase}')
            values=[];target=-2500*pa/60
            for i in range(int(seconds*5)):
                delta+=0.18*(target-delta)
                raw=round(BASE+delta+random.gauss(0,40));values.append(raw)
                emit('LIVE',phase,pa,raw=raw,line=f'LIVE,Device_ms={device},Temp_C={T},Raw_ADC={raw},Delta_ADC={raw-BASE:.2f},Wind=NOT_READY')
                t+=0.2;device+=200
            if point:
                mean=sum(values[-20:])/20
                ref=10*math.sqrt(pa/60)
                cmd=('p' if phase=='cal' else 'v')+f' {ref:.5f}'
                emit('DEVICE',phase,pa,line=f'POINT,REF_MPS={ref:.4f},MEAN_ADC={mean:.2f},DELTA_ADC={mean-BASE:.2f},STD_ADC=45.0,TEMP_C={T},N=50',cmd=cmd)
        emit('DEVICE','idle',0,line=f'ZERO,ADC={BASE:.2f},SIGMA=40.0,TEMP_C={T},N=50')
        for pa in [3,5,10,22,38,60]:segment(pa,'cal',seconds=8,point=True)
        for pa in [8,15,30,49]:segment(pa,'val',seconds=8,point=True)
        segment(3,'step',seconds=8);segment(22,'step',seconds=12);segment(3,'step',seconds=6)
        for pa in [3,5,10,15,22,30,38,49,60,49,38,30,22,15,10,5,3]:segment(pa,'ramp',seconds=4)
    print('DEMO ONLY. Saved:',output)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',default='data/demo_SYNTHETIC_DO_NOT_SUBMIT.csv');a=p.parse_args();main(Path(a.output))
