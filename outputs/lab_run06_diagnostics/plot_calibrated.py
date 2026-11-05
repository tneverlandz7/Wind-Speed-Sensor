"""Convert recorded raw samples to speed; does not reconstruct the 80 Hz EMA."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'python'))
from calibration_model import density, predict

model = json.loads((ROOT/'outputs/lab_run06_assumed/model.json').read_text())
paths = {'sensor': ROOT/'data/lab_run06.csv', 'windows': ROOT/'data/lab_run06_windows.csv',
         'assumed_speeds': ROOT/'data/lab_run06_assumed_speeds.csv'}
for name, path in paths.items():
    if hashlib.sha256(path.read_bytes()).hexdigest() != model['inputs'][name]['sha256']:
        raise ValueError(f'{name} changed since calibration; refit before plotting')
sensor = pd.read_csv(paths['sensor'])
windows = pd.read_csv(paths['windows'])
assumptions = pd.read_csv(paths['assumed_speeds']).set_index('name').assumed_mps.to_dict()
live = sensor[sensor.kind == 'LIVE'].copy()
for column in ['raw_adc', 'temperature_c', 'host_epoch_s', 'host_elapsed_s']:
    live[column] = pd.to_numeric(live[column], errors='coerce')
if not np.isfinite(live[['raw_adc', 'temperature_c', 'host_epoch_s', 'host_elapsed_s']]).all().all():
    raise ValueError('Nonfinite raw readings or timestamps')
live['density_kgm3'] = density(live.temperature_c)
live['predicted_raw_mps'] = predict(live.raw_adc-model['zero_adc'], live.density_kgm3,
                                     model['beta'], model['sign'], model['zero_sigma_adc'])
live['window'] = ''
live['assumed_mps'] = np.nan
for _, window in windows.iterrows():
    mask = live.host_epoch_s.between(window.start_epoch, window.end_epoch, inclusive='left')
    live.loc[mask, 'window'] = window['name']
    live.loc[mask, 'assumed_mps'] = assumptions[window['name']]
out = Path(__file__).resolve().parent
columns = ['host_iso', 'host_epoch_s', 'host_elapsed_s', 'raw_adc', 'temperature_c',
           'density_kgm3', 'predicted_raw_mps', 'window', 'assumed_mps']
live[columns].to_csv(out/'calibrated_raw_timeseries.csv', index=False)

fig, axes = plt.subplots(2, 1, figsize=(11, 7.5), gridspec_kw={'height_ratios': [1.6, 1]})
base = float((sensor.host_epoch_s-sensor.host_elapsed_s).median())
for ax in axes:
    # Break the line during the blocking zero capture rather than interpolate it.
    plotted = live.predicted_raw_mps.where(live.host_epoch_s.diff().fillna(0) <= 1.)
    ax.plot(live.host_elapsed_s, plotted, lw=1.2, color='tab:blue', label='Calibrated raw samples (no software EMA)')
    for i, (_, window) in enumerate(windows.iterrows()):
        start, end = window.start_epoch-base, window.end_epoch-base
        ax.axvspan(start, end, color='tab:green', alpha=.1)
        ax.plot([start, end], [assumptions[window['name']]]*2, '--', lw=1.7, color='tab:orange',
                label='Assumed window speed (not measured)' if i == 0 else None)
    ax.set(xlabel='Seconds since logger started', ylabel='Predicted wind speed (m/s)')
    ax.grid(alpha=.2)
axes[0].set(title='lab_run06 converted using its provisional assumed-speed calibration', xlim=(0, 180), ylim=(0, 12))
axes[0].legend(loc='upper right', fontsize=8)
zoom = live[live.host_elapsed_s.between(104, 119)]
peak = zoom.loc[zoom.predicted_raw_mps.idxmax()]
axes[1].set(title='Zoom: overshoot before the speed_6 window', xlim=(104, 131), ylim=(0, 8))
axes[1].annotate(f'Peak {peak.predicted_raw_mps:.2f} m/s',
                 xy=(peak.host_elapsed_s, peak.predicted_raw_mps),
                 xytext=(peak.host_elapsed_s+3, 7.2), arrowprops={'arrowstyle': '->'})
fig.text(.5, .012, 'Converted from ~5 Hz raw ADC and measured temperature. No recorded tunnel reference; not a replay of the 200 Hz filtered output.',
         ha='center', fontsize=8)
fig.tight_layout(rect=[0, .035, 1, 1])
fig.savefig(out/'calibrated_wind_speed.png', dpi=170)
plt.close(fig)
print('Saved:', out/'calibrated_wind_speed.png')
print('Saved:', out/'calibrated_raw_timeseries.csv')
print(f'Overshoot peak at {peak.host_elapsed_s:.2f} s: {peak.predicted_raw_mps:.4f} m/s')
print('Window sample means:', live[live.window != ''].groupby('window').predicted_raw_mps.mean().to_dict())
