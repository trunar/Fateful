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

import sys
import gi

from gettext import gettext as _

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw
from .window import FatefulWindow


COLOR_CHOICES = [
    ('system', _('Follow system')),
    ('blue', _('Blue')),
    ('teal', _('Teal')),
    ('green', _('Green')),
    ('yellow', _('Yellow')),
    ('orange', _('Orange')),
    ('red', _('Red')),
    ('pink', _('Pink')),
    ('purple', _('Purple')),
    ('slate', _('Slate')),
]

ANIMATION_CHOICES = [
    ('slow', _('Slow')),
    ('default', _('Default')),
    ('fast', _('Fast')),
    ('instant', _('Instant')),
]


class FatefulApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id='io.github.trunar.Fateful',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
                         resource_base_path='/io/github/trunar/Fateful')
        self.settings = Gio.Settings.new('io.github.trunar.Fateful')
        self.create_action('quit', lambda *_: self.quit(), ['<control>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action)
        self.create_action('shortcuts', self.on_shortcuts_action,
                           ['<control>question'])
        self._gtk_settings = None

    def do_activate(self):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        self._select_animation_default_from_system()
        self._watch_reduced_motion_setting()
        win = self.props.active_window
        if not win:
            win = FatefulWindow(application=self)
        win.present()

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        about = Adw.AboutDialog(application_name='Fateful',
                                application_icon='io.github.trunar.Fateful',
                                developer_name='Andrii Indyk',
                                version='0.1.0',
                                license_type=Gtk.License.MIT_X11,
                                # Translators: Replace "translator-credits" with your name/username, and optionally an email or URL.
                                translator_credits = _('translator-credits'),
                                developers=['Andrii Indyk'],
                                copyright='© 2026 Andrii Indyk')
        about.set_comments(
            _('A compact Fate dice roller for quick four-die rolls.'))
        about.add_legal_section(
            _('Dice sounds'),
            'Wuzzy',
            Gtk.License.CUSTOM,
            'CC0 1.0 Public Domain Dedication. '
            '<a href="https://opengameart.org/content/wooden-dice-on-wodden-table-roll">'
            'Source on OpenGameArt</a>')
        about.add_legal_section(
            _('Fate Core Font'),
            'Evil Hat Productions, LLC',
            Gtk.License.CUSTOM,
            _('Copyright © 2012 Evil Hat Productions, LLC. The embedded font '
              'notice names Fred Hicks and Jeremy Keller. The Four Actions '
              'icons were designed by Jeremy Keller. Used with permission.'))
        about.present(self.props.active_window)

    def on_preferences_action(self, *_args):
        """Present appearance and animation preferences."""
        self._select_animation_default_from_system()
        dialog = Adw.PreferencesDialog.new()
        page = Adw.PreferencesPage.new()
        page.set_title(_('General'))
        page.set_icon_name('preferences-other-symbolic')

        appearance = Adw.PreferencesGroup.new()
        appearance.set_title(_('Appearance'))
        color_row = Adw.ComboRow.new()
        color_row.set_title(_('Dice color'))
        color_row.set_subtitle(_('Choose a color for the dice.'))
        color_row.set_model(Gtk.StringList.new(
            [label for _value, label in COLOR_CHOICES]))
        color_index = next(
            (i for i, (value, _label) in enumerate(COLOR_CHOICES)
             if value == self.settings.get_string('dice-color')), 0)
        color_row.set_selected(color_index)
        color_row.connect('notify::selected', self._on_color_preference_changed)
        appearance.add(color_row)
        page.add(appearance)

        motion = Adw.PreferencesGroup.new()
        motion.set_title(_('Animation'))
        speed_row = Adw.ComboRow.new()
        speed_row.set_title(_('Roll speed'))
        speed_row.set_subtitle(_('Set how quickly the dice roll.'))
        speed_row.set_model(Gtk.StringList.new(
            [label for _value, label in ANIMATION_CHOICES]))
        speed_index = next(
            (i for i, (value, _label) in enumerate(ANIMATION_CHOICES)
             if value == self.settings.get_string('animation-speed')), 1)
        speed_row.set_selected(speed_index)
        speed_row.connect('notify::selected', self._on_speed_preference_changed)
        motion.add(speed_row)
        page.add(motion)

        dialog.add(page)
        dialog.present(self.props.active_window)

    def _on_color_preference_changed(self, row, _pspec):
        index = row.get_selected()
        if index < len(COLOR_CHOICES):
            self.settings.set_string('dice-color', COLOR_CHOICES[index][0])

    def _on_speed_preference_changed(self, row, _pspec):
        index = row.get_selected()
        if index < len(ANIMATION_CHOICES):
            self.settings.set_string('animation-speed', ANIMATION_CHOICES[index][0])
            self.settings.set_boolean('animation-speed-customized', True)

    def _select_animation_default_from_system(self):
        if self.settings.get_boolean('animation-speed-customized'):
            return

        gtk_settings = Gtk.Settings.get_default()
        if not gtk_settings:
            return
        try:
            reduced = int(gtk_settings.get_property(
                'gtk-interface-reduced-motion')) == 1
            reduced = reduced or not gtk_settings.get_property('gtk-enable-animations')
        except (AttributeError, TypeError, ValueError):
            reduced = not gtk_settings.get_property('gtk-enable-animations')

        self.settings.set_string('animation-speed', 'instant' if reduced else 'default')

    def _watch_reduced_motion_setting(self):
        if self._gtk_settings:
            return
        self._gtk_settings = Gtk.Settings.get_default()
        if not self._gtk_settings:
            return
        self._gtk_settings.connect(
            'notify::gtk-enable-animations', self._on_reduced_motion_changed)
        if self._gtk_settings.find_property('gtk-interface-reduced-motion'):
            self._gtk_settings.connect(
                'notify::gtk-interface-reduced-motion',
                self._on_reduced_motion_changed)

    def _on_reduced_motion_changed(self, *_args):
        self._select_animation_default_from_system()

    def on_shortcuts_action(self, *_args):
        """Show the keyboard shortcuts dialog."""
        builder = Gtk.Builder.new_from_resource(
            '/io/github/trunar/Fateful/shortcuts-dialog.ui')
        dialog = builder.get_object('shortcuts_dialog')
        dialog.present(self.props.active_window)

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version):
    """The application's entry point."""
    app = FatefulApplication()
    return app.run(sys.argv)
