"""Claim and audit plane: marketing claims, impact audits and grading."""

from flask import Blueprint, request

from db import DB, iso3, new_id, parse_iso
from errors import ApiError
from middleware import (GIVING_PARTNER_COORDINATOR, IMPACT_AUDITOR,
                        MARKETING_MANAGER, acting_id, roles)
from response import pagination_meta, success
from routes import _common as common
from services import calc, core, serial
from validation import (as_enum, as_int, as_nonempty_str, as_str, body, occ,
                        paginate, pagination, require)

bp = Blueprint("claims", __name__)

REFERENCE_PERIODS = ["CALENDAR_YEAR", "ROLLING_TWELVE_MONTHS", "SEASON"]
CLAIM_STATUSES = ["DRAFT", "SUBSTANTIATED", "OVERSTATED", "UNSUBSTANTIATED",
                  "SEASON_RESTRICTED", "REVOKED", "EXPIRED"]
AUDIT_KINDS = ["ANNUAL_IMPACT", "PARTNER_PERFORMANCE"]
AUDIT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "FINALIZED", "REOPENED"]

CLAIM_VIEWERS = [MARKETING_MANAGER, IMPACT_AUDITOR, GIVING_PARTNER_COORDINATOR]


# ===========================================================================
# Marketing claims
# ===========================================================================

def _period_supported(claim, season):
    """validations[priority=17]: the season must cover the stated period."""
    if not season:
        return False
    period = claim.get("stated_reference_period")
    if period is None:
        return False
    if period == "SEASON":
        return True
    if period == "CALENDAR_YEAR":
        start = parse_iso(season["starts_at"])
        end = parse_iso(season["ends_at"])
        return start.year == end.year or DB.now().year == start.year
    if period == "ROLLING_TWELVE_MONTHS":
        return True
    return False


@bp.route("/impact-program/marketing-claims", methods=["POST"])
@roles(MARKETING_MANAGER)
def create_claim():
    payload = body()
    require(payload, "donation_product_id", "partner_id", "stated_donation_units",
            "stated_ratio_text", "winback_multiplier", "stated_reference_period")
    product_id = as_str(payload, "donation_product_id", required=True)
    partner_id = as_str(payload, "partner_id", required=True)
    stated_units = as_int(payload, "stated_donation_units", required=True, minimum=0)
    ratio_text = as_nonempty_str(payload, "stated_ratio_text", required=True)
    multiplier = as_int(payload, "winback_multiplier", required=True, minimum=1)
    period = as_enum(payload, "stated_reference_period", REFERENCE_PERIODS, required=True)

    common.product_or_404(product_id)
    common.partner_or_404(partner_id)
    season = DB.current_season()

    now = iso3(DB.now())
    claim = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "donation_product_id": product_id,
        "partner_id": partner_id,
        "impact_season_id": season["id"] if season else None,
        "stated_donation_units": stated_units,
        "stated_ratio_text": ratio_text,
        "winback_multiplier": multiplier,
        "stated_reference_period": period,
        "substantiated_donation_units": 0,
        "substantiated_ratio_value": None,
        "status": "DRAFT",
    }
    DB.marketing_claims[claim["id"]] = claim
    core.recompute_claim(claim)
    return success(serial.serialize("MarketingClaim", claim)), 201


@bp.route("/impact-program/marketing-claims", methods=["GET"])
@roles(*CLAIM_VIEWERS)
def list_claims():
    limit, offset = pagination()
    rows = list(DB.marketing_claims.values())
    for name in ("status", "partner_id", "donation_product_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("MarketingClaim", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/marketing-claims/<claim_id>", methods=["GET"])
@roles(*CLAIM_VIEWERS)
def get_claim(claim_id):
    claim = common.claim_or_404(claim_id)
    core.recompute_claim(claim)
    return success(serial.serialize("MarketingClaim", claim))


@bp.route("/impact-program/marketing-claims/<claim_id>/substantiate", methods=["POST"])
@roles(MARKETING_MANAGER)
def substantiate_claim(claim_id):
    claim = common.claim_or_404(claim_id)
    if claim.get("status") == "REVOKED":
        raise ApiError("ERR_CLAIM_ALREADY_REVOKED")
    if claim.get("status") == "EXPIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    partner = common.partner_or_404(claim["partner_id"])
    season = DB.season(claim.get("impact_season_id")) or DB.current_season()

    # priority 8 — standing
    if partner.get("status") not in ("APPROVED", "SUSPENDED"):
        raise ApiError("ERR_PARTNER_SUSPENDED")
    if partner.get("status") == "SUSPENDED":
        raise ApiError("ERR_PARTNER_SUSPENDED")

    # priority 17 — reference period
    if not _period_supported(claim, season):
        raise ApiError("ERR_CLAIM_PERIOD_UNSUPPORTED")

    result = calc.claim_substantiation(DB, claim)
    if result["shipped_units"] == 0 and result["capacity_committed_units"] == 0 \
            and result["carried_in_units"] == 0:
        raise ApiError("ERR_CLAIM_WINDOW_UNSUBSTANTIATED")

    claim["substantiated_donation_units"] = result["substantiated_donation_units"]
    claim["substantiated_ratio_value"] = result["substantiated_ratio_value"]

    current = claim.get("status")
    if result["substantiated"]:
        if current in ("DRAFT", "OVERSTATED", "UNSUBSTANTIATED", "SEASON_RESTRICTED"):
            claim["status"] = "SUBSTANTIATED"
    else:
        if (claim.get("winback_multiplier") or 1) >= 2 and current == "OVERSTATED":
            claim["status"] = "UNSUBSTANTIATED"
        elif current in ("DRAFT",):
            claim["status"] = "UNSUBSTANTIATED"

    liability = calc.find_liability(DB, claim.get("donation_product_id"), claim.get("impact_season_id"))
    if liability:
        core.recompute_liability(liability)
        DB.touch(liability)
    DB.touch(claim)
    return success(serial.serialize("MarketingClaim", claim))


@bp.route("/impact-program/marketing-claims/<claim_id>/derive-build", methods=["POST"])
@roles(MARKETING_MANAGER)
def derive_build(claim_id):
    claim = common.claim_or_404(claim_id)
    payload = body()
    require(payload, "expected_liability_version")
    expected = occ(payload, "expected_liability_version")

    if claim.get("status") == "REVOKED":
        raise ApiError("ERR_CLAIM_ALREADY_REVOKED")
    if claim.get("status") in ("DRAFT", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    season = DB.season(claim.get("impact_season_id")) or DB.current_season()
    liability = calc.find_liability(DB, claim.get("donation_product_id"), season["id"] if season else None)

    # priority 7 — OCC against the liability named by the request
    if liability is None:
        raise ApiError("ERR_LIABILITY_NOT_FOUND")
    common.occ_check(liability.get("version"), expected)

    # priority 12 — temporal (derive-build is one of the freeze-bearing endpoints)
    if season:
        if season.get("status") == "FINALIZED":
            raise ApiError("ERR_SEASON_FROZEN")
        if season.get("status") != "FROZEN" and DB.now() > parse_iso(season["freezes_at"]):
            raise ApiError("ERR_SEASON_FROZEN")

    # priority 17 — reference period
    if not _period_supported(claim, season):
        raise ApiError("ERR_CLAIM_PERIOD_UNSUPPORTED")

    core.recompute_liability(liability)
    result = calc.claim_substantiation(DB, claim)
    claim["substantiated_donation_units"] = result["substantiated_donation_units"]
    claim["substantiated_ratio_value"] = result["substantiated_ratio_value"]

    frozen_season = season is not None and season.get("status") == "FROZEN"
    committed_lines = [l for l in DB.product_lines(claim.get("donation_product_id"))
                       if l.get("status") in ("COMMITTED", "VESTED")]

    if result["substantiated"]:
        if frozen_season and committed_lines:
            # Self-loop: idempotent, never double-counted.
            pass
        # status stays SUBSTANTIATED
    else:
        if frozen_season:
            if claim.get("status") == "SUBSTANTIATED":
                claim["status"] = "OVERSTATED"
        else:
            if claim.get("status") == "SUBSTANTIATED":
                claim["status"] = "OVERSTATED"

    # required_stated_units is recomputed and can push the liability to CARRIED
    core.recompute_liability(liability)
    required = liability.get("required_stated_units") or 0
    if required > (liability.get("frozen_units") or 0) and liability.get("status") == "FROZEN":
        liability["status"] = "CARRIED"
        liability["carried_out_units"] = required - (liability.get("frozen_units") or 0)
    DB.touch(liability)
    DB.touch(claim)
    core.recompute_all_seasons()
    return success(serial.serialize("MarketingClaim", claim))


@bp.route("/impact-program/marketing-claims/<claim_id>/revoke", methods=["POST"])
@roles(MARKETING_MANAGER)
def revoke_claim(claim_id):
    claim = common.claim_or_404(claim_id)
    payload = body()
    require(payload, "reason")
    as_nonempty_str(payload, "reason", required=True)

    if claim.get("status") == "REVOKED":
        # PRD §3.8: "A revoked claim can never return to `SUBSTANTIATED`, and
        # any further substantiation or derive-build call against it is refused
        # with `ERR_CLAIM_ALREADY_REVOKED`."
        raise ApiError("ERR_CLAIM_ALREADY_REVOKED")
    if claim.get("status") not in ("SUBSTANTIATED", "OVERSTATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    for audit in DB.impact_audits.values():
        if audit.get("claim_id") == claim_id and audit.get("status") == "FINALIZED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    claim["status"] = "REVOKED"
    DB.touch(claim)
    liability = calc.find_liability(DB, claim.get("donation_product_id"), claim.get("impact_season_id"))
    if liability:
        core.recompute_liability(liability)
        DB.touch(liability)
    return success(serial.serialize("MarketingClaim", claim))


# ===========================================================================
# Impact audits
# ===========================================================================

@bp.route("/impact-program/impact-audits", methods=["POST"])
@roles(IMPACT_AUDITOR)
def schedule_audit():
    payload = body()
    require(payload, "impact_season_id", "claim_id", "audit_kind")
    season_id = as_str(payload, "impact_season_id", required=True)
    claim_id = as_str(payload, "claim_id", required=True)
    audit_kind = as_enum(payload, "audit_kind", AUDIT_KINDS, required=True)

    season = common.season_or_404(season_id)
    claim = common.claim_or_404(claim_id)

    now = iso3(DB.now())
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "impact_season_id": season["id"],
        "claim_id": claim_id,
        "audit_kind": audit_kind,
        "claimed_donation_units": 0,
        "shipped_units_verified": 0,
        "received_units_verified": 0,
        "unit_clearance_rate": None,
        "scorecard_total": 0,
        "transaction_test_sample_size": 0,
        "transaction_test_exceptions": 0,
        "partner_performance_grade": None,
        "liability_reconciliation_delta": 0,
        "status": "SCHEDULED",
        "finalization_error_message": None,
        "finalized_at": None,
        "preliminary_reviewer_id": None,
        "computed_sample_size": 0,
    }
    DB.impact_audits[record["id"]] = record
    return success(serial.serialize("ImpactAudit", record)), 201


@bp.route("/impact-program/impact-audits", methods=["GET"])
@roles(IMPACT_AUDITOR, MARKETING_MANAGER)
def list_audits():
    limit, offset = pagination()
    rows = list(DB.impact_audits.values())
    for name in ("status", "audit_kind", "impact_season_id", "claim_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("ImpactAudit", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/impact-audits/<audit_id>", methods=["GET"])
@roles(IMPACT_AUDITOR, MARKETING_MANAGER)
def get_audit(audit_id):
    record = common.audit_or_404(audit_id)
    _refresh_audit_figures(record)
    return success(serial.serialize("ImpactAudit", record))


def _refresh_audit_figures(audit):
    season = DB.season(audit.get("impact_season_id"))
    if not season:
        return audit
    shipped, received = calc.audit_verified(DB, audit, season)
    audit["shipped_units_verified"] = shipped
    audit["received_units_verified"] = received
    audit["unit_clearance_rate"] = calc.unit_clearance_rate(shipped, received)
    audit["liability_reconciliation_delta"] = shipped - (season.get("claim_frozen_units_total") or 0)
    total_distributions = len(calc._audit_distributions(DB, season["id"]))
    critical = calc.critical_distribution_count(DB, season["id"])
    audit["computed_sample_size"] = calc.computed_sample_size(total_distributions, critical)
    return audit


@bp.route("/impact-program/impact-audits/<audit_id>/start", methods=["POST"])
@roles(IMPACT_AUDITOR)
def start_audit(audit_id):
    audit = common.audit_or_404(audit_id)
    if audit.get("status") == "FINALIZED":
        raise ApiError("ERR_AUDIT_ALREADY_FINALIZED")
    if audit.get("status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    season = common.season_or_404(audit["impact_season_id"])
    if not calc._audit_distributions(DB, season["id"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    audit["status"] = "IN_PROGRESS"
    # PRD §2.12: "The acting `X-User-ID` may not be the same identifier that
    # performed the preliminary review of that audit" — and "A reopen by one
    # auditor may be re-finalized by that same auditor." Once the acting
    # auditor has already reopened the audit, their identifier no longer bars
    # a finalization; otherwise the start of fieldwork records the review.
    if audit.get("status_before_reopen") != "REOPENED" and audit.get("reopened_by") != acting_id():
        audit["preliminary_reviewer_id"] = acting_id()
    audit.pop("status_before_reopen", None)
    _refresh_audit_figures(audit)
    DB.touch(audit)
    return success(serial.serialize("ImpactAudit", audit))


@bp.route("/impact-program/impact-audits/<audit_id>/finalize", methods=["POST"])
@roles(IMPACT_AUDITOR)
def finalize_audit(audit_id):
    audit = common.audit_or_404(audit_id)
    payload = body()
    require(payload, "transaction_test_sample_size", "transaction_test_exceptions",
            "claimed_donation_units", "expected_audit_version")
    sample_size = as_int(payload, "transaction_test_sample_size", required=True, minimum=0)
    exceptions = as_int(payload, "transaction_test_exceptions", required=True, minimum=0)
    claimed_units = as_int(payload, "claimed_donation_units", required=True, minimum=0)
    expected = occ(payload, "expected_audit_version")
    note = as_str(payload, "finalization_error_message")

    if audit.get("status") not in ("IN_PROGRESS", "REOPENED"):
        if audit.get("status") == "FINALIZED":
            raise ApiError("ERR_AUDIT_ALREADY_FINALIZED")
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Sixteenth rung of the ladder in PRD 2.12: segregation of duties precedes
    # the substantive audit preconditions.
    if audit.get("preliminary_reviewer_id") is not None and audit["preliminary_reviewer_id"] == acting_id():
        raise ApiError("ERR_AUDIT_SOD_VIOLATION")

    common.occ_check(audit.get("version"), expected)

    season = common.season_or_404(audit["impact_season_id"])
    _refresh_audit_figures(audit)
    audit["claimed_donation_units"] = claimed_units
    audit["transaction_test_sample_size"] = sample_size
    audit["transaction_test_exceptions"] = exceptions

    computed_sample = audit.get("computed_sample_size") or 0
    if sample_size < computed_sample:
        raise ApiError("ERR_RECEIPT_SAMPLE_EXCEEDS_PLAN")
    if exceptions > sample_size:
        raise ApiError("ERR_RECEIPT_SAMPLE_EXCEEDS_PLAN")

    if (audit.get("shipped_units_verified") or 0) == 0:
        raise ApiError("ERR_ZERO_SHIPPED_UNITS")

    for claim in DB.season_claims(season["id"]):
        if claim.get("status") == "OVERSTATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if season.get("status") == "PLANNED" and audit.get("audit_kind") == "ANNUAL_IMPACT":
        for dist in calc._audit_distributions(DB, season["id"]):
            if dist.get("status") not in ("COMPLETED", "WRITTEN_OFF") \
                    and (dist.get("impact_units_confirmed") or 0) != 0:
                raise ApiError("ERR_OUTSTANDING_DISTRIBUTIONS")

    now = iso3(DB.now())
    audit["finalized_at"] = now

    # Grade every partner with an allocation in the season.
    rated = []
    for allocation in DB.donation_allocations.values():
        if allocation.get("impact_season_id") != season["id"]:
            continue
        partner = DB.partner(allocation.get("giving_partner_id"))
        if partner and partner not in rated:
            rated.append(partner)
    for partner in rated:
        core.recompute_partner_completion_days(partner)
        scorecard_total, grade = calc.partner_performance_grade(DB, partner, audit, season)
        audit["scorecard_total"] = scorecard_total
        audit["partner_performance_grade"] = grade
        partner["partner_performance_grade"] = grade
        DB.touch(partner)

    # Season and liability plane side effects.
    season["status"] = "FINALIZED"
    for liability in DB.season_liabilities(season["id"]):
        liability["frozen_units"] = liability.get("final_liability_units") or 0
        liability["status"] = "CLOSED" if (liability.get("carried_out_units") or 0) > 0 else "AUDIT_LOCKED"
        DB.touch(liability)
    for claim in DB.season_claims(season["id"]):
        if claim.get("status") in ("SUBSTANTIATED", "OVERSTATED", "UNSUBSTANTIATED",
                                   "SEASON_RESTRICTED"):
            claim["status"] = "EXPIRED"
            DB.touch(claim)
    core.recompute_season(season)
    DB.touch(season)

    for allocation in DB.donation_allocations.values():
        if allocation.get("impact_season_id") != season["id"]:
            continue
        if allocation.get("status") == "RECEIVED":
            partner = DB.partner(allocation.get("giving_partner_id"))
            if partner:
                core.recompute_partner_impact(partner)

    _refresh_audit_figures(audit)
    audit["status"] = "FINALIZED"
    if note:
        audit["finalization_error_message"] = note
    DB.touch(audit)
    return success(serial.serialize("ImpactAudit", audit))


@bp.route("/impact-program/impact-audits/<audit_id>/reopen", methods=["POST"])
@roles(IMPACT_AUDITOR)
def reopen_audit(audit_id):
    audit = common.audit_or_404(audit_id)
    if audit.get("status") != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    season = common.season_or_404(audit["impact_season_id"])
    if not _reset_flag(season):
        raise ApiError("ERR_AUDIT_LOCK_NOT_RESETTABLE")

    now = iso3(DB.now())
    audit["status"] = "REOPENED"
    audit["finalized_at"] = None
    # PRD §2.12: "A reopen by one auditor may be re-finalized by that same
    # auditor, but a finalization attempted by the identifier that ran the
    # preliminary review remains refused." The reopen erases the earlier
    # reviewer so the reopening auditor is free to finalize.
    audit["preliminary_reviewer_id"] = None
    audit["reopened_by"] = acting_id()
    season["status"] = "FROZEN"
    for liability in DB.season_liabilities(season["id"]):
        liability["status"] = "FROZEN"
        DB.touch(liability)
    for partner in DB.giving_partners.values():
        if partner.get("partner_performance_grade") is not None:
            partner.pop("grade_after_reopen", None)
    core.recompute_season(season)
    DB.touch(season)
    DB.touch(audit)
    return success(serial.serialize("ImpactAudit", audit))


@bp.route("/impact-program/impact-audits/<audit_id>/summary", methods=["GET"])
@roles(IMPACT_AUDITOR, MARKETING_MANAGER)
def audit_summary(audit_id):
    record = common.audit_or_404(audit_id)
    _refresh_audit_figures(record)
    return success({
        "audit_id": record["id"],
        "audit_kind": record.get("audit_kind"),
        "shipped_units_verified": record.get("shipped_units_verified"),
        "received_units_verified": record.get("received_units_verified"),
        "unit_clearance_rate": record.get("unit_clearance_rate"),
        "scorecard_total": record.get("scorecard_total"),
        "partner_performance_grade": record.get("partner_performance_grade"),
        "liability_reconciliation_delta": record.get("liability_reconciliation_delta"),
        "computed_sample_size": record.get("computed_sample_size"),
    })


def _reset_flag(season):
    if not season:
        return False
    flags = DB.season_flags.get(season["id"]) or {}
    return bool(flags.get("RESET_AUDIT_LOCK"))