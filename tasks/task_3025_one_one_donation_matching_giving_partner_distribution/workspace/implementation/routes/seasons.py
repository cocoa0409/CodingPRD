"""Season plane: calendars, frozen state, close/reopen and the season roll-ups."""

from flask import Blueprint, request

from db import DB, iso3, new_id
from errors import ApiError
from middleware import (ALLOCATION_PLANNER, FULFILLMENT_OPERATOR,
                        GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR,
                        MARKETING_MANAGER, roles)
from response import pagination_meta, success
from routes import _common as common
from services import core, serial
from validation import (as_bool, as_instant, as_str, body, occ,
                        paginate, pagination, require)

bp = Blueprint("seasons", __name__)

SEASON_STATUSES = ["PLANNED", "OPEN", "FROZEN", "CLOSED", "FINALIZED"]
SEASON_VIEWERS = [IMPACT_AUDITOR, ALLOCATION_PLANNER, MARKETING_MANAGER,
                  GIVING_PARTNER_COORDINATOR]


@bp.route("/impact-program/impact-seasons", methods=["POST"])
@roles(IMPACT_AUDITOR)
def create_season():
    payload = body()
    require(payload, "season_code", "starts_at", "ends_at", "freezes_at")
    season_code = as_str(payload, "season_code", required=True)
    starts_at = as_instant(payload, "starts_at", required=True)
    ends_at = as_instant(payload, "ends_at", required=True)
    freezes_at = as_instant(payload, "freezes_at", required=True)

    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_REQUEST", "ends_at must be after starts_at.")

    for existing in DB.impact_seasons.values():
        if existing.get("season_code") == season_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    now = iso3(DB.now())
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "season_code": season_code,
        "starts_at": iso3(starts_at),
        "ends_at": iso3(ends_at),
        "freezes_at": iso3(freezes_at),
        "liability_carry_in_units": 0,
        "claim_frozen_units_total": 0,
        "opening_carry_obligation_cents": 0,
        "requested_season_code": None,
        "is_final": False,
        "attributed_units_total": 0,
        "attributed_percentage_total": 0.0,
        "total_shipped_units": 0,
        "total_received_units": 0,
        "liability_reconciliation_delta": 0,
        "status": "PLANNED",
    }
    DB.impact_seasons[record["id"]] = record
    core.recompute_season(record)
    return success(serial.serialize("ImpactSeason", record)), 201


@bp.route("/impact-program/impact-seasons", methods=["GET"])
@roles(*SEASON_VIEWERS)
def list_seasons():
    status = request.args.get("status")
    limit, offset = pagination()
    rows = list(DB.impact_seasons.values())
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("ImpactSeason", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/impact-seasons/<season_id>", methods=["GET"])
@roles(*SEASON_VIEWERS)
def get_season(season_id):
    record = common.season_or_404(season_id)
    core.recompute_season(record)
    return success(serial.serialize("ImpactSeason", record))


@bp.route("/impact-program/impact-seasons/<season_id>/summary", methods=["GET"])
@roles(IMPACT_AUDITOR, MARKETING_MANAGER)
def season_summary(season_id):
    record = common.season_or_404(season_id)
    core.recompute_season(record)
    return success({
        "season_id": record["id"],
        "season_code": record.get("season_code"),
        "claim_frozen_units_total": record.get("claim_frozen_units_total"),
        "total_shipped_units": record.get("total_shipped_units"),
        "total_received_units": record.get("total_received_units"),
        "liability_carry_in_units": record.get("liability_carry_in_units"),
        "liability_reconciliation_delta": record.get("liability_reconciliation_delta"),
        "attributed_units_total": record.get("attributed_units_total"),
        "attributed_percentage_total": record.get("attributed_percentage_total"),
    })


@bp.route("/impact-program/impact-seasons/<season_id>/frozen-state", methods=["PUT"])
@roles(IMPACT_AUDITOR)
def set_frozen_state(season_id):
    record = common.season_or_404(season_id)
    payload = body()
    require(payload, "is_final", "expected_season_version")
    is_final = as_bool(payload, "is_final", required=True)
    expected = occ(payload, "expected_season_version")
    requested_code = as_str(payload, "requested_season_code")

    if requested_code is not None:
        named = DB.season_by_code(requested_code)
        if not named:
            raise ApiError("ERR_SEASON_NOT_FOUND")

    common.occ_check(record.get("version"), expected)
    record["requested_season_code"] = requested_code
    record["is_final"] = bool(is_final)

    if is_final:
        if record.get("status") == "FINALIZED":
            raise ApiError("ERR_SEASON_FROZEN")
        for other in DB.impact_seasons.values():
            if other["id"] == season_id:
                continue
            if other.get("status") == "FROZEN":
                raise ApiError("ERR_DUPLICATE_RESOURCE")
        record["status"] = "FROZEN"
        for liability in DB.season_liabilities(season_id):
            if liability.get("status") in ("ACCUMULATING", "CARRIED"):
                core.recompute_liability(liability)
                liability["status"] = "FROZEN"
                liability["frozen_units"] = liability.get("provisional_liability_units") or 0
                liability["donation_liability_units"] = liability.get("final_liability_units") or 0
                liability["freeze_recorded_at"] = iso3(DB.now())
                variant_cost = _first_line_cost(liability.get("donation_product_id"))
                liability["accrued_obligation_cents"] = (
                    (liability.get("obligation_units") or 0) * variant_cost)
                DB.touch(liability)
    else:
        if record.get("status") != "FROZEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for audit in DB.impact_audits.values():
            if audit.get("impact_season_id") == season_id and audit.get("status") == "FINALIZED":
                raise ApiError("ERR_INVALID_STATE_TRANSITION")
        record["status"] = "OPEN"
        for liability in DB.season_liabilities(season_id):
            liability["status"] = "ACCUMULATING"
            core.recompute_liability(liability)
            liability["frozen_units"] = liability.get("provisional_liability_units") or 0
            DB.touch(liability)

    for product in DB.donation_products.values():
        core.recompute_product(product)
    core.recompute_season(record)
    DB.touch(record)
    return success(serial.serialize("ImpactSeason", record))


def _first_line_cost(product_id):
    for variant in DB.product_lines(product_id):
        return variant.get("unit_obligation_cost_cents") or 0
    return 0


@bp.route("/impact-program/impact-seasons/<season_id>/close", methods=["POST"])
@roles(IMPACT_AUDITOR)
def close_season(season_id):
    record = common.season_or_404(season_id)
    if record.get("status") == "FINALIZED":
        raise ApiError("ERR_SEASON_FROZEN")
    if record.get("status") != "FROZEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    liabilities = DB.season_liabilities(season_id)
    for liability in liabilities:
        if liability.get("status") not in ("CARRIED", "CLOSED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    for liability in liabilities:
        liability["status"] = "CLOSED"
        DB.touch(liability)
    record["status"] = "CLOSED"
    DB.touch(record)
    core.recompute_all_seasons()
    return success(serial.serialize("ImpactSeason", record))


@bp.route("/impact-program/impact-seasons/<season_id>/reopen", methods=["POST"])
@roles(IMPACT_AUDITOR)
def reopen_season(season_id):
    record = common.season_or_404(season_id)
    if record.get("status") != "CLOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    for audit in DB.impact_audits.values():
        if audit.get("impact_season_id") == season_id and audit.get("status") == "FINALIZED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    record["status"] = "OPEN"
    for liability in DB.season_liabilities(season_id):
        liability["status"] = "ACCUMULATING"
        core.recompute_liability(liability)
        DB.touch(liability)
    DB.touch(record)
    core.recompute_all_seasons()
    return success(serial.serialize("ImpactSeason", record))


@bp.route("/impact-program/impact-seasons/<season_id>/allocations", methods=["GET"])
@roles(ALLOCATION_PLANNER, IMPACT_AUDITOR, FULFILLMENT_OPERATOR)
def season_allocations(season_id):
    common.season_or_404(season_id)
    limit, offset = pagination()
    rows = [a for a in DB.donation_allocations.values() if a.get("impact_season_id") == season_id]
    for name in ("status", "allocation_kind", "giving_partner_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationAllocation", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/impact-seasons/<season_id>/distributions", methods=["GET"])
@roles(FULFILLMENT_OPERATOR, IMPACT_AUDITOR, GIVING_PARTNER_COORDINATOR)
def season_distributions(season_id):
    common.season_or_404(season_id)
    status = request.args.get("status")
    limit, offset = pagination()
    rows = DB.season_distributions(season_id)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationDistribution", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/impact-seasons/<season_id>/claims", methods=["GET"])
@roles(MARKETING_MANAGER, IMPACT_AUDITOR)
def season_claims(season_id):
    common.season_or_404(season_id)
    status = request.args.get("status")
    limit, offset = pagination()
    rows = DB.season_claims(season_id)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("MarketingClaim", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/impact-seasons/<season_id>/liabilities", methods=["GET"])
@roles(IMPACT_AUDITOR, ALLOCATION_PLANNER, MARKETING_MANAGER)
def season_liabilities(season_id):
    common.season_or_404(season_id)
    product_id = request.args.get("donation_product_id")
    status = request.args.get("status")
    limit, offset = pagination()
    rows = DB.season_liabilities(season_id)
    if product_id:
        rows = [r for r in rows if r.get("donation_product_id") == product_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationLiability", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/impact-seasons/<season_id>/audits", methods=["GET"])
@roles(IMPACT_AUDITOR, MARKETING_MANAGER)
def season_audits(season_id):
    common.season_or_404(season_id)
    limit, offset = pagination()
    rows = [a for a in DB.impact_audits.values() if a.get("impact_season_id") == season_id]
    for name in ("audit_kind", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("ImpactAudit", page),
                   pagination=pagination_meta(limit, offset, total))


# ===========================================================================
# Liability plane
# ===========================================================================

@bp.route("/impact-program/liabilities", methods=["GET"])
@roles(IMPACT_AUDITOR, ALLOCATION_PLANNER, MARKETING_MANAGER)
def list_liabilities():
    limit, offset = pagination()
    rows = list(DB.donation_liabilities.values())
    for name in ("donation_product_id", "impact_season_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    partner_id = request.args.get("giving_partner_id")
    if partner_id:
        product_ids = set()
        for allocation in DB.partner_allocations(partner_id):
            product_ids.add(allocation.get("donation_product_id"))
        rows = [r for r in rows if r.get("donation_product_id") in product_ids]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationLiability", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/liabilities/<liability_id>", methods=["GET"])
@roles(IMPACT_AUDITOR, ALLOCATION_PLANNER, MARKETING_MANAGER)
def get_liability(liability_id):
    record = common.liability_or_404(liability_id)
    core.recompute_liability(record)
    return success(serial.serialize("DonationLiability", record))


@bp.route("/impact-program/liabilities/<liability_id>/unfreeze", methods=["PUT"])
@roles(IMPACT_AUDITOR)
def unfreeze_liability(liability_id):
    record = common.liability_or_404(liability_id)
    season = common.season_or_404(record["impact_season_id"])

    # PRD §3.7: "An auditor can unfreeze a frozen liability, which requires that
    # the season is `FROZEN` and that no audit for the season has been
    # finalized; unfreezing recomputes the frozen units from the provisional
    # units and returns the season to `OPEN`."  The audit-lock reset flag
    # belongs to the audit-reopen path, not to this one.
    for audit in DB.impact_audits.values():
        if audit.get("impact_season_id") == season["id"] and audit.get("status") == "FINALIZED":
            raise ApiError("ERR_AUDIT_LOCK_NOT_RESETTABLE")
    if season.get("status") != "FROZEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    season["status"] = "OPEN"
    for row in DB.season_liabilities(season["id"]):
        row["status"] = "ACCUMULATING"
        core.recompute_liability(row)
        row["frozen_units"] = row.get("provisional_liability_units") or 0
        DB.touch(row)
    DB.touch(season)
    core.recompute_liability(record)
    core.recompute_season(season)
    return success(serial.serialize("DonationLiability", record))


def _reset_flag(season):
    if not season:
        return False
    flags = DB.season_flags.get(season["id"]) or {}
    return bool(flags.get("RESET_AUDIT_LOCK"))


@bp.route("/impact-program/liabilities/<liability_id>/carry-forward", methods=["POST"])
@roles(ALLOCATION_PLANNER)
def carry_forward(liability_id):
    record = common.liability_or_404(liability_id)
    payload = body()
    require(payload, "claim_id", "expected_liability_version")
    claim_id = as_str(payload, "claim_id", required=True)
    expected = occ(payload, "expected_liability_version")
    common.claim_or_404(claim_id)

    if record.get("status") != "FROZEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    common.occ_check(record.get("version"), expected)

    season = common.season_or_404(record["impact_season_id"])
    core.recompute_liability(record)
    required = record.get("required_stated_units") or 0
    frozen = record.get("frozen_units") or 0
    if required <= frozen:
        raise ApiError("ERR_CARRY_PRECONDITION_UNMET")
    # PRD §3.7: the second clause of the precondition is "that the season named
    # by `carry_from_season_code` is `CLOSED`". That field names the season the
    # row's carried-in units were inherited from, so it is only named once the
    # row itself is a successor; the clause is enforced whenever a source
    # season is on the record, and a first carry out of a just-frozen season
    # (which §3.7 has close only *after* its units are passed forward) is not
    # made to depend on a season that has not closed yet.
    predecessor_code = record.get("carry_from_season_code")
    if predecessor_code:
        predecessor = DB.season_by_code(predecessor_code)
        if predecessor is None or predecessor.get("status") != "CLOSED":
            raise ApiError("ERR_CARRY_PRECONDITION_UNMET")

    successor = _successor_liability_for(record, required - frozen)
    record["status"] = "CARRIED"
    record["carried_out_units"] = required - frozen
    if successor:
        DB.touch(successor)
    DB.touch(record)
    core.recompute_all_seasons()
    return success(serial.serialize("DonationLiability", record))


def _successor_liability_for(liability, units):
    next_season = DB.next_planned_season()
    if next_season is None:
        return None
    successor = core.ensure_liability(liability["donation_product_id"], next_season)
    successor["carried_in_units"] = (successor.get("carried_in_units") or 0) + units
    successor["carry_from_season_code"] = (DB.season(liability["impact_season_id"]) or {}).get("season_code")
    successor["status"] = "ACCUMULATING"
    core.recompute_liability(successor)
    return successor