#!/usr/bin/python3
"""Per-user installation, preserving existing favorites and unrelated settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from collector import CONFIG, settings

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
UUID = 'francos-monitor@francos.local'
APP = 'local.francos.SystemMonitor.desktop'
os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{os.getuid()}/bus')
os.environ.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# Resolve runtime dependencies before changing the installed application.
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, Gtk
for command in ('make', 'cc', 'systemctl', 'gdbus', 'gnome-extensions'):
    if not shutil.which(command):
        raise SystemExit(f'Dependência ausente: {command}')
version = subprocess.check_output(['gnome-shell', '--version'], text=True).strip()
if version.split()[-1].split('.')[0] != '50':
    raise SystemExit(f'Esta versão requer GNOME Shell 50. Detectado: {version}')
if not Gio.SettingsSchemaSource.get_default().lookup('org.gnome.shell.extensions.dash-to-dock', True):
    raise SystemExit('Instale e habilite Ubuntu Dock ou Dash to Dock antes de continuar.')
subprocess.run(['make', 'build'], cwd=ROOT, check=True)
unit = HOME / '.config/systemd/user/francos-system-monitor.service'
if unit.exists():
    subprocess.run(['systemctl', '--user', 'stop', 'francos-system-monitor.service'], check=True)
native_binary = HOME / '.local/bin/francos-collector'
native_binary.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / 'build/francos-collector', native_binary)
extension = HOME / '.local/share/gnome-shell/extensions' / UUID
extension.mkdir(parents=True, exist_ok=True)
for file in (ROOT / 'extension').iterdir():
    if file.is_file():
        shutil.copy2(file, extension / file.name)
for name in ('preferences.py', 'collector.py'):
    shutil.copy2(ROOT / 'src' / name, extension / name)
icon = HOME / '.local/share/icons/hicolor/scalable/apps/francos-system-monitor.svg'
put(icon, '''<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
<rect x="2" y="2" width="44" height="44" rx="11" fill="#18222e"/>
<path d="M10 34V22" stroke="#67b5ff" stroke-width="5"/>
<path d="M19 34V15" stroke="#ab92ff" stroke-width="5"/>
<path d="M28 34V25" stroke="#57d6b2" stroke-width="5"/>
<path d="M37 34V10" stroke="#ffbe70" stroke-width="5"/></svg>''')
launcher = HOME / '.local/bin/francos-system-monitor'
put(launcher, '''#!/bin/sh
exec gdbus call --session --dest local.francos.SystemMonitor --object-path /local/francos/SystemMonitor --method local.francos.SystemMonitor.Toggle
''')
launcher.chmod(0o755)
put(HOME / '.local/share/applications' / APP, f'''[Desktop Entry]
Type=Application
Name=Francos System Monitor
Comment=CPU, GPU, RAM e VRAM em tempo real
Exec="{launcher}"
Icon=francos-system-monitor
Terminal=false
Categories=System;Monitor;
StartupNotify=false
Actions=Preferences;

[Desktop Action Preferences]
Name=Configurações
Exec=/usr/bin/python3 "{extension}/preferences.py"
''')
put(HOME / '.config/systemd/user/francos-system-monitor.service', f'''[Unit]
Description=Francos System Monitor native telemetry
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart="{native_binary}"
Restart=on-failure
RestartSec=3
Nice=10
NoNewPrivileges=true

[Install]
WantedBy=graphical-session.target
''')
if not CONFIG.exists():
    put(CONFIG, json.dumps(settings(), indent=2) + '\n')
subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
if settings()['autostart']:
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'francos-system-monitor.service'], check=True)
else:
    subprocess.run(['systemctl', '--user', 'start', 'francos-system-monitor.service'], check=True)
shell = Gio.Settings.new('org.gnome.shell')
favorites = shell.get_strv('favorite-apps')
if APP not in favorites:
    shell.set_strv('favorite-apps', favorites + [APP])
enabled = shell.get_strv('enabled-extensions')
if UUID not in enabled:
    shell.set_strv('enabled-extensions', enabled + [UUID])
Gio.Settings.sync()
subprocess.run(['update-desktop-database', str(HOME / '.local/share/applications')], check=False)
print('Instalação por usuário concluída. A extensão nova precisa ser carregada na sessão atual ou no próximo login.')
