"""Dispute adjudication and the retroactive corrections it produces
(PRD section 3.9)."""
import clock
import constants
import db
import money
import queries
from errors import ApiError
from services import load_pay


def reference_instant(dispute):
    """The instant the 30-day filing window is measured from."""
    if dispute["dispute_kind"] == "MILEAGE":
        load = db.loads.get(dispute["load_id"])
        if load is not None and load.get("settlement_id") is None:
            return load.get("delivered_at")
        origin = db.settlements.get(load["settlement_id"]) if load is not None else None
        return _settlement_instant(origin)
    origin = db.settlements.get(dispute["settlement_id"])
    return _settlement_instant(origin)


def _settlement_instant(settlement):
    if settlement is None:
        return None
    for field in ("paid_at", "approved_at", "prepared_at", "created_at"):
        if settlement.get(field) is not None:
            return settlement[field]
    return None


def origin_per_diem_method(dispute, load):
    """The per diem method of the ORIGIN package, never the current one."""
    package_id = None
    if load is not None:
        package_id = load.get("pay_package_id_snapshot")
    else:
        origin = db.settlements.get(dispute.get("settlement_id"))
        if origin is not None:
            for line in queries.lines_of(origin["id"]):
                if line["reference_type"] != "LOAD":
                    continue
                origin_load = db.loads.get(line["reference_id"])
                if origin_load is not None and origin_load.get("pay_package_id_snapshot"):
                    package_id = origin_load["pay_package_id_snapshot"]
                    break
        if package_id is None:
            driver = db.drivers.get(dispute["driver_id"])
            package_id = driver.get("pay_package_id") if driver else None
    package = db.pay_packages.get(package_id)
    return package["per_diem_method"] if package else "NONE"


def taxable_delta(delta_gross_cents, per_diem_method):
    """Signed; the magnitude is rounded and the sign re-applied."""
    if per_diem_method != "PERCENT_OF_LINEHAUL":
        return delta_gross_cents
    return delta_gross_cents - money.bps(delta_gross_cents, constants.PER_DIEM_PCT_BPS)


def create_correction(
    driver,
    origin_settlement_id,
    source_load_id,
    source_dispute_id,
    correction_type,
    reason_code,
    delta_gross_cents,
    delta_taxable_cents,
):
    correction = {
        "driver_id": driver["id"],
        "origin_settlement_id": origin_settlement_id,
        "applied_settlement_id": None,
        "source_load_id": source_load_id,
        "source_dispute_id": source_dispute_id,
        "correction_type": correction_type,
        "delta_gross_cents": delta_gross_cents,
        "delta_taxable_cents": delta_taxable_cents,
        "reason_code": reason_code,
        "status": "PENDING",
        "applied_at": None,
        "cancelled_at": None,
        "cancelled_by_user_id": None,
    }
    db.stamp_new(correction)
    db.retro_corrections[correction["id"]] = correction
    return correction


def origin_linehaul_amount(load):
    """The amount of the single linehaul line on the origin settlement for this load."""
    settlement_id = load.get("settlement_id")
    if settlement_id is None:
        return 0
    for line in queries.lines_of(settlement_id):
        if line["line_type"] not in ("LINEHAUL_PER_MILE", "LINEHAUL_PERCENT"):
            continue
        if line["reference_id"] == load["id"]:
            return line["amount_cents"]
    return 0


def deny(dispute, resolution_note, user_id):
    dispute["status"] = "DENIED"
    dispute["resolution_note"] = resolution_note
    dispute["resolved_by_user_id"] = user_id
    dispute["adjustment_cents"] = None
    db.touch(dispute)
    return dispute


def uphold(dispute, resolution_note, user_id):
    driver = db.drivers.get(dispute["driver_id"])
    dispute["resolution_note"] = resolution_note
    dispute["resolved_by_user_id"] = user_id
    dispute["status"] = "UPHELD"

    if dispute["dispute_kind"] == "MILEAGE":
        load = db.loads.get(dispute["load_id"])
        if load["pay_status"] == "ACCRUED":
            # Branch A: the load has not been paid, so it is re-graded in place.
            old_amount = load["linehaul_pay_cents"] or 0
            load_pay.recompute(load, dispute["claimed_guide"], dispute["claimed_miles"])
            db.touch(load)
            dispute["adjustment_cents"] = (load["linehaul_pay_cents"] or 0) - old_amount
            dispute["resolution_correction_id"] = None
            db.touch(dispute)
            return dispute

        if load["pay_status"] != "SETTLED":
            raise ApiError("ERR_LOAD_ALREADY_SETTLED")

        # Branch B: the money has gone out, so a correction carries the re-grade.
        origin_settlement_id = load["settlement_id"]
        old_amount = origin_linehaul_amount(load)
        load_pay.recompute(load, dispute["claimed_guide"], dispute["claimed_miles"])
        load["pay_status"] = "ADJUSTED"
        db.touch(load)
        delta_gross = (load["linehaul_pay_cents"] or 0) - old_amount
        correction = create_correction(
            driver,
            origin_settlement_id,
            load["id"],
            dispute["id"],
            "MILEAGE_REGRADE",
            "MILEAGE_DISPUTE_UPHELD",
            delta_gross,
            taxable_delta(delta_gross, origin_per_diem_method(dispute, load)),
        )
        db.touch(driver)
        dispute["adjustment_cents"] = delta_gross
        dispute["resolution_correction_id"] = correction["id"]
        db.touch(dispute)
        return dispute

    # Branch C: a pay dispute against an approved or paid statement.
    origin = db.settlements.get(dispute["settlement_id"])
    if origin["status"] not in ("APPROVED", "PAID"):
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    delta_gross = dispute["claimed_amount_cents"]
    correction = create_correction(
        driver,
        dispute["settlement_id"],
        None,
        dispute["id"],
        "PAY_ADJUSTMENT",
        "PAY_DISPUTE_UPHELD",
        delta_gross,
        taxable_delta(delta_gross, origin_per_diem_method(dispute, None)),
    )
    db.touch(driver)
    dispute["adjustment_cents"] = delta_gross
    dispute["resolution_correction_id"] = correction["id"]
    db.touch(dispute)
    return dispute


def cancel_correction(correction, user_id):
    correction["status"] = "CANCELLED"
    correction["cancelled_at"] = clock.now()
    correction["cancelled_by_user_id"] = user_id
    db.touch(correction)

    if correction["source_load_id"]:
        load = db.loads.get(correction["source_load_id"])
        if load is not None and load["pay_status"] == "ADJUSTED":
            # The money movement is abandoned; the re-graded figures stay put.
            load["pay_status"] = "SETTLED"
            db.touch(load)

    driver = db.drivers.get(correction["driver_id"])
    if driver is not None:
        db.touch(driver)
    return correction
