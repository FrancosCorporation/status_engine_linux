import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const ROOT = `${Gio.File.new_for_uri(import.meta.url.split('?')[0]).get_parent().get_parent().get_path()}/evidence`;
GLib.mkdir_with_parents(ROOT, 0o755);
const delay = milliseconds => new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, milliseconds,
    () => { resolve(); return GLib.SOURCE_REMOVE; }));
const assert = (condition, message) => { if (!condition) throw new Error(message); };
async function capture(name) {
    const stream = Gio.File.new_for_path(`${ROOT}/${name}.png`).replace(null, false, Gio.FileCreateFlags.NONE, null);
    try { await new Shell.Screenshot().screenshot(false, stream); } finally { stream.close(null); }
}

export async function run() {
    const results = {started: new Date().toISOString(), checks: {}};
    const seat = global.stage.context.get_backend().get_default_seat();
    const pointer = seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
    const keyboard = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
    const ext = Main.extensionManager.lookup('francos-monitor@francos.local').stateObj;
    const move = (x, y) => pointer.notify_absolute_motion(GLib.get_monotonic_time(), x, y);
    const click = async (x, y) => {
        move(x, y);
        pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        await delay(40);
        pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
        await delay(450);
    };
    const sourceClick = async () => {
        const [x, y] = ext._binding.actor.get_transformed_position();
        const [w, h] = ext._binding.actor.get_transformed_size();
        await click(x + w / 2, y + h / 2);
    };
    try {
        await delay(2700);
        if (ext._menu.isOpen) ext._menu.close();
        assert(ext._binding.actor.mapped, 'Launcher is not mapped');
        results.checks.A = JSON.parse(ext._status());
        await sourceClick();
        assert(ext._menu.isOpen, 'First dock click failed');
        results.checks.B = JSON.parse(ext._status());
        await capture('panel-dark');
        await sourceClick();
        assert(!ext._menu.isOpen, 'Second dock click failed');
        const sequence = ext._data.sequence;
        await delay(2300);
        assert(ext._data.sequence > sequence, 'Closed panel stopped collection');
        await sourceClick();
        keyboard.notify_keyval(GLib.get_monotonic_time(), Clutter.KEY_Escape, Clutter.KeyState.PRESSED);
        keyboard.notify_keyval(GLib.get_monotonic_time(), Clutter.KEY_Escape, Clutter.KeyState.RELEASED);
        await delay(400);
        assert(!ext._menu.isOpen, 'Escape failed');
        await sourceClick();
        await click(1800, 1100);
        assert(!ext._menu.isOpen, 'Outside click failed');
        results.checks.C = {secondClick: true, escape: true, outside: true, collectionContinues: true};
        const [x, y] = ext._binding.actor.get_transformed_position();
        const tooltip = ext._tip;
        let samples = [];
        let interferenceRetries = 0;
        move(x + 26, y + 29);
        await delay(1000);
        for (let attempt = 0; attempt < 16 && samples.length < 4; attempt++) {
            await delay(1100);
            const [px, py] = global.get_pointer();
            if (!ext._binding.actor.hover || Math.abs(px - x - 26) > 3 || Math.abs(py - y - 29) > 3) {
                interferenceRetries++;
                samples = [];
                move(x + 26, y + 29);
                continue;
            }
            assert(tooltip.visible, 'Hover tooltip is not visible');
            const text = tooltip.get_text();
            const expected = ['cpu', 'gpu', 'ram', 'vram'].filter(k => ext._data.settings.visible[k])
                .map(k => `${k.toUpperCase()}: ${ext._value(k)}`).join('\n');
            assert(text === expected, `Tooltip mismatch. Actual=${JSON.stringify(text)} expected=${JSON.stringify(expected)}`);
            assert(!ext._menu.isOpen, 'Hover opened the dashboard');
            samples.push({sequence: ext._data.sequence, text});
        }
        assert(samples.length === 4, 'Physical pointer activity prevented a stationary-hover test');
        assert(new Set(samples.map(s => s.sequence)).size === 4, 'Hover data did not advance');
        results.checks.hover = {stationary: true, samples, interferenceRetries};
        await capture('hover-live');
        move(1800, 1100);
        await delay(400);
        const cycles = [];
        for (let i = 0; i < 15; i++) {
            await sourceClick();
            assert(ext._menu.isOpen, `Repeated open failed at cycle ${i}`);
            await sourceClick();
            assert(!ext._menu.isOpen, `Repeated close failed at cycle ${i}`);
            cycles.push(ext._data.sequence);
        }
        results.checks.H = {cycles: cycles.length, final: JSON.parse(ext._status())};
        await sourceClick();
        const find = actor => {
            if (actor instanceof St.Button && actor.label === 'Configurações') return actor;
            for (const child of actor.get_children()) { const found = find(child); if (found) return found; }
            return null;
        };
        const button = find(ext._menu.actor);
        assert(button, 'Settings button missing');
        const [bx, by] = button.get_transformed_position();
        await click(bx + button.width / 2, by + button.height / 2);
        await delay(1500);
        const window = global.get_window_actors().map(a => a.meta_window)
            .find(w => w.get_title() === 'Francos • Configurações');
        assert(window, 'Settings window did not open');
        results.checks.settings = {openedFromPanel: true};
        await capture('preferences');
        window.delete(global.get_current_time());
        results.passed = true;
    } catch (error) {
        results.passed = false;
        results.error = String(error);
        await capture('desktop-failure');
    } finally {
        if (ext._menu.isOpen) ext._menu.close();
        pointer.run_dispose();
        keyboard.run_dispose();
        results.finished = new Date().toISOString();
        GLib.file_set_contents(`${ROOT}/desktop-checks.json`, JSON.stringify(results, null, 2));
    }
}
