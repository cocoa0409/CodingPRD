"""Participants: manufacturers, test labs and retailers (PRD 3.2, 3.5, 3.8)."""

from flask import Blueprint

import calc
import cascades
import lookups
import serialize
import store
import validation as v
from auth import (
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    PROGRAM_ADMINISTRATOR,
    RETAILER,
    TEST_LAB_OPERATOR,
    caller,
    own,
)
from envelope import created, ok
from store import base_row

bp = Blueprint("participants", __name__)

ENTERPRISE_CLASSES = ("SMALL", "LARGE")
ACCREDITATION_STATUSES = ("ACCREDITED", "PROBATION", "REVOKED")


@bp.post("/labeling/manufacturers")
def create_manufacturer():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    legal_name = v.field_str(body, "legal_name", max_len=200)
    contact_email = v.field_str(body, "contact_email", max_len=320)
    enterprise_class = v.field_enum(body, "enterprise_class", ENTERPRISE_CLASSES)
    annual_us_revenue_cents = v.field_int(body, "annual_us_revenue_cents", minimum=0)

    lookups.unique_or_reject(store.manufacturers, "legal_name", legal_name)

    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "enterprise_class": enterprise_class,
            "annual_us_revenue_cents": annual_us_revenue_cents,
            # Enrolment initialises the penalty ledger explicitly.
            "standing": "GOOD",
            "outstanding_penalty_cents": 0,
            "paid_penalty_cents": 0,
            "vacated_penalty_cents": 0,
            "total_assessed_penalty_cents": 0,
            "upheld_case_count": 0,
        }
    )
    store.manufacturers[row["id"]] = row
    return created(serialize.manufacturer(row))


@bp.get("/labeling/manufacturers/<identifier>")
def read_manufacturer(identifier):
    caller(PROGRAM_ADMINISTRATOR, CONFORMITY_REVIEWER, MANUFACTURER)
    return ok(serialize.manufacturer(lookups.need_manufacturer(identifier)))


@bp.post("/labeling/test-labs")
def create_test_lab():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    lab_name = v.field_str(body, "lab_name", max_len=200)
    accreditation_status = v.field_enum(body, "accreditation_status", ACCREDITATION_STATUSES)
    total_bench_hours = v.field_int(body, "total_bench_hours", minimum=1)
    concurrent_bench_capacity = v.field_int(body, "concurrent_bench_capacity", minimum=1)

    lookups.unique_or_reject(store.test_labs, "lab_name", lab_name)

    row = base_row()
    row.update(
        {
            "lab_name": lab_name,
            "accreditation_status": accreditation_status,
            "total_bench_hours": total_bench_hours,
            "concurrent_bench_capacity": concurrent_bench_capacity,
            "reserved_bench_hours": 0,
            "available_bench_hours": total_bench_hours,
        }
    )
    store.test_labs[row["id"]] = row
    return created(serialize.test_lab(row))


@bp.get("/labeling/test-labs/<identifier>")
def read_test_lab(identifier):
    caller(PROGRAM_ADMINISTRATOR, CONFORMITY_REVIEWER, TEST_LAB_OPERATOR, MANUFACTURER)
    return ok(serialize.test_lab(lookups.need_lab(identifier)))


@bp.post("/labeling/retailers")
def create_retailer():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    retailer_name = v.field_str(body, "retailer_name", max_len=200)
    lookups.unique_or_reject(store.retailers, "retailer_name", retailer_name)

    row = base_row()
    row.update(
        {
            "retailer_name": retailer_name,
            "education_materials_ack": False,
            "education_program_version": None,
            "active_display_count": 0,
            "participation_tier": "BASELINE",
        }
    )
    store.retailers[row["id"]] = row
    return created(serialize.retailer(row))


@bp.get("/labeling/retailers/<identifier>")
def read_retailer(identifier):
    caller(PROGRAM_ADMINISTRATOR, RETAILER, MANUFACTURER)
    return ok(serialize.retailer(lookups.need_retailer(identifier)))


@bp.post("/labeling/retailers/<identifier>/education-ack")
def acknowledge_education(identifier):
    actor = caller(RETAILER)
    # Ownership (rung 3) is directly comparable here and precedes existence.
    own(identifier == actor.user_id)
    retailer = lookups.need_retailer(identifier)

    body = v.raw_body()
    education_program_version = v.field_str(body, "education_program_version", max_len=64)

    count = len(
        [
            auth
            for auth in store.authorizations_of_retailer(retailer["id"])
            if auth["status"] == "AUTHORIZED"
        ]
    )
    cascades.apply_changes(
        retailer,
        {
            "education_materials_ack": True,
            "education_program_version": education_program_version,
            "active_display_count": count,
            "participation_tier": calc.retailer_participation_tier(True, count),
        },
    )
    return created(serialize.retailer(retailer))
