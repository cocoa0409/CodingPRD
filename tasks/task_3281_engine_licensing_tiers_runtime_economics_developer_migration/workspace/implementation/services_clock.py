"""Clock advance cascades: subscription/agreement expiry, invoice overdue,
commitment voiding. SUNSET cascades are triggered by the transition endpoint."""
from datetime import timedelta

from db import db
from helpers import touch, iso_date_str


def evaluate_clock_events():
    """Called when the logical clock advances (including initial set)."""
    today = db.clock.date()

    # SeatSubscription expiry
    for s in db.seat_subscriptions.values():
        if s["subscription_status"] in ("ACTIVE", "EXHAUSTED"):
            from helpers import parse_date
            end = parse_date(s["coverage_end"])
            if end is not None and today >= end:
                s["subscription_status"] = "EXPIRED"
                s["active_seats"] = 0
                s["available_seats"] = s["purchased_seats"]
                touch(s)

    # ExportAgreement expiry
    for a in db.export_agreements.values():
        if a["agreement_status"] in ("PENDING", "ACTIVE"):
            from helpers import parse_date
            end = parse_date(a["term_end"])
            if end is not None and today > end:
                a["agreement_status"] = "EXPIRED"
                touch(a)

    # Invoice overdue
    for inv in db.invoices.values():
        if (inv["assessment_status"] == "FINALIZED"
                and inv["payment_status"] == "UNPAID"
                and inv.get("due_date")):
            from helpers import parse_date
            due = parse_date(inv["due_date"])
            outstanding = inv["final_amount_cents"] - inv["paid_cents"] - inv["waived_cents"]
            if due is not None and today > due and outstanding > 0:
                inv["payment_status"] = "OVERDUE"
                touch(inv)
                proj = db.projects.get(inv["project_id"])
                if proj:
                    org = db.orgs.get(proj["org_id"])
                    if org:
                        from services_calc import compute_standing
                        compute_standing(org)

    # GrandfatherCommitment auto-void past deadline (unattested)
    for c in db.grandfather_commitments.values():
        if c["commitment_status"] == "ACTIVE" and not c.get("attested"):
            from helpers import parse_date
            deadline = parse_date(c["attestation_deadline"])
            if deadline is not None and today > deadline:
                c["commitment_status"] = "VOIDED"
                touch(c)
                proj = db.projects.get(c["project_id"])
                if proj and proj.get("pinned_policy_change_id") == c["policy_change_id"]:
                    proj["pinned_policy_change_id"] = None
                    touch(proj)
