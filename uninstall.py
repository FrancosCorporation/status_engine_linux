#!/usr/bin/python3
"""Remove only this application's integration, retaining source and settings."""
from pathlib import Path
import os
import shutil
import subprocess
import gi
from gi.repository import Gio
os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{os.getuid()}/bus')
home = Path.home()
uuid = 'francos-monitor@francos.local'
subprocess.run(['gnome-extensions', 'disable', uuid], check=False)
subprocess.run(['systemctl', '--user', 'disable', '--now', 'francos-system-monitor.service'], check=False)
shell = Gio.Settings.new('org.gnome.shell')
for key, value in [('favorite-apps', 'local.francos.SystemMonitor.desktop'), ('enabled-extensions', uuid)]:
    shell.set_strv(key, [s for s in shell.get_strv(key) if s != value])
Gio.Settings.sync()
for path in ['.local/bin/francos-collector', '.local/bin/francos-system-monitor', '.local/share/applications/local.francos.SystemMonitor.desktop',
             '.local/share/icons/hicolor/scalable/apps/francos-system-monitor.svg',
             '.config/systemd/user/francos-system-monitor.service']:
    (home / path).unlink(missing_ok=True)
extension = home / '.local/share/gnome-shell/extensions' / uuid
if extension.exists():
    shutil.rmtree(extension)
subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
print('Integração removida. Código-fonte e configurações pessoais preservados.')
