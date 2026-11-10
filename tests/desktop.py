"""GNOME Looking Glass QA through the existing virtual keyboard and X clipboard."""
import os
from pathlib import Path
import subprocess
import shutil
import time
os.environ.update(DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{os.getuid()}/bus',
                  XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}', WAYLAND_DISPLAY='wayland-0',
                  DISPLAY=':0', XAUTHORITY=os.environ.get('XAUTHORITY', ''))
XCLIP = shutil.which('xclip')
if not XCLIP:
    raise SystemExit('O teste gráfico requer xclip, wl-clipboard e ydotool instalados na sessão.')


def keys(*codes):
    subprocess.run(['ydotool', 'key', *codes], check=True, stdout=subprocess.DEVNULL)


def evaluate(command):
    base = [XCLIP, '-selection', 'clipboard']
    targets = subprocess.run(base + ['-out', '-target', 'TARGETS'], capture_output=True, timeout=3)
    available = targets.stdout.decode().splitlines()
    target = next((t for t in ['UTF8_STRING', 'image/png', 'STRING'] if t in available), None)
    original = subprocess.check_output(base + ['-out', '-target', target], timeout=3) if target else None
    try:
        subprocess.run(['wl-copy', '--type', 'text/plain;charset=utf-8'], input=command.encode(), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        keys('56:1', '60:1', '60:0', '56:0')
        time.sleep(0.4)
        subprocess.run(['ydotool', 'type', '--key-delay', '10', 'lg'], check=True)
        keys('28:1', '28:0')
        time.sleep(0.8)
        keys('29:1', '47:1', '47:0', '29:0')
        time.sleep(0.2)
        keys('28:1', '28:0')
        time.sleep(1.2)
        keys('1:1', '1:0')
    finally:
        if target:
            subprocess.run(['wl-copy', '--type', 'image/png' if target == 'image/png' else 'text/plain;charset=utf-8'], input=original, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)


if __name__ == '__main__':
    import sys
    evaluate(sys.argv[1])
