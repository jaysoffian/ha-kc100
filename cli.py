#!/usr/bin/env -S uv run python
"""KC100 CLI: get/set individual camera features or dump all state.

Usage:
    ./cli.py <host> dump
    ./cli.py <host> get <feature>
    ./cli.py <host> set <feature> <value> [<value2> ...]
    ./cli.py <host> raw '{"module":{"method":{...}}}'

<host> is an IP address or hostname.
Credentials from env: KASA_USERNAME, KASA_PASSWORD.

Examples:
    ./cli.py kc100-porch.lan dump
    ./cli.py 192.168.1.139 get power
    ./cli.py 192.168.1.139 set power off
    ./cli.py 192.168.1.139 set motion.sensitivity high
    ./cli.py 192.168.1.139 set motion.sensitivity_level 5 5
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from custom_components.kc100.client import KC100Client, KC100ProtocolError

# feature-name -> (getter, setter, value-parser)
FEATURES: dict[str, tuple[str, str, type | None]] = {
    "power": ("get_power", "set_power", str),
    "led": ("get_led", "set_led", str),
    "motion.enabled": ("get_motion_enabled", "set_motion_enabled", str),
    "motion.sensitivity": ("get_motion_sensitivity", "set_motion_sensitivity", str),
    "motion.sensitivity_level": (
        "get_motion_sensitivity_level",
        "set_motion_sensitivity_level",
        None,
    ),
    "motion.min_trigger_time": (
        "get_motion_min_trigger_time",
        "set_motion_min_trigger_time",
        None,
    ),
    "motion.detect_area": ("get_motion_detect_area", "set_motion_detect_area", None),
    "sound.enabled": ("get_sound_enabled", "set_sound_enabled", str),
    "sound.sensitivity": ("get_sound_sensitivity", "set_sound_sensitivity", str),
    "resolution": ("get_resolution", "set_resolution", str),
    "quality": ("get_channel_quality", "set_channel_quality", str),
    "rotation": ("get_rotation", "set_rotation", int),
    "power_frequency": ("get_power_frequency", "set_power_frequency", int),
    "osd.logo": ("get_osd_logo", "set_osd_logo", str),
    "osd.time": ("get_osd_time", "set_osd_time", str),
    "night_vision": ("get_night_vision", "set_night_vision", str),
    "time": ("get_time", "", None),
    "cloud": ("get_cloud_info", "", None),
}


def _usage() -> None:
    print(__doc__, file=sys.stderr)
    print("\nfeatures:", file=sys.stderr)
    for name in FEATURES:
        print(f"  {name}", file=sys.stderr)
    sys.exit(2)


def _parse_value(raw: str, parser: type | None) -> Any:
    if parser is None:
        # try JSON, fall back to string
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return parser(raw)


async def _dump(client: KC100Client) -> None:
    for name, (getter, _, _) in FEATURES.items():
        try:
            val = await getattr(client, getter)()
        except KC100ProtocolError as e:
            val = f"<err {e.err_code}>"
        print(f"  {name:28} {val}")


async def _main() -> None:
    if len(sys.argv) < 3:
        _usage()
    host = sys.argv[1]
    action = sys.argv[2]
    username = os.environ.get("KASA_USERNAME")
    password = os.environ.get("KASA_PASSWORD")
    if not username or not password:
        print("set KASA_USERNAME and KASA_PASSWORD", file=sys.stderr)
        sys.exit(2)

    async with KC100Client(host, username, password) as client:
        if action == "dump":
            await _dump(client)
            return
        if action == "raw":
            if len(sys.argv) < 4:
                _usage()
            cmd = json.loads(sys.argv[3])
            resp = await client.send(cmd)
            print(json.dumps(resp, indent=2))
            return
        if action == "get":
            if len(sys.argv) < 4:
                _usage()
            feature = sys.argv[3]
            if feature not in FEATURES:
                _usage()
            getter = FEATURES[feature][0]
            val = await getattr(client, getter)()
            print(val)
            return
        if action == "set":
            if len(sys.argv) < 5:
                _usage()
            feature = sys.argv[3]
            if feature not in FEATURES:
                _usage()
            _, setter, parser = FEATURES[feature]
            if not setter:
                print(f"{feature} is read-only", file=sys.stderr)
                sys.exit(2)
            args = [_parse_value(a, parser) for a in sys.argv[4:]]
            await getattr(client, setter)(*args)
            # read back
            val = await getattr(client, FEATURES[feature][0])()
            print(f"ok, now: {val}")
            return
        _usage()


if __name__ == "__main__":
    asyncio.run(_main())
