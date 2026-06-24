# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Listeners de activación push-to-talk.

Dos backends con la misma interfaz (``start()`` / ``stop()`` y callbacks
``on_start`` / ``on_stop``):

* :class:`~kwhisper.hotkey.evdev_listener.EvdevListener` — PRINCIPAL. Lee
  ``/dev/input`` directamente: detecta KEY_DOWN (mantener → grabar) y KEY_UP
  (soltar → transcribir). Requiere pertenecer al grupo ``input``.
* :class:`~kwhisper.hotkey.portal_listener.PortalListener` — FALLBACK en modo
  toggle vía el portal GlobalShortcuts de KDE. No requiere grupo ``input`` pero
  no hace push-to-talk real (pulsar para empezar / pulsar para parar).
"""
