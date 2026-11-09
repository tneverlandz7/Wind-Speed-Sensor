import csv
import io
import sys
import unittest
import tempfile
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from log_serial import WindowRecorder, host_timestamp, direct_speed_command
import log_serial


class InlineThread:
    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()


class LoggingTests(unittest.TestCase):
    def test_timestamp_uses_same_epoch_for_iso(self):
        stamp = host_timestamp(1000.125)
        self.assertEqual(stamp['host_epoch_s'], 1000.125)
        self.assertEqual(stamp['host_iso'], '1970-01-01T00:16:40.125+00:00')

    def test_windows_flush_and_reject_invalid_transitions(self):
        stream = io.StringIO()
        windows = WindowRecorder(stream)
        windows.begin('cal', 'speed_2', 100)
        self.assertTrue(windows.blocks('z'))
        self.assertTrue(windows.blocks('g'))
        with self.assertRaises(ValueError):
            windows.begin('val', 'nested', 101)
        windows.end(110)
        self.assertFalse(windows.blocks('z'))
        with self.assertRaises(ValueError):
            windows.end(111)
        with self.assertRaises(ValueError):
            windows.begin('cal', 'speed_2', 111)
        windows.begin('val', 'unfinished', 112)
        rows = list(csv.DictReader(io.StringIO(stream.getvalue())))
        self.assertEqual(float(rows[0]['end_epoch']), 110)
        self.assertEqual(rows[1]['end_epoch'], '')

    def test_invalid_markers_and_clock(self):
        for role, name, time in [('bad', 'x', 1), ('cal', '', 1), ('cal', 'x', float('nan'))]:
            with self.assertRaises(ValueError):
                WindowRecorder(io.StringIO()).begin(role, name, time)
        windows = WindowRecorder(io.StringIO())
        windows.begin('cal', 'x', 10)
        with self.assertRaises(ValueError):
            windows.end(9)

    def test_direct_speed_is_not_pressure(self):
        self.assertEqual(direct_speed_command('speed-p', '4.12'), 'p 4.12000')
        self.assertEqual(direct_speed_command('speed-v', '5'), 'v 5.00000')
        for value in ['nan', 'inf', '1.9', '10.1', 'abc']:
            with self.assertRaises(ValueError):
                direct_speed_command('speed-p', value)

    def run_logger(self, commands, out):
        serial = MagicMock()
        serial.__enter__.return_value = serial
        with patch.object(log_serial.serial, 'Serial', return_value=serial), \
             patch.object(log_serial.threading, 'Thread', InlineThread), \
             patch('builtins.input', side_effect=[*commands, EOFError()]), \
             patch('builtins.print'):
            log_serial.main('FAKE_PORT', 115200, out)
        return serial

    def test_direct_speed_record_retains_measured_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/'run.csv'
            serial = self.run_logger(['speed-p 4.12', 'stop'], out)
            serial.write.assert_called_once_with(b'p 4.12000\n')
            rows = list(csv.DictReader(io.StringIO(out.read_text())))
            self.assertEqual(float(rows[0]['ref_mps']), 4.12)
            self.assertEqual(rows[0]['pressure_pa'], '')
            self.assertGreater(float(rows[0]['host_epoch_s']), 0)

    def test_main_does_not_send_zero_during_window(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/'run.csv'
            serial = self.run_logger(['begin cal w1', 'z', 'end', 'stop'], out)
            serial.write.assert_not_called()
            rows = list(csv.DictReader(io.StringIO(out.with_name('run_windows.csv').read_text())))
            self.assertEqual(rows[0]['name'], 'w1')
            self.assertGreater(float(rows[0]['end_epoch']), float(rows[0]['start_epoch']))
            with self.assertRaisesRegex(ValueError, 'already exists'):
                self.run_logger(['stop'], out)

    def test_uncalibrated_live_adc_and_temperature_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/'run.csv'
            commands = queue.Queue()
            commands.put('z')
            serial = MagicMock()
            serial.__enter__.return_value = serial
            serial.in_waiting = 0
            def receive(_):
                commands.put('stop')
                return (b'ZERO,ADC=1000,SIGMA=1,TEMP_C=20,N=50\n'
                        b'LIVE,Device_ms=6000,Temp_C=20,Raw_ADC=1100,Delta_ADC=100,Wind=NOT_READY\n')
            serial.read.side_effect = receive
            with patch.object(log_serial.serial, 'Serial', return_value=serial), \
                 patch.object(log_serial.threading, 'Thread'), \
                 patch.object(log_serial.queue, 'Queue', return_value=commands), patch('builtins.print'):
                log_serial.main('FAKE_PORT', 115200, out)
            rows = list(csv.DictReader(io.StringIO(out.read_text())))
            live = next(row for row in rows if row['kind'] == 'LIVE')
            self.assertEqual(float(live['raw_adc']), 1100.)
            self.assertEqual(float(live['temperature_c']), 20.)
            self.assertEqual(live['wind_mps'], '')
            self.assertEqual(live['ref_mps'], '')
            self.assertGreater(float(live['host_epoch_s']), 0)


if __name__ == '__main__':
    unittest.main()
