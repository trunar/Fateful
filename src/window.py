# MIT License
#
# Copyright (c) 2026 Unknown
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# SPDX-License-Identifier: MIT

import random
import time
import math
import sys
import ctypes
import ctypes.util
import queue
import threading
from pathlib import Path
from gettext import gettext as _

import gi

gi.require_version('PangoCairo', '1.0')

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, PangoCairo


@Gtk.Template(resource_path='/io/github/trunar/Fateful/window.ui')
class FatefulWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'FatefulWindow'

    content_box = Gtk.Template.Child()
    result_label = Gtk.Template.Child()
    history_box = Gtk.Template.Child()
    sound_button = Gtk.Template.Child()

    DIE_COUNT = 4
    HISTORY_LIMIT = 4
    HISTORY_ROW_HEIGHT = 34
    HISTORY_ROW_GAP = 3
    HISTORY_SLOT_PITCH = HISTORY_ROW_HEIGHT + HISTORY_ROW_GAP
    HISTORY_AREA_HEIGHT = (
        HISTORY_LIMIT * HISTORY_ROW_HEIGHT
        + (HISTORY_LIMIT - 1) * HISTORY_ROW_GAP)
    HISTORY_LANDING_DURATION = 0.36
    ROLL_DURATIONS = {
        'slow': 2.5,
        'default': 1.7,
        'fast': 1.0,
        'instant': 0.0,
    }
    PALETTE_COLORS = {
        'blue': (0x35 / 255, 0x84 / 255, 0xe4 / 255),
        'teal': (0x21 / 255, 0x90 / 255, 0xa4 / 255),
        'green': (0x3a / 255, 0x94 / 255, 0x4a / 255),
        'yellow': (0xc8 / 255, 0x88 / 255, 0x00 / 255),
        'orange': (0xed / 255, 0x5b / 255, 0x00 / 255),
        'red': (0xe6 / 255, 0x2d / 255, 0x42 / 255),
        'pink': (0xd5 / 255, 0x61 / 255, 0x99 / 255),
        'purple': (0x91 / 255, 0x41 / 255, 0xac / 255),
        'slate': (0x6f / 255, 0x83 / 255, 0x96 / 255),
    }
    LADDER = {
        -4: _('Horrifying'),
        -3: _('Catastrophic'),
        -2: _('Terrible'),
        -1: _('Poor'),
        0: _('Mediocre'),
        1: _('Average'),
        2: _('Fair'),
        3: _('Good'),
        4: _('Great'),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rng = random.SystemRandom()
        self._dice = []
        self._history = []
        self._rolling = False
        self._roll_started = 0.0
        self._roll_source = None
        self._history_animation_source = None
        self._sound_timeout_sources = []
        self._fate_font_available = self._register_fate_font()
        self.settings = self.get_application().settings
        package_dir = Path(__file__).resolve().parents[1]
        sound_dir = package_dir / 'sounds'
        if not sound_dir.is_dir():
            sound_dir = package_dir / 'data' / 'sounds'
        self._sound_files = sorted(sound_dir.glob('*.flac'))
        self.style_manager = Adw.StyleManager.get_default()
        self._result_color_provider = None
        self.history_box.set_size_request(330, self.HISTORY_AREA_HEIGHT)

        self.sound_button.set_active(
            not self.settings.get_boolean('sound-enabled'))
        self._update_sound_button()
        self.sound_button.connect('toggled', self._on_sound_toggled)
        self._install_styles()
        self._build_board()
        self.settings.connect('changed::dice-color', self._on_dice_color_changed)
        self.style_manager.connect('notify::accent-color', self._on_system_accent_changed)
        self._apply_dice_color()

        roll_action = Gio.SimpleAction.new('roll', None)
        roll_action.connect('activate', self._on_roll_action)
        self.add_action(roll_action)
        self.get_application().set_accels_for_action('win.roll', ['space'])
        self._sound_player = DiceSoundPlayer(
            self._sound_files,
            muted=not self.settings.get_boolean('sound-enabled'))

    def _install_styles(self):
        provider = Gtk.CssProvider()
        provider.load_from_resource('/io/github/trunar/Fateful/style.css')
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build_board(self):
        board = Gtk.Fixed()
        board.set_halign(Gtk.Align.CENTER)
        board.set_valign(Gtk.Align.CENTER)
        board.add_css_class('dice-board')

        for index in range(self.DIE_COUNT):
            die = FateDie()
            die.button.connect('clicked', self._on_die_clicked)
            self._dice.append(die)
            board.put(die.button, (index % 2) * 158, (index // 2) * 158)

        board.set_size_request(318, 318)

        self.content_box.remove(self.result_label)
        dice_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        dice_section.set_halign(Gtk.Align.CENTER)
        dice_section.set_valign(Gtk.Align.START)
        dice_section.set_vexpand(False)
        dice_section.append(board)
        dice_section.append(self.result_label)
        self.content_box.insert_child_after(dice_section, None)
        self.result_label.set_text('')
        self._render_history()

    def _on_roll_action(self, *_args):
        self._start_roll()

    def _on_die_clicked(self, *_args):
        self._start_roll()

    def _start_roll(self):
        if self._rolling:
            return

        self._rolling = True
        self._roll_started = time.monotonic()
        self.result_label.set_text('')
        speed = self.settings.get_string('animation-speed')
        self._roll_duration = self.ROLL_DURATIONS.get(speed, 1.7)
        if self._roll_duration == 0:
            self._schedule_roll_sounds(self._roll_duration)
            self._complete_roll()
            return

        self._schedule_roll_sounds(self._roll_duration)
        for die in self._dice:
            die.button.set_sensitive(False)
            die.start_animation(self._rng, self._roll_started)
            die.set_face(self._rng.choice((-1, 0, 1)))

        self._roll_source = GLib.timeout_add(32, self._animate_roll)

    def _schedule_roll_sounds(self, duration):
        self._clear_sound_timeouts()
        if not self.settings.get_boolean('sound-enabled') or not self._sound_files:
            return
        sound_count = (self._rng.randint(2, min(3, len(self._sound_files)))
                       if len(self._sound_files) > 1 else 1)
        sounds = self._rng.sample(self._sound_files, sound_count)
        if duration == 0:
            delays = [0.0]
            for _ in range(sound_count - 1):
                delays.append(delays[-1] + self._rng.uniform(0.14, 0.28))
        else:
            # Keep the sound starts in the roll's final stretch, spaced apart.
            final_stretch = min(duration, 0.8)
            start = duration - final_stretch
            delays = [
                max(0.0, start + final_stretch * (index + 1)
                    / (sound_count + 1) + self._rng.uniform(-0.04, 0.04))
                for index in range(sound_count)
            ]

        for sound_file, delay in zip(sounds, delays):
            source_ref = [None]

            def play_scheduled_sound(filename=sound_file,
                                     timeout_ref=source_ref):
                self._sound_timeout_sources.remove(timeout_ref[0])
                if self.settings.get_boolean('sound-enabled'):
                    self._play_sound(filename)
                return GLib.SOURCE_REMOVE

            source_id = GLib.timeout_add(
                max(1, round(delay * 1000)), play_scheduled_sound)
            source_ref[0] = source_id
            self._sound_timeout_sources.append(source_id)

    def _clear_sound_timeouts(self):
        for source_id in self._sound_timeout_sources:
            GLib.source_remove(source_id)
        self._sound_timeout_sources.clear()

    def _play_sound(self, sound_file):
        if not self.settings.get_boolean('sound-enabled'):
            return
        self._sound_player.play(sound_file)

    def _on_sound_toggled(self, button):
        enabled = not button.get_active()
        self.settings.set_boolean('sound-enabled', enabled)
        if not enabled:
            self._clear_sound_timeouts()
        self._sound_player.set_muted(not enabled)
        self._update_sound_button()

    def _update_sound_button(self):
        enabled = self.settings.get_boolean('sound-enabled')
        self.sound_button.set_active(not enabled)
        icon_name = ('audio-volume-high-symbolic' if enabled
                     else 'audio-volume-muted-symbolic')
        self.sound_button.set_child(Gtk.Image.new_from_icon_name(icon_name))
        self.sound_button.set_tooltip_text(
            _('Mute sounds') if enabled else _('Unmute sounds'))

    def _animate_roll(self):
        now = time.monotonic()
        elapsed = now - self._roll_started

        for die in self._dice:
            if now >= die.next_face_change:
                die.set_face(self._rng.choice((-1, 0, 1)))
                die.next_face_change = (
                    now + die.face_change_interval * self._rng.uniform(0.8, 1.2))

        if elapsed < self._roll_duration:
            for die in self._dice:
                die.area.queue_draw()
            return GLib.SOURCE_CONTINUE

        self._complete_roll()
        return GLib.SOURCE_REMOVE

    def _complete_roll(self):
        result_faces = [self._rng.choice((-1, 0, 1)) for _ in self._dice]
        for die, face in zip(self._dice, result_faces):
            die.set_face(face)
            die.stop_animation()
            die.button.set_sensitive(True)

        total = sum(result_faces)
        descriptor = self.LADDER[total]
        self.result_label.set_text(f'{descriptor} {total:+d}')
        self._history.insert(0, (result_faces, descriptor, total))
        self._history = self._history[:self.HISTORY_LIMIT]
        self._render_history(animate_newest=self._roll_duration > 0)
        self._rolling = False
        self._roll_source = None

    def _render_history(self, animate_newest=False):
        if self._history_animation_source:
            GLib.source_remove(self._history_animation_source)
            self._history_animation_source = None

        child = self.history_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.history_box.remove(child)
            child = next_child

        moving_rows = []
        for age, (faces, descriptor, total) in enumerate(self._history):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            row.set_halign(Gtk.Align.START)
            row.set_size_request(330, self.HISTORY_ROW_HEIGHT)
            row.add_css_class('history-row')
            row.set_opacity((0.50, 0.30, 0.16, 0.08)[age])

            for face in faces:
                if self._fate_font_available:
                    glyph = '+' if face > 0 else '-' if face < 0 else '.'
                    icon = Gtk.Label(label=glyph)
                    icon.set_size_request(26, -1)
                    icon.set_xalign(0.5)
                    icon.add_css_class('history-die')
                else:
                    icon = Gtk.DrawingArea()
                    icon.set_content_width(20)
                    icon.set_content_height(20)
                    icon.set_draw_func(lambda _area, cr, width, height,
                                       value=face: paint_die(
                                           cr, width, height, value, 0.0,
                                           inverse=True))
                row.append(icon)

            value = Gtk.Label(label=f'{descriptor} {total:+d}')
            value.add_css_class('history-value')
            value.add_css_class('history-result')
            row.append(value)

            target_y = age * self.HISTORY_SLOT_PITCH
            start_y = target_y
            if animate_newest:
                if age == 0:
                    start_y -= 52
                else:
                    start_y -= self.HISTORY_SLOT_PITCH

            self.history_box.put(row, 0, start_y)
            if animate_newest:
                moving_rows.append((row, start_y, target_y))

        if animate_newest and moving_rows:
            started_at = time.monotonic()

            def animate_history_landing():
                progress = min(
                    1.0,
                    (time.monotonic() - started_at) / self.HISTORY_LANDING_DURATION)
                eased = 1 + 2.2 * (progress - 1) ** 3 + 1.2 * (progress - 1) ** 2
                for row, start_y, target_y in moving_rows:
                    y = start_y + (target_y - start_y) * eased
                    self.history_box.move(row, 0, y)

                if progress < 1.0:
                    return GLib.SOURCE_CONTINUE
                for row, _start_y, target_y in moving_rows:
                    self.history_box.move(row, 0, target_y)
                self._history_animation_source = None
                return GLib.SOURCE_REMOVE

            self._history_animation_source = GLib.timeout_add(
                16, animate_history_landing)

    def _on_dice_color_changed(self, *_args):
        self._apply_dice_color()

    def _on_system_accent_changed(self, *_args):
        if self.settings.get_string('dice-color') == 'system':
            self._apply_dice_color()

    def _apply_dice_color(self):
        color_name = self.settings.get_string('dice-color')
        if color_name == 'system':
            rgba = self.style_manager.get_accent_color_rgba()
            color = (rgba.red, rgba.green, rgba.blue)
            css_color = rgba.to_string()
        else:
            color = self.PALETTE_COLORS.get(color_name,
                                           self.PALETTE_COLORS['blue'])
            css_color = '#{:02x}{:02x}{:02x}'.format(
                *(round(channel * 255) for channel in color))

        for die in self._dice:
            die.set_color(color)

        display = Gdk.Display.get_default()
        if not display:
            return
        if self._result_color_provider:
            Gtk.StyleContext.remove_provider_for_display(
                display, self._result_color_provider)
        self._result_color_provider = Gtk.CssProvider()
        self._result_color_provider.load_from_data(
            f'.roll-result {{ color: {css_color}; }}'.encode())
        Gtk.StyleContext.add_provider_for_display(
            display, self._result_color_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    @staticmethod
    def _register_fate_font():
        package_dir = Path(__file__).resolve().parents[1]
        font_path = package_dir / 'fonts' / 'Fate Core Font.ttf'
        if not font_path.is_file():
            font_path = package_dir / 'data' / 'fonts' / 'Fate Core Font.ttf'
        if not font_path.is_file():
            return False

        fontconfig_path = ctypes.util.find_library('fontconfig')
        if not fontconfig_path:
            return False
        try:
            fontconfig = ctypes.CDLL(fontconfig_path)
            add_app_font = fontconfig.FcConfigAppFontAddFile
            add_app_font.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
            add_app_font.restype = ctypes.c_int
            if not add_app_font(None, str(font_path).encode()):
                return False
            PangoCairo.FontMap.get_default().changed()
            return True
        except (AttributeError, OSError):
            return False


class DiceSoundPlayer:
    """Play and warm up sound pipelines without blocking GTK's main thread."""

    def __init__(self, sound_files, muted=False):
        self._sound_files = [str(path) for path in sound_files]
        self._commands = queue.Queue()
        self._muted = muted
        self._thread = threading.Thread(
            target=self._run, name='fateful-audio', daemon=True)
        self._thread.start()

    def play(self, sound_file):
        self._commands.put(('play', str(sound_file)))

    def set_muted(self, muted):
        self._commands.put(('mute', muted))

    def _run(self):
        try:
            gi.require_version('Gst', '1.0')
            from gi.repository import Gst
            Gst.init(None)
        except (ImportError, ValueError) as error:
            print(f'Unable to initialize dice audio: {error}', file=sys.stderr)
            return

        active_pipelines = []
        message_types = Gst.MessageType.ERROR | Gst.MessageType.EOS

        def start_pipeline(filename, warmup=False):
            pipeline = Gst.ElementFactory.make('playbin', None)
            if not pipeline:
                print('Unable to create dice audio playback pipeline',
                      file=sys.stderr)
                return
            pipeline.set_property(
                'uri', Gio.File.new_for_path(filename).get_uri())
            pipeline.set_property(
                'volume', 0.0 if warmup or self._muted else 0.7)
            result = pipeline.set_state(Gst.State.PLAYING)
            if result == Gst.StateChangeReturn.FAILURE:
                print(f'Unable to play dice sound: {filename}', file=sys.stderr)
                pipeline.set_state(Gst.State.NULL)
                return
            active_pipelines.append((pipeline, pipeline.get_bus(), warmup))

        if self._sound_files:
            # Open the audio backend silently before the first roll needs it.
            start_pipeline(random.choice(self._sound_files), warmup=True)

        running = True
        while running:
            try:
                command, value = self._commands.get(timeout=0.02)
            except queue.Empty:
                command, value = None, None

            if command == 'play':
                start_pipeline(value)
            elif command == 'mute':
                self._muted = value
                for pipeline, _bus, warmup in active_pipelines:
                    pipeline.set_property(
                        'volume', 0.0 if warmup or self._muted else 0.7)
            elif command == 'stop':
                running = False

            for entry in active_pipelines[:]:
                pipeline, bus, warmup = entry
                message = bus.timed_pop_filtered(0, message_types)
                if message is None:
                    continue
                if message.type == Gst.MessageType.ERROR:
                    error, _debug = message.parse_error()
                    print(f'Dice audio playback error: {error}', file=sys.stderr)
                pipeline.set_state(Gst.State.NULL)
                active_pipelines.remove(entry)

        for pipeline, _bus, _warmup in active_pipelines:
            pipeline.set_state(Gst.State.NULL)


class FateDie:
    def __init__(self):
        self.face = 0
        self.angle = 0.0
        self.direction = 1
        self._animation_start = 0.0
        self.angular_speed = 14.0
        self.angular_phase = 0.0
        self.movement_x_phase = 0.0
        self.movement_y_phase = 1.0
        self.movement_x_speed = 15.0
        self.movement_y_speed = 11.0
        self.face_change_interval = 0.12
        self.next_face_change = 0.0
        self.color = (0x35 / 255, 0x84 / 255, 0xe4 / 255)
        self.area = Gtk.DrawingArea()
        self.area.set_content_width(160)
        self.area.set_content_height(160)
        self.area.set_draw_func(self._draw)
        self.area.add_css_class('die-face')

        self.button = Gtk.Button(child=self.area)
        self.button.add_css_class('die-button')
        self.button.set_tooltip_text(_('Roll the Fate dice'))
        self.button.set_hexpand(True)
        self.button.set_vexpand(True)
        self.button.set_size_request(160, 160)

    @staticmethod
    def face_text(face):
        return '+' if face > 0 else '−' if face < 0 else ''

    def set_face(self, face):
        self.face = face
        self.area.queue_draw()

    def set_color(self, color):
        self.color = color
        self.area.queue_draw()

    def start_animation(self, rng, started_at):
        self.direction = rng.choice((-1, 1))
        self.angular_speed = rng.uniform(13.0, 22.0)
        self.angular_phase = rng.uniform(0.0, math.tau)
        self.movement_x_phase = rng.uniform(0.0, math.tau)
        self.movement_y_phase = rng.uniform(0.0, math.tau)
        self.movement_x_speed = rng.uniform(13.0, 24.0)
        self.movement_y_speed = rng.uniform(11.0, 20.0)
        self.face_change_interval = rng.uniform(0.06, 0.14)
        self.next_face_change = started_at + rng.uniform(0.0, self.face_change_interval)
        self._animation_start = started_at

    def stop_animation(self):
        self._animation_start = 0.0
        self.angle = 0.0
        self.area.queue_draw()

    def _draw(self, _area, cr, width, height):
        now = time.monotonic()
        if self._animation_start:
            t = now - self._animation_start
            self.angle = self.direction * 0.20 * math.sin(
                t * self.angular_speed + self.angular_phase)
            jiggle_x = 3.0 * math.sin(
                t * self.movement_x_speed + self.movement_x_phase)
            jiggle_y = 2.0 * math.sin(
                t * self.movement_y_speed + self.movement_y_phase)
        else:
            jiggle_x = 0.0
            jiggle_y = 0.0

        paint_die(cr, width, height, self.face, self.angle,
                  jiggle_x, jiggle_y, color=self.color)

    @staticmethod
    def _rounded_rectangle(cr, x, y, width, height, radius):
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        cr.close_path()


def paint_die(cr, width, height, face, angle, offset_x=0.0, offset_y=0.0,
              inverse=False, color=(0x35 / 255, 0x84 / 255, 0xe4 / 255)):
    size = min(width, height) * (0.92 if inverse else 0.80)
    x = (width - size) / 2
    y = (height - size) / 2
    cr.save()
    cr.translate(width / 2, height / 2)
    cr.rotate(angle)
    cr.translate(-width / 2, -height / 2)
    cr.translate(offset_x, offset_y)

    if inverse:
        cr.set_source_rgb(1, 1, 1)
    else:
        cr.set_source_rgb(*color)
    FateDie._rounded_rectangle(cr, x, y, size, size, size * 0.11)
    cr.fill()

    if face:
        if inverse:
            cr.set_operator(0)  # CAIRO_OPERATOR_CLEAR
        else:
            cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(max(4.0, size * 0.09))
        cr.set_line_cap(1)
        mid_x = width / 2
        mid_y = height / 2
        arm = size * 0.28
        cr.move_to(mid_x - arm, mid_y)
        cr.line_to(mid_x + arm, mid_y)
        if face > 0:
            cr.move_to(mid_x, mid_y - arm)
            cr.line_to(mid_x, mid_y + arm)
        cr.stroke()
        if inverse:
            cr.set_operator(2)  # CAIRO_OPERATOR_OVER

    cr.restore()
