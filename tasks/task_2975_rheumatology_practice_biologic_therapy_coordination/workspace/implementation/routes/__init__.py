"""Route blueprints, one module per domain area of PRD section 3."""

from . import (
    appointments,
    assistance,
    authorizations,
    episodes,
    labs,
    ops,
    reference,
    screening,
    visits,
)

BLUEPRINTS = (
    reference.bp,
    visits.bp,
    screening.bp,
    episodes.bp,
    authorizations.bp,
    labs.bp,
    appointments.bp,
    assistance.bp,
    ops.bp,
)

__all__ = ["BLUEPRINTS"]
