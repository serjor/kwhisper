# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Push-to-talk activation listeners.

Two backends with the same interface (``start()`` / ``stop()`` and the
``on_start`` / ``on_stop`` callbacks):

* :class:`~kwhisper.hotkey.evdev_listener.EvdevListener` — PRIMARY. Reads
  ``/dev/input`` directly: detects KEY_DOWN (hold → record) and KEY_UP
  (release → transcribe). Requires membership in the ``input`` group.
* :class:`~kwhisper.hotkey.portal_listener.PortalListener` — FALLBACK in toggle
  mode via KDE's GlobalShortcuts portal. Does not require the ``input`` group but
  is not real push-to-talk (press to start / press to stop).
"""
