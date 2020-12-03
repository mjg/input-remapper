#!/usr/bin/python3
# -*- coding: utf-8 -*-
# key-mapper - GUI for device specific keyboard mappings
# Copyright (C) 2020 sezanzeb <proxima@hip70890b.de>
#
# This file is part of key-mapper.
#
# key-mapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# key-mapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with key-mapper.  If not, see <https://www.gnu.org/licenses/>.


"""Inject a keycode based on the mapping."""


import asyncio

import evdev

from keymapper.logger import logger
from keymapper.dev.ev_abs_mapper import JOYSTICK


def should_map_event_as_btn(type, code):
    """Does this event describe a button.

    Especially important for gamepad events, some of the buttons
    require special rules.

    Parameters
    ----------
    type : int
        one of evdev.events
    code : int
        linux keycode
    """
    if type == evdev.events.EV_KEY:
        return True

    if type == evdev.events.EV_ABS and code not in JOYSTICK:
        return True

    return False


def handle_keycode(code_code_mapping, macros, event, uinput):
    """Write the mapped keycode or forward unmapped ones.

    Parameters
    ----------
    code_code_mapping : dict
        mapping of linux-keycode to linux-keycode.
    macros : dict
        mapping of linux-keycode to _Macro objects
    """
    if event.value == 2:
        # button-hold event
        return

    input_keycode = event.code
    input_type = event.type

    if input_keycode in macros:
        if event.value != 1:
            # only key-down events trigger macros
            return

        macro = macros[input_keycode]
        logger.spam(
            'got code:%s value:%s, maps to macro %s',
            input_keycode,
            event.value,
            macro.code
        )
        asyncio.ensure_future(macro.run())
        return

    if input_keycode in code_code_mapping:
        target_keycode = code_code_mapping[input_keycode]
        target_type = evdev.events.EV_KEY
        logger.spam(
            'got code:%s value:%s event:%s, maps to EV_KEY:%s',
            input_keycode,
            event.value,
            evdev.ecodes.EV[event.type],
            target_keycode
        )
    else:
        logger.spam(
            'got unmapped code:%s value:%s',
            input_keycode,
            event.value,
        )
        target_keycode = input_keycode
        target_type = input_type

    uinput.write(target_type, target_keycode, event.value)
    uinput.syn()