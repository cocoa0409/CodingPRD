"""Employment contracts, the training-allowance ledger and validation windows
(PRD §3.3, §3.4; scaffold §1.2 EmploymentContract / ValidationPeriod)."""

from db import db, ts, parse_dt
from errors import (
    err,
    ERR_CONTRACT_NOT_FOUND,
    ERR_VALIDATION_PERIOD_NOT_FOUND,
    ERR_CANDIDATE_NOT_FOUND,
    ERR_ADVISOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_ALLOWANCE_CAP_EXCEEDED,
    ERR_EXTENSION_LIMIT_REACHED,
    ERR_NO_OPEN_VALIDATION_WINDOW,
    ERR_VALIDATION_WINDOW_INVALID,
    ERR_VALIDATION_WINDOW_OVERLAP,
)
from services import calc, derived, recruiting


def get(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        raise err(ERR_CONTRACT_NOT_FOUND, "no employment contract with id %s" % contract_id)
    return row


def get_period(period_id):
    row = db.validation_periods.get(period_id)
    if row is None:
        raise err(ERR_VALIDATION_PERIOD_NOT_FOUND,
                  "no validation period with id %s" % period_id)
    return row


# ---------------------------------------------------------------------------
# Contracting (PRD §3.3)
# ---------------------------------------------------------------------------
def create_contract(data):
    # Body foreign keys resolve in declared input order (PRD §2.4): advisor_id
    # then candidate_id.
    advisor_id = data.get("advisor_id")
    if advisor_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "advisor_id is required")
    advisor = db.advisors.get(advisor_id)
    if advisor is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % advisor_id)
    candidate_id = data.get("candidate_id")
    if candidate_id is None:
        raise err(ERR_CANDIDATE_NOT_FOUND, "candidate_id is required")
    candidate = db.candidates.get(candidate_id)
    if candidate is None:
        raise err(ERR_CANDIDATE_NOT_FOUND,
                  "no recruiting candidate with id %s" % candidate_id)

    # OCC pre-empts the state path on the pinned parent (PRD §2.6, §2.10).
    expected = data.get("expected_candidate_version")
    if expected is None:
        raise err(ERR_INVALID_REQUEST, "expected_candidate_version is required")
    if expected != candidate["version"]:
        raise err(ERR_STALE_VERSION,
                  "the candidate version has advanced since it was observed")

    from middleware import require_fields
    require_fields(data, ["contract_type", "start_date", "training_allowance_total_cents",
                          "training_allowance_mode", "validation_requirement_cents"])
    if candidate["stage"] != "OFFER_ACCEPTED":
        raise err(ERR_INVALID_STATE, "the candidate is not OFFER_ACCEPTED")
    existing = [c for c in db.contracts.values() if c["candidate_id"] == candidate_id]
    if existing:
        raise err(ERR_INVALID_STATE, "the candidate already has an employment contract")
    if advisor["contract_status"] != "NOT_CONTRACTED":
        raise err(ERR_INVALID_STATE, "the advisor is not NOT_CONTRACTED")

    contract = {
        "advisor_id": advisor_id,
        "candidate_id": candidate_id,
        "contract_type": data.get("contract_type"),
        "start_date": parse_dt(data.get("start_date")),
        "end_date": None,
        "training_allowance_total_cents": int(data.get("training_allowance_total_cents") or 0),
        "training_allowance_paid_cents": 0,
        "validation_requirement_cents": int(data.get("validation_requirement_cents") or 0),
        "training_allowance_mode": data.get("training_allowance_mode"),
        "contract_status": "ACTIVE_TRAINING",
    }
    db.stamp_create(contract)
    db.insert(db.contracts, contract)

    advisor["contract_status"] = "ACTIVE_TRAINING"
    advisor["validation_posture"] = "VALIDATING"
    advisor["orphan_pool_access"] = False
    db.touch(advisor)

    recruiting.set_stage(candidate, "CONTRACTED")
    return contract


# ---------------------------------------------------------------------------
# Training allowance (PRD §3.3)
# ---------------------------------------------------------------------------
def _production_toward_requirement(advisor_id):
    total = 0
    for credit in db.credits.values():
        if credit["advisor_id"] != advisor_id:
            continue
        if credit["credit_type"] not in derived.PRIMARY_CHANNELS:
            continue
        if credit["status"] not in ("ACCRUED", "PAID"):
            continue
        total += int(credit["gross_commission_cents"])
    return total


def draw_allowance(contract):
    requirement = calc.product_requirement_cents(contract)
    met = _production_toward_requirement(contract["advisor_id"]) >= requirement
    draw = calc.draw_per_window(contract, met)
    paid = int(contract["training_allowance_paid_cents"])
    total = int(contract["training_allowance_total_cents"])
    if paid + draw > total:
        raise err(ERR_ALLOWANCE_CAP_EXCEEDED,
                  "the draw would push the allowance beyond its total")
    if draw > 0:
        contract["training_allowance_paid_cents"] = paid + draw
        db.touch(contract)
        credit = {
            "policy_id": None,
            "advisor_id": contract["advisor_id"],
            "credit_type": "TRAINING_ALLOWANCE",
            "credit_pct": 0.0,
            "gross_commission_cents": draw,
            "net_commission_cents": draw,
            "advanced_paid_cents": 0,
            "case_gross_commission_cents": 0,
            "chargeback_assessed_cents": 0,
            "recovered_cents": 0,
            "chargeback_reason": None,
            "status": "ACCRUED",
        }
        db.stamp_create(credit)
        db.insert(db.credits, credit)
    contract["recruiter_override_cents"] = calc.recruiter_override_cents(contract)
    return contract


# ---------------------------------------------------------------------------
# Validation windows (PRD §3.4)
# ---------------------------------------------------------------------------
def _window_overlaps(contract_id, start, end, exclude_id=None):
    """Half-open comparison: shared boundary instants touch but do not overlap."""
    for row in db.validation_periods.values():
        if row["id"] == exclude_id:
            continue
        if row["contract_id"] != contract_id:
            continue
        if row["status"] not in ("OPEN", "EXTENDED"):
            continue
        if start < row["end_date"] and row["start_date"] < end:
            return True
    return False


def _validate_window(contract, start, end, exclude_id=None):
    if start >= end:
        raise err(ERR_VALIDATION_WINDOW_INVALID,
                  "start_date must be strictly before end_date")
    if start < contract["start_date"]:
        raise err(ERR_VALIDATION_WINDOW_INVALID,
                  "the window falls outside the contract's live span")
    if contract["end_date"] is not None and end > contract["end_date"]:
        raise err(ERR_VALIDATION_WINDOW_INVALID,
                  "the window falls outside the contract's live span")
    if _window_overlaps(contract["id"], start, end, exclude_id):
        raise err(ERR_VALIDATION_WINDOW_OVERLAP,
                  "the window overlaps an existing OPEN or EXTENDED window")


def create_period(data):
    contract_id = data.get("contract_id")
    if contract_id is None:
        raise err(ERR_CONTRACT_NOT_FOUND, "contract_id is required")
    contract = get(contract_id)

    expected = data.get("expected_contract_version")
    if expected is None:
        raise err(ERR_INVALID_REQUEST, "expected_contract_version is required")
    if expected != contract["version"]:
        raise err(ERR_STALE_VERSION,
                  "the contract version has advanced since it was observed")

    if contract["contract_status"] not in ("ACTIVE_TRAINING", "VALIDATING"):
        if contract["contract_status"] == "TERMINATED":
            raise err(ERR_ALREADY_TERMINAL, "the contract is terminated")
        raise err(ERR_INVALID_STATE,
                  "the contract is not ACTIVE_TRAINING or VALIDATING")

    from middleware import require_fields
    require_fields(data, ["period_number", "start_date", "end_date",
                          "required_production_cents"])
    start = parse_dt(data.get("start_date"))
    end = parse_dt(data.get("end_date"))
    _validate_window(contract, start, end)

    period = {
        "contract_id": contract_id,
        "advisor_id": contract["advisor_id"],
        "period_number": data.get("period_number"),
        "start_date": start,
        "end_date": end,
        "required_production_cents": int(data.get("required_production_cents") or 0),
        "achieved_production_cents": 0,
        "extension_count": 0,
        "extended_end_date": None,
        "evaluated_at": None,
        "status": "OPEN",
    }
    db.stamp_create(period)
    db.insert(db.validation_periods, period)

    contract["contract_status"] = "VALIDATING"
    db.touch(contract)
    advisor = db.advisors.get(contract["advisor_id"])
    if advisor is not None:
        advisor["contract_status"] = "VALIDATING"
        advisor["validation_posture"] = "VALIDATING"
        db.touch(advisor)
    derived.recompute_team_production(contract["advisor_id"])
    return period


def attained_production(period):
    """§1.3 validation_production_attainment: half-open window; PRIMARY,
    SPLIT_LEAD, SPLIT_SUPPORT and RENEWAL credits with status ACCRUED, PAID or
    CHARGED_BACK. OVERRIDE_* and TRAINING_ALLOWANCE rows are excluded."""
    total = 0
    for credit in sorted(db.credits.values(), key=lambda c: (c.get("created_at") or "", c["id"])):
        if credit["advisor_id"] != period["advisor_id"]:
            continue
        if credit["credit_type"] not in derived.ATTAINMENT_CHANNELS:
            continue
        if credit["status"] not in derived.LIVE_ATTAINMENT_STATUSES:
            continue
        created = parse_dt(credit["created_at"])
        if created >= period["start_date"] and created < period["end_date"]:
            total += int(credit["gross_commission_cents"])
    return total


def evaluate_period(period):
    if period["status"] not in ("OPEN", "EXTENDED"):
        raise err(ERR_NO_OPEN_VALIDATION_WINDOW,
                  "the window is not OPEN or EXTENDED")
    contract = get(period["contract_id"])
    if period["status"] == "OPEN" and contract["contract_status"] != "VALIDATING":
        raise err(ERR_NO_OPEN_VALIDATION_WINDOW,
                  "the contract has no OPEN validation window")
    if contract["contract_status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the contract is terminated")

    achieved = attained_production(period)
    period["achieved_production_cents"] = achieved
    required = int(period["required_production_cents"])

    if achieved >= required:
        _pass(period, contract)
        return period

    if period["status"] == "EXTENDED":
        # Re-evaluated after the extension and still short: back to OPEN.
        period["status"] = "OPEN"
        period["evaluated_at"] = ts(db.now())
        db.touch(period)
        return period

    if period["extension_count"] >= calc.MAX_EXTENSIONS:
        raise err(ERR_INVALID_STATE,
                  "a window at the extension limit cannot be failed")
    period["status"] = "FAILED"
    period["extension_count"] = period["extension_count"] + 1
    period["evaluated_at"] = ts(db.now())
    db.touch(period)
    contract["contract_status"] = "AT_RISK"
    db.touch(contract)
    advisor = db.advisors.get(period["advisor_id"])
    if advisor is not None:
        advisor["contract_status"] = "AT_RISK"
        advisor["validation_posture"] = "AT_RISK"
        advisor["orphan_pool_access"] = False
        db.touch(advisor)
    return period


def _pass(period, contract):
    period["status"] = "PASSED"
    period["evaluated_at"] = ts(db.now())
    db.touch(period)
    contract["contract_status"] = "VALIDATED"
    db.touch(contract)
    advisor = db.advisors.get(period["advisor_id"])
    if advisor is not None:
        advisor["contract_status"] = "VALIDATED"
        advisor["validation_posture"] = "VALIDATED"
        advisor["orphan_pool_access"] = True
        db.touch(advisor)
        # Depth one: ACCRUED credits of this advisor are recomputed now that the
        # post-validation branch applies.
        for credit in db.credits.values():
            if credit["advisor_id"] == advisor["id"] and credit["status"] == "ACCRUED":
                derived.refresh_credit_amounts(credit)
                db.touch(credit)
    derived.cascade_rollups()


def extend_period(period, new_end_date):
    if period["status"] == "FAILED":
        raise err(ERR_ALREADY_TERMINAL, "the window has already failed")
    # PRD §3.4: "Once a window is EXTENDED, evaluating it ... returns the window
    # to OPEN when it is still short of its requirement." An EXTENDED window is
    # therefore itself extendable again.
    if period["status"] not in ("OPEN", "EXTENDED"):
        raise err(ERR_INVALID_STATE, "only an OPEN window may be extended")
    if period["extension_count"] >= calc.MAX_EXTENSIONS:
        raise err(ERR_EXTENSION_LIMIT_REACHED,
                  "the window has reached the extension limit")
    if int(period["achieved_production_cents"]) >= int(period["required_production_cents"]):
        raise err(ERR_INVALID_STATE,
                  "a window that has met its requirement may not be extended")
    contract = get(period["contract_id"])
    end = parse_dt(new_end_date)
    _validate_window(contract, period["start_date"], end, exclude_id=period["id"])
    period["extended_end_date"] = end
    period["end_date"] = end
    period["extension_count"] = period["extension_count"] + 1
    period["status"] = "EXTENDED"
    db.touch(period)
    return period