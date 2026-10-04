"""Optimistic concurrency control (PRD §2.9).

Agency-scoped writes carry ``expected_agency_version`` and agent-scoped writes
carry ``expected_agent_version``.  A supplied value that does not match the
parent record's current ``version`` refuses the write with ERR_STALE_VERSION
(HTTP 412) and no state is changed.  An omitted field performs no check.

This is a pure version check: it does not depend on requests overlapping.
"""

from errors import ApiError, ERR_STALE_VERSION


def check(parent, supplied, field_name="expected_version"):
    if supplied is None:
        return
    try:
        supplied_value = int(supplied)
    except (TypeError, ValueError):
        raise ApiError(ERR_STALE_VERSION,
                       "%s must be an integer version." % field_name)
    if supplied_value != int(parent.get("version", 1)):
        raise ApiError(ERR_STALE_VERSION)