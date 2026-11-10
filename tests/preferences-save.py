"""GTK4 save-handler integration. Restores the user's original settings."""
import json
import os
from pathlib import Path
import sys
os.environ.update(DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{os.getuid()}/bus',
                  XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}', WAYLAND_DISPLAY='wayland-0')
ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'evidence').mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'src'))
from preferences import Preferences
from collector import CONFIG
original = CONFIG.read_bytes()
app = Preferences()
result = {}
try:
    app.register(None)
    app.activate()
    app.controls['interval'].set_value(1.5)
    app.save()
    result['savedInterval'] = json.loads(CONFIG.read_text())['interval']
    result['feedback'] = app.feedback.get_text()
    assert result['savedInterval'] == 1.5
    assert result['feedback'] == 'Configurações salvas.'
    result['passed'] = True
finally:
    temporary = CONFIG.with_suffix('.tmp')
    temporary.write_bytes(original)
    temporary.replace(CONFIG)
    for window in app.get_windows():
        window.destroy()
    app.quit()
    result['restored'] = CONFIG.read_bytes() == original
    (ROOT / 'evidence/preferences-save.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
