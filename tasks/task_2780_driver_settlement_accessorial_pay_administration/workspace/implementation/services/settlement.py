"""Settlement preparation, approval, payment and the compensating void
(PRD sections 3.6, 3.7 and 3.8)."""
import clock
import constants
import db
import money
import queries
from errors import ApiError
from services import accessorial as accessorial_service
from services import escrow as escrow_service
from services import load_pay


# ---------------------------------------------------------------------------
# period accrual
# ---------------------------------------------------------------------------
def eligible_loads(settlement):
    """Loads belonging to the half-open period, in delivered_at ascending order."""
    rows = []
    for load in db.loads.values():
        if load["driver_id"] != settlement["driver_id"]:
            continue
        if load["movement_status"] != "DELIVERED":
            continue
        if load["pay_status"] != "ACCRUED":
            continue
        if load["settlement_id"] is not None:
            continue
        delivered_at = load["delivered_at"]
        if delivered_at is None:
            continue
        if delivered_at < settlement["period_start"]:
            continue
        if delivered_at >= settlement["period_end"]:
            continue
        rows.append(load)
    return sorted(rows, key=lambda l: (l["delivered_at"], l["created_at"], l["_seq"]))


def eligible_claims(settlement):
    """Approved claims whose end_at falls in the same half-open window."""
    rows = []
    for claim in db.accessorial_claims.values():
        if claim["driver_id"] != settlement["driver_id"]:
            continue
        if claim["status"] != "APPROVED":
            continue
        if claim["settlement_id"] is not None:
            continue
        end_at = claim["end_at"]
        if end_at < settlement["period_start"]:
            continue
        if end_at >= settlement["period_end"]:
            continue
        rows.append(claim)
    return sorted(rows, key=lambda c: (c["end_at"], c["created_at"], c["_seq"]))


def _new_line(settlement_id, line_type, reference_type, reference_id, quantity,
              rate_value, amount_cents, taxable, sequence):
    return {
        "settlement_id": settlement_id,
        "line_type": line_type,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "quantity": quantity,
        "rate_value": rate_value,
        "amount_cents": amount_cents,
        "taxable": taxable,
        "sequence": sequence,
    }


def days_out_count(loads):
    dates = set()
    for load in loads:
        start = load.get("dispatched_at")
        end = load.get("delivered_at")
        if start is None or end is None:
            continue
        dates |= accessorial_service.date_set(start, end)
    return len(dates)


# ---------------------------------------------------------------------------
# preparation
# ---------------------------------------------------------------------------
def prepare(settlement, driver, user_id):
    """Sweep the period, generate every line in the pinned order and compute
    every total.  Nothing is committed until the last gate has passed."""
    loads = eligible_loads(settlement)
    claims = eligible_claims(settlement)
    retro_lines = [l for l in queries.lines_of(settlement["id"]) if l["line_type"] == "RETRO_CORRECTION"]

    if not loads and not claims and not retro_lines:
        raise ApiError("ERR_NO_SETTLEABLE_ACTIVITY")

    if not driver.get("pay_package_id"):
        raise ApiError("ERR_DRIVER_HAS_NO_PAY_PACKAGE")

    settlement_id = settlement["id"]
    sequence = queries.max_line_sequence(settlement_id) + 1
    pending = []

    # 1. loads, in accrual order: linehaul, then hourly, then activity
    for load in loads:
        package = db.pay_packages.get(load["pay_package_id_snapshot"])
        components = queries.components_by_type(package["id"]) if package else {}
        line_type = load["linehaul_line_type"]
        if line_type in ("LINEHAUL_PER_MILE", "LINEHAUL_PERCENT"):
            quantity = load["paid_miles"] if line_type == "LINEHAUL_PER_MILE" else 1
            pending.append(
                _new_line(
                    settlement_id,
                    line_type,
                    "LOAD",
                    load["id"],
                    quantity,
                    load_pay.rate_of(components, line_type),
                    load["linehaul_pay_cents"],
                    load_pay.taxable_of(components, line_type),
                    sequence,
                )
            )
            sequence += 1
        hourly = load_pay.hourly_pay(load, components)
        if hourly > 0:
            pending.append(
                _new_line(
                    settlement_id,
                    "HOURLY",
                    "LOAD",
                    load["id"],
                    money.round2(load["hours_worked_minutes"], 60),
                    load_pay.rate_of(components, "HOURLY"),
                    hourly,
                    load_pay.taxable_of(components, "HOURLY"),
                    sequence,
                )
            )
            sequence += 1
        if components.get("ACTIVITY") is not None:
            pending.append(
                _new_line(
                    settlement_id,
                    "ACTIVITY",
                    "LOAD",
                    load["id"],
                    1,
                    load_pay.rate_of(components, "ACTIVITY"),
                    load_pay.activity_pay(components),
                    load_pay.taxable_of(components, "ACTIVITY"),
                    sequence,
                )
            )
            sequence += 1

    # 2. approved claims, in accrual order
    for claim in claims:
        pending.append(
            _new_line(
                settlement_id,
                "ACCESSORIAL",
                "ACCESSORIAL_CLAIM",
                claim["id"],
                claim["billable_units"],
                None,
                claim["amount_cents"],
                True,
                sequence,
            )
        )
        sequence += 1

    # 3. statement header totals
    all_lines = retro_lines + pending
    linehaul_total = sum(
        l["amount_cents"] for l in all_lines if l["line_type"] in constants.LINEHAUL_TOTAL_LINE_TYPES
    )
    accessorial_total = sum(
        l["amount_cents"] for l in all_lines if l["line_type"] == "ACCESSORIAL"
    )
    retro_total = sum(
        l["amount_cents"] for l in all_lines if l["line_type"] == "RETRO_CORRECTION"
    )
    gross = linehaul_total + accessorial_total + retro_total

    # 4. per diem allocation
    out_days = days_out_count(loads)
    package = db.pay_packages.get(driver.get("pay_package_id"))
    method = package["per_diem_method"] if package else "NONE"
    if not driver.get("per_diem_elected") or method == "NONE":
        per_diem_non_taxable = 0
        per_diem_excess = 0
    else:
        if method == "DAY_BASED":
            gross_per_diem = out_days * constants.PER_DIEM_DAILY_CENTS
        else:
            gross_per_diem = money.bps(linehaul_total, constants.PER_DIEM_PCT_BPS)
        cap = money.bps(gross, constants.PER_DIEM_MAX_PCT_OF_GROSS_BPS)
        per_diem_non_taxable = min(gross_per_diem, cap)
        per_diem_excess = max(gross_per_diem - cap, 0)
    if per_diem_non_taxable > 0:
        pending.append(
            _new_line(
                settlement_id,
                "PER_DIEM",
                "DRIVER",
                driver["id"],
                1,
                None,
                per_diem_non_taxable,
                False,
                sequence,
            )
        )
        sequence += 1
    taxable_wages = gross - per_diem_non_taxable

    # 5. escrow accrual -- round each earning line, then sum
    escrow_deduction = 0
    if driver.get("escrow_status") == "COLLECTING":
        accrual_lines = sorted(
            [l for l in all_lines if l["line_type"] in constants.LINEHAUL_TOTAL_LINE_TYPES],
            key=lambda l: l["sequence"],
        )
        raw_accrual = sum(
            money.bps(l["amount_cents"], constants.ESCROW_ACCRUAL_BPS) for l in accrual_lines
        )
        headroom = (driver.get("escrow_target_cents") or 0) - queries.escrow_balance(driver["id"])
        escrow_deduction = min(
            raw_accrual, driver.get("escrow_monthly_deduction_cents") or 0, headroom
        )
        if escrow_deduction < 0:
            escrow_deduction = 0
    if escrow_deduction > 0:
        pending.append(
            _new_line(
                settlement_id,
                "ESCROW_DEDUCTION",
                "DRIVER",
                driver["id"],
                1,
                None,
                escrow_deduction,
                False,
                sequence,
            )
        )
        sequence += 1

    # 6. the advance-recovery waterfall against a capped pool
    provisional_net = gross - escrow_deduction
    pool = money.bps(provisional_net, constants.ADVANCE_RECOVERY_CAP_BPS)
    advance_recovery = 0
    for advance in queries.advances_for_waterfall(driver["id"]):
        if pool <= 0:
            break
        outstanding = queries.advance_outstanding_cents(advance)
        take = min(advance["installment_cents"], outstanding, pool)
        if take <= 0:
            continue
        pending.append(
            _new_line(
                settlement_id,
                "ADVANCE_RECOVERY",
                "ADVANCE",
                advance["id"],
                1,
                None,
                take,
                False,
                sequence,
            )
        )
        sequence += 1
        pool -= take
        advance_recovery += take

    # 7. deduction total and net pay
    deduction_total = escrow_deduction + advance_recovery
    net_pay = gross - deduction_total

    # the itemization gate, then last of all the money floor
    if settlement["itemization_required"]:
        for line in all_lines:
            if line["line_type"] not in constants.EARNING_LINE_TYPES:
                continue
            if line["reference_id"] is None or line["quantity"] is None:
                raise ApiError("ERR_ITEMIZATION_INCOMPLETE")
            if line["line_type"] == "ACCESSORIAL":
                claim = db.accessorial_claims.get(line["reference_id"])
                if claim is None or not claim.get("document_ref"):
                    raise ApiError("ERR_ITEMIZATION_INCOMPLETE")

    if net_pay < 0:
        raise ApiError("ERR_NEGATIVE_NET_PAY")

    # --- commit: nothing above this line mutated the store -----------------
    for line in pending:
        db.stamp_log(line)
        db.settlement_lines[line["id"]] = line

    settlement["status"] = "PREPARED"
    settlement["prepared_by_user_id"] = user_id
    settlement["prepared_at"] = clock.now()
    settlement["linehaul_total_cents"] = linehaul_total
    settlement["accessorial_total_cents"] = accessorial_total
    settlement["retro_correction_total_cents"] = retro_total
    settlement["gross_pay_cents"] = gross
    settlement["days_out_count"] = out_days
    settlement["per_diem_non_taxable_cents"] = per_diem_non_taxable
    settlement["per_diem_excess_taxable_cents"] = per_diem_excess
    settlement["taxable_wages_cents"] = taxable_wages
    settlement["escrow_deduction_cents"] = escrow_deduction
    settlement["advance_recovery_cents"] = advance_recovery
    settlement["deduction_total_cents"] = deduction_total
    settlement["net_pay_cents"] = net_pay
    db.touch(settlement)

    # close the swept work against this statement
    for load in loads:
        load["pay_status"] = "SETTLED"
        load["settlement_id"] = settlement_id
        db.touch(load)
    for claim in claims:
        claim["status"] = "PAID"
        claim["settlement_id"] = settlement_id
        db.touch(claim)

    return settlement


# ---------------------------------------------------------------------------
# the retroactive-correction sweep
# ---------------------------------------------------------------------------
def apply_corrections(settlement, driver):
    corrections = queries.corrections_of(driver["id"], "PENDING")
    if not corrections:
        raise ApiError("ERR_NO_PENDING_CORRECTIONS")

    settlement_id = settlement["id"]
    sequence = queries.max_line_sequence(settlement_id) + 1
    now = clock.now()
    for correction in corrections:
        line = _new_line(
            settlement_id,
            "RETRO_CORRECTION",
            "RETRO_CORRECTION",
            correction["id"],
            1,
            None,
            correction["delta_gross_cents"],
            True,
            sequence,
        )
        sequence += 1
        db.stamp_log(line)
        db.settlement_lines[line["id"]] = line
        correction["status"] = "APPLIED"
        correction["applied_at"] = now
        correction["applied_settlement_id"] = settlement_id
        db.touch(correction)

    settlement["retro_correction_total_cents"] = queries.line_total(
        settlement_id, ("RETRO_CORRECTION",)
    )
    db.touch(settlement)
    db.touch(driver)
    return settlement


# ---------------------------------------------------------------------------
# advance status axis
# ---------------------------------------------------------------------------
def _derived_advance_status(advance):
    if advance["status"] == "CANCELLED":
        return "CANCELLED"
    recovered = queries.advance_recovered_cents(advance["id"])
    outstanding = advance["amount_cents"] - recovered
    if outstanding <= 0:
        return "RECOVERED"
    if recovered > 0:
        return "RECOVERING"
    return "ISSUED"


def _settle_advance_axis(settlement_id):
    """Move every advance this settlement recovered against along its own axis."""
    seen = []
    for line in queries.lines_of(settlement_id):
        if line["line_type"] != "ADVANCE_RECOVERY":
            continue
        if line["reference_id"] in seen:
            continue
        seen.append(line["reference_id"])
    for advance_id in seen:
        advance = db.advances.get(advance_id)
        if advance is None:
            continue
        target = _derived_advance_status(advance)
        if target != advance["status"]:
            advance["status"] = target
            db.touch(advance)


def _unwind_advance_axis(advance_ids):
    """Walk RECOVERED back to RECOVERING or all the way to ISSUED after a void."""
    for advance_id in advance_ids:
        advance = db.advances.get(advance_id)
        if advance is None:
            continue
        target = _derived_advance_status(advance)
        if target != advance["status"]:
            advance["status"] = target
            db.touch(advance)


# ---------------------------------------------------------------------------
# approval, payment, void
# ---------------------------------------------------------------------------
def approve(settlement, driver, user_id):
    settlement["status"] = "APPROVED"
    settlement["approved_by_user_id"] = user_id
    settlement["approved_at"] = clock.now()
    db.touch(settlement)

    driver_bumps = 1
    escrow_line = None
    for line in queries.lines_of(settlement["id"]):
        if line["line_type"] == "ESCROW_DEDUCTION":
            escrow_line = line
            break
    if escrow_line is not None:
        escrow_service.append(
            driver,
            "DEPOSIT",
            escrow_line["amount_cents"],
            "SETTLEMENT_ACCRUAL",
            user_id,
            settlement_id=settlement["id"],
        )
        driver_bumps += escrow_service.drive_axis(driver)

    _settle_advance_axis(settlement["id"])
    db.touch(driver, bump=driver_bumps)
    return settlement


def pay(settlement, payment_reference):
    settlement["status"] = "PAID"
    settlement["paid_at"] = clock.now()
    settlement["payment_reference"] = payment_reference
    db.touch(settlement)
    return settlement


def void(settlement, driver, void_reason_code, user_id):
    previous_status = settlement["status"]
    settlement_id = settlement["id"]

    settlement["status"] = "VOIDED"
    settlement["voided_at"] = clock.now()
    settlement["void_reason_code"] = void_reason_code
    db.touch(settlement)

    if previous_status == "DRAFT":
        # Nothing else has happened yet, so the void is just those stamps.
        return settlement

    deposit = None
    if previous_status == "APPROVED":
        for entry in queries.escrow_entries_of(driver["id"]):
            if entry["settlement_id"] == settlement_id and entry["txn_type"] == "DEPOSIT":
                deposit = entry

    # every settlement line is deleted and every money field reset to 0
    touched_advance_ids = []
    for line in queries.lines_of(settlement_id):
        if line["line_type"] == "ADVANCE_RECOVERY" and line["reference_id"] not in touched_advance_ids:
            touched_advance_ids.append(line["reference_id"])
        db.settlement_lines.pop(line["id"], None)

    for field in (
        "linehaul_total_cents",
        "accessorial_total_cents",
        "retro_correction_total_cents",
        "gross_pay_cents",
        "days_out_count",
        "per_diem_non_taxable_cents",
        "per_diem_excess_taxable_cents",
        "taxable_wages_cents",
        "escrow_deduction_cents",
        "advance_recovery_cents",
        "deduction_total_cents",
        "net_pay_cents",
    ):
        settlement[field] = 0

    # swept loads return to ACCRUED, swept claims return to APPROVED
    for load in db.loads.values():
        if load["settlement_id"] == settlement_id:
            load["pay_status"] = "ACCRUED"
            load["settlement_id"] = None
            db.touch(load)
    for claim in db.accessorial_claims.values():
        if claim["settlement_id"] == settlement_id:
            claim["status"] = "APPROVED"
            claim["settlement_id"] = None
            db.touch(claim)

    _unwind_advance_axis(touched_advance_ids)

    # APPLIED corrections return to PENDING
    for correction in db.retro_corrections.values():
        if correction["applied_settlement_id"] == settlement_id and correction["status"] == "APPLIED":
            correction["status"] = "PENDING"
            correction["applied_at"] = None
            correction["applied_settlement_id"] = None
            db.touch(correction)

    if previous_status == "APPROVED":
        driver_bumps = 1
        if deposit is not None:
            escrow_service.append(
                driver,
                "REVERSAL",
                -deposit["amount_cents"],
                "SETTLEMENT_VOID",
                user_id,
                settlement_id=settlement_id,
                reverses_transaction_id=deposit["id"],
            )
            driver_bumps += escrow_service.drive_axis(driver)
        db.touch(driver, bump=driver_bumps)

    return settlement
