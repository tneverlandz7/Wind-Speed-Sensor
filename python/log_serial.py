"""Log calibration (original LIVE) plus 200 Hz float-only (g) or seq,float (j) streams.

Offline recorder only. Every wind-speed calculation remains on the STM32.
Python `p 3` / `v 8` accepts differential pressure in Pa, not speed.
"""
import argparse
import csv
import datetime
import math
import queue
import threading
import time
from pathlib import Path
import serial

FIELDS=['host_iso','host_epoch_s','host_elapsed_s','kind','phase','pressure_pa','ref_mps',
        'device_ms','temperature_c','raw_adc','delta_adc','wind_mps','sequence','command','raw_line']

def host_timestamp(epoch=None):
    epoch = time.time() if epoch is None else epoch
    return {'host_epoch_s': epoch,
            'host_iso': datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat(timespec='milliseconds')}


class WindowRecorder:
    """Persist even unfinished windows so an interrupted run cannot look complete."""
    def __init__(self, stream):
        self.stream = stream
        self.rows = []
        self.active = None
        self._save()

    def _save(self):
        self.stream.seek(0)
        self.stream.truncate()
        writer = csv.DictWriter(self.stream, fieldnames=['name', 'role', 'start_epoch', 'end_epoch'])
        writer.writeheader()
        writer.writerows(self.rows)
        self.stream.flush()

    def begin(self, role, name, epoch):
        if self.active is not None:
            raise ValueError('End the current window first')
        if role not in ('cal', 'val') or not name.strip() or not math.isfinite(epoch):
            raise ValueError('Use begin cal|val NAME with a valid clock')
        if any(row['name'] == name for row in self.rows):
            raise ValueError('Window names must be unique')
        if self.rows and epoch < self.rows[-1]['end_epoch']:
            raise ValueError('Host clock moved backward')
        self.active = {'name': name, 'role': role, 'start_epoch': epoch, 'end_epoch': ''}
        self.rows.append(self.active)
        self._save()

    def end(self, epoch):
        if self.active is None:
            raise ValueError('No window is open')
        if not math.isfinite(epoch) or epoch <= self.active['start_epoch']:
            raise ValueError('Window end must follow its start; check the host clock')
        self.active['end_epoch'] = epoch
        self.active = None
        self._save()

    def blocks(self, action):
        return self.active is not None and action not in ('end', 'stop', 'note', 'begin')


def direct_speed_command(action, value):
    speed = float(value)
    if action not in ('speed-p', 'speed-v') or not math.isfinite(speed) or not 2 <= speed <= 10:
        raise ValueError('Use speed-p|speed-v <2..10 m/s>')
    return f'{action[-1]} {speed:.5f}'

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
    print('Offline calibration: begin cal|val NAME, then end. Stay in LIVE mode; no p/v needed.')
    print('Direct reference speed commands: speed-p MPS | speed-v MPS (2..10 m/s).')
    base=time.monotonic()
    phase='idle';pressure=None;reference_mps=None;stream_kind='';count=0
    windows_path = out.with_name(out.stem + '_windows.csv')
    if out.exists() or windows_path.exists():
        raise ValueError('Log or windows file already exists; choose a new --output name')
    with serial.Serial(port,baud,timeout=0.05) as ser, out.open('x',newline='',encoding='utf-8') as fp, windows_path.open('x',newline='',encoding='utf-8') as window_fp:
        windows = WindowRecorder(window_fp)
        writer=csv.DictWriter(fp,fieldnames=FIELDS)
        writer.writeheader()
        def record(kind,line='',command='',extra=None):
            nonlocal count
            rec={**host_timestamp(),'host_elapsed_s':round(time.monotonic()-base,6),
                 'kind':kind,'phase':phase,'pressure_pa':pressure,
                 'ref_mps':round(reference_mps,5) if reference_mps is not None else '',
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
                    if windows.blocks(act):
                        print('End the measurement window before sending commands or changing modes');continue
                    if act=='stop':
                        if windows.active is not None:
                            print('WARNING: unfinished window saved with blank end; it cannot be fitted. Use end before stop.')
                        if stream_kind: ser.write(b'x\n');ser.flush()
                        record('EVENT',command='stop');fp.flush()
                        print('Saved:',out,'total rows:',count)
                        return
                    if act in ('begin', 'end'):
                        try:
                            if stream_kind:
                                raise ValueError('Exit stream with x and wait for STREAM_EXIT; windows require LIVE raw ADC/temperature')
                            if act == 'begin':
                                marker = command.split(maxsplit=2)
                                if len(marker) != 3:
                                    raise ValueError('Use begin cal|val NAME')
                                windows.begin(marker[1], marker[2], time.time())
                                phase = marker[1]
                                pressure = reference_mps = None
                            else:
                                windows.end(time.time())
                                phase = 'idle'
                            record('EVENT', command=command)
                            fp.flush()
                            print('Window saved:', command, '->', windows_path)
                        except ValueError as exc:
                            print(exc)
                    elif act in ('speed-p', 'speed-v'):
                        try:
                            forward = direct_speed_command(act, parts[1] if len(parts) > 1 else '')
                            phase = 'cal' if act == 'speed-p' else 'val'
                            pressure = None
                            reference_mps = float(parts[1])
                            ser.write((forward+'\n').encode());ser.flush()
                            record('EVENT', command=f'{command} => {forward}')
                            print('Sent:', forward, '(measured m/s)')
                        except ValueError as exc:
                            print(exc)
                    elif act in ('pressure','p','v'):
                        try:
                            pa=float(parts[1]);assert 0<=pa<=60
                        except (IndexError,ValueError,AssertionError):
                            print('Use pressure <0..60 Pa> / p <Pa> / v <Pa>');continue
                        pressure=pa
                        reference_mps=pressure_to_speed(pa)
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
