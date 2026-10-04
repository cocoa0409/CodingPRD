"""Route blueprints for the PTAB docket API."""

from . import (
    clock,
    parties,
    patents,
    matters,
    petitions,
    proceedings,
    briefs,
    discovery,
    amendments,
    hearings,
    decisions,
    appeals,
    rooms,
)

ALL_BLUEPRINTS = [
    clock.bp,
    parties.bp,
    patents.bp,
    matters.bp,
    petitions.bp,
    proceedings.bp,
    briefs.bp,
    discovery.bp,
    amendments.bp,
    hearings.bp,
    decisions.bp,
    appeals.bp,
    rooms.bp,
]
