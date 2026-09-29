"""Existence resolution (ladder rules 4 and 5) and season-status gates (rule 9)."""

from db import db
from errors import ApiError

_NOT_FOUND = {
    "seasons": "ERR_SEASON_NOT_FOUND",
    "price_zones": "ERR_ZONE_NOT_FOUND",
    "stores": "ERR_STORE_NOT_FOUND",
    "items": "ERR_ITEM_NOT_FOUND",
    "sales_weeks": "ERR_ITEM_NOT_FOUND",
    "estimates": "ERR_ESTIMATE_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "steps": "ERR_STEP_NOT_FOUND",
    "executions": "ERR_EXECUTION_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "dispositions": "ERR_DISPOSITION_NOT_FOUND",
    "exit_reviews": "ERR_SEASON_NOT_FOUND",
}


def fetch(collection, row_id):
    row = db.get(collection, row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection],
                       "No such resource: %s" % (row_id,))
    return row


def season(row_id):
    return fetch("seasons", row_id)


def price_zone(row_id):
    return fetch("price_zones", row_id)


def store(row_id):
    return fetch("stores", row_id)


def item(row_id):
    return fetch("items", row_id)


def estimate(row_id):
    return fetch("estimates", row_id)


def plan(row_id):
    return fetch("plans", row_id)


def step(row_id):
    return fetch("steps", row_id)


def execution(row_id):
    return fetch("executions", row_id)


def reservation(row_id):
    return fetch("reservations", row_id)


def agreement(row_id):
    return fetch("agreements", row_id)


def claim(row_id):
    return fetch("claims", row_id)


def disposition(row_id):
    return fetch("dispositions", row_id)


def sales_week(row_id):
    return fetch("sales_weeks", row_id)


def exit_review(row_id):
    return fetch("exit_reviews", row_id)


# --------------------------------------------------------------------------
# Season-status gates (rule 9)
# --------------------------------------------------------------------------

def gate_not_closed(season_row):
    """A CLOSED season accepts no write at all."""
    if season_row is not None and season_row["status"] == "CLOSED":
        raise ApiError("ERR_SEASON_CLOSED",
                       "The governing season is CLOSED and accepts no writes.")


def gate_active(season_row):
    """The governing season must be ACTIVE or EXIT_WINDOW."""
    gate_not_closed(season_row)
    if season_row["status"] not in ("ACTIVE", "EXIT_WINDOW"):
        raise ApiError("ERR_SEASON_NOT_ACTIVE",
                       "The governing season must be ACTIVE or EXIT_WINDOW.")


def gate_exit_window(season_row):
    """The governing season must be in EXIT_WINDOW specifically."""
    gate_not_closed(season_row)
    if season_row["status"] != "EXIT_WINDOW":
        raise ApiError("ERR_SEASON_NOT_IN_EXIT_WINDOW",
                       "The governing season must be in EXIT_WINDOW.")
