"""Response helpers that reconcile version bumps before serialization."""

import derive
from envelope import ok


def saved(serializer, row, status=200):
    """Finish a mutating request: reconcile versions, then serialize."""
    derive.commit()
    return ok(serializer(row), status)


def made(serializer, row):
    return saved(serializer, row, 201)


def computed(data):
    """Finish a read-only computed endpoint."""
    return ok(data)
