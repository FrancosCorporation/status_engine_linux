#!/usr/bin/python3
"""GTK4 preferences. Settings commit atomically when Apply is pressed."""
import json
from pathlib import Path
import subprocess
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio
from collector import CONFIG, METRICS, gpus, settings


class Preferences(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.francos.SystemMonitor.Preferences')
        self.connect('activate', self.activate)
        self.controls = {}

    def activate(self, *_):
        if self.get_active_window():
            self.get_active_window().present()
            return
        self.config = settings()
        window = Gtk.ApplicationWindow(application=self, title='Francos • Configurações', default_width=480, default_height=640)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=20, margin_bottom=20, margin_start=24, margin_end=24)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.set_child(body)
        outer.append(scroll)
        heading = Gtk.Label(label='Francos System Monitor', xalign=0)
        heading.add_css_class('title-2')
        body.append(heading)

        def row(label, widget):
            box = Gtk.Box(spacing=12)
            box.append(Gtk.Label(label=label, xalign=0, hexpand=True, wrap=True))
            box.append(widget)
            body.append(box)
            return widget

        self.controls['interval'] = row('Atualização em segundos', Gtk.SpinButton.new_with_range(0.5, 30, 0.5))
        self.controls['interval'].set_value(self.config['interval'])
        for key in METRICS:
            switch = Gtk.Switch(active=self.config['visible'][key], valign=Gtk.Align.CENTER)
            self.controls[f'visible-{key}'] = row(f'Mostrar {key.upper()}', switch)
            color = Gdk.RGBA()
            color.parse(self.config['colors'][key])
            self.controls[f'color-{key}'] = row(f'Cor de {key.upper()}', Gtk.ColorButton(rgba=color))
        for key, label in [('absolute', 'Memória em GiB'), ('history', 'Gráficos históricos'),
                           ('alerts', 'Alertas de utilização'), ('autostart', 'Coletar ao iniciar a sessão')]:
            self.controls[key] = row(label, Gtk.Switch(active=self.config[key], valign=Gtk.Align.CENTER))
        self.controls['threshold'] = row('Limite dos alertas (%)', Gtk.SpinButton.new_with_range(1, 100, 1))
        self.controls['threshold'].set_value(self.config['threshold'])
        self.controls['opacity'] = row('Opacidade (%)', Gtk.SpinButton.new_with_range(50, 100, 1))
        self.controls['opacity'].set_value(self.config['opacity'] * 100)
        self.controls['mini'] = row('Mini-indicadores', Gtk.DropDown.new_from_strings(['Barras', 'Gráficos']))
        self.controls['mini'].set_selected(1 if self.config['mini'] == 'graphs' else 0)
        self.controls['appearance'] = row('Aparência', Gtk.DropDown.new_from_strings(['Sistema', 'Claro', 'Escuro']))
        self.controls['appearance'].set_selected(['system', 'light', 'dark'].index(self.config['appearance']))
        self.devices = gpus()
        labels = ['Automática'] + [f"{g['name']} · {g['pci']}" for g in self.devices]
        self.controls['gpu'] = row('GPU AMD', Gtk.DropDown.new_from_strings(labels))
        self.controls['gpu'].set_selected(next((i + 1 for i, g in enumerate(self.devices) if g['pci'] == self.config['gpu']), 0))
        self.feedback = Gtk.Label(label='', xalign=0, wrap=True)
        outer.append(self.feedback)
        apply = Gtk.Button(label='Aplicar configurações')
        apply.add_css_class('suggested-action')
        apply.connect('clicked', self.save)
        outer.append(apply)
        window.set_child(outer)
        window.present()

    def save(self, *_):
        data = self.config.copy()
        data['interval'] = float(self.controls['interval'].get_value())
        data['opacity'] = self.controls['opacity'].get_value() / 100
        data['threshold'] = int(self.controls['threshold'].get_value())
        data['visible'] = {k: self.controls[f'visible-{k}'].get_active() for k in METRICS}
        data['colors'] = {}
        for key in METRICS:
            rgba = self.controls[f'color-{key}'].get_rgba()
            data['colors'][key] = '#{:02x}{:02x}{:02x}'.format(*[round(v * 255) for v in (rgba.red, rgba.green, rgba.blue)])
        for key in ('absolute', 'history', 'alerts', 'autostart'):
            data[key] = self.controls[key].get_active()
        data['mini'] = ['bars', 'graphs'][self.controls['mini'].get_selected()]
        data['appearance'] = ['system', 'light', 'dark'][self.controls['appearance'].get_selected()]
        selected = self.controls['gpu'].get_selected()
        data['gpu'] = self.devices[selected - 1]['pci'] if selected else ''
        try:
            subprocess.run(['systemctl', '--user', 'enable' if data['autostart'] else 'disable',
                            'francos-system-monitor.service'], check=True, capture_output=True)
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            temporary = CONFIG.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, indent=2) + '\n')
            temporary.replace(CONFIG)
            self.config = data
            self.feedback.set_text('Configurações salvas.')
        except (OSError, subprocess.CalledProcessError) as error:
            self.feedback.set_text(f'Falha ao salvar configurações. {error}')


if __name__ == '__main__':
    Preferences().run()
