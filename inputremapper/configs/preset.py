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
from __future__ import annotations

"""Contains and manages mappings."""

import os
import re
import json
import glob
import time

from typing import Tuple, Dict, List, Optional, Iterator, Type, Iterable, Any, Union

from pydantic import ValidationError
from inputremapper.logger import logger
from inputremapper.configs.mapping import Mapping
from inputremapper.configs.paths import touch, get_preset_path, mkdir

from inputremapper.input_event import InputEvent
from inputremapper.event_combination import EventCombination
from inputremapper.groups import groups


def common_data(list1: Iterable, list2: Iterable) -> List:
    """Return common members of two iterables as list."""
    # traverse in the 1st list
    common = []
    for x in list1:
        # traverse in the 2nd list
        for y in list2:
            # if one common
            if x == y:
                common.append(x)
    return common


class Preset:
    """Contains and manages mappings of a single preset."""

    _mappings: Dict[EventCombination, Mapping]
    # a copy of mappings for keeping track of changes
    _saved_mappings: Dict[EventCombination, Mapping]
    _path: Optional[os.PathLike]
    _mapping_factpry: Type[Mapping]  # the mapping class which is used by load()

    def __init__(
        self,
        path: Optional[os.PathLike] = None,
        mapping_factory: Type[Mapping] = Mapping,
    ) -> None:
        self._mappings = {}
        self._saved_mappings = {}
        self._path = path
        self._mapping_factory = mapping_factory

    def __iter__(self) -> Iterator[Mapping]:
        """Iterate over Mapping objects."""
        return iter(self._mappings.values())

    def __len__(self) -> int:
        return len(self._mappings)

    def has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changed."""
        return self._mappings != self._saved_mappings

    def remove(self, combination: EventCombination) -> None:
        """Remove a mapping from the preset by providing the EventCombination."""

        if not isinstance(combination, EventCombination):
            raise TypeError(
                f"combination must by of type EventCombination, got {type(combination)}"
            )

        for permutation in combination.get_permutations():
            if permutation in self._mappings.keys():
                combination = permutation
                break
        try:
            mapping = self._mappings.pop(combination)
            mapping.remove_combination_changed_callback()
        except KeyError:
            logger.debug(f"unable to remove non-existing mapping with {combination = }")
            pass

    def add(self, mapping: Mapping) -> None:
        """Add a mapping to the preset."""
        for permutation in mapping.event_combination.get_permutations():
            if permutation in self._mappings:
                raise KeyError(
                    "a mapping with this event_combination: %s already exists",
                    permutation,
                )

        mapping.set_combination_changed_callback(self._combination_changed_callback)
        self._mappings[mapping.event_combination] = mapping

    def empty(self) -> None:
        """Remove all mappings and custom configs without saving.
        note: self.has_unsaved_changes() will report True
        """
        for mapping in self._mappings.values():
            mapping.remove_combination_changed_callback()
        self._mappings = {}

    def clear(self) -> None:
        """Remove all mappings and also self.path."""
        self.empty()
        self._saved_mappings = {}
        self.path = None

    def load(self) -> None:
        """Load from the mapping from the disc, clears all existing mappings."""
        logger.info('Loading preset from "%s"', self.path)

        if not self.path or not os.path.exists(self.path):
            raise FileNotFoundError(f'Tried to load non-existing preset "{self.path}"')

        self._saved_mappings = self._get_mappings_from_disc()
        self.empty()
        for mapping in self._saved_mappings.values():
            # use the external add method to make sure
            # the _combination_changed_callback is attached
            self.add(mapping.copy())

    def save(self) -> None:
        """Dump as JSON to self.path."""

        if not self.path:
            logger.debug("unable to save preset without a path set Preset.path first")
            return

        touch(str(self.path))  # touch expects a string, not a Posix path
        if not self.has_unsaved_changes():
            return

        logger.info("Saving preset to %s", self.path)

        json_ready = {}
        saved_mappings = {}
        for mapping in self:
            if not mapping.is_valid():
                if not isinstance(mapping.event_combination, EventCombination):
                    # we save invalid mapping except for those with
                    # invalid event_combination
                    logger.debug("skipping invalid mapping %s", mapping)
                    continue
                combinations = [m.event_combination for m in self]
                common = common_data(
                    mapping.event_combination.get_permutations(), combinations
                )
                if len(common) > 1:
                    logger.debug(
                        "skipping mapping with duplicate event combination %s", mapping
                    )
                    continue

            d = mapping.dict(exclude_defaults=True)
            combination = d.pop("event_combination")
            json_ready[combination.json_str()] = d

            saved_mappings[combination] = mapping.copy()
            saved_mappings[combination].remove_combination_changed_callback()

        with open(self.path, "w") as file:
            json.dump(json_ready, file, indent=4)
            file.write("\n")

        self._saved_mappings = saved_mappings

    def is_valid(self) -> bool:
        return False not in [mapping.is_valid() for mapping in self]

    def get_mapping(self, combination: Optional[EventCombination]) -> Optional[Mapping]:
        """Return the Mapping that is mapped to this EventCombination.
        Parameters
        ----------
        combination : EventCombination
        """
        if not combination:
            return None

        if not isinstance(combination, EventCombination):
            raise TypeError(
                f"combination must by of type EventCombination, got {type(combination)}"
            )

        for permutation in combination.get_permutations():
            existing = self._mappings.get(permutation)
            if existing is not None:
                return existing

        return None

    def dangerously_mapped_btn_left(self) -> bool:
        """Return True if this mapping disables BTN_Left."""
        if EventCombination(InputEvent.btn_left()) not in [
            m.event_combination for m in self
        ]:
            return False

        values: List[str | Tuple[int, int] | None] = []
        for mapping in self:
            if mapping.output_symbol is None:
                continue
            values.append(mapping.output_symbol.lower())
            values.append(mapping.get_output_type_code())
        print(values)
        return (
            "btn_left" not in values
            or InputEvent.btn_left().type_and_code not in values
        )

    def _combination_changed_callback(
        self, new: EventCombination, old: EventCombination
    ) -> None:
        for permutation in new.get_permutations():
            if permutation in self._mappings.keys() and permutation != old:
                raise KeyError("combination already exists in the preset")
        self._mappings[new] = self._mappings.pop(old)

    def _update_saved_mappings(self) -> None:
        if self.path is None:
            return

        if not os.path.exists(self.path):
            self._saved_mappings = {}
            return
        self._saved_mappings = self._get_mappings_from_disc()

    def _get_mappings_from_disc(self) -> Dict[EventCombination, Mapping]:
        mappings: Dict[EventCombination, Mapping] = {}
        if not self.path:
            logger.debug("unable to read preset without a path set Preset.path first")
            return mappings

        with open(self.path, "r") as file:
            try:
                preset_dict = json.load(file)
            except json.JSONDecodeError:
                logger.error("unable to decode json file: %s", self.path)
                return mappings

        for combination, mapping_dict in preset_dict.items():
            try:
                mapping = self._mapping_factory(
                    event_combination=combination, **mapping_dict
                )
            except ValidationError as error:
                logger.error(
                    "failed to Validate mapping for %s: %s",
                    combination,
                    error,
                )
                continue

            mappings[mapping.event_combination] = mapping
        return mappings

    @property
    def path(self) -> Optional[os.PathLike]:
        return self._path

    @path.setter
    def path(self, path: Optional[os.PathLike]):
        if path != self.path:
            self._path = path
            self._update_saved_mappings()


###########################################################################
# Method from previously presets.py
# TODO: See what can be implemented as classmethod or
#  member function of Preset
###########################################################################


def get_available_preset_name(group_name, preset="new preset", copy=False):
    """Increment the preset name until it is available."""
    if group_name is None:
        # endless loop otherwise
        raise ValueError("group_name may not be None")

    preset = preset.strip()

    if copy and not re.match(r"^.+\scopy( \d+)?$", preset):
        preset = f"{preset} copy"

    # find a name that is not already taken
    if os.path.exists(get_preset_path(group_name, preset)):
        # if there already is a trailing number, increment it instead of
        # adding another one
        match = re.match(r"^(.+) (\d+)$", preset)
        if match:
            preset = match[1]
            i = int(match[2]) + 1
        else:
            i = 2

        while os.path.exists(get_preset_path(group_name, f"{preset} {i}")):
            i += 1

        return f"{preset} {i}"

    return preset


def get_presets(group_name: str) -> List[str]:
    """Get all preset filenames for the device and user, starting with the newest.

    Parameters
    ----------
    group_name : string
    """
    device_folder = get_preset_path(group_name)
    mkdir(device_folder)

    paths = glob.glob(os.path.join(device_folder, "*.json"))
    presets = [
        os.path.splitext(os.path.basename(path))[0]
        for path in sorted(paths, key=os.path.getmtime)
    ]
    # the highest timestamp to the front
    presets.reverse()
    return presets


def get_any_preset() -> Tuple[str | None, str | None]:
    """Return the first found tuple of (device, preset)."""
    group_names = groups.list_group_names()
    if len(group_names) == 0:
        return None, None
    any_device = list(group_names)[0]
    any_preset = get_presets(any_device)
    return any_device, any_preset[0] if any_preset else None


def find_newest_preset(group_name=None):
    """Get a tuple of (device, preset) that was most recently modified
    in the users home directory.

    If no device has been configured yet, return an arbitrary device.

    Parameters
    ----------
    group_name : string
        If set, will return the newest preset for the device or None
    """
    # sort the oldest files to the front in order to use pop to get the newest
    if group_name is None:
        paths = sorted(
            glob.glob(os.path.join(get_preset_path(), "*/*.json")),
            key=os.path.getmtime,
        )
    else:
        paths = sorted(
            glob.glob(os.path.join(get_preset_path(group_name), "*.json")),
            key=os.path.getmtime,
        )

    if len(paths) == 0:
        logger.debug("No presets found")
        return get_any_preset()

    group_names = groups.list_group_names()

    newest_path = None
    while len(paths) > 0:
        # take the newest path
        path = paths.pop()
        preset = os.path.split(path)[1]
        group_name = os.path.split(os.path.split(path)[0])[1]
        if group_name in group_names:
            newest_path = path
            break

    if newest_path is None:
        return get_any_preset()

    preset = os.path.splitext(preset)[0]
    logger.debug('The newest preset is "%s", "%s"', group_name, preset)

    return group_name, preset


def delete_preset(group_name, preset):
    """Delete one of the users presets."""
    preset_path = get_preset_path(group_name, preset)
    if not os.path.exists(preset_path):
        logger.debug('Cannot remove non existing path "%s"', preset_path)
        return

    logger.info('Removing "%s"', preset_path)
    os.remove(preset_path)

    device_path = get_preset_path(group_name)
    if os.path.exists(device_path) and len(os.listdir(device_path)) == 0:
        logger.debug('Removing empty dir "%s"', device_path)
        os.rmdir(device_path)


def rename_preset(group_name, old_preset_name, new_preset_name):
    """Rename one of the users presets while avoiding name conflicts."""
    if new_preset_name == old_preset_name:
        return old_preset_name

    new_preset_name = get_available_preset_name(group_name, new_preset_name)
    logger.info('Moving "%s" to "%s"', old_preset_name, new_preset_name)
    os.rename(
        get_preset_path(group_name, old_preset_name),
        get_preset_path(group_name, new_preset_name),
    )
    # set the modification date to now
    now = time.time()
    os.utime(get_preset_path(group_name, new_preset_name), (now, now))
    return new_preset_name
