"""The clock sweep (PRD 2.5): five effects applied against the new logical
time, in pinned order."""
import clock
import db
from services import calc, lifecycle


def run_sweep():
    now = clock.now()

    # 1. Withdrawal enforcement: PUBLISHED notices due -> EFFECTIVE with cascade
    for notice in db.sorted_items(db.withdrawal_notices):
        if notice["status"] == "PUBLISHED" and notice["effective_on"] <= now:
            notice["status"] = "EFFECTIVE"
            db.mutate(notice)
            cert = db.certifications.get(notice["certification_id"])
            if cert is not None and cert["status"] in ("ACTIVE", "SUSPENDED"):
                lifecycle.withdraw_certification(cert)

    # 2. Certification expiry: ACTIVE with expires_on <= now -> EXPIRED
    #    (SUSPENDED certifications do not expire)
    for cert in db.sorted_items(db.certifications):
        if (cert["status"] == "ACTIVE" and cert["expires_on"] is not None
                and cert["expires_on"] <= now):
            cert["status"] = "EXPIRED"
            db.mutate(cert)

    # 3. Overdue marking: SCHEDULED inspections whose scheduled_for < now
    for insp in db.sorted_items(db.inspections):
        if insp["status"] == "SCHEDULED" and insp["scheduled_for"] < now:
            insp["status"] = "OVERDUE"
            db.mutate(insp)

    # 4. Standard status refresh from effectiveness windows
    for standard in db.sorted_items(db.standards):
        derived = calc.standard_status(standard, now)
        if standard["status"] != derived:
            standard["status"] = derived
            db.mutate(standard)

    # 5. Conformity aging: STANDARD-regime factories recompute windowed score
    for factory in db.sorted_items(db.factories):
        if factory["conformity_regime"] == "STANDARD":
            lifecycle.recompute_factory(factory, event=None)
