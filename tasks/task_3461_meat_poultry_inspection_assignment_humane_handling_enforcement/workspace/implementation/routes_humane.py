"""Humane handling observation and egregious-event authority (PRD §3.5)."""
from flask import Blueprint, request

import store
from authz import require_ownership, require_roles
from cascades import egregious_humane_cascade
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_HUMANE_EVENT_NOT_FOUND,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SOD_REVIEWER_IS_ISSUER,
    ERR_SPECIES_NOT_SUPPORTED,
)
from guards import entity_or_404, establishment_or_404, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import SEVERITIES, SPECIES_ENUM, not_future, require_enum, require_string, require_timestamp

bp = Blueprint("humane_handling_events", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


def _event_or_404(event_id):
    return entity_or_404("humane_events", event_id, ERR_HUMANE_EVENT_NOT_FOUND)


def _decide(event_id, decision):
    user_id, _ = require_roles("SupervisoryReviewer")
    event = _event_or_404(event_id)
    # Withdrawal freeze precedes the resource-state check within tier 5 (PRD §2.5/§2.7).
    establishment = establishment_or_404(event["establishment_id"])
    require_not_withdrawn(establishment)
    # Tier 5 state check precedes the tier 10 segregation check (PRD §2.7).
    if event["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "decision requires status REPORTED")
    if user_id == event["reported_by_inspector_id"]:
        raise_err(ERR_SOD_REVIEWER_IS_ISSUER, "reviewer must not be the reporting inspector")
    event["status"] = decision
    touch(event)
    if decision == "CONFIRMED" and event["severity"] == "EGREGIOUS":
        # Immediate suspension authority: the auto action is born IN_EFFECT
        # and its activation cascade fires in the same request.
        egregious_humane_cascade(establishment)
    return success_object(event)


@bp.post("/inspection/humane-handling-events")
def create_event():
    user_id, _ = require_roles("Inspector")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    reported_by_inspector_id = require_string(body, "reported_by_inspector_id")
    species = require_enum(body, "species", SPECIES_ENUM)
    severity = require_enum(body, "severity", SEVERITIES)
    observed_at = require_timestamp(body, "observed_at")
    description = require_string(body, "description")

    require_ownership(user_id, reported_by_inspector_id)
    establishment = establishment_or_404(establishment_id)
    entity_or_404("inspectors", reported_by_inspector_id, ERR_INSPECTOR_NOT_FOUND)
    require_not_withdrawn(establishment)
    # Tier 7 before tier 9: future observation beats species mismatch.
    not_future(observed_at, "observed_at")
    if species not in establishment["species_classes"]:
        raise_err(ERR_SPECIES_NOT_SUPPORTED, "species is not handled by the establishment")

    event = {
        "establishment_id": establishment_id,
        "reported_by_inspector_id": reported_by_inspector_id,
        "species": species,
        "severity": severity,
        "observed_at": observed_at,
        "description": description,
        "status": "REPORTED",
    }
    stamp_new(event)
    insert("humane_events", event)
    return success_object(event, status=201)


@bp.get("/inspection/humane-handling-events")
def list_events():
    require_roles(*READ_ROLES)
    rows = store.all_of("humane_events")
    for param in ("establishment_id", "reported_by_inspector_id", "status", "severity"):
        value = request.args.get(param)
        if value is not None:
            rows = [e for e in rows if e.get(param) == value]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/inspection/humane-handling-events/<event_id>")
def get_event(event_id):
    require_roles(*READ_ROLES)
    return success_object(_event_or_404(event_id))


@bp.post("/inspection/humane-handling-events/<event_id>/confirm")
def confirm_event(event_id):
    return _decide(event_id, "CONFIRMED")


@bp.post("/inspection/humane-handling-events/<event_id>/dismiss")
def dismiss_event(event_id):
    return _decide(event_id, "DISMISSED")
