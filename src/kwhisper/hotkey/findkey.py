# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Interactive helper: press a key and show its evdev name for config.toml.

Usage:  kwhisper-findkey
"""

from __future__ import annotations

import sys

from ..i18n import t


def main() -> int:
    try:
        import evdev
        from evdev import ecodes
    except ImportError:
        print(t("findkey.no_evdev"), file=sys.stderr)
        return 1

    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    keyboards = [d for d in devices if ecodes.EV_KEY in d.capabilities()]
    if not keyboards:
        print(t("findkey.no_keyboard"), file=sys.stderr)
        print(t("findkey.no_keyboard_hint"), file=sys.stderr)
        return 1

    print(t("findkey.prompt"))
    import selectors

    sel = selectors.DefaultSelector()
    for d in keyboards:
        sel.register(d, selectors.EVENT_READ)

    try:
        while True:
            for key, _ in sel.select():
                dev = key.fileobj
                for event in dev.read():
                    if event.type != ecodes.EV_KEY or event.value != 1:
                        continue  # KEY_DOWN only
                    names = ecodes.keys.get(event.code, f"CODE_{event.code}")
                    name = names[0] if isinstance(names, (list, tuple)) else names
                    print(t("findkey.key_line", name=name, code=event.code,
                            path=dev.path, dev=dev.name))
                    print(t("findkey.config_hint", name=name))
    except KeyboardInterrupt:
        print(t("findkey.done"))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
