"""Supplier scoring: on_time_ship_rate, chargeback_rate, compliance_score,
and automatic status transitions (PRD §3.7)."""
from decimal import Decimal

import clock
from db import db
from decimal_utils import round_half_up_2dp


def touch(supplier):
    supplier["updated_at"] = clock.now_str()
    supplier["version"] += 1


def _closed_drop_ship_shipments(supplier_id):
    rows = [
        s
        for s in db.shipments.values()
        if s["supplier_id"] == supplier_id
        and s["fulfillment_mode"] == "DROP_SHIP"
        and s["current_state"] == "DELIVERED"
        and s["delivered_at"] is not None
    ]
    # delivered_at DESC, tie-break created_at ASC (all timestamps are
    # fixed-width UTC ISO strings, so plain string sort is chronological).
    # Stable two-pass sort: primary delivered_at DESC, secondary created_at ASC.
    rows.sort(key=lambda s: s["created_at"])
    rows.sort(key=lambda s: s["delivered_at"], reverse=True)
    return rows


def compute_metrics(supplier_id, window="rolling"):
    shipments = _closed_drop_ship_shipments(supplier_id)
    if window == "rolling":
        shipments = shipments[:5]
    if shipments:
        on_time = sum(
            1
            for s in shipments
            if s["actual_ship_date"] is not None
            and s["promised_ship_date"] is not None
            and s["actual_ship_date"] <= s["promised_ship_date"]
        )
        on_time_rate = round_half_up_2dp(Decimal(100 * on_time) / Decimal(len(shipments)))
    else:
        on_time_rate = Decimal("100.00")

    settled = sum(
        1
        for c in db.chargebacks.values()
        if c["supplier_id"] == supplier_id and c["status"] == "SETTLED"
    )
    denominator = sum(
        1
        for s in db.shipments.values()
        if s["supplier_id"] == supplier_id and s["current_state"] != "EXCEPTION"
    )
    if denominator == 0:
        chargeback_rate = Decimal("0.00")
    else:
        chargeback_rate = round_half_up_2dp(Decimal(100 * settled) / Decimal(denominator))

    # The weighted sum consumes the already-rounded 2dp rates.
    compliance = round_half_up_2dp(
        Decimal("0.60") * on_time_rate + Decimal("0.40") * (Decimal("100") - chargeback_rate)
    )
    return {
        "on_time_ship_rate": float(on_time_rate),
        "chargeback_rate": float(chargeback_rate),
        "compliance_score": float(compliance),
    }


def recompute_supplier(supplier_id):
    supplier = db.suppliers.get(supplier_id)
    if supplier is None:
        return
    metrics = compute_metrics(supplier_id, window="rolling")
    supplier["on_time_ship_rate"] = metrics["on_time_ship_rate"]
    supplier["chargeback_rate"] = metrics["chargeback_rate"]
    supplier["compliance_score"] = metrics["compliance_score"]

    score = Decimal(str(metrics["compliance_score"]))
    status = supplier["status"]
    if status == "ACTIVE" and score < Decimal("70.00"):
        supplier["status"] = "PROBATION"
    elif status == "PROBATION":
        if score < Decimal("50.00"):
            supplier["status"] = "SUSPENDED"
        elif score >= Decimal("80.00"):
            supplier["status"] = "ACTIVE"
    # No automatic path out of SUSPENDED.
    touch(supplier)
