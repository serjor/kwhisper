# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Helper interactivo: pulsa una tecla y muestra su nombre evdev para config.toml.

Uso:  kwhisper-findkey
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import evdev
        from evdev import ecodes
    except ImportError:
        print("Falta python-evdev. Instala con: sudo pacman -S python-evdev", file=sys.stderr)
        return 1

    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    keyboards = [d for d in devices if ecodes.EV_KEY in d.capabilities()]
    if not keyboards:
        print("No se encontró ningún teclado. ¿Estás en el grupo 'input'?", file=sys.stderr)
        print("  sudo usermod -aG input $USER   (luego cierra sesión y vuelve a entrar)", file=sys.stderr)
        return 1

    print("Pulsa la tecla que quieras usar para push-to-talk (Ctrl+C para salir)…\n")
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
                        continue  # solo KEY_DOWN
                    names = ecodes.keys.get(event.code, f"CODE_{event.code}")
                    name = names[0] if isinstance(names, (list, tuple)) else names
                    print(f"  tecla: {name}   (code={event.code})   dispositivo: {dev.path} — {dev.name}")
                    print(f'\n  → pon en ~/.config/kwhisper/config.toml:  key = "{name}"\n')
    except KeyboardInterrupt:
        print("\nFin.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
