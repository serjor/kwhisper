# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Push-to-talk listener via evdev (direct read from /dev/input).

Detects KEY_DOWN (value=1 → on_start) and KEY_UP (value=0 → on_stop) of the
configured key, ignoring autorepeat (value=2). It does not call ``grab()``: the
key still reaches the focused app, so a dedicated, rarely-used key is preferable.

Requires membership in the ``input`` group to read /dev/input/event*.
"""

from __future__ import annotations

import logging
import selectors
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class HotkeyPermissionError(RuntimeError):
    pass


class EvdevListener:
    def __init__(self, key_name: str, on_start: Callable[[], object],
                 on_stop: Callable[[], object], device_path: str = ""):
        self.key_name = key_name
        self.on_start = on_start
        self.on_stop = on_stop
        self.device_path = device_path
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._key_code: int | None = None
        self._pressed = False

    def _resolve_key(self) -> int:
        from evdev import ecodes
        code = ecodes.ecodes.get(self.key_name)
        if code is None:
            raise ValueError(
                f"Tecla desconocida: {self.key_name!r}. Usa `kwhisper-findkey` "
                f"para descubrir el nombre correcto (p.ej. KEY_PAUSE)."
            )
        return code

    def _open_devices(self):
        import evdev
        from evdev import ecodes

        if self.device_path:
            paths = [self.device_path]
        else:
            paths = evdev.list_devices()
        devices = []
        for p in paths:
            try:
                dev = evdev.InputDevice(p)
            except PermissionError as exc:
                raise HotkeyPermissionError(
                    "Sin permiso para leer /dev/input. Añádete al grupo input:\n"
                    "  sudo usermod -aG input $USER   (y vuelve a iniciar sesión)\n"
                    "O usa el fallback del portal:  [hotkey] backend = \"portal\""
                ) from exc
            caps = dev.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            # Monitor the keyboards that report our key (or all of them if going by device_path).
            if self.device_path or self._key_code in keys:
                devices.append(dev)
            else:
                dev.close()
        if not devices:
            raise HotkeyPermissionError(
                f"Ningún dispositivo expone la tecla {self.key_name}. "
                f"Comprueba con `kwhisper-findkey` o fija [hotkey] device."
            )
        log.info("Escuchando %d dispositivo(s) para la tecla %s",
                 len(devices), self.key_name)
        return devices

    def _run(self, devices: list) -> None:
        from evdev import ecodes

        sel = selectors.DefaultSelector()
        for d in devices:
            sel.register(d, selectors.EVENT_READ)
        try:
            while not self._stop_evt.is_set():
                for key, _ in sel.select(timeout=0.5):
                    dev = key.fileobj
                    try:
                        events = list(dev.read())
                    except OSError:
                        # Device gone (USB disconnected): we must unregister and
                        # close it, otherwise epoll keeps marking it ready in a
                        # tight loop → 100% CPU.
                        self._drop_device(sel, devices, dev)
                        continue
                    for event in events:
                        if event.type != ecodes.EV_KEY or event.code != self._key_code:
                            continue
                        if event.value == 1 and not self._pressed:      # KEY_DOWN
                            self._pressed = True
                            self._safe(self.on_start)
                        elif event.value == 0 and self._pressed:        # KEY_UP
                            self._pressed = False
                            self._safe(self.on_stop)
                        # value == 2 (autorepeat) → ignore
                if not devices and not self._stop_evt.is_set():
                    devices = self._reconnect(sel)
        finally:
            for d in devices:
                try:
                    d.close()
                except Exception:  # noqa: BLE001
                    pass

    @staticmethod
    def _drop_device(sel, devices: list, dev) -> None:  # noqa: ANN001
        try:
            sel.unregister(dev)
        except KeyError:
            pass
        try:
            dev.close()
        except Exception:  # noqa: BLE001
            pass
        if dev in devices:
            devices.remove(dev)
        log.warning("Teclado desconectado: %s", getattr(dev, "path", "?"))

    def _reconnect(self, sel) -> list:  # noqa: ANN001
        """Reopen devices with backoff after a USB disconnect."""
        delay = 1.0
        while not self._stop_evt.is_set():
            if self._stop_evt.wait(delay):
                return []
            try:
                devices = self._open_devices()
            except HotkeyPermissionError:
                delay = min(delay * 2, 30.0)  # no keyboard yet: wait longer
                continue
            for d in devices:
                sel.register(d, selectors.EVENT_READ)
            log.info("Teclado reconectado (%d dispositivo/s).", len(devices))
            return devices
        return []

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Error en callback de hotkey")

    def start(self) -> None:
        # Resolve the key and open the devices SYNCHRONOUSLY: this way a
        # permission error / nonexistent key propagates to the caller (app.py)
        # which reports it, instead of dying silently in the background thread.
        self._key_code = self._resolve_key()
        devices = self._open_devices()
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, args=(devices,),
                                        name="evdev-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2)
