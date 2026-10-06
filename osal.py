"""OS abstraction layer: everything on-duty needs from the operating system, behind one import.

    import osal
    osal.idle_seconds() · osal.system_asleep() · osal.display_count() · osal.mic_in_use()
    osal.list_voices() · osal.speak(voice, rate, text) · osal.notify(title, message, sound) · osal.play_alert(volume)

macOS is implemented (osal_macos.py). To port to Linux or Windows, add osal_linux.py / osal_windows.py with the same
functions (see CONTRIBUTING.md for what each one must do) and extend the dispatch below.
"""

import sys

if sys.platform == "darwin":
    from osal_macos import *  # noqa: F403
else:
    raise SystemExit(f"on-duty doesn't support {sys.platform!r} yet. Porting is welcome: see CONTRIBUTING.md (osal.py).")
