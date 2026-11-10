import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / 'build/francos-collector'


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        (self.proc / 'cpuinfo').write_text('processor : 0\nmodel name : Fixture CPU\nphysical id : 0\ncore id : 0\n\n')
        (self.proc / 'stat').write_text('cpu 100 20 40 300 50 6 7 8 30 10\n')
        (self.proc / 'meminfo').write_text('MemTotal: 1000 kB\nMemFree: 50 kB\nMemAvailable: 400 kB\n')
        self.env = dict(os.environ, HOME=str(self.root), XDG_RUNTIME_DIR=str(self.root),
                        FRANCOS_PROC_ROOT=str(self.proc), FRANCOS_HWMON_GLOB=str(self.root / 'hwmon/hwmon*'), FRANCOS_DRM_GLOB=str(self.root / 'drm/card[0-9]*'))
        self.config = self.root / '.config/francos-system-monitor/settings.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"interval":0.5}')

    def tearDown(self):
        self.temp.cleanup()

    def once(self):
        return json.loads(subprocess.check_output([str(BINARY), '--once'], env=self.env))

    def test_memory_cpu_and_no_gpu(self):
        data = self.once()
        self.assertEqual(data['ram']['percent'], 60)
        self.assertEqual(data['ram']['used'], 614400)
        self.assertIsNone(data['values']['cpu'])
        self.assertIsNone(data['values']['gpu'])
        self.assertIsNone(data['vram']['total'])
        self.assertEqual(data['cpu']['cores'], 1)

    def test_config_validation_and_migration(self):
        self.config.write_text(json.dumps({'interval': 0, 'opacity': 4, 'appearance': 'bad',
            'mini': 'bad', 'colors': {'cpu': 'bad'}, 'visible': {'cpu': 'bad'}, 'threshold': 1000}))
        config = self.once()['settings']
        self.assertEqual(config['interval'], 0.5)
        self.assertEqual(config['opacity'], 1)
        self.assertEqual(config['colors']['cpu'], '#67b5ff')
        self.assertEqual(config['visible']['cpu'], True)
        self.assertEqual(config['appearance'], 'system')
        self.assertEqual(config['mini'], 'bars')
        self.assertEqual(config['threshold'], 100)
        self.config.write_text('{broken')
        self.assertEqual(self.once()['settings']['interval'], 1)

    def test_card1_and_vram_independent_of_ram(self):
        device = self.root / '0000:05:00.0'
        device.mkdir()
        (device / 'vendor').write_text('0x1002')
        (device / 'gpu_busy_percent').write_text('17')
        (device / 'mem_info_vram_used').write_text(str(3 * 1024 ** 3))
        (device / 'mem_info_vram_total').write_text(str(12 * 1024 ** 3))
        (device / 'product_name').write_text('Fixture AMD')
        thermal = device / 'hwmon/hwmon9'
        thermal.mkdir(parents=True)
        (thermal / 'temp1_label').write_text('edge')
        (thermal / 'temp1_input').write_text('53000')
        (thermal / 'temp2_label').write_text('junction')
        (thermal / 'temp2_input').write_text('79000')
        (self.root / 'amdgpu').mkdir()
        (device / 'driver').symlink_to(self.root / 'amdgpu')
        card = self.root / 'drm/card1'
        card.mkdir(parents=True)
        (card / 'device').symlink_to(device)
        data = self.once()
        self.assertEqual(data['gpu']['pci'], '0000:05:00.0')
        self.assertEqual(data['gpu']['driver'], 'amdgpu')
        self.assertEqual(data['values']['gpu'], 17)
        self.assertEqual(data['temperatures']['gpu'], 53)
        self.assertEqual(data['vram']['percent'], 25)
        self.assertEqual(data['ram']['percent'], 60)
        (device / 'gpu_busy_percent').unlink()
        self.assertIsNone(self.once()['values']['gpu'])

    def test_cpu_temperature_uses_package_and_ignores_nvme(self):
        monitor = self.root / 'hwmon/hwmon4'
        monitor.mkdir(parents=True)
        (monitor / 'name').write_text('coretemp')
        (monitor / 'temp1_label').write_text('Package id 0')
        (monitor / 'temp1_input').write_text('70000')
        (monitor / 'temp2_label').write_text('Core 0')
        (monitor / 'temp2_input').write_text('63000')
        nvme = self.root / 'hwmon/hwmon0'
        nvme.mkdir()
        (nvme / 'name').write_text('nvme')
        (nvme / 'temp1_input').write_text('99000')
        self.assertEqual(self.once()['temperatures']['cpu'], 70)
        (monitor / 'temp1_input').write_text('999999')
        self.assertIsNone(self.once()['temperatures']['cpu'])

    def test_deltas_single_instance_and_shutdown(self):
        process = subprocess.Popen([str(BINARY)], env=self.env)
        state = self.root / 'francos-system-monitor.json'
        try:
            deadline = time.monotonic() + 3
            while not state.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(state.exists())
            (self.proc / 'stat').write_text('cpu 180 20 40 320 50 6 7 8 30 10\n')
            time.sleep(0.7)
            self.assertEqual(json.loads(state.read_text())['values']['cpu'], 80)
            second = subprocess.run([str(BINARY)], env=self.env, timeout=2)
            self.assertEqual(second.returncode, 0)
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=2)
        self.assertEqual(process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
