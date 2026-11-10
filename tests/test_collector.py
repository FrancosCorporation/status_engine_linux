import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import collector as c


class TelemetryTests(unittest.TestCase):
    def test_cpu_excludes_guest_double_count(self):
        with tempfile.NamedTemporaryFile(mode='w+') as file:
            file.write('cpu 100 20 40 300 50 6 7 8 30 10\n')
            file.flush()
            self.assertEqual(c.cpu_counters(file.name), (531, 350))

    def test_ram_uses_available(self):
        with tempfile.NamedTemporaryFile(mode='w+') as file:
            file.write('MemTotal: 1000 kB\nMemFree: 50 kB\nMemAvailable: 400 kB\n')
            file.flush()
            self.assertEqual(c.memory(file.name), {'used': 614400, 'total': 1024000, 'percent': 60.0})

    def test_missing_memavailable(self):
        with tempfile.NamedTemporaryFile(mode='w+') as file:
            file.write('MemTotal: 1000 kB\n')
            file.flush()
            self.assertIsNone(c.memory(file.name)['percent'])

    def test_missing_sensor(self):
        self.assertIsNone(c.number('/no/such/francos-sensor'))

    def test_cpu_deltas_and_absent_gpu(self):
        with patch.object(c, 'gpus', return_value=[]), patch.object(c, 'cpu_counters', side_effect=[(100, 60), (200, 80)]):
            monitor = c.Collector()
            self.assertIsNone(monitor.sample()['values']['cpu'])
            data = monitor.sample()
            self.assertEqual(data['values']['cpu'], 80)
            self.assertIsNone(data['values']['gpu'])
            self.assertIsNone(data['vram']['used'])

    def test_history_bounded(self):
        with patch.object(c, 'gpus', return_value=[]):
            monitor = c.Collector()
            for _ in range(100):
                monitor.sample()
            self.assertEqual(len(monitor.history['cpu']), 90)

    def test_settings_corrupt_file(self):
        with tempfile.NamedTemporaryFile(mode='w+') as file:
            file.write('{bad')
            file.flush()
            with patch.object(c, 'CONFIG', Path(file.name)):
                self.assertEqual(c.settings(), c.DEFAULTS)

    def test_settings_clamp(self):
        with tempfile.NamedTemporaryFile(mode='w+') as file:
            json.dump({'interval': 0.01, 'colors': {'cpu': 'invalid'}}, file)
            file.flush()
            with patch.object(c, 'CONFIG', Path(file.name)):
                self.assertEqual(c.settings()['interval'], 0.5)
                self.assertEqual(c.settings()['colors']['cpu'], c.DEFAULTS['colors']['cpu'])


if __name__ == '__main__':
    unittest.main()
