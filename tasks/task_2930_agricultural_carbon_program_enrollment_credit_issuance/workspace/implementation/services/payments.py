"""Grower payment accrual (section 3.9)."""

from decimal import Decimal

import db
from services import calc, common


def _create(enrollment, crop_year, credit_batch_id, payable_acres, gross_cents):
    holdback_percentage = calc.holdback_pct(enrollment, db.current_crop_year())
    holdback_cents, net_cents = calc.settle_payment(gross_cents, holdback_percentage)
    row = db.common_fields()
    row.update({
        "enrollment_id": enrollment["id"],
        "credit_batch_id": credit_batch_id,
        "crop_year": crop_year,
        "payment_model": enrollment["payment_model"],
        "payable_acres": payable_acres,
        "gross_amount_cents": gross_cents,
        "holdback_pct": holdback_percentage,
        "holdback_cents": holdback_cents,
        "net_amount_cents": net_cents,
        "status": "ACCRUED",
        "paid_at": None,
    })
    db.grower_payments[row["id"]] = row
    common.add_accrual(enrollment, net_cents)
    return row


def accrue_per_acre(enrollment, crop_year):
    payable_acres = Decimal(enrollment["enrolled_acres"])
    gross = calc.per_acre_gross_cents(payable_acres, enrollment["per_acre_rate_cents"])
    return _create(enrollment, crop_year, None, payable_acres, gross)


def accrue_per_credit(enrollment, batch):
    gross = calc.per_credit_gross_cents(
        batch["issued_credits"], enrollment["per_credit_share_pct"]
    )
    return _create(enrollment, batch["vintage_year"], batch["id"], None, gross)


def duplicate_accrual_exists(enrollment_id, crop_year, payment_model):
    for payment in db.grower_payments.values():
        if (
            payment["enrollment_id"] == enrollment_id
            and payment["crop_year"] == crop_year
            and payment["payment_model"] == payment_model
            and payment["status"] == "ACCRUED"
        ):
            return True
    return False
