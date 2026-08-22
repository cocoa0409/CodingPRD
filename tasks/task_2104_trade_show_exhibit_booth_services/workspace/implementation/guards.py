"""Shared rung guards from the precedence ladder in PRD §2.9."""
from errors import ApiError


def transition(current, terminal_states, allowed_from):
    """Rungs 10 and 11.

    A target already sitting in a terminal state of its machine is refused with
    ERR_ENTITY_TERMINAL; otherwise a from-state the transition does not declare
    is refused with ERR_INVALID_STATE_TRANSITION.
    """
    if current in terminal_states:
        raise ApiError("ERR_ENTITY_TERMINAL",
                       "The target is already in the terminal state %s" % current)
    if current not in allowed_from:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The transition is not declared from state %s" % current)


def occ(expected, actual, error_id):
    """Rung 12 — the declared parent version must equal the current version."""
    if int(expected) != int(actual):
        raise ApiError(error_id, "The declared parent version is stale")


def show_accepting(show, allowed_statuses):
    """Rung 13."""
    if show is None or show["status"] not in allowed_statuses:
        raise ApiError("ERR_SHOW_NOT_ACCEPTING",
                       "The show does not admit this operation in status %s"
                       % (show["status"] if show else "UNKNOWN"))


def booth_not_frozen(booth):
    """Rung 14."""
    if booth["posture"] == "FROZEN":
        raise ApiError("ERR_BOOTH_FROZEN", "The booth is FROZEN")


def booth_open(booth):
    """Rungs 14 then 15 — FROZEN outranks RESTRICTED where both would apply."""
    booth_not_frozen(booth)
    if booth["posture"] == "RESTRICTED":
        raise ApiError("ERR_BOOTH_RESTRICTED", "The booth is RESTRICTED")


def not_empty(values, label):
    """Rung 30."""
    if not values:
        raise ApiError("ERR_EMPTY_COLLECTION", "%s must not be empty" % label)
