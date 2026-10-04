"""Routes: payer contracts, fee schedule rates, credentialing enrollments."""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (
    err_contract_not_active,
    err_cutover,
    err_enroll_overlap,
    err_expedited,
    err_invalid,
    err_no_ratification,
    err_not_found,
    err_transition,
    err_uplift,
)
from middleware import get_context, require_roles
from response import (
    created,
    new_entity,
    ok,
    paginate,
    parse_pagination,
    touch,
)
from services import contract_terminate_cascade, round_half_up_4dp
from validate import (
    body_json,
    require_date,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("contracts", __name__)


# ---------------------------------------------------------------------------
# PayerContract
# ---------------------------------------------------------------------------

@bp.route("/api/payer-contracts", methods=["POST"])
def create_contract():
    require_roles("PayerContractingOfficer")
    data = body_json()
    medical_group_id = require_str(data, "medical_group_id")
    payer_name = require_str(data, "payer_name")
    contract_type = require_enum(
        data, "contract_type", {"FEE_FOR_SERVICE", "VALUE_BASED", "HYBRID"}
    )
    effective = require_date(data, "effective_date")
    group = store.medical_groups.get(medical_group_id)
    if group is None:
        raise err_not_found("MEDICAL_GROUP", "Medical group not found")
    if group["status"] != "OPERATING":
        from errors import err_group_not_operating

        raise err_group_not_operating()
    c = new_entity()
    c.update(
        medical_group_id=medical_group_id,
        payer_name=payer_name,
        contract_type=contract_type,
        effective_date=effective.isoformat(),
        ratifying_vote_id=None,
        status="NEGOTIATION",
        value_based_pool_eligible=contract_type in ("VALUE_BASED", "HYBRID"),
    )
    store.payer_contracts[c["id"]] = c
    return created(c)


@bp.route("/api/payer-contracts", methods=["GET"])
def list_contracts():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.payer_contracts.values())
    mgid = request.args.get("medical_group_id")
    if mgid is not None:
        items = [c for c in items if c["medical_group_id"] == mgid]
    rv = request.args.get("ratifying_vote_id")
    if rv is not None:
        items = [c for c in items if c.get("ratifying_vote_id") == rv]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/payer-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    get_context()
    c = store.payer_contracts.get(cid)
    if c is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    return ok(c)


@bp.route("/api/payer-contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    require_roles("PayerContractingOfficer")
    c = store.payer_contracts.get(cid)
    if c is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    if c["status"] != "NEGOTIATION":
        raise err_transition("Contract is not NEGOTIATION")
    passing = None
    for v in store.votes.values():
        if (
            v["subject_contract_id"] == c["id"]
            and v["motion_type"] == "PAYER_CONTRACT_RATIFICATION"
            and v["status"] == "PASSED"
        ):
            passing = v
            break
    if passing is None:
        raise err_no_ratification()
    today = store.clock_date()
    if today < date.fromisoformat(c["effective_date"]):
        raise err_cutover("Clock date is before the contract effective_date")
    if c["contract_type"] in ("FEE_FOR_SERVICE", "HYBRID"):
        proposed = [
            r
            for r in store.fee_schedule_rates.values()
            if r["payer_contract_id"] == c["id"] and r["status"] == "PROPOSED"
        ]
        if not proposed:
            raise err_uplift()
        total = Decimal("0")
        for r in proposed:
            total += Decimal(str(r["uplift_pct"]))
        avg = round_half_up_4dp(total / Decimal(len(proposed)))
        if avg < Decimal("0.0800"):
            raise err_uplift()
    c["status"] = "ACTIVE"
    c["ratifying_vote_id"] = passing["id"]
    touch(c)
    for r in store.fee_schedule_rates.values():
        if r["payer_contract_id"] == c["id"] and r["status"] == "PROPOSED":
            r["status"] = "ACTIVE"
            touch(r)
    return ok(c)


@bp.route("/api/payer-contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    require_roles("ComplianceOfficer")
    c = store.payer_contracts.get(cid)
    if c is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    if c["status"] != "ACTIVE":
        raise err_transition("Contract is not ACTIVE")
    c["status"] = "TERMINATED"
    touch(c)
    contract_terminate_cascade(c)
    return ok(c)


# ---------------------------------------------------------------------------
# FeeScheduleRate
# ---------------------------------------------------------------------------

@bp.route("/api/fee-schedule-rates", methods=["POST"])
def create_rate():
    require_roles("PayerContractingOfficer")
    data = body_json()
    payer_contract_id = require_str(data, "payer_contract_id")
    cpt_code = require_str(data, "cpt_code")
    legacy_rate_cents = require_int(data, "legacy_rate_cents")
    group_rate_cents = require_int(data, "group_rate_cents")
    if legacy_rate_cents <= 0:
        raise err_invalid("legacy_rate_cents must be positive")
    if group_rate_cents <= 0:
        raise err_invalid("group_rate_cents must be positive")
    contract = store.payer_contracts.get(payer_contract_id)
    if contract is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    if contract["status"] != "NEGOTIATION":
        raise err_transition("Contract must be NEGOTIATION")
    # supersede existing PROPOSED rate for the same contract+code
    for r in store.fee_schedule_rates.values():
        if (
            r["payer_contract_id"] == payer_contract_id
            and r["cpt_code"] == cpt_code
            and r["status"] == "PROPOSED"
        ):
            r["status"] = "SUPERSEDED"
            touch(r)
    uplift = round_half_up_4dp(
        (Decimal(group_rate_cents) - Decimal(legacy_rate_cents))
        / Decimal(legacy_rate_cents)
    )
    r = new_entity()
    r.update(
        payer_contract_id=payer_contract_id,
        cpt_code=cpt_code,
        legacy_rate_cents=legacy_rate_cents,
        group_rate_cents=group_rate_cents,
        uplift_pct=float(uplift),
        status="PROPOSED",
    )
    store.fee_schedule_rates[r["id"]] = r
    return created(r)


@bp.route("/api/fee-schedule-rates", methods=["GET"])
def list_rates():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.fee_schedule_rates.values())
    cid = request.args.get("payer_contract_id")
    if cid is not None:
        items = [r for r in items if r["payer_contract_id"] == cid]
    code = request.args.get("cpt_code")
    if code is not None:
        items = [r for r in items if r["cpt_code"] == code]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/fee-schedule-rates/<rid>", methods=["GET"])
def get_rate(rid):
    get_context()
    r = store.fee_schedule_rates.get(rid)
    if r is None:
        raise err_not_found("RATE", "Fee schedule rate not found")
    return ok(r)


# ---------------------------------------------------------------------------
# CredentialingEnrollment
# ---------------------------------------------------------------------------

@bp.route("/api/credentialing-enrollments", methods=["POST"])
def create_enrollment():
    require_roles("CredentialingCoordinator")
    data = body_json()
    provider_id = require_str(data, "provider_id")
    payer_contract_id = require_str(data, "payer_contract_id")
    channel = require_enum(data, "channel", {"STANDARD", "EXPEDITED"})
    requested = require_date(data, "requested_effective_date")
    provider = store.providers.get(provider_id)
    if provider is None:
        raise err_not_found("PROVIDER", "Provider not found")
    contract = store.payer_contracts.get(payer_contract_id)
    if contract is None:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    if contract["status"] != "ACTIVE":
        raise err_contract_not_active()
    practice = store.practices.get(provider["practice_id"])
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] not in ("ONBOARDING", "AFFILIATED"):
        raise err_transition("Practice must be ONBOARDING or AFFILIATED")
    application_date = store.clock_date()
    if requested < application_date:
        raise err_invalid("requested_effective_date precedes application_date")
    if channel == "EXPEDITED" and (requested - application_date).days > 45:
        raise err_expedited()
    en = new_entity()
    en.update(
        provider_id=provider_id,
        payer_contract_id=payer_contract_id,
        channel=channel,
        application_date=application_date.isoformat(),
        requested_effective_date=requested.isoformat(),
        effective_date=None,
        termination_date=None,
        status="SUBMITTED",
    )
    store.enrollments[en["id"]] = en
    return created(en)


@bp.route("/api/credentialing-enrollments", methods=["GET"])
def list_enrollments():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.enrollments.values())
    pid = request.args.get("provider_id")
    if pid is not None:
        items = [e for e in items if e["provider_id"] == pid]
    cid = request.args.get("payer_contract_id")
    if cid is not None:
        items = [e for e in items if e["payer_contract_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/credentialing-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    get_context()
    e = store.enrollments.get(eid)
    if e is None:
        raise err_not_found("ENROLLMENT", "Enrollment not found")
    return ok(e)


def _compute_effective_date(enrollment, provider):
    lag = 90 if enrollment["channel"] == "STANDARD" else 30
    lag_date = date.fromisoformat(enrollment["application_date"]) + timedelta(days=lag)
    esd = date.fromisoformat(provider["employment_start_date"])
    return max(lag_date, esd)


def _check_window_overlap(enrollment, new_effective):
    """Closed interval [effective_date, termination_date] overlap check against
    other non-TERMINATED enrollments for same provider+contract. A window with
    termination_date null is unbounded on the right."""
    for other in store.enrollments.values():
        if other["id"] == enrollment["id"]:
            continue
        if other["provider_id"] != enrollment["provider_id"]:
            continue
        if other["payer_contract_id"] != enrollment["payer_contract_id"]:
            continue
        # PRD §2.10: enrollment windows are closed intervals over
        # [effective_date, termination_date]; the termination day itself is
        # occupied, so TERMINATED enrollments still occupy their window.
        if other["status"] == "SUBMITTED":
            # no effective_date yet -> no fixed window; skip
            continue
        o_end = (
            date.fromisoformat(other["termination_date"])
            if other.get("termination_date")
            else date.max
        )
        # new window: [new_effective, date.max) (termination unknown at approval)
        if new_effective <= o_end:
            raise err_enroll_overlap()


@bp.route("/api/credentialing-enrollments/<eid>/approve", methods=["POST"])
def approve_enrollment(eid):
    require_roles("CredentialingCoordinator")
    en = store.enrollments.get(eid)
    if en is None:
        raise err_not_found("ENROLLMENT", "Enrollment not found")
    if en["status"] != "SUBMITTED":
        raise err_transition("Enrollment is not SUBMITTED")
    provider = store.providers.get(en["provider_id"])
    if provider is None:
        raise err_not_found("PROVIDER", "Provider not found")
    practice = store.practices.get(provider["practice_id"])
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] not in ("ONBOARDING", "AFFILIATED"):
        raise err_transition("Practice must be ONBOARDING or AFFILIATED")
    effective = _compute_effective_date(en, provider)
    _check_window_overlap(en, effective)
    en["effective_date"] = effective.isoformat()
    if practice["status"] == "ONBOARDING":
        en["status"] = "APPROVED"
        touch(en)
    else:
        from services import enrollment_to_effective

        en["effective_date"] = effective.isoformat()
        en["status"] = "SUBMITTED"  # enrollment_to_effective flips it
        enrollment_to_effective(en)
    return ok(en)


@bp.route("/api/credentialing-enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment(eid):
    require_roles("CredentialingCoordinator", "ComplianceOfficer")
    data = body_json()
    if "termination_date" not in data or data["termination_date"] is None:
        raise err_invalid("termination_date is required")
    term = require_date(data, "termination_date")
    en = store.enrollments.get(eid)
    if en is None:
        raise err_not_found("ENROLLMENT", "Enrollment not found")
    if en["status"] not in ("SUBMITTED", "APPROVED", "EFFECTIVE"):
        raise err_transition("Enrollment already terminated")
    en["status"] = "TERMINATED"
    en["termination_date"] = term.isoformat()
    touch(en)
    return ok(en)
