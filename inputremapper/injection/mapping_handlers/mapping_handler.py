#!/usr/bin/python3
# -*- coding: utf-8 -*-
# input-remapper - GUI for device specific keyboard mappings
# Copyright (C) 2022 sezanzeb <proxima@sezanzeb.de>
#
# This file is part of input-remapper.
#
# input-remapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# input-remapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with input-remapper.  If not, see <https://www.gnu.org/licenses/>.
"""Provides protocols for mapping handlers


*** The architecture behind mapping handlers ***

Handling an InputEvent is done in 3 steps:
 1. Input Event Handling
    A MappingHandler that does Input event handling receives Input Events directly from the EventReader.
    To do so it must implement the InputEventHandler protocol.
    A InputEventHandler may handle multiple events (InputEvent.type_and_code)

 2. Event Transformation
    The event gets transformed as described by the mapping.
    e.g.: combining multiple events to a single one
        transforming EV_ABS to EV_REL
        macros
        ...
    Multiple transformations may get chained

 3. Event Injection
    The transformed event gets injected to a global_uinput

MappingHandlers can implement one or more of these steps.

Overview of implemented handlers and the steps they implement:

Step 1:
 - HierarchyHandler

Step 1 and 2:
 - CombinationHandler
 - AbsToBtnHandler
 - RelToBtnHandler

Step 1, 2 and 3:
 - AbsToRelHandler

Step 2 and 3:
 - KeyHandler
 - MacroHandler
"""
from __future__ import annotations

import enum

import evdev
from typing import Dict, Protocol, Set, Optional, List

from inputremapper.configs.mapping import Mapping
from inputremapper.configs.preset import Preset
from inputremapper.exceptions import MappingParsingError
from inputremapper.input_event import InputEvent, EventActions
from inputremapper.event_combination import EventCombination
from inputremapper.logger import logger


class EventListener(Protocol):
    async def __call__(self, event: evdev.InputEvent) -> None:
        ...


class ContextProtocol(Protocol):
    """The parts from context needed for macros."""

    preset: Preset
    listeners: Set[EventListener]


class InputEventHandler(Protocol):
    """The protocol any handler, which can be part of an event pipeline, must follow."""

    def notify(
        self,
        event: InputEvent,
        source: evdev.InputDevice,
        forward: evdev.UInput,
        supress: bool = False,
    ) -> bool:
        ...

    def reset(self) -> None:
        """Reset the state of the handler e.g. release any buttons."""
        ...


class HandlerEnums(enum.Enum):
    # converting to btn
    abs2btn = enum.auto()
    rel2btn = enum.auto()

    macro = enum.auto()
    key = enum.auto()

    # converting to "analog"
    btn2rel = enum.auto()
    rel2rel = enum.auto()
    abs2rel = enum.auto()

    btn2abs = enum.auto()
    rel2abs = enum.auto()
    abs2abs = enum.auto()

    # special handlers
    combination = enum.auto()
    hierarchy = enum.auto()
    axisswitch = enum.auto()
    disable = enum.auto()


class MappingHandler(InputEventHandler):
    """The protocol an InputEventHandler must follow if it should be
    dynamically integrated in an event-pipeline by the mapping parser
    """

    mapping: Mapping
    # all input events this handler cares about
    # should always be a subset of mapping.event_combination
    input_events: List[InputEvent]
    _sub_handler: Optional[InputEventHandler]

    # https://bugs.python.org/issue44807
    def __init__(
        self,
        combination: EventCombination,
        mapping: Mapping,
        **_,
    ) -> None:
        """Initialize the handler

        Parameters
        ----------
        combination : EventCombination
            the combination from sub_handler.wrap_with()
        mapping :  Mapping
        """
        new_combination = []
        for event in combination:
            if event.value != 0:
                event = event.modify(action=EventActions.as_key)
            new_combination.append(event)

        self.mapping = mapping
        self.input_events = new_combination
        self._sub_handler = None

    def needs_wrapping(self) -> bool:
        """If this handler needs to be wrapped in another MappingHandler."""
        return len(self.wrap_with()) > 0

    def needs_ranking(self) -> bool:
        """If this handler needs ranking and wrapping with a HierarchyHandler."""
        return False

    def rank_by(self) -> Optional[EventCombination]:
        """The combination for which this handler needs ranking."""
        pass

    def wrap_with(self) -> Dict[EventCombination, HandlerEnums]:
        """A dict of EventCombination -> HandlerEnums."""
        # this handler should be wrapped with the MappingHandler corresponding
        # to the HandlerEnums, and the EventCombination as first argument
        # TODO: better explanation
        return {}

    def set_sub_handler(self, handler: InputEventHandler) -> None:
        """Give this handler a sub_handler."""
        self._sub_handler = handler

    def occlude_input_event(self, event: InputEvent) -> None:
        """Remove the event from self.input_events."""
        if not self.input_events:
            logger.debug_mapping_handler(self)
            raise MappingParsingError(
                "cannot remove a non existing event", mapping_handler=self
            )
        # should be called for each event a wrapping-handler
        # has in its input_events EventCombination
        self.input_events.remove(event)
