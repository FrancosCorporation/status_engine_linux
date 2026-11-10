"""Low-cost Linux telemetry. No workload generation or privileged access."""
import glob
import json
import os
from pathlib import Path
import re
import time
import subprocess

GIB = 1024 ** 3
METRICS = ('cpu', 'gpu', 'ram', 'vram')
DEFAULTS = {
    'interval': 1.0, 'visible': {k: True for k in METRICS},
    'colors': dict(zip(METRICS, ('#67b5ff', '#ab92ff', '#57d6b2', '#ffbe70'))),
    'absolute': True, 'mini': 'bars', 'history': True, 'gpu': '',
    'opacity': 0.97, 'appearance': 'system', 'alerts': False, 'threshold': 90,
    'autostart': True,
}
CONFIG = Path.home() / '.config/francos-system-monitor/settings.json'
STATE = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'francos-system-monitor.json'


def settings():
    result = json.loads(json.dumps(DEFAULTS))
    try:
        data = json.loads(CONFIG.read_text())
        if not isinstance(data, dict):
            return result
        for key in result:
            if key in data:
                if isinstance(result[key], dict) and isinstance(data[key], dict):
                    result[key].update({k: v for k, v in data[key].items() if k in result[key] and isinstance(v, type(result[key][k]))})
                elif isinstance(data[key], type(result[key])):
                    result[key] = data[key]
        result['interval'] = max(0.5, min(30.0, float(result['interval'])))
        result['opacity'] = max(0.5, min(1.0, float(result['opacity'])))
        result['threshold'] = max(1, min(100, result['threshold']))
        if result['mini'] not in ('bars', 'graphs'):
            result['mini'] = 'bars'
        if result['appearance'] not in ('system', 'light', 'dark'):
            result['appearance'] = 'system'
        for key, color in result['colors'].items():
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                result['colors'][key] = DEFAULTS['colors'][key]
    except (OSError, ValueError, TypeError):
        pass
    return result


def number(path):
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def cpu_counters(path='/proc/stat'):
    values = [int(n) for n in Path(path).read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def memory(path='/proc/meminfo'):
    info = {}
    for line in Path(path).read_text().splitlines():
        key, value = line.split(':', 1)
        info[key] = int(value.split()[0]) * 1024
    total = info['MemTotal']
    available = info.get('MemAvailable')
    if available is None:
        return {'used': None, 'total': total, 'percent': None}
    used = max(0, total - available)
    return {'used': used, 'total': total, 'percent': used / total * 100 if total else None}


def gpus():
    devices = []
    for card in sorted(glob.glob('/sys/class/drm/card[0-9]*')):
        if not re.fullmatch(r'card\d+', Path(card).name):
            continue
        device = Path(card) / 'device'
        try:
            if int((device / 'vendor').read_text(), 16) != 0x1002:
                continue
            pci = device.resolve().name
            driver = (device / 'driver').resolve().name
            name = 'AMD Radeon'
            # amdgpu exposes product_name on some kernels.
            product = device / 'product_name'
            if product.exists():
                name = product.read_text().strip()
            else:
                try:
                    text = subprocess.check_output(['lspci', '-s', pci], text=True, timeout=2).strip()
                    name = text.split(': ', 1)[-1]
                except (OSError, subprocess.SubprocessError):
                    name = f'AMD Radeon · {pci}'
            devices.append({'path': str(device), 'pci': pci, 'name': name, 'driver': driver})
        except (OSError, ValueError):
            continue
    return devices


class Collector:
    def __init__(self):
        self.previous = None
        self.devices = gpus()
        info = Path('/proc/cpuinfo').read_text().split('\n\n')
        entries = [dict(line.split(':', 1) for line in block.splitlines() if ':' in line) for block in info]
        entries = [{k.strip(): v.strip() for k, v in entry.items()} for entry in entries if entry]
        self.cpu = {
            'name': entries[0].get('model name', 'CPU'),
            'threads': len(entries),
            'cores': len({(e.get('physical id', '0'), e.get('core id', e.get('processor'))) for e in entries}),
        }
        self.history = {k: [] for k in METRICS}
        self.sequence = 0

    def sample(self, config=None):
        config = config or settings()
        current = cpu_counters()
        cpu = None
        if self.previous:
            total = current[0] - self.previous[0]
            idle = current[1] - self.previous[1]
            if total > 0:
                cpu = max(0, min(100, (total - idle) / total * 100))
        self.previous = current
        selected = next((g for g in self.devices if g['pci'] == config['gpu']), None)
        selected = selected or next(iter(self.devices), None)
        gpu, vram = None, {'used': None, 'total': None, 'percent': None}
        if selected:
            path = Path(selected['path'])
            gpu = number(path / 'gpu_busy_percent')
            used, total = number(path / 'mem_info_vram_used'), number(path / 'mem_info_vram_total')
            vram = {'used': used, 'total': total, 'percent': used / total * 100 if used is not None and total else None}
        ram = memory()
        values = {'cpu': cpu, 'gpu': gpu, 'ram': ram['percent'], 'vram': vram['percent']}
        for key in METRICS:
            self.history[key].append(values[key])
            self.history[key] = self.history[key][-90:]
        self.sequence += 1
        return {'timestamp': time.time(), 'sequence': self.sequence, 'values': values,
                'cpu': self.cpu, 'gpu': selected, 'gpus': self.devices,
                'ram': ram, 'vram': vram, 'history': self.history, 'settings': config}


def write_state(data):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(STATE)
