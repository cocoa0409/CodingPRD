"""Grants, vesting tranches and the grant approval workflow."""

from flask import Blueprint, request

import auth
import calc
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, BOARD, COMPLIANCE, DELEGATED, PARTICIPANT, PLAN_ADMIN
from errors import ApiError, invalid

bp = Blueprint("grants", __name__)

GRANT_READERS = (PLAN_ADMIN, BOARD, DELEGATED, COMPLIANCE, AUDITOR)
GRANT_ROW_READERS = GRANT_READERS + (PARTICIPANT,)
AWARD_TYPES = ("RSU", "PSU", "ISO", "NSO")
FULL_VALUE_AWARDS = ("RSU", "PSU")
MAX_GRANT_REVISIONS = 2
CANCELLABLE = ("DRAFT", "PENDING_APPROVAL", "CHANGES_REQUESTED", "APPROVED",
               "GRANTED", "PARTIALLY_FORFEITED")


@bp.route("/grants", methods=["POST"])
def create_grant():
    actor = auth.begin(PLAN_ADMIN)
    body = actor.body
    plan_ref = validate.raw_id(body, "plan_id")
    if plan_ref is not None:
        services.plan_or_404(plan_ref)
    participant_ref = validate.raw_id(body, "participant_id")
    if participant_ref is not None:
        services.participant_or_404(participant_ref)
    plan_id = validate.field_id(body, "plan_id")
    participant_id = validate.field_id(body, "participant_id")
    plan = services.plan_or_404(plan_id)
    participant = services.participant_or_404(participant_id)
    award_type = validate.field_enum(body, "award_type", AWARD_TYPES)
    target_shares = validate.field_int(body, "target_shares", minimum=1)
    price_supplied = validate.present(body, "exercise_price_cents")
    price = validate.field_int(body, "exercise_price_cents", required=False, default=0)
    if award_type in FULL_VALUE_AWARDS:
        if price_supplied and price != 0:
            raise invalid("A full-value award may not carry an exercise price.")
        price = 0
    else:
        if not price_supplied or price <= 0:
            raise invalid("An option award requires a positive exercise_price_cents.")
    services.require_plan_active(plan)
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    row = store.base_row()
    row.update({
        "plan_id": plan_id,
        "participant_id": participant_id,
        "award_type": award_type,
        "target_shares": target_shares,
        "exercise_price_cents": price,
        "status": "DRAFT",
        "grant_date": None,
        "approval_path": None,
        "approved_under_authority_id": None,
        "approved_by_user_id": None,
        "submitted_by_user_id": None,
        "approved_at": None,
        "changes_requested_count": 0,
        "weighted_reserve_shares": 0,
        "outstanding_shares": 0,
        "cancel_reason": None,
    })
    store.grants[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/grants", methods=["GET"])
def list_grants():
    auth.begin(*GRANT_READERS)
    rows = list(store.grants.values())
    for param in ("plan_id", "participant_id", "approved_under_authority_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return envelope.page(store.sort_default(rows))


@bp.route("/grants/<grant_id>", methods=["GET"])
def read_grant(grant_id):
    actor = auth.begin(*GRANT_ROW_READERS)
    row = services.grant_or_404(grant_id)
    auth.scope(actor, row["participant_id"])
    return envelope.ok(store.public(row))


# --- vesting tranches -------------------------------------------------------

@bp.route("/grants/<grant_id>/vesting-tranches", methods=["POST"])
def append_tranche(grant_id):
    actor = auth.begin(PLAN_ADMIN)
    body = actor.body
    grant = services.grant_or_404(grant_id)
    cycle_ref = validate.raw_id(body, "performance_cycle_id")
    if cycle_ref is not None:
        services.cycle_or_404(cycle_ref)
    vest_type = validate.field_enum(body, "vest_type", ("TIME", "PERFORMANCE"))
    tranche_index = validate.field_int(body, "tranche_index", minimum=1)
    scheduled_vest_date = validate.field_date(body, "scheduled_vest_date")
    target_shares = validate.field_int(body, "target_shares", minimum=1)
    cycle_id = None
    if vest_type == "TIME":
        if validate.present(body, "performance_cycle_id"):
            raise invalid("A time-vesting tranche may not name a performance cycle.")
        shares = target_shares
    else:
        cycle_id = validate.field_id(body, "performance_cycle_id")
        shares = 0
    for other in store.tranches.values():
        if other["grant_id"] == grant_id and other["tranche_index"] == tranche_index:
            raise invalid("tranche_index must be unique inside its grant.")
    if grant["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_GRANT_INVALID_STATE")
    services.require_plan_active(services.plan_of_grant(grant))
    row = store.base_row()
    row.update({
        "grant_id": grant_id,
        "performance_cycle_id": cycle_id,
        "tranche_index": tranche_index,
        "vest_type": vest_type,
        "scheduled_vest_date": clock.fmt_date(scheduled_vest_date),
        "target_shares": target_shares,
        "shares": shares,
        "status": "UNVESTED",
        "acceleration_reason": None,
        "vested_at": None,
    })
    store.tranches[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/vesting-tranches", methods=["GET"])
def list_tranches():
    auth.begin(*GRANT_READERS)
    rows = list(store.tranches.values())
    for param in ("grant_id", "performance_cycle_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return envelope.page(store.sort_default(rows))


@bp.route("/vesting-tranches/<tranche_id>", methods=["GET"])
def read_tranche(tranche_id):
    actor = auth.begin(*GRANT_ROW_READERS)
    row = services.tranche_or_404(tranche_id)
    auth.scope(actor, store.grants[row["grant_id"]]["participant_id"])
    return envelope.ok(store.public(row))


# --- approval workflow ------------------------------------------------------

@bp.route("/grants/<grant_id>/submit", methods=["POST"])
def submit_grant(grant_id):
    actor = auth.begin(PLAN_ADMIN)
    grant = services.grant_or_404(grant_id)
    if grant["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_GRANT_INVALID_STATE")
    if not services.tranches_of(grant_id):
        raise ApiError("ERR_GRANT_INVALID_STATE")
    services.require_plan_active(services.plan_of_grant(grant))
    if store.participants[grant["participant_id"]]["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    grant["status"] = "PENDING_APPROVAL"
    grant["submitted_by_user_id"] = actor.user_id
    store.touch(grant)
    return envelope.ok(store.public(grant))


@bp.route("/grants/<grant_id>/request-changes", methods=["POST"])
def request_changes(grant_id):
    actor = auth.begin(BOARD, DELEGATED)
    grant = services.grant_or_404(grant_id)
    validate.field_str(actor.body, "change_note")
    if grant["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    if grant["changes_requested_count"] >= MAX_GRANT_REVISIONS:
        raise ApiError("ERR_MAX_GRANT_REVISIONS_EXCEEDED")
    grant["status"] = "CHANGES_REQUESTED"
    grant["changes_requested_count"] += 1
    store.touch(grant)
    return envelope.ok(store.public(grant))


@bp.route("/grants/<grant_id>/revise", methods=["POST"])
def revise_grant(grant_id):
    actor = auth.begin(PLAN_ADMIN)
    body = actor.body
    grant = services.grant_or_404(grant_id)
    target_shares = validate.field_int(body, "target_shares", minimum=1)
    price_supplied = validate.present(body, "exercise_price_cents")
    price = validate.field_int(body, "exercise_price_cents", required=False)
    if price_supplied and grant["award_type"] not in FULL_VALUE_AWARDS:
        if price != grant["exercise_price_cents"]:
            raise ApiError("ERR_EXERCISE_PRICE_MISMATCH")
    if grant["status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    grant["target_shares"] = target_shares
    store.touch(grant)
    return envelope.ok(store.public(grant))


@bp.route("/grants/<grant_id>/approve", methods=["POST"])
def approve_grant(grant_id):
    actor = auth.authenticate()
    if actor.role not in (BOARD, DELEGATED):
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    body = actor.body
    declared_path = body.get("approval_path")
    if declared_path == "BOARD" and actor.role != BOARD:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if declared_path == "DELEGATED" and actor.role != DELEGATED:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    grant = services.grant_or_404(grant_id)
    authority_ref = validate.raw_id(body, "authority_id")
    if declared_path == "DELEGATED" and authority_ref is not None:
        services.authority_or_404(authority_ref)
    approval_path = validate.field_enum(body, "approval_path", ("BOARD", "DELEGATED"))
    authority = None
    if approval_path == "DELEGATED":
        authority = services.authority_or_404(validate.field_id(body, "authority_id"))
    if grant["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    plan = services.plan_of_grant(grant)
    services.require_plan_active(plan)
    if actor.user_id == grant["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    participant = store.participants[grant["participant_id"]]
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    weighted = services.weighted_for(grant, plan)

    if approval_path == "DELEGATED":
        if grant["award_type"] == "PSU" or participant["insider_status"] == "SECTION_16_OFFICER":
            raise ApiError("ERR_DELEGATED_APPROVAL_BLOCKED")
        today = clock.today()
        effective = (
            authority["status"] == "ACTIVE"
            and authority["plan_id"] == grant["plan_id"]
            and authority["delegate_user_id"] == actor.user_id
            and clock.parse_date(authority["effective_from"]) <= today
            <= clock.parse_date(authority["effective_to"])
        )
        if not effective:
            raise ApiError("ERR_AUTHORITY_NOT_EFFECTIVE")
        if weighted > authority["per_grant_share_cap"]:
            raise ApiError("ERR_AUTHORITY_PER_GRANT_CAP_EXCEEDED")
        if authority["consumed_shares"] + weighted > authority["aggregate_share_cap"]:
            raise ApiError("ERR_AUTHORITY_CAP_EXCEEDED")

    projected = plan["fiscal_year_gross_granted_shares"] + weighted
    if projected * calc.BPS_SCALE > plan["burn_rate_limit_bps"] * plan["common_shares_outstanding"]:
        raise ApiError("ERR_BURN_RATE_LIMIT_EXCEEDED")
    if plan["available_reserve_shares"] < weighted:
        raise ApiError("ERR_RESERVE_INSUFFICIENT")

    grant["status"] = "APPROVED"
    grant["approval_path"] = approval_path
    grant["approved_by_user_id"] = actor.user_id
    grant["approved_at"] = clock.fmt_instant(clock.now())
    grant["weighted_reserve_shares"] = weighted
    if authority is not None:
        grant["approved_under_authority_id"] = authority["id"]
        authority["consumed_shares"] += weighted
        authority["remaining_shares"] = (
            authority["aggregate_share_cap"] - authority["consumed_shares"])
        if authority["remaining_shares"] == 0:
            authority["status"] = "EXHAUSTED"
        store.touch(authority)
    plan["shares_committed_cumulative"] += weighted
    plan["fiscal_year_gross_granted_shares"] += weighted
    services.recompute_reserve(plan)
    services.recompute_burn_rates(plan)
    store.touch(plan)
    store.touch(grant)
    return envelope.ok(store.public(grant))


@bp.route("/grants/<grant_id>/issue", methods=["POST"])
def issue_grant(grant_id):
    auth.begin(PLAN_ADMIN)
    grant = services.grant_or_404(grant_id)
    if grant["status"] != "APPROVED":
        raise ApiError("ERR_GRANT_INVALID_STATE")
    plan = services.plan_of_grant(grant)
    services.require_plan_active(plan)
    grant_date = _resolve_grant_date(plan)
    if grant_date is None:
        raise ApiError("ERR_NO_ELIGIBLE_GRANT_DATE")
    grant["grant_date"] = clock.fmt_date(grant_date)
    grant["status"] = "GRANTED"
    grant["outstanding_shares"] = calc.outstanding_shares(services.tranches_of(grant_id))
    store.touch(grant)
    return envelope.ok(store.public(grant))


def _resolve_grant_date(plan):
    now = clock.now()
    windows = [w for w in store.windows.values() if w["plan_id"] == plan["id"]]
    for window in windows:
        if window["status"] == "OPEN" and (
            clock.parse_instant(window["open_at"]) <= now
            < clock.parse_instant(window["close_at"])
        ):
            return now.date()
    upcoming = [
        w for w in windows
        if w["status"] == "SCHEDULED" and clock.parse_instant(w["open_at"]) > now
    ]
    if not upcoming:
        return None
    chosen = sorted(
        upcoming, key=lambda w: (clock.parse_instant(w["open_at"]), w["created_at"], w["_seq"])
    )[0]
    return clock.parse_instant(chosen["open_at"]).date()


@bp.route("/grants/<grant_id>/cancel", methods=["POST"])
def cancel_grant(grant_id):
    actor = auth.begin(PLAN_ADMIN, BOARD)
    grant = services.grant_or_404(grant_id)
    reason = validate.field_str(actor.body, "cancel_reason")
    rows = services.tranches_of(grant_id)
    if grant["status"] not in CANCELLABLE:
        raise ApiError("ERR_GRANT_INVALID_STATE")
    if any(t["status"] == "SETTLED" for t in rows):
        raise ApiError("ERR_GRANT_INVALID_STATE")
    plan = services.plan_of_grant(grant)
    services.require_plan_active(plan)

    released = grant["weighted_reserve_shares"]
    grant["status"] = "CANCELLED"
    grant["cancel_reason"] = reason
    for tranche in rows:
        if tranche["status"] in ("UNVESTED", "VESTED"):
            was_vested = tranche["status"] == "VESTED"
            tranche["status"] = "FORFEITED"
            store.touch(tranche)
            if was_vested:
                services.reverse_pending_tax_events(tranche, "FOR_CAUSE_CLAWBACK")
    if released > 0:
        plan["shares_returned_cumulative"] += released
        plan["fiscal_year_returned_shares"] += released
        services.recompute_reserve(plan)
        services.recompute_burn_rates(plan)
        store.touch(plan)
        if grant["approval_path"] == "DELEGATED" and grant["approved_under_authority_id"]:
            authority = store.authorities.get(grant["approved_under_authority_id"])
            if authority is not None:
                authority["consumed_shares"] -= released
                authority["remaining_shares"] = (
                    authority["aggregate_share_cap"] - authority["consumed_shares"])
                if authority["status"] == "EXHAUSTED" and authority["remaining_shares"] > 0:
                    authority["status"] = "ACTIVE"
                store.touch(authority)
    grant["weighted_reserve_shares"] = 0
    grant["outstanding_shares"] = 0
    store.touch(grant)
    return envelope.ok(store.public(grant))
