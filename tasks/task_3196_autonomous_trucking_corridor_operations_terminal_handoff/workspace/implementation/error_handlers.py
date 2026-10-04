"""ApiError delivery.

`app.py` installs the blanket handler; this module exposes the helper the
handlers use so the error envelope is produced in exactly one place.
"""

from core import ApiError
from response import error_envelope


def handle(error):
    return error_envelope(error)


__all__ = ["ApiError", "handle"]