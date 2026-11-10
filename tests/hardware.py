import json
import glob
import os
from pathlib import Path
import subprocess
import time
os.environ.update(DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{os.getuid()}/bus', XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}')
ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'evidence').mkdir(exist_ok=True)
state = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'francos-system-monitor.json'

def cpu():
    v = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(v), v[3] + v[4]

start = cpu()
time.sleep(1)
end = cpu()
sample = json.loads(state.read_text())
independent_cpu = 100 * (1 - (end[1] - start[1]) / (end[0] - start[0]))
mem = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
if not sample['gpu']:
    raise SystemExit('Esta comparação de hardware requer uma GPU AMD selecionada.')
gpu = Path(sample['gpu']['path'])
report = {
 'D': {'system_cpu_percent': independent_cpu, 'monitor_cpu_percent': sample['values']['cpu'],
       'system_gpu_percent': int((gpu / 'gpu_busy_percent').read_text()), 'monitor_gpu_percent': sample['values']['gpu']},
 'E': {'system_ram_used': mem['MemTotal'] - mem['MemAvailable'], 'monitor_ram_used': sample['ram']['used'],
       'system_ram_total': mem['MemTotal'], 'monitor_ram_total': sample['ram']['total'],
       'system_vram_used': int((gpu / 'mem_info_vram_used').read_text()), 'monitor_vram_used': sample['vram']['used'],
       'system_vram_total': int((gpu / 'mem_info_vram_total').read_text()), 'monitor_vram_total': sample['vram']['total']},
 'F': [],
 'I': {key: subprocess.check_output(['systemctl','--user',command,'francos-system-monitor.service'],text=True).strip()
       for key,command in [('enabled','is-enabled'),('active','is-active')]},
 'note': 'Independent observations have different sampling instants. Exact algorithms and unavailable sensors are fixture-tested.'}
cpu_sensors = []
for name in glob.glob('/sys/class/hwmon/hwmon*/name'):
    if Path(name).read_text().strip() != 'coretemp':
        continue
    for label in Path(name).parent.glob('temp*_label'):
        if label.read_text().startswith('Package id'):
            cpu_sensors.append(str(label).replace('_label', '_input'))
report['temperatures'] = {
    'monitor': sample['temperatures'],
    'system_cpu_celsius': max((int(Path(path).read_text()) / 1000 for path in cpu_sensors), default=None),
    'cpu_sources': cpu_sensors,
    'system_gpu_celsius': int(Path(sample['gpu']['temperature_path']).read_text()) / 1000,
    'gpu_source': sample['gpu']['temperature_path'],
}
assert report['E']['system_ram_total'] == report['E']['monitor_ram_total']
assert report['E']['system_vram_total'] == report['E']['monitor_vram_total']
for _ in range(5):
    data = json.loads(state.read_text())
    report['F'].append({k: data[k] for k in ['sequence','timestamp','values']})
    time.sleep(1.1)
assert len(set(s['sequence'] for s in report['F'])) == 5
report['gpu_idle_observed_in_window'] = any(s['values']['gpu'] == 0 for s in report['F'])
(ROOT / 'evidence/hardware.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
