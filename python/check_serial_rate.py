#!/usr/bin/env python3
"""Bench-test STM32 200 Hz UART *line transport* using debug sequence numbers.

Run on a free COM port. The script sends 'j' and expects seq,float 200 times/sec.
This diagnostic mode intentionally DOES NOT require tunnel calibration, so it
can be tested in a dorm. It proves output cadence, NOT underlying ADC SPS.
"""
import argparse
import csv
import statistics
import time
from pathlib import Path
import serial


def run(port, seconds, path, baud):
    path.parent.mkdir(parents=True, exist_ok=True)
    with serial.Serial(port, baud, timeout=0.2) as ser:
        # Some boards reset on opening a serial port; wait for USB/VCP startup.
        time.sleep(1.6)
        ser.reset_input_buffer()
        ser.write(b'j\n')
        ser.flush()
        start = time.monotonic()
        rows = []
        ignored = []
        while time.monotonic()-start < seconds:
            b = ser.readline()
            when = time.monotonic() - start
            if not b:
                continue
            line = b.decode('utf-8','replace').strip()
            parts = line.split(',')
            if len(parts) == 2 and parts[0].strip().isdigit():
                try:
                    rows.append((when, int(parts[0]), float(parts[1])))
                    continue
                except ValueError:
                    pass
            if len(ignored)<12:
                ignored.append(line)
        ser.write(b'x\n')
        ser.flush()
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['host_elapsed_s','sequence','speed_mps'])
        w.writerows(rows)
    print('Saved:', path, 'parsed numeric rows:',len(rows))
    if ignored: print('Other lines seen:', ignored)
    if len(rows)<2:
        print('ERROR: no streaming data. Check firmware upload, COM port, and debug command j.')
        return 1
    seq=[r[1] for r in rows]
    missing=sum(max(0,b-a-1) for a,b in zip(seq[:-1],seq[1:]))
    received_window=rows[-1][0]-rows[0][0]
    effective_hz=(len(rows)-1)/received_window if received_window>0 else 0
    expected_hz=200
    gaps=[b[0]-a[0] for a,b in zip(rows[:-1],rows[1:])]
    print('Sequence range:',seq[0], 'to',seq[-1])
    print('Missing sequence numbers:',missing)
    print('Observed host throughput (rows/s):',round(effective_hz,2))
    print('Host interarrival median (ms):',round(statistics.median(gaps)*1000,2))
    print('Host interarrival max (ms):',round(max(gaps)*1000,2))
    print('Expected 200 Hz = 5 ms. Host arrival gaps include OS/USB buffering; do not use as exact device jitter.')
    if not (195<=effective_hz<=205 and missing==0):
        print('WARNING: throughput or sequence continuity failed preflight; inspect log and MCU missed_slots report.')
        return 2
    print('PASS: serial sequence continuity and approximate 200 Hz host throughput in this test.')
    return 0

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',required=True,help='e.g. COM7')
    ap.add_argument('--seconds',type=float,default=12)
    ap.add_argument('--baud',type=int,default=115200)
    ap.add_argument('--output',type=Path,default=Path('data/serial_rate_debug.csv'))
    args=ap.parse_args()
    raise SystemExit(run(args.port,args.seconds,args.output,args.baud))
