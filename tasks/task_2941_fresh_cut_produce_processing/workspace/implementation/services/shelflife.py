"""Shelf life and code date: the PROVISIONAL and FINAL variants."""

import datetime

import db
from util import iso_date, julian_label

TEMP_DEDUCTION_DAYS = {"IN_SPEC": 0, "MARGINAL": 1, "OUT_OF_SPEC": 2}
HARVEST_LAG_GRACE_DAYS = 1
SHELF_LIFE_FLOOR_DAYS = 3
SPIN_SHORTFALL_PENALTY_DAYS = 1
APC_ELEVATED_CFU_G = 1000000
MICRO_PENALTY_DAYS = 2


def active_consumptions(run_id):
    return [
        c
        for c in db.rows("lot_consumptions")
        if c["process_run_id"] == run_id and c["status"] == "ACTIVE"
    ]


def label_for(code_date, code_date_format):
    if code_date_format == "JULIAN":
        return julian_label(code_date)
    return iso_date(code_date)


def compute(run, reference_dt, micro_penalty):
    product = db.find("products", run["product_id"])
    spec = db.find("customer_specs", run["customer_spec_id"])
    base_days = min(product["base_shelf_life_days"], spec["max_shelf_life_days_offered"])

    temp_penalty = 0
    oldest_harvest = None
    for c in active_consumptions(run["id"]):
        receipt = db.find("raw_receipts", c["raw_receipt_id"])
        if receipt is None:
            continue
        grade_days = TEMP_DEDUCTION_DAYS.get(receipt["temp_grade"], 0)
        if grade_days > temp_penalty:
            temp_penalty = grade_days
        lot = db.find("grower_lots", receipt["grower_lot_id"])
        if lot is not None:
            harvest = db.dt_of(lot, "harvest_datetime")
            if harvest is not None and (oldest_harvest is None or harvest < oldest_harvest):
                oldest_harvest = harvest

    harvest_penalty = 0
    if oldest_harvest is not None and reference_dt is not None:
        delta_seconds = int((reference_dt - oldest_harvest).total_seconds())
        elapsed_hours = delta_seconds // 3600
        lag_days = elapsed_hours // 24
        harvest_penalty = max(0, lag_days - HARVEST_LAG_GRACE_DAYS)

    spin_penalty = 0
    if run.get("spin_rpm") is not None and run["spin_rpm"] < product["min_spin_rpm"]:
        spin_penalty = SPIN_SHORTFALL_PENALTY_DAYS

    days = max(
        SHELF_LIFE_FLOOR_DAYS,
        base_days - temp_penalty - harvest_penalty - spin_penalty - micro_penalty,
    )
    code_date = reference_dt.date() + datetime.timedelta(days=days)
    return days, iso_date(code_date), label_for(code_date, spec["code_date_format"])


def micro_penalty_for(hold):
    apc = hold.get("latest_apc_cfu_g")
    if apc is not None and apc >= APC_ELEVATED_CFU_G:
        return MICRO_PENALTY_DAYS
    return 0
