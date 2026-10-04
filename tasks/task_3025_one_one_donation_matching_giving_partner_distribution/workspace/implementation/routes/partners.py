"""Giving partner plane: onboarding, vetting rounds, standing and roll-ups."""

from flask import Blueprint, request

from db import DB, iso3, new_id
from errors import ApiError
from middleware import (ALLOCATION_PLANNER, FULFILLMENT_OPERATOR,
                        GIVING_PARTNER_COORDINATOR, GIVING_PARTNER_ORG,
                        IMPACT_AUDITOR, MARKETING_MANAGER, PROVISIONING_PARTNER,
                        require_own_partner, roles)
from response import pagination_meta, success
from routes import _common as common
from services import calc, core, serial
from validation import (as_bool, as_enum, as_instant, as_int, as_nonempty_str,
                        as_str, body, paginate, pagination, require)

bp = Blueprint("partners", __name__)

PARTNER_TYPES = [
    "HOMELESS_SHELTER", "DOMESTIC_VIOLENCE_SHELTER", "YOUTH_OUTREACH",
    "VETERAN_OUTREACH", "DISASTER_RELIEF", "COMMUNITY_HEALTH_CLINIC",
]
REGIONS = ["NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST"]
NEED_TIERS = ["CRITICAL", "HIGH", "MODERATE", "LOW"]
STANDING = ["APPROVED", "SUSPENDED", "INACTIVE"]
ROUND_OUTCOMES = ["REQUESTED", "DOCUMENTS_SUBMITTED", "EVALUATING", "APPROVED",
                  "REJECTED", "EXPIRED"]
PARTNER_VIEWERS = [GIVING_PARTNER_COORDINATOR, PROVISIONING_PARTNER,
                   ALLOCATION_PLANNER, MARKETING_MANAGER, IMPACT_AUDITOR]


def _latest_round(partner):
    rounds = [r for r in DB.vetting_rounds.values() if r.get("partner_id") == partner["id"]]
    if not rounds:
        return None
    rounds.sort(key=lambda r: r.get("round_number") or 0)
    return rounds[-1]


def _round_points(partner):
    latest = _latest_round(partner)
    return (latest or {}).get("need_verification_points") or 0


def _recompute_partner_need(partner):
    partner["need_score"] = calc.need_score(partner, _round_points(partner))
    return partner


# ===========================================================================
# Giving partners
# ===========================================================================

@bp.route("/impact-program/giving-partners", methods=["POST"])
@roles(GIVING_PARTNER_COORDINATOR)
def onboard_partner():
    payload = body()
    require(payload, "legal_name", "partner_type", "operating_region",
            "operating_state_code", "registry_id", "ein", "founded_year",
            "unduplicated_recipients_per_facility", "need_tier")
    legal_name = as_nonempty_str(payload, "legal_name", required=True)
    partner_type = as_enum(payload, "partner_type", PARTNER_TYPES, required=True)
    operating_region = as_enum(payload, "operating_region", REGIONS, required=True)
    operating_state_code = as_nonempty_str(payload, "operating_state_code", required=True)
    registry_id = as_str(payload, "registry_id", required=True)
    ein = as_str(payload, "ein", required=True)
    founded_year = as_int(payload, "founded_year", required=True, minimum=1900, maximum=2026)
    recipients = as_int(payload, "unduplicated_recipients_per_facility", required=True, minimum=0)
    need_tier = as_enum(payload, "need_tier", NEED_TIERS, required=True)
    radius = as_int(payload, "service_radius_miles", default=50, minimum=0)

    now = iso3(DB.now())
    partner = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "legal_name": legal_name,
        "partner_type": partner_type,
        "operating_region": operating_region,
        "operating_state_code": operating_state_code,
        "service_radius_miles": radius,
        "registry_id": registry_id,
        "ein": ein,
        "founded_year": founded_year,
        "unduplicated_recipients_per_facility": recipients,
        "need_tier": need_tier,
        "registry_verified": calc.registry_verified(registry_id, ein),
        "status": "VETTING",
        "vetting_round": 1,
        "latest_vetting_round_id": None,
        "total_rejections": 0,
        "need_score": 0,
        "capacity_utilization_units": 0,
        "impact_units_total": 0,
        "impact_units_retail_equivalent": 0,
        "avg_distribution_completion_days": None,
        "claim_attributed_units": 0,
        "attributed_percentage": 0.0,
        "entrance_returns_units": 0,
        "partner_performance_grade": None,
        "last_vetted_at": None,
    }
    DB.giving_partners[partner["id"]] = partner

    # Onboarding is inseparable from the first review (PRD 3.1).
    round_record = _create_round(partner, 1, "REQUESTED")
    partner["latest_vetting_round_id"] = round_record["id"]
    partner["need_score"] = calc.need_score(partner, 0)
    return success(serial.serialize("GivingPartner", partner)), 201


def _create_round(partner, round_number, outcome):
    now = iso3(DB.now())
    record = {
        "id": new_id(),
        "created_at": now,
        "partner_id": partner["id"],
        "round_number": round_number,
        "outcome": outcome,
        "registry_check_passed": None,
        "tax_check_passed": None,
        "on_site_check_passed": None,
        "capacity_check_passed": None,
        "need_verification_points": None,
        "need_verification_evidence": None,
        "valid_until": None,
        "outcome_message": None,
    }
    DB.vetting_rounds[record["id"]] = record
    return record


@bp.route("/impact-program/giving-partners", methods=["GET"])
@roles(*PARTNER_VIEWERS)
def list_partners():
    status = request.args.get("status")
    partner_type = request.args.get("partner_type")
    region = request.args.get("operating_region")
    need_tier = request.args.get("need_tier")
    limit, offset = pagination()

    rows = list(DB.giving_partners.values())
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if partner_type:
        rows = [r for r in rows if r.get("partner_type") == partner_type]
    if region:
        rows = [r for r in rows if r.get("operating_region") == region]
    if need_tier:
        rows = [r for r in rows if r.get("need_tier") == need_tier]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("GivingPartner", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/giving-partners/<partner_id>", methods=["GET"])
@roles(*(PARTNER_VIEWERS + [GIVING_PARTNER_ORG]))
def get_partner(partner_id):
    partner = common.partner_or_404(partner_id)
    require_own_partner(partner_id)
    core.recompute_partner(partner)
    return success(serial.serialize("GivingPartner", partner))


@bp.route("/impact-program/giving-partners/<partner_id>", methods=["PUT"])
@roles(GIVING_PARTNER_COORDINATOR)
def update_partner(partner_id):
    partner = common.partner_or_404(partner_id)
    payload = body()
    require(payload, "legal_name", "need_tier", "unduplicated_recipients_per_facility")
    partner["legal_name"] = as_nonempty_str(payload, "legal_name", required=True)
    partner["need_tier"] = as_enum(payload, "need_tier", NEED_TIERS, required=True)
    partner["unduplicated_recipients_per_facility"] = as_int(
        payload, "unduplicated_recipients_per_facility", required=True, minimum=0)
    radius = as_int(payload, "service_radius_miles", minimum=0)
    if radius is not None:
        partner["service_radius_miles"] = radius
    _recompute_partner_need(partner)
    DB.touch(partner)
    return success(serial.serialize("GivingPartner", partner))


# -- standing cascades -------------------------------------------------------

@bp.route("/impact-program/giving-partners/<partner_id>/status", methods=["PUT"])
@roles(GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR)
def set_partner_status(partner_id):
    partner = common.partner_or_404(partner_id)
    payload = body()
    require(payload, "status")
    target = as_enum(payload, "status", STANDING, required=True)
    current = partner.get("status")

    if target == "SUSPENDED":
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for audit in DB.impact_audits.values():
            if audit.get("audit_kind") != "PARTNER_PERFORMANCE":
                continue
            if audit.get("status") == "IN_PROGRESS" and _audit_names_partner(audit, partner):
                raise ApiError("ERR_INVALID_STATE_TRANSITION")
        partner["status"] = "SUSPENDED"
        for profile in DB.capacity_profiles.values():
            if profile.get("partner_id") == partner["id"] and profile.get("status") == "ACTIVE":
                profile["status"] = "LOCKED"
                DB.touch(profile)
        for allocation in DB.donation_allocations.values():
            if allocation.get("giving_partner_id") != partner["id"]:
                continue
            if allocation.get("status") == "PENDING_ALLOCATION":
                allocation["status"] = "CANCELLED"
                DB.touch(allocation)
                _release_capacity(allocation)
        for claim in DB.marketing_claims.values():
            if claim.get("partner_id") != partner["id"]:
                continue
            if claim.get("status") == "SUBSTANTIATED":
                claim["status"] = "SEASON_RESTRICTED"
                DB.touch(claim)

    elif target == "APPROVED":
        if current != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        season = DB.current_season()
        if season and season.get("status") == "FINALIZED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        partner["status"] = "APPROVED"
        for profile in DB.capacity_profiles.values():
            if profile.get("partner_id") == partner["id"] and profile.get("status") == "LOCKED":
                profile["status"] = "ACTIVE"
                DB.touch(profile)
        for claim in DB.marketing_claims.values():
            if claim.get("partner_id") != partner["id"]:
                continue
            if claim.get("status") == "SEASON_RESTRICTED":
                claim["status"] = "SUBSTANTIATED"
                core.recompute_claim(claim)
                DB.touch(claim)

    elif target == "INACTIVE":
        if current not in ("APPROVED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for allocation in DB.partner_allocations(partner["id"]):
            if allocation.get("status") not in calc.TERMINAL_ALLOCATION_STATUSES:
                raise ApiError("ERR_INVALID_STATE_TRANSITION")
        partner["status"] = "INACTIVE"
        for profile in DB.capacity_profiles.values():
            if profile.get("partner_id") == partner["id"]:
                profile["status"] = "SUPERSEDED"
                DB.touch(profile)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    DB.touch(partner)
    core.recompute_all_seasons()
    return success(serial.serialize("GivingPartner", partner))


def _audit_names_partner(audit, partner):
    claim = DB.claim(audit.get("claim_id"))
    if claim and claim.get("partner_id") == partner["id"]:
        return True
    season_id = audit.get("impact_season_id")
    for allocation in DB.partner_allocations(partner["id"], season_id):
        return True
    return False


def _release_capacity(allocation):
    season = DB.season(allocation["impact_season_id"])
    if not season:
        return
    for profile in DB.capacity_profiles.values():
        if profile.get("partner_id") != allocation["giving_partner_id"]:
            continue
        if profile.get("season_code") != season.get("season_code"):
            continue
        core.refresh_profile_status(profile)
        DB.touch(profile)
    partner = DB.partner(allocation["giving_partner_id"])
    if partner:
        core.recompute_partner_impact(partner)


# -- roll-ups ----------------------------------------------------------------

@bp.route("/impact-program/giving-partners/<partner_id>/attributed-units", methods=["GET"])
@roles(IMPACT_AUDITOR, MARKETING_MANAGER, GIVING_PARTNER_ORG)
def attributed_units(partner_id):
    partner = common.partner_or_404(partner_id)
    require_own_partner(partner_id)
    season = DB.current_season()
    core.recompute_partner_attribution(partner)
    approved = [p for p in DB.giving_partners.values() if p.get("status") == "APPROVED"]
    for row in approved:
        core.recompute_partner_attribution(row)
    total = sum(p.get("claim_attributed_units") or 0 for p in approved)
    shares, _ = calc.attributed_percentages(DB, approved, total)
    payload = {
        "partner_id": partner_id,
        "season_code": season.get("season_code") if season else None,
        "claim_attributed_units": partner.get("claim_attributed_units") or 0,
        "attributed_percentage": shares.get(partner_id, 0.0),
        "season_attributed_units_total": total,
        "cooperatives": [],
    }
    return success(payload)


@bp.route("/impact-program/giving-partners/<partner_id>/return-exposure", methods=["GET"])
@roles(IMPACT_AUDITOR, PROVISIONING_PARTNER, GIVING_PARTNER_ORG)
def return_exposure(partner_id):
    partner = common.partner_or_404(partner_id)
    require_own_partner(partner_id)
    core.recompute_partner_entrance_returns(partner)
    season = DB.current_season()

    lines = []
    returned_units_total = 0
    liability_units_retained = 0
    for request_row in DB.return_requests.values():
        if request_row.get("status") not in ("CREDITED", "EXCHANGED"):
            continue
        line = DB.order_line(request_row.get("sales_order_line_id"))
        if not line:
            continue
        variant = DB.product_line(line.get("donation_product_line_id"))
        product = DB.product(variant.get("donation_product_id")) if variant else None
        if not product or core.attributed_partner_id(product["id"]) != partner["id"]:
            continue
        returned_units_total += request_row.get("requested_units") or 0
        liability_units_retained += line.get("obligated_units") or 0
        lines.append({
            "return_id": request_row["id"],
            "sales_order_line_id": line["id"],
            "requested_units": request_row.get("requested_units"),
            "status": request_row.get("status"),
            "obligated_units": line.get("obligated_units"),
        })

    payload = {
        "partner_id": partner_id,
        "season_code": season.get("season_code") if season else None,
        "entrance_returns_units": partner.get("entrance_returns_units") or 0,
        "returned_units_total": returned_units_total,
        "liability_units_retained": liability_units_retained,
        "lines": lines,
    }
    return success(payload)


@bp.route("/impact-program/giving-partners/<partner_id>/allocations", methods=["GET"])
@roles(ALLOCATION_PLANNER, FULFILLMENT_OPERATOR, IMPACT_AUDITOR, GIVING_PARTNER_COORDINATOR)
def partner_allocations(partner_id):
    common.partner_or_404(partner_id)
    season_id = request.args.get("impact_season_id")
    status = request.args.get("status")
    kind = request.args.get("allocation_kind")
    limit, offset = pagination()
    rows = DB.partner_allocations(partner_id, season_id, kind)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationAllocation", page),
                   pagination=pagination_meta(limit, offset, total))


# ===========================================================================
# Vetting rounds
# ===========================================================================

@bp.route("/impact-program/vetting-rounds", methods=["GET"])
@roles(GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR)
def list_all_rounds():
    partner_id = request.args.get("partner_id")
    outcome = request.args.get("outcome")
    limit, offset = pagination()
    rows = list(DB.vetting_rounds.values())
    if partner_id:
        rows = [r for r in rows if r.get("partner_id") == partner_id]
    if outcome:
        rows = [r for r in rows if r.get("outcome") == outcome]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("round_number") or 0))
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("GivingPartnerVetting", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/giving-partners/<partner_id>/vetting-rounds", methods=["GET"])
@roles(GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR)
def list_partner_rounds(partner_id):
    common.partner_or_404(partner_id)
    outcome = request.args.get("outcome")
    limit, offset = pagination()
    rows = [r for r in DB.vetting_rounds.values() if r.get("partner_id") == partner_id]
    if outcome:
        rows = [r for r in rows if r.get("outcome") == outcome]
    rows.sort(key=lambda r: r.get("round_number") or 0)
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("GivingPartnerVetting", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/vetting-rounds/<vetting_id>", methods=["GET"])
@roles(GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR)
def get_round(vetting_id):
    record = common.vetting_or_404(vetting_id)
    return success(serial.serialize("GivingPartnerVetting", record))


@bp.route("/impact-program/vetting-rounds/<vetting_id>", methods=["PUT"])
@roles(GIVING_PARTNER_COORDINATOR)
def update_round(vetting_id):
    record = common.vetting_or_404(vetting_id)
    partner = common.partner_or_404(record["partner_id"])
    payload = body()
    require(payload, "outcome")
    outcome = as_enum(payload, "outcome", ROUND_OUTCOMES, required=True)

    if record.get("outcome") == "EXPIRED":
        raise ApiError("ERR_VETTING_ROUND_TERMINAL")

    current = record.get("outcome")
    if outcome == current:
        # PRD §3.1: "A successful round write also advances the round's own
        # outcome" — a write that names the outcome the round already holds
        # advances nothing and simply records the evidence it carries (which is
        # what recomputes `need_score`, per §3.1).
        _record_round_evidence(record, partner, payload)
        return success(serial.serialize("GivingPartnerVetting", record))

    if outcome == "DOCUMENTS_SUBMITTED":
        allowed_from = ("REQUESTED",)
        if current == "APPROVED":
            _require_performance_reopen(partner)
        elif current not in allowed_from:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if current == "REQUESTED":
            if payload.get("registry_check_passed") is None or payload.get("tax_check_passed") is None:
                raise ApiError("ERR_INVALID_REQUEST",
                               "registry_check_passed and tax_check_passed are required.")
    elif outcome == "EVALUATING":
        # PRD §3.1 recomputes need_score "on any vetting-round write that
        # changes the verification points", so evidence may be re-recorded on a
        # round that already sits at `EVALUATING`.
        if current not in ("DOCUMENTS_SUBMITTED", "EVALUATING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    elif outcome == "REQUESTED":
        if current != "EVALUATING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        message = payload.get("outcome_message")
        if not isinstance(message, str) or message.strip() == "":
            raise ApiError("ERR_INVALID_REQUEST", "outcome_message must be non-empty.")
    elif outcome in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Use the approve or reject operation to record that outcome.")
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    _record_round_evidence(record, partner, payload)

    record["outcome"] = outcome

    if outcome == "REQUESTED":
        # A round sent back for information counts as a rejection (PRD 3.1).
        partner["status"] = "CANDIDATE"
        partner["total_rejections"] = (partner.get("total_rejections") or 0) + 1
        DB.touch(partner)
    elif outcome == "DOCUMENTS_SUBMITTED" and current == "APPROVED":
        partner["status"] = "VETTING"
        partner["registry_verified"] = calc.registry_verified(
            partner.get("registry_id"), partner.get("ein"))
        DB.touch(partner)
    elif outcome == "EVALUATING":
        if partner.get("status") == "CANDIDATE":
            partner["status"] = "VETTING"
            DB.touch(partner)

    _recompute_partner_need(partner)
    core.recompute_partner(partner)
    return success(serial.serialize("GivingPartnerVetting", record))


def _record_round_evidence(record, partner, payload):
    """Write the round's evidence fields and recompute the partner's need score.

    PRD §3.1: "Alongside the four verification flags ... the coordinator records
    `need_verification_points` ... the supporting `need_verification_evidence`, a
    `valid_until` instant and an `outcome_message`", and "`need_score` is
    recomputed ... on any vetting-round write that changes the verification
    points".
    """
    for field, setter in (
        ("registry_check_passed", as_bool),
        ("tax_check_passed", as_bool),
        ("on_site_check_passed", as_bool),
        ("capacity_check_passed", as_bool),
    ):
        if field in payload:
            record[field] = setter(payload, field)
    if "need_verification_points" in payload:
        record["need_verification_points"] = as_int(
            payload, "need_verification_points", minimum=0, maximum=5)
    if "need_verification_evidence" in payload:
        record["need_verification_evidence"] = as_str(payload, "need_verification_evidence")
    if "valid_until" in payload:
        record["valid_until"] = iso3(as_instant(payload, "valid_until"))
    if "outcome_message" in payload:
        record["outcome_message"] = as_str(payload, "outcome_message")
    _recompute_partner_need(partner)
    return record


def _require_performance_reopen(partner):
    season = DB.current_season()
    graded = False
    if season:
        for audit in DB.impact_audits.values():
            if audit.get("audit_kind") != "PARTNER_PERFORMANCE":
                continue
            if audit.get("impact_season_id") != season["id"]:
                continue
            if audit.get("status") == "FINALIZED" and _audit_names_partner(audit, partner):
                graded = True
    if not graded:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if partner.get("partner_performance_grade") not in ("MONITORED", "PROBATION"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


@bp.route("/impact-program/vetting-rounds/<vetting_id>/approve", methods=["POST"])
@roles(GIVING_PARTNER_COORDINATOR)
def approve_round(vetting_id):
    record = common.vetting_or_404(vetting_id)
    partner = common.partner_or_404(record["partner_id"])
    if record.get("outcome") == "EXPIRED":
        raise ApiError("ERR_VETTING_ROUND_TERMINAL")
    # PRD §3.1: "The same approval path is available out of the round's
    # `EVALUATING` outcome, with the identical two conditions." A round the
    # partner already carries sits at `APPROVED`, and PRD §3.1's narrower
    # reopening path (a finalized performance audit plus a MONITORED or
    # PROBATION grade) does not apply here — the approval gate itself is what
    # this endpoint evaluates.
    if record.get("outcome") not in ("EVALUATING", "VETTING", "DOCUMENTS_SUBMITTED",
                                     "APPROVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    _recompute_partner_need(partner)
    flags = [record.get("registry_check_passed"), record.get("tax_check_passed"),
             record.get("on_site_check_passed"), record.get("capacity_check_passed")]
    if not partner.get("registry_verified") or not all(flag is True for flag in flags):
        raise ApiError("ERR_REGISTRY_NOT_VERIFIED")
    if (partner.get("need_score") or 0) < calc.APPROVAL_MINIMUM:
        raise ApiError("ERR_NEED_SCORE_BELOW_MINIMUM")

    record["outcome"] = "APPROVED"
    partner["status"] = "APPROVED"
    partner["last_vetted_at"] = iso3(DB.now())
    _recompute_partner_need(partner)
    DB.touch(partner)

    # Profiles open for every season still PLANNED (PRD 3.1).
    for season in DB.impact_seasons.values():
        if season.get("status") != "PLANNED":
            continue
        _open_capacity_profile(partner, season)

    core.recompute_partner(partner)
    core.recompute_all_seasons()
    return success(serial.serialize("GivingPartnerVetting", record))


def _open_capacity_profile(partner, season, max_units=None):
    exists = any(p.get("partner_id") == partner["id"]
                 and p.get("season_code") == season.get("season_code")
                 for p in DB.capacity_profiles.values())
    if exists:
        return None
    now = iso3(DB.now())
    profile = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "partner_id": partner["id"],
        "season_code": season.get("season_code"),
        "max_allocatable_units": max_units if max_units is not None
        else (partner.get("unduplicated_recipients_per_facility") or 0),
        "_system_created": True,
        "reserved_units": 0,
        "committed_units": 0,
        "capacity_utilization_units": 0,
        # PRD §3.2: "A profile's `effective_from` instant is when its ceiling
        # becomes readable and its `effective_to` instant when it stops being
        # selectable." The approval path opens a placeholder before the
        # coordinator declares the window, so neither instant is set yet and
        # the row stays unreadable until an explicit declaration supersedes it.
        "effective_from": None,
        "effective_to": None,
        "status": "ACTIVE",
        "partner_open_season": True,
        "need_tier": partner.get("need_tier"),
    }
    DB.capacity_profiles[profile["id"]] = profile
    return profile


@bp.route("/impact-program/vetting-rounds/<vetting_id>/reject", methods=["POST"])
@roles(GIVING_PARTNER_COORDINATOR)
def reject_round(vetting_id):
    record = common.vetting_or_404(vetting_id)
    partner = common.partner_or_404(record["partner_id"])
    payload = body()
    require(payload, "outcome_message")
    message = as_nonempty_str(payload, "outcome_message", required=True)

    if record.get("outcome") == "EXPIRED":
        raise ApiError("ERR_VETTING_ROUND_TERMINAL")
    if record.get("outcome") in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    record["outcome"] = "REJECTED"
    record["outcome_message"] = message
    partner["total_rejections"] = (partner.get("total_rejections") or 0) + 1
    partner["status"] = "REJECTED_FINAL" if partner["total_rejections"] >= 2 else "REJECTED"
    DB.touch(partner)
    core.recompute_partner(partner)
    return success(serial.serialize("GivingPartnerVetting", record))


@bp.route("/impact-program/vetting-rounds/<vetting_id>/reopen", methods=["POST"])
@roles(GIVING_PARTNER_COORDINATOR)
def reopen_round(vetting_id):
    record = common.vetting_or_404(vetting_id)
    partner = common.partner_or_404(record["partner_id"])
    if (partner.get("total_rejections") or 0) >= 2 or record.get("outcome") != "REJECTED":
        raise ApiError("ERR_PARTNER_REJECTION_FINAL")

    next_number = (partner.get("vetting_round") or 0) + 1
    fresh = _create_round(partner, next_number, "DOCUMENTS_SUBMITTED")
    partner["vetting_round"] = next_number
    partner["latest_vetting_round_id"] = fresh["id"]
    partner["status"] = "VETTING"
    DB.touch(partner)
    core.recompute_partner(partner)
    return success(serial.serialize("GivingPartnerVetting", fresh))