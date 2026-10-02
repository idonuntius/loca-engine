"""Location backends.

A backend is the *only* thing that knows how a location is actually injected into a
device. Everything above it (service, API, CLI) depends solely on the
``LocationEngineBackend`` protocol in ``base.py``, so the real pymobiledevice3
implementation can be swapped for a fake (tests) or a future native implementation.
"""
