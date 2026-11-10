import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
const ROOT = Gio.File.new_for_uri(import.meta.url.split('?')[0]).get_parent().get_parent().get_path();
GLib.mkdir_with_parents(`${ROOT}/evidence`, 0o755);
const delay = ms => new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => { resolve(); return GLib.SOURCE_REMOVE; }));
const assert = (value, message) => { if (!value) throw new Error(message); };

export async function run() {
    const results = {};
    const ext = Main.extensionManager.lookup('francos-monitor@francos.local').stateObj;
    const file = Gio.File.new_for_path(`${GLib.get_home_dir()}/.config/francos-system-monitor/settings.json`);
    const original = file.load_contents(null)[1];
    const saved = JSON.parse(new TextDecoder().decode(original));
    try {
        await delay(2700);
        const options = {...saved, appearance: 'light', absolute: false, mini: 'graphs', history: false,
            interval: 0.5, opacity: 0.85, visible: {...saved.visible, gpu: false}};
        file.replace_contents(JSON.stringify(options), null, false, Gio.FileCreateFlags.NONE, null);
        await delay(1800);
        const start = ext._data.sequence;
        ext._menu.open();
        await delay(1000);
        assert(ext._data.settings.interval === 0.5, 'Native interval not reloaded');
        assert(!ext._cards.gpu.card.visible, 'Metric visibility failed');
        assert(!ext._cards.cpu.history.visible, 'History toggle failed');
        assert(ext._cards.ram.value.text.endsWith('%'), 'Percentage mode failed');
        assert(ext._data.settings.mini === 'graphs', 'Mini graph setting failed');
        assert(ext._data.sequence - start >= 1, 'Fast sampling failed');
        const stream = Gio.File.new_for_path(`${ROOT}/evidence/panel-light.png`).replace(null, false, Gio.FileCreateFlags.NONE, null);
        await new Shell.Screenshot().screenshot(false, stream);
        stream.close(null);
        results.liveSettings = true;
        results.light = JSON.parse(ext._status());
        ext._menu.close();
        results.passed = true;
    } catch (error) {
        results.passed = false;
        results.error = String(error);
    } finally {
        file.replace_contents(original, null, false, Gio.FileCreateFlags.NONE, null);
        await delay(1500);
        results.originalRestored = ext._data.settings.appearance === saved.appearance && ext._data.settings.interval === saved.interval;
        GLib.file_set_contents(`${ROOT}/evidence/configuration-checks.json`, JSON.stringify(results, null, 2));
    }
}
