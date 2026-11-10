import json
import os
from pathlib import Path
import subprocess
import time
os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{os.getuid()}/bus'
ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'evidence').mkdir(exist_ok=True)
pid = int(subprocess.check_output(['systemctl', '--user', 'show', 'francos-system-monitor.service', '-p', 'MainPID', '--value']))


def counters():
    fields = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
    status = Path(f'/proc/{pid}/status').read_text().splitlines()
    rss = next(int(line.split()[1]) for line in status if line.startswith('VmRSS:'))
    return int(fields[11]) + int(fields[12]), rss


first, initial_rss = counters()
start = time.monotonic()
time.sleep(30)
last, final_rss = counters()
elapsed = time.monotonic() - start
result = {'pid': pid, 'seconds': elapsed,
          'cpu_percent_one_core': (last - first) / os.sysconf('SC_CLK_TCK') / elapsed * 100,
          'rss_initial_kib': initial_rss, 'rss_final_kib': final_rss,
          'scope': 'Native C telemetry service. GNOME UI shares the existing gnome-shell process.'}
(ROOT / 'evidence/performance.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
