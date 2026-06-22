"""Fallback: atajo global vía el portal GlobalShortcuts de KDE (modo TOGGLE).

No requiere grupo ``input``. No es push-to-talk real: la primera activación
empieza a grabar y la siguiente para (toggle), porque el evento de soltado del
portal no es fiable en KWin si se pulsan otras teclas (bug KWin 483183).

El usuario debe asignar la combinación real en
Preferencias del Sistema → Atajos de teclado → kwhisper, tras el primer arranque.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

_PORTAL = "org.freedesktop.portal.Desktop"
_PATH = "/org/freedesktop/portal/desktop"
_SHORTCUT_ID = "toggle_dictation"


# Introspección estática del objeto Request: permite suscribir el handler de
# Response ANTES de llamar a CreateSession (sin esperar a que el objeto exista),
# eliminando la carrera en que la señal llega antes de conectar el handler.
_REQUEST_XML = """<node>
  <interface name="org.freedesktop.portal.Request">
    <method name="Close"/>
    <signal name="Response">
      <arg type="u" name="response"/>
      <arg type="a{sv}" name="results"/>
    </signal>
  </interface>
</node>"""


class PortalListener:
    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None],
                 on_error: Callable[[str], None] | None = None):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_error = on_error
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recording = False

    def _toggle(self) -> None:
        try:
            if self._recording:
                self._recording = False
                self.on_stop()
            else:
                self._recording = True
                self.on_start()
        except Exception:  # noqa: BLE001
            log.exception("Error en toggle del portal")

    def _fail(self, msg: str) -> None:
        log.error(msg)
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:  # noqa: BLE001
                pass

    async def _setup(self) -> None:
        from dbus_next import Variant
        from dbus_next import introspection as intr
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType

        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        introspection = await bus.introspect(_PORTAL, _PATH)
        obj = bus.get_proxy_object(_PORTAL, _PATH, introspection)
        gs = obj.get_interface("org.freedesktop.portal.GlobalShortcuts")

        token = "kwhisper_create"
        session_token = "kwhisper_session"

        # Predecir el object path del Request y suscribir el handler ANTES de
        # CreateSession. Path: /org/freedesktop/portal/desktop/request/<SENDER>/<token>
        sender = bus.unique_name[1:].replace(".", "_")
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

        session_handle = {"value": None}
        done = asyncio.Event()

        req_node = intr.Node.parse(_REQUEST_XML)
        req_obj = bus.get_proxy_object(_PORTAL, request_path, req_node)
        req = req_obj.get_interface("org.freedesktop.portal.Request")

        def on_response(code, results):  # noqa: ANN001
            if code == 0 and "session_handle" in results:
                session_handle["value"] = results["session_handle"].value
            done.set()

        req.on_response(on_response)  # conectado antes de iniciar la petición

        await gs.call_create_session({
            "handle_token": Variant("s", token),
            "session_handle_token": Variant("s", session_token),
        })

        try:
            await asyncio.wait_for(done.wait(), timeout=15)
        except asyncio.TimeoutError:
            self._fail("El portal de atajos no respondió (timeout). "
                       "¿xdg-desktop-portal-kde activo? El hotkey no funcionará.")
            return

        sh = session_handle["value"]
        if not sh:
            self._fail("El portal no devolvió session_handle; el hotkey no funcionará.")
            return

        # BindShortcuts: registra el atajo (el usuario asigna la tecla en Preferencias).
        await gs.call_bind_shortcuts(
            sh,
            [(_SHORTCUT_ID, {"description": Variant("s", "kwhisper: dictar (toggle)")})],
            "",
            {},
        )

        def on_activated(session, shortcut_id, timestamp, options):  # noqa: ANN001
            if shortcut_id == _SHORTCUT_ID:
                self._toggle()

        gs.on_activated(on_activated)
        log.info("Portal GlobalShortcuts listo. Asigna la tecla en "
                 "Preferencias del Sistema → Atajos → kwhisper.")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._setup())
            self._loop.run_forever()
        except Exception:  # noqa: BLE001
            log.exception("Fallo en el listener del portal")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="portal-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
