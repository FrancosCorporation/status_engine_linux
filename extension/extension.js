import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Cairo from 'cairo';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const APP = 'local.francos.SystemMonitor.desktop';
const KEYS = ['cpu', 'gpu', 'ram', 'vram'];
const XML = `<node><interface name="local.francos.SystemMonitor">
<method name="Toggle"/><method name="SetOpen"><arg type="b" direction="in"/></method>
<method name="Status"><arg type="s" direction="out"/></method>
</interface></node>`;

function color(cr, hex, alpha = 1) {
    const value = parseInt(hex.slice(1), 16);
    cr.setSourceRGBA((value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255, alpha);
}

function graph(area, values, hex, mini = false) {
    const cr = area.get_context();
    const [w, h] = area.get_surface_size();
    color(cr, hex, 0.12);
    cr.rectangle(0, h - 1, w, 1);
    cr.fill();
    if (values.length > 1) {
        cr.moveTo(0, h);
        values.forEach((value, i) => {
            const x = i * w / (values.length - 1);
            const y = h - Math.max(0, Math.min(100, value ?? 0)) / 100 * (h - 3);
            cr.lineTo(x, y);
        });
        cr.lineTo(w, h);
        cr.closePath();
        color(cr, hex, 0.13);
        cr.fill();
        color(cr, hex, 0.95);
        cr.setLineWidth(mini ? 1.2 : 1.8);
        let started = false;
        values.forEach((value, i) => {
            if (value === null) { started = false; return; }
            const x = i * w / (values.length - 1);
            const y = h - Math.max(0, Math.min(100, value)) / 100 * (h - 3);
            if (started) cr.lineTo(x, y); else cr.moveTo(x, y);
            started = true;
        });
        cr.stroke();
    }
    cr.$dispose();
}

export default class FrancosMonitor extends Extension {
    enable() {
        this._alive = true;
        this._data = null;
        this._binding = null;
        this._reading = false;
        this._lastAlert = 0;
        this._interfaceSettings = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        this._manager = new PopupMenu.PopupMenuManager(Main.layoutManager);
        this._bus = Gio.DBusExportedObject.wrapJSObject(XML, {
            Toggle: () => this._toggle(),
            SetOpen: open => { if (open !== Boolean(this._menu?.isOpen)) this._toggle(); },
            Status: () => this._status(),
        });
        this._bus.export(Gio.DBus.session, '/local/francos/SystemMonitor');
        this._busOwner = Gio.bus_own_name_on_connection(Gio.DBus.session,
            'local.francos.SystemMonitor', Gio.BusNameOwnerFlags.NONE, null, null);
        this._state = Gio.File.new_for_path(`${GLib.get_user_runtime_dir()}/francos-system-monitor.json`);
        this._cancellable = new Gio.Cancellable();
        this._monitor = this._state.monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._monitor.connect('changed', () => this._read());
        this._read();
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2000, () => {
            this._findLauncher();
            if (!this._data || Date.now() / 1000 - this._data.timestamp > Math.max(5, this._data.settings.interval * 3))
                this._read();
            return GLib.SOURCE_CONTINUE;
        });
        this._findLauncher();
    }

    // GNOME 50 adapter. Observe an existing launcher actor, without replacing
    // extension methods or changing Ubuntu Dock's source or preferences.
    _findLauncher() {
        if (this._binding) return;
        const search = actor => {
            if (String(actor).includes('DockAppIcon') && actor._delegate?.app?.get_id?.() === APP && actor._delegate.icon?._iconBin)
                return actor;
            for (const child of actor.get_children()) {
                const found = search(child);
                if (found) return found;
            }
            return null;
        };
        const actor = search(Main.layoutManager.uiGroup);
        if (!actor) return;
        const bin = actor._delegate.icon._iconBin;
        const original = bin.get_child();
        const area = new St.DrawingArea({width: 40, height: 40, x_expand: true, y_expand: true});
        area.connect('repaint', () => this._paintMini(area));
        bin.set_child(area);
        const container = actor.get_parent();
        const oldLabel = actor._delegate.app.get_name();
        container.setLabelText?.('');
        this._tip = new St.Label({style_class: 'dash-label francos-tooltip', visible: false});
        Main.layoutManager.addChrome(this._tip);
        const hover = actor.connect('notify::hover', () => this._syncTooltip());
        const click = actor.connect('captured-event', (_actor, event) => {
            if (event.type() === Clutter.EventType.BUTTON_PRESS && event.get_button() === 1) {
                this._toggle(event.get_time());
                return Clutter.EVENT_STOP;
            }
            if (event.type() === Clutter.EventType.BUTTON_RELEASE && event.get_button() === 1)
                return Clutter.EVENT_STOP;
            return Clutter.EVENT_PROPAGATE;
        });
        const destroy = actor.connect('destroy', () => {
            this._destroyMenu();
            this._destroyTooltip();
            this._binding = null;
        });
        this._binding = {actor, bin, original, area, click, destroy, hover, container, oldLabel};
        this._buildMenu(actor);
        area.queue_repaint();
        this._syncTooltip();
    }

    _buildMenu(actor) {
        this._menu = new PopupMenu.PopupMenu(actor, 0.5, St.Side.BOTTOM);
        this._menu.actor.add_style_class_name('francos-menu');
        Main.uiGroup.add_child(this._menu.actor);
        this._menu.actor.hide();
        // Consume a source-icon press before PopupMenuManager dismisses the
        // modal grab and redispatches that same press to the launcher.
        this._menu.actor.connect('captured-event', (_actor, event) => {
            const target = global.stage.get_event_actor(event);
            if (event.type() === Clutter.EventType.BUTTON_PRESS && event.get_button() === 1 && actor.contains(target)) {
                if (event.get_time() !== this._openingEventTime) this._menu.close();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this._manager.addMenu(this._menu);
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        const body = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL,
            style_class: 'francos-body', x_expand: true});
        item.add_child(body);
        this._menu.addMenuItem(item);
        body.add_child(new St.Label({text: 'Francos System Monitor', style_class: 'francos-title'}));
        body.add_child(new St.Label({text: 'Atividade do computador', style_class: 'francos-subtitle'}));
        this._cards = {};
        for (const key of KEYS) {
            const card = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL,
                style_class: 'francos-card', x_expand: true});
            const row = new St.BoxLayout({x_expand: true});
            const title = new St.Label({text: key.toUpperCase(), x_expand: true, style_class: 'francos-key'});
            const value = new St.Label({text: '—', style_class: 'francos-value'});
            row.add_child(title);
            row.add_child(value);
            card.add_child(row);
            const detail = new St.Label({text: '', style_class: 'francos-detail'});
            detail.clutter_text.set_line_wrap(true);
            detail.clutter_text.set_ellipsize(3);
            card.add_child(detail);
            const history = new St.DrawingArea({height: 24, x_expand: true});
            history.connect('repaint', () => {
                const data = this._data;
                graph(history, data?.history[key] ?? [], data?.settings.colors[key] ?? '#67b5ff');
            });
            card.add_child(history);
            const track = new St.Bin({height: 4, x_expand: true, style_class: 'francos-track',
                x_align: Clutter.ActorAlign.FILL});
            const fill = new St.Widget({height: 4, x_align: Clutter.ActorAlign.START});
            track.set_child(fill);
            track.connect('notify::width', () => this._updateFill(key));
            card.add_child(track);
            body.add_child(card);
            this._cards[key] = {card, title, value, detail, history, track, fill};
        }
        const footer = new St.BoxLayout({style_class: 'francos-footer', x_expand: true});
        this._updated = new St.Label({text: 'Aguardando coleta', x_expand: true, y_align: Clutter.ActorAlign.CENTER,
            style_class: 'francos-detail'});
        const button = new St.Button({label: 'Configurações', style_class: 'francos-settings', can_focus: true});
        button.connect('clicked', () => {
            this._menu.close();
            Gio.Subprocess.new(['/usr/bin/python3', `${this.path}/preferences.py`],
                Gio.SubprocessFlags.NONE);
        });
        footer.add_child(this._updated);
        footer.add_child(button);
        body.add_child(footer);
        this._menu.connect('open-state-changed', (_menu, open) => {
            if (open) this._render();
            this._syncTooltip();
        });
    }

    _updateFill(key) {
        const card = this._cards?.[key];
        if (!card || !this._data) return;
        card.fill.width = Math.max(0, card.track.width * (this._data.values[key] ?? 0) / 100);
        card.fill.set_style(`background-color: ${this._data.settings.colors[key]}; border-radius: 2px;`);
    }

    _read() {
        if (this._reading) return;
        this._reading = true;
        this._state.load_contents_async(this._cancellable, (file, result) => {
            if (!this._alive) return;
            this._reading = false;
            try {
                const [, bytes] = file.load_contents_finish(result);
                const data = JSON.parse(new TextDecoder().decode(bytes));
                if (this._data?.sequence === data.sequence && this._data?.timestamp === data.timestamp) {
                    if (Date.now() / 1000 - data.timestamp > Math.max(5, data.settings.interval * 3)) {
                        this._binding?.area.queue_repaint();
                        this._tooltip();
                        if (this._menu?.isOpen) this._render();
                    }
                    return;
                }
                this._data = data;
                this._binding?.area.queue_repaint();
                this._tooltip();
                if (this._menu?.isOpen) this._render();
                if (data.settings.alerts && Date.now() - this._lastAlert > 300000) {
                    const high = KEYS.filter(k => data.settings.visible[k] && data.values[k] >= data.settings.threshold);
                    if (high.length) {
                        Main.notify('Francos System Monitor', `${high.join(', ').toUpperCase()} acima de ${data.settings.threshold}%`);
                        this._lastAlert = Date.now();
                    }
                }
            } catch (error) {
                if (!this._cancellable.is_cancelled()) {
                    this._data = null;
                    this._tooltip();
                    this._binding?.area.queue_repaint();
                    if (this._menu?.isOpen) this._render();
                }
            }
        });
    }

    _tooltip() {
        if (!this._binding) return;
        const text = KEYS.filter(k => this._data?.settings.visible[k] ?? true)
            .map(k => `${k.toUpperCase()}: ${this._value(k)}`).join('\n');
        this._binding.actor.accessible_name = text;
        if (this._tip?.visible) {
            if (this._tip.get_text() !== text) this._tip.set_text(text);
            const [x, y] = this._binding.actor.get_transformed_position();
            const [width] = this._binding.actor.get_transformed_size();
            const [, tipWidth] = this._tip.get_preferred_width(-1);
            const [, tipHeight] = this._tip.get_preferred_height(tipWidth);
            const monitor = Main.layoutManager.findMonitorForActor(this._binding.actor);
            const left = Math.max(monitor.x + 5, Math.min(x + (width - tipWidth) / 2, monitor.x + monitor.width - tipWidth - 5));
            this._tip.set_position(Math.round(left), Math.round(y - tipHeight - 10));
        }
    }

    _syncTooltip() {
        if (this._tipTimer) GLib.source_remove(this._tipTimer);
        this._tipTimer = null;
        if (!this._binding?.actor.hover || this._menu?.isOpen) {
            this._tip?.hide();
            return;
        }
        this._tipTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
            this._tipTimer = null;
            this._tip.show();
            this._tooltip();
            return GLib.SOURCE_REMOVE;
        });
    }

    _destroyTooltip() {
        if (this._tipTimer) GLib.source_remove(this._tipTimer);
        this._tipTimer = null;
        this._tip?.destroy();
        this._tip = null;
    }

    _value(key) {
        const data = this._data;
        const value = data?.values[key];
        if (data && Date.now() / 1000 - data.timestamp > Math.max(5, data.settings.interval * 3)) return 'Indisponível';
        if (value === null || value === undefined) return 'Indisponível';
        if (data.settings.absolute && (key === 'ram' || key === 'vram')) {
            const mem = data[key];
            return `${(mem.used / 1073741824).toFixed(1)}/${(mem.total / 1073741824).toFixed(1)} GiB`;
        }
        const thermal = data.temperatures?.[key];
        const suffix = (key === 'cpu' || key === 'gpu') ?
            ` · ${Number.isFinite(thermal) ? `${thermal.toFixed(0)} °C` : 'temp. indisponível'}` : '';
        return `${value.toFixed(0)}%${suffix}`;
    }

    _paintMini(area) {
        const cr = area.get_context();
        const [w, h] = area.get_surface_size();
        color(cr, '#18222e', 0.95);
        cr.rectangle(1, 1, w - 2, h - 2);
        cr.fill();
        const data = this._data;
        const keys = KEYS.filter(k => data?.settings.visible[k] ?? true);
        const bw = (w - 12) / Math.max(1, keys.length);
        const stale = !data || Date.now() / 1000 - data.timestamp > Math.max(5, data.settings.interval * 3);
        keys.forEach((key, i) => {
            const hex = data?.settings.colors[key] ?? '#718197';
            const x = 6 + i * bw;
            const value = stale ? null : data.values[key];
            color(cr, hex, 0.22);
            cr.rectangle(x, 7, bw - 2, h - 14);
            cr.fill();
            color(cr, hex, value === null ? 0.35 : 1);
            if (data?.settings.mini === 'graphs' && !stale) {
                const values = data.history[key].slice(-16);
                cr.setLineWidth(1.4);
                values.forEach((v, n) => {
                    const px = x + n * (bw - 2) / Math.max(1, values.length - 1);
                    const py = h - 7 - (v ?? 0) / 100 * (h - 14);
                    if (n) cr.lineTo(px, py); else cr.moveTo(px, py);
                });
                cr.stroke();
            } else {
                const height = value === null ? 2 : Math.max(2, (h - 14) * value / 100);
                cr.rectangle(x, h - 7 - height, bw - 2, height);
                cr.fill();
            }
        });
        cr.$dispose();
    }

    _render() {
        const data = this._data;
        if (!data) {
            this._updated.text = 'Coletor indisponível';
            for (const card of Object.values(this._cards)) {
                card.value.text = 'Indisponível';
                card.detail.text = 'Aguardando dados do sistema';
            }
            return;
        }
        const {settings} = data;
        const light = settings.appearance === 'light' || (settings.appearance === 'system' &&
            this._interfaceSettings.get_string('color-scheme') !== 'prefer-dark');
        this._menu.actor.set_style(`color: ${light ? '#172332' : '#edf2fa'};`);
        const box = this._menu.box;
        box.set_style(`background-color: rgba(${light ? '246,248,252' : '25,30,40'},${settings.opacity}); border-radius: 16px;`);
        for (const key of KEYS) {
            const card = this._cards[key];
            card.card.visible = settings.visible[key];
            card.title.set_style(`color: ${settings.colors[key]};`);
            card.value.text = this._value(key);
            if (key === 'cpu') card.detail.text = `${data.cpu.name}\n${data.cpu.cores} núcleos · ${data.cpu.threads} threads`;
            else if (key === 'gpu') card.detail.text = data.gpu ? `${data.gpu.name}\n${data.gpu.driver} · ${data.gpu.pci}` : 'Sensor AMD indisponível';
            else card.detail.text = data.values[key] === null ? 'Sensor indisponível' :
                `${data.values[key].toFixed(1)}% em uso · ${key === 'ram' ? 'MemAvailable' : 'memória dedicada'}`;
            card.history.visible = settings.history;
            card.track.visible = key === 'ram' || key === 'vram';
            if (settings.history && card.card.visible) card.history.queue_repaint();
            this._updateFill(key);
        }
        const age = Date.now() / 1000 - data.timestamp;
        this._updated.text = age > Math.max(5, settings.interval * 3) ? 'Coleta desatualizada' :
            `Atualizado ${new Date(data.timestamp * 1000).toLocaleTimeString('pt-BR')}`;
    }

    _toggle(eventTime = 0) {
        if (!this._data || Date.now() / 1000 - this._data.timestamp > Math.max(5, this._data.settings.interval * 3))
            Gio.Subprocess.new(['systemctl', '--user', 'start', 'francos-system-monitor.service'], Gio.SubprocessFlags.NONE);
        this._findLauncher();
        if (!this._menu?.isOpen) this._openingEventTime = eventTime;
        this._menu?.toggle();
    }

    _status() {
        const actor = this._binding?.actor;
        const [x, y] = actor?.get_transformed_position() ?? [0, 0];
        const [width, height] = actor?.get_transformed_size() ?? [0, 0];
        return JSON.stringify({attached: Boolean(actor), open: Boolean(this._menu?.isOpen),
            x, y, width, height, sequence: this._data?.sequence ?? 0,
            timestamp: this._data?.timestamp ?? 0, values: this._data?.values, temperatures: this._data?.temperatures,
            cards: this._cards ? Object.fromEntries(KEYS.map(k => [k, this._cards[k].value.text])) : {},
            pointer: global.get_pointer(),
            tooltip: {visible: this._tip?.visible ?? false,
                text: this._tip?.get_text() ?? ''},
            panel: this._menu ? {width: this._menu.actor.width, height: this._menu.actor.height} : null});
    }

    _destroyMenu() {
        if (this._menu) {
            this._manager.removeMenu(this._menu);
            this._menu.destroy();
            this._menu = null;
        }
        this._cards = null;
    }

    disable() {
        this._alive = false;
        this._cancellable?.cancel();
        this._monitor?.cancel();
        this._monitor = null;
        if (this._timer) GLib.source_remove(this._timer);
        this._timer = null;
        this._destroyMenu();
        this._destroyTooltip();
        if (this._binding) {
            const {actor, bin, original, area, click, destroy, hover, container, oldLabel} = this._binding;
            actor.disconnect(click);
            actor.disconnect(destroy);
            actor.disconnect(hover);
            bin.set_child(original);
            area.destroy();
            container.setLabelText?.(oldLabel);
            this._binding = null;
        }
        this._bus?.unexport();
        if (this._busOwner) Gio.bus_unown_name(this._busOwner);
        this._bus = null;
        this._busOwner = 0;
        this._data = null;
    }
}
