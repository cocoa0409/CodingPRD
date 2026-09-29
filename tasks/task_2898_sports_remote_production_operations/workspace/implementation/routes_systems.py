"""Show systems: data-feed preparation, and the rehearsal / camera-blocking session."""

from flask import Blueprint

import domain
import store
from core import (
    ApiError,
    OPERATOR_ROLES,
    Payload,
    ROLE_TECHNICAL_DIRECTOR,
    invalid,
    now_utc,
    page_result,
    query_enum,
    query_string,
    require_roles,
    respond_object,
)
from routes_production import require_open_production

bp = Blueprint("systems", __name__, url_prefix="/broadcast-ops")


# ---------------------------------------------------------------------------
# SystemPrep
# ---------------------------------------------------------------------------
@bp.post("/system-preps")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_prep():
    body = Payload()
    production_id = body.string("production_id")
    data_feed_id = body.string("data_feed_id")
    system_kind = body.enum("system_kind", domain.SYSTEM_KINDS)
    replay_channels = body.integer("replay_channel_count", required=False, minimum=1)
    if system_kind == "REPLAY" and replay_channels is None:
        raise invalid("replay_channel_count is required when system_kind is REPLAY.")
    if system_kind != "REPLAY" and replay_channels is not None:
        raise invalid("replay_channel_count is forbidden unless system_kind is REPLAY.")

    production = store.find_production(production_id)
    feed = store.find_feed(data_feed_id)
    require_open_production(production)
    if feed["status"] != "ACTIVE":
        raise ApiError(
            "ERR_FEED_STATE_INVALID",
            "A preparation may only be bound to an ACTIVE data feed.",
            409,
        )
    for other in domain.production_preps(production):
        if other["system_kind"] == system_kind:
            raise ApiError(
                "ERR_DUPLICATE_PREP_KIND",
                "The production already holds a preparation of this system kind.",
                409,
            )

    prep = store.new_row(
        production_id=production["id"],
        data_feed_id=feed["id"],
        system_kind=system_kind,
        replay_channel_count=replay_channels,
        feed_validated_at=None,
        status="PENDING",
    )
    store.PREPS[prep["id"]] = prep
    domain.recompute_production_scalars(production)
    return respond_object(domain.prep_json(prep), 201)


@bp.get("/system-preps/<prep_id>")
@require_roles(*OPERATOR_ROLES)
def read_prep(prep_id):
    return respond_object(domain.prep_json(store.find_prep(prep_id)))


@bp.get("/system-preps")
@require_roles(*OPERATOR_ROLES)
def list_preps():
    production_id = query_string("production_id")
    data_feed_id = query_string("data_feed_id")
    status = query_enum("status", domain.PREP_STATUSES)
    rows = store.ordered(store.PREPS)
    if production_id is not None:
        rows = [r for r in rows if r["production_id"] == production_id]
    if data_feed_id is not None:
        rows = [r for r in rows if r["data_feed_id"] == data_feed_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_result(rows, domain.prep_json)


@bp.post("/system-preps/<prep_id>/validate-feed")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def validate_prep_feed(prep_id):
    prep = store.find_prep(prep_id)
    if prep["status"] not in ("PENDING", "FAILED"):
        raise ApiError(
            "ERR_PREP_STATE_INVALID",
            "Only a PENDING or FAILED preparation may be validated.",
            409,
        )
    feed = store.FEEDS.get(prep["data_feed_id"])
    if feed is None or feed["status"] != "ACTIVE":
        raise ApiError("ERR_FEED_STATE_INVALID", "The data feed is not ACTIVE.", 409)
    if now_utc() >= feed["contract_expiry_utc"]:
        raise ApiError(
            "ERR_FEED_CONTRACT_EXPIRED",
            "The feed's data-rights contract has lapsed.",
            422,
        )
    if feed["active_consumer_count"] >= feed["max_concurrent_consumers"]:
        raise ApiError(
            "ERR_FEED_CONSUMER_LIMIT",
            "The feed is already carrying its maximum concurrent consumers.",
            409,
        )

    # Latency is a branch, never an error.
    if feed["latency_ms"] <= domain.MAX_FEED_LATENCY_MS:
        store.set_fields(prep, status="VALIDATED", feed_validated_at=now_utc())
        domain.recompute_feed_consumers(feed)
    else:
        store.set_fields(prep, status="FAILED", feed_validated_at=None)

    production = store.PRODUCTIONS.get(prep["production_id"])
    if production is not None:
        domain.recompute_production_stage(production)
    return respond_object(domain.prep_json(prep))


# ---------------------------------------------------------------------------
# Rehearsal
# ---------------------------------------------------------------------------
@bp.post("/rehearsals")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_rehearsal():
    body = Payload()
    production_id = body.string("production_id")
    scheduled_start = body.instant("scheduled_start_utc")

    production = store.find_production(production_id)
    if scheduled_start >= production["scheduled_start_utc"]:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "The rehearsal must be scheduled strictly before the production's air time.",
            422,
        )
    if production["status"] not in ("PROVISIONED", "REHEARSED"):
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID",
            "A rehearsal may only be booked for a PROVISIONED or REHEARSED production.",
            409,
        )

    rehearsal = store.new_row(
        production_id=production["id"],
        scheduled_start_utc=scheduled_start,
        camera_blocking_positions_cleared=None,
        venue_signoff=None,
        league_ops_signoff=None,
        outcome_notes=None,
        status="SCHEDULED",
    )
    store.REHEARSALS[rehearsal["id"]] = rehearsal
    return respond_object(domain.rehearsal_json(rehearsal), 201)


@bp.get("/rehearsals/<rehearsal_id>")
@require_roles(*OPERATOR_ROLES)
def read_rehearsal(rehearsal_id):
    return respond_object(domain.rehearsal_json(store.find_rehearsal(rehearsal_id)))


@bp.get("/productions/<production_id>/rehearsals")
@require_roles(*OPERATOR_ROLES)
def list_production_rehearsals(production_id):
    production = store.find_production(production_id)
    status = query_enum("status", domain.REHEARSAL_STATUSES)
    rows = domain.production_rehearsals(production)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_result(rows, domain.rehearsal_json)


@bp.post("/rehearsals/<rehearsal_id>/outcome")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def record_rehearsal_outcome(rehearsal_id):
    body = Payload()
    outcome = body.enum("outcome", ("COMPLETED", "ABORTED"))
    cleared = body.integer("camera_blocking_positions_cleared", required=False, minimum=0)
    venue_signoff = body.boolean("venue_signoff", required=False)
    league_signoff = body.boolean("league_ops_signoff", required=False)
    notes = body.string("outcome_notes", required=False, allow_blank=True)

    rehearsal = store.find_rehearsal(rehearsal_id)
    production = store.PRODUCTIONS.get(rehearsal["production_id"])

    if outcome == "COMPLETED" and (production is None or production["status"] != "PROVISIONED"):
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID",
            "A COMPLETED rehearsal outcome requires a PROVISIONED production.",
            409,
        )
    if rehearsal["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_REHEARSAL_STATE_INVALID",
            "Only a SCHEDULED rehearsal may record an outcome.",
            409,
        )

    if outcome == "COMPLETED":
        survey = domain.approved_survey(production)
        required_positions = survey["camera_position_count"] if survey is not None else None
        if (
            cleared is None
            or required_positions is None
            or cleared != required_positions
            or venue_signoff is not True
            or league_signoff is not True
        ):
            raise ApiError(
                "ERR_REHEARSAL_SIGNOFF_INCOMPLETE",
                "The full camera plot must be blocked and both signoffs must be affirmative.",
                422,
            )

    store.set_fields(
        rehearsal,
        camera_blocking_positions_cleared=cleared,
        venue_signoff=venue_signoff,
        league_ops_signoff=league_signoff,
        outcome_notes=notes,
        status=outcome,
    )

    if outcome == "COMPLETED":
        domain.set_readiness_hold(production, False)
        domain.recompute_production_stage(production)
        if production["status"] == "PROVISIONED":
            store.set_fields(production, status="REHEARSED")
    return respond_object(domain.rehearsal_json(rehearsal))
