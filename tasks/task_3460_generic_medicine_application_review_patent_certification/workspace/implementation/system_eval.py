"""System transitions: clock-driven rules and TENTATIVE_APPROVAL re-evaluation.

PRD 2.4: advancing the clock is the single trigger that re-evaluates every
time-driven rule. PRD 3.7: after every clock advance, litigation event,
certification amendment, patent expiry, or exclusivity transition, every
tentatively approved application is re-examined for full approval.
"""
from clock import add_days, add_months, parse_date, today
from domain import (
    award_for_app,
    carve_out_problem,
    exclusivity_blocked,
    patent_blocked_until,
)
from state import STORE, touch


def reevaluate_tentative_approvals():
    t = today()
    for app in list(STORE["applications"].values()):
        if app["status"] != "TENTATIVE_APPROVAL":
            continue
        if patent_blocked_until(app) is not None:
            continue
        if exclusivity_blocked(app):
            continue
        if carve_out_problem(app) is not None:
            continue  # protections drifted; holds until labeling is amended
        app["status"] = "APPROVED"
        app["approval_date"] = t.isoformat()  # tentative_approval_date retained
        award = award_for_app(app["id"])
        if award is not None and award["status"] == "ELIGIBLE":
            award["status"] = "AWARDED"
            award["awarded_date"] = t.isoformat()
            award["approval_date"] = t.isoformat()
            award["marketing_deadline"] = add_days(t, 75).isoformat()
            touch(award)
        touch(app)


def forfeit_award(award, reason):
    """ELIGIBLE|AWARDED|ACTIVE -> FORFEITED; blocking releases re-evaluate."""
    if award["status"] not in ("ELIGIBLE", "AWARDED", "ACTIVE"):
        return
    was_blocking = award["status"] in ("AWARDED", "ACTIVE")
    award["status"] = "FORFEITED"
    award["forfeiture_reason"] = reason
    touch(award)
    if was_blocking:
        # Siblings' exclusivity_blocked lifts; their tentative approvals re-run.
        reevaluate_tentative_approvals()


def on_clock_change():
    t = today()

    # Listed patents expire once the clock has moved beyond expiry_date.
    for p in STORE["patents"].values():
        if p["status"] == "LISTED" and parse_date(p["expiry_date"]) < t:
            p["status"] = "EXPIRED"
            touch(p)

    # Protected-indication windows expire beyond protected_until.
    for w in STORE["protections"].values():
        if w["status"] == "ACTIVE" and parse_date(w["protected_until"]) < t:
            w["status"] = "EXPIRED"
            touch(w)

    # Unanswered deficiency letters lapse their cycle and the application.
    for c in list(STORE["cycles"].values()):
        if (c["status"] == "CRL_ISSUED"
                and c["deficiency_response_received_date"] is None
                and c["deficiency_response_due_date"] is not None
                and t > parse_date(c["deficiency_response_due_date"])):
            c["status"] = "LAPSED"
            c["closed_reason"] = "LAPSED"
            touch(c)
            app = STORE["applications"][c["application_id"]]
            app["status"] = "LAPSED"
            touch(app)
            aw = award_for_app(app["id"])
            if aw is not None and aw["status"] == "ELIGIBLE":
                forfeit_award(aw, "APPLICATION_LAPSED")

    # Suit windows close with no suit recorded.
    for n in STORE["notices"].values():
        if n["status"] == "NOTICE_SENT" and t > parse_date(n["suit_deadline"]):
            n["status"] = "NO_SUIT_FILED"
            touch(n)

    # Litigation stays expire while no court outcome is recorded.
    for n in STORE["notices"].values():
        if (n["status"] == "SUIT_FILED" and n["court_outcome"] == "NONE"
                and n["stay_until"] and t > parse_date(n["stay_until"])):
            n["status"] = "STAY_EXPIRED"
            touch(n)

    # 30-month tentative-approval failure clock (from ELIGIBLE).
    for a in list(STORE["awards"].values()):
        if a["status"] != "ELIGIBLE":
            continue
        app = STORE["applications"][a["application_id"]]
        if app["status"] in ("TENTATIVE_APPROVAL", "APPROVED"):
            continue
        if app["received_date"] is None:
            continue
        if t > add_months(parse_date(app["received_date"]), 30):
            forfeit_award(a, "TA_NOT_OBTAINED_30MO")

    # Failure to commence marketing within 75 days (from AWARDED).
    for a in list(STORE["awards"].values()):
        if (a["status"] == "AWARDED" and a["first_marketing_date"] is None
                and a["marketing_deadline"] is not None
                and t > parse_date(a["marketing_deadline"])):
            forfeit_award(a, "MARKETING_NOT_COMMENCED_75D")

    # 180-day exclusivity expires AT exclusivity_end_date.
    for a in STORE["awards"].values():
        if (a["status"] == "ACTIVE" and a["exclusivity_end_date"]
                and t >= parse_date(a["exclusivity_end_date"])):
            a["status"] = "EXPIRED"
            touch(a)

    # CBE-30 supplements take effect on day 30 while still SUBMITTED.
    for s in STORE["supplements"].values():
        if (s["pathway"] == "CBE_30" and s["review_status"] == "SUBMITTED"
                and s["effectivity"] == "NOT_EFFECTIVE"):
            eff = add_days(parse_date(s["submitted_date"]), 30)
            if t >= eff:
                s["effectivity"] = "EFFECTIVE"
                s["effective_date"] = eff.isoformat()
                touch(s)

    # Tentative approvals convert once nothing blocks them any more.
    reevaluate_tentative_approvals()
