"""Log calibration (original LIVE) plus 200 Hz float-only (g) or seq,float (j) streams.

Offline recorder only. Every wind-speed calculation remains on the STM32.
Python `p 3` / `v 8` accepts differential pressure in Pa, not speed.
"""
import argparse
import csv
import datetime
import queue
import threading
import time
from pathlib import Path
import serial

FIELDS=['host_iso','host_elapsed_s','kind','phase','pressure_pa','ref_mps',
        'device_ms','temperature_c','raw_adc','delta_adc','wind_mps','sequence','command','raw_line']

def pressure_to_speed(pa):
    return 10.0 * (max(0.0,pa)/60.0)**0.5

def parse_fields(line):
    ans={}
    for piece in line.split(',')[1:]:
        if '=' in piece:
            k,v=piece.split('=',1)
            ans[k.strip()]=v.strip()
    return ans

def numeric(v):
    try: return float(v)
    except (ValueError,TypeError): return ''

def main(port,baud,out,model_file=None):
    out.parent.mkdir(parents=True,exist_ok=True)
    if model_file is None:
        model_file=out.with_name(out.stem+'_calibration_restore.txt')
    commands=queue.Queue()
    def command_input():
        while True:
            try: commands.put(input('cmd> ').strip())
            except EOFError:
                commands.put('stop')
                return
    print('Opening',port,'at',baud,'baud. Close Arduino Serial Monitor before connecting.')
    print('Commands: z | p 3 | v 8 | pressure 15 | phase step|ramp|idle | g | j | x | q | r | d | load | note TEXT | stop')
    print('p/v/pressure take pressure in Pa; g=float-only demo 200Hz; j=seq,float diagnostic 200Hz; x=exit.')
    print('Reference labels are only ASSUMED: 10 sqrt(Pa/60); obtain synchronized Dwyer/Pitot ground truth.')
    print('Calibration restore file:',model_file)
    base=time.monotonic()
    phase='idle';pressure=0.0;stream_kind='';count=0
    with serial.Serial(port,baud,timeout=0.05) as ser, out.open('w',newline='',encoding='utf-8') as fp:
        writer=csv.DictWriter(fp,fieldnames=FIELDS)
        writer.writeheader()
        def record(kind,line='',command='',extra=None):
            nonlocal count
            now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')
            rec={'host_iso':now,'host_elapsed_s':round(time.monotonic()-base,6),
                 'kind':kind,'phase':phase,'pressure_pa':pressure,
                 'ref_mps':round(pressure_to_speed(pressure),5),
                 'command':command,'raw_line':line}
            if extra: rec.update(extra)
            writer.writerow(rec);count+=1
            # Buffered flushing is sufficient; no fsync per row.
            if count%25==0:fp.flush()
        threading.Thread(target=command_input,daemon=True).start()
        buf=''
        try:
            while True:
                while not commands.empty():
                    command=commands.get().strip()
                    parts=command.split(maxsplit=1)
                    act=parts[0].lower() if parts else ''
                    if act=='stop':
                        if stream_kind: ser.write(b'x\n');ser.flush()
                        record('EVENT',command='stop');fp.flush()
                        print('Saved:',out,'total rows:',count)
                        return
                    if act in ('pressure','p','v'):
                        try:
                            pa=float(parts[1]);assert 0<=pa<=60
                        except (IndexError,ValueError,AssertionError):
                            print('Use pressure <0..60 Pa> / p <Pa> / v <Pa>');continue
                        pressure=pa
                        if act in ('p','v'):
                            phase='cal' if act=='p' else 'val'
                            forward=f'{act} {pressure_to_speed(pa):.5f}'
                            ser.write((forward+'\n').encode());ser.flush()
                            record('EVENT',command=f'{command} => {forward}')
                            print('Sent:',forward,'(speed inferred from Pa)')
                        else:
                            record('EVENT',command=command)
                            print('Pressure annotation:',pa,'Pa')
                    elif act=='phase':
                        if len(parts)<2 or parts[1].lower() not in ('idle','step','ramp','cal','val','demo'):
                            print('phase idle|step|ramp|cal|val|demo');continue
                        phase=parts[1].lower()
                        record('EVENT',command=command)
                    elif act=='load':
                        try:
                            restore_line=model_file.read_text(encoding='utf-8').strip()
                            if not restore_line.startswith('k '):raise ValueError('Not a k calibration command')
                            if stream_kind:print('Exit stream with x before loading calibration');continue
                            ser.write((restore_line+'\n').encode());ser.flush()
                            record('EVENT',command='load => '+restore_line)
                            print('Sent saved MCU calibration:',restore_line)
                        except (OSError,ValueError) as exc:
                            print('Cannot load calibration file:',exc)
                    elif act in ('g','j'):
                        ser.write((act+'\n').encode());ser.flush()
                        stream_kind=act;phase='demo'
                        record('EVENT',command=act)
                        print('200Hz stream requested. g gives float only, j gives seq,float. Send x to exit.')
                    elif act=='x':
                        ser.write(b'x\n');ser.flush()
                        record('EVENT',command='x')
                        print('Requested exit from 200Hz mode; draining previous numeric lines.')
                    elif act in ('z','q','r','d','s','h'):
                        ser.write((act+'\n').encode());ser.flush()
                        record('EVENT',command=act)
                    elif act=='note':record('EVENT',command=command)
                    elif act:print('Unknown command:',command)
                received=ser.read(ser.in_waiting or 1)
                if not received:continue
                buf+=received.decode('utf-8','replace')
                while '\n' in buf:
                    line,buf=buf.split('\n',1)
                    line=line.strip()
                    if not line:continue
                    if line.startswith('LIVE,'):
                        d=parse_fields(line)
                        record('LIVE',line,extra={
                            'device_ms':numeric(d.get('Device_ms')),
                            'temperature_c':numeric(d.get('Temp_C')),
                            'raw_adc':numeric(d.get('Raw_ADC')),
                            'delta_adc':numeric(d.get('Delta_ADC')),
                            'wind_mps':numeric(d.get('Wind_mps'))})
                    else:
                        got=False
                        if stream_kind=='j':
                            a=line.split(',')
                            if len(a)==2 and a[0].isdigit():
                                try:
                                    record('STREAM',line,extra={'sequence':int(a[0]),'wind_mps':float(a[1])})
                                    got=True
                                except ValueError:pass
                        elif stream_kind=='g':
                            try:
                                record('STREAM',line,extra={'wind_mps':float(line)})
                                got=True
                            except ValueError:pass
                        if not got:
                            record('DEVICE',line)
                            if line.startswith('RESTORE_CMD,'):
                                restore=line.partition(',')[2].strip()
                                if restore.startswith('k '):
                                    model_file.write_text(restore+'\n',encoding='utf-8')
                                    print('Saved calibration restore command to:',model_file)
                            if line.startswith('STREAM_EXIT'):
                                stream_kind=''
                            print('[DEVICE]',line)
        except KeyboardInterrupt:
            record('EVENT',command='keyboard interrupt')
            fp.flush()
            print('\nSaved:',out,'total rows:',count)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',required=True)
    ap.add_argument('--baud',type=int,default=115200)
    ap.add_argument('--output',type=Path,default=Path('data/session_200hz.csv'))
    ap.add_argument('--model-file',type=Path,default=None)
    args=ap.parse_args()
    main(args.port,args.baud,args.output,args.model_file)
