"""The pinned four-step clock sweep (PRD 2.4). Runs on every clock advance.

Order is contractual:
  1. SCHEDULED review cases with opened_at <= now open (inclusive).
  2. DCIs in ISSUED/RESPONDED/DEFICIENT with response_deadline < now delinquent
     (strict), firing the referral/auto-suspension cascade.
  3. ACTIVE certifications with certified_until < now expire (strict).
  4. GRANTED state registrations with renewal_due_at + 30 days < now lapse
     (strict).
"""
from datetime import timedelta

import constants
from db import sorted_rows, store, touch
from services.cascade import dci_delinquency_cascade


def run(now):
    # Step 1: open due review cases.
    for case in sorted_rows(store["review_cases"].values()):
        if case["status"] == "SCHEDULED" and case["opened_at"] <= now:
            case["status"] = "OPEN"
            touch(case)
            product = store["products"][case["product_id"]]
            if product["status"] == "REGISTERED":
                product["status"] = "UNDER_REVIEW"
                touch(product)

    # Step 2: delinquent data call-ins (strict <), firing the cascade.
    for dci in sorted_rows(store["dcis"].values()):
        if dci["status"] in ("ISSUED", "RESPONDED", "DEFICIENT") and dci["response_deadline"] < now:
            dci_delinquency_cascade(dci, now)

    # Step 3: expire applicator certifications (strict <).
    for cert in sorted_rows(store["certifications"].values()):
        if cert["status"] == "ACTIVE" and cert["certified_until"] < now:
            cert["status"] = "EXPIRED"
            touch(cert)

    # Step 4: lapse state registrations past the 30-day grace (strict <).
    for reg in sorted_rows(store["state_registrations"].values()):
        if (
            reg["status"] == "GRANTED"
            and reg["renewal_due_at"] + timedelta(days=constants.RENEWAL_GRACE_DAYS) < now
        ):
            reg["status"] = "LAPSED"
            touch(reg)
