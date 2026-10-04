"""Shared existence/state guards used across route modules.

Pipeline placement (PRD §2.7): existence is tier 3 (path ids left to right,
then body-supplied FK references); the establishment state gates
(NOT_GRANTED / SUSPENDED / WITHDRAWN) are tier 5.
"""
import store
from errors import (
    raise_err,
    ERR_ESTABLISHMENT_NOT_FOUND,
    ERR_ESTABLISHMENT_WITHDRAWN,
    ERR_ESTABLISHMENT_NOT_GRANTED,
    ERR_ESTABLISHMENT_SUSPENDED,
)


def entity_or_404(kind, entity_id, error_pair):
    entity = store.get(kind, entity_id)
    if entity is None:
        raise_err(error_pair, "%s does not exist" % kind[:-1])
    return entity


def establishment_or_404(establishment_id):
    return entity_or_404("establishments", establishment_id, ERR_ESTABLISHMENT_NOT_FOUND)


def require_not_withdrawn(establishment):
    """PRD §2.5: withdrawal is terminal; any subsequent operational write
    against a withdrawn establishment is rejected."""
    if establishment is not None and establishment["grant_status"] == "WITHDRAWN":
        raise_err(ERR_ESTABLISHMENT_WITHDRAWN, "establishment grant is withdrawn")


def require_granted(establishment):
    if establishment["grant_status"] != "GRANTED":
        raise_err(ERR_ESTABLISHMENT_NOT_GRANTED, "establishment does not hold a grant")


def require_not_suspended(establishment):
    if establishment["inspection_status"] == "SUSPENDED":
        raise_err(ERR_ESTABLISHMENT_SUSPENDED, "establishment is suspended")
