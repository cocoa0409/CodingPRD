"""Household registration (PRD section 3.7)."""
from __future__ import annotations

from flask import Blueprint

import serializers
from db import mark_created, new_record, store
from errors import ApiError
from middleware import endpoint
from response import created
from validation import bad, body, req_enum, req_int, req_str

bp = Blueprint("households", __name__)

APPLICANT_NAME_MAX = 120
MIN_HOUSEHOLD_SIZE = 1
MAX_HOUSEHOLD_SIZE = 8
CREDIT_TIERS = ("A", "B", "C")


@bp.post("/households")
@endpoint("LeasingAgent")
def register_household():
    payload = body()
    name = req_str(payload, "primary_applicant_name", 1, APPLICANT_NAME_MAX)
    email = req_str(payload, "email", 1)
    if "@" not in email:
        raise bad("email must contain an at-sign")
    household_size = req_int(payload, "household_size", MIN_HOUSEHOLD_SIZE, MAX_HOUSEHOLD_SIZE)
    monthly_income_cents = req_int(payload, "monthly_income_cents", minimum=0)
    credit_tier = req_enum(payload, "credit_tier", CREDIT_TIERS)

    for existing in store.households.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "email must be unique across households")

    household = new_record("Household", {
        "primary_applicant_name": name,
        "email": email,
        "household_size": household_size,
        "monthly_income_cents": monthly_income_cents,
        "credit_tier": credit_tier,
        "active_lease_count": 0,
    })
    store.households[household["id"]] = household
    mark_created(household)
    return created(serializers.household, household)
