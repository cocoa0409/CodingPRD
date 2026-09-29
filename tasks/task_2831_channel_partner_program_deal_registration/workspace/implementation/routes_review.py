"""PerformanceReview endpoints: preparation, remediation and decision."""
from flask import g

import calc
import cascades
import serialize
import store
import validate as v
from auth import acting_partner_scope, endpoint
from constants import REMEDIATION_DAYS
from errors import ApiError
from guards import find, find_partner, invalid_state
from response import created, filtered, listing, object_response

_DERIVED = ("tier", "tier_status", "standing_reason", "cert_credit_total",
            "trailing_revenue_cents", "marketing_qualified_spend_cents",
            "marketing_attainment_pct", "open_conflict_count",
            "portal_entitlement_level")


def _partner_state(partner):
    return tuple(partner[name] for name in _DERIVED)


def _touch_once(partner, before_state, before_version):
    """One version bump per request even when several recomputes ran."""
    if partner["version"] != before_version:
        return
    if _partner_state(partner) != before_state:
        store.touch(partner)


def register(app):
    @app.route("/performance-reviews", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_review():
        body = v.body()
        # existence (3)
        partner_ref = v.fk_candidate(body, "partner_id")
        partner = find_partner(partner_ref) if partner_ref is not None else None
        # request shape (5)
        partner_id = v.req_string(body, "partner_id")
        period_start = v.req_instant(body, "period_start")
        period_end = v.req_instant(body, "period_end")
        v.interval(period_start, period_end, "period_start", "period_end")
        findings_count = v.opt_int(body, "findings_count", minimum=0, default=0)
        before_state = _partner_state(partner)
        before_version = partner["version"]
        # cascade E sweeps lapsed certifications before anything is scored
        cascades.cascade_e(partner)
        cert_credit, revenue, score, tier = calc.score_variant(
            partner, period_start, period_end, "PROVISIONAL")
        _touch_once(partner, before_state, before_version)
        instant = store.now()
        row = {
            "partner_id": partner_id,
            "period_start": period_start,
            "period_end": period_end,
            "findings_count": findings_count,
            "remediation_due_at": None,
            "provisional_cert_credit": cert_credit,
            "provisional_revenue_cents": revenue,
            "provisional_score": score,
            "recommended_tier": tier,
            "final_cert_credit": None,
            "final_revenue_cents": None,
            "final_score": None,
            "approved_tier": None,
            "marketing_attainment_pct": calc.q4(partner["marketing_attainment_pct"]),
            "status": "PREPARED",
            "prepared_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "remediation_note": None,
        }
        if findings_count > 0:
            # PREPARED -> FINDINGS_OPEN in the very same response
            row["status"] = "FINDINGS_OPEN"
            row["remediation_due_at"] = store.plus_days(instant, REMEDIATION_DAYS)
        store.insert("reviews", row)
        return created(serialize.review(row))

    @app.route("/performance-reviews", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_reviews():
        rows = store.ordered(store.all_rows("reviews"))
        rows = filtered(rows, [("partner_id", "partner_id"), ("status", "status")])
        return listing(rows, serialize.review)

    @app.route("/performance-reviews/<review_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_review(review_id):
        row = find("reviews", review_id)
        return object_response(serialize.review(row))

    @app.route("/performance-reviews/<review_id>/remediate", methods=["POST"])
    @endpoint("Partner")
    def remediate_review(review_id):
        review = find("reviews", review_id)
        # partner scoping (4)
        acting_partner_scope(review["partner_id"])
        body = v.body()
        note = v.req_string(body, "remediation_note")
        # state precondition (9)
        if review["status"] != "FINDINGS_OPEN":
            raise invalid_state("Only a FINDINGS_OPEN review can be remediated.")
        # audit remediation (14), against this review's own deadline
        due = review["remediation_due_at"]
        if due is not None and store.now() > due:
            raise ApiError("ERR_AUDIT_REMEDIATION_OVERDUE",
                           "The remediation deadline has passed.")
        review["status"] = "REMEDIATED"
        review["remediation_note"] = note
        store.touch(review)
        return object_response(serialize.review(review))

    @app.route("/performance-reviews/<review_id>/decision", methods=["POST"])
    @endpoint("ChannelDirector")
    def decide_review(review_id):
        review = find("reviews", review_id)
        body = v.body()
        decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
        status = review["status"]
        instant = store.now()
        # state precondition (9)
        if decision == "APPROVE":
            if status not in ("PREPARED", "REMEDIATED"):
                raise invalid_state(
                    "An approval needs a PREPARED or REMEDIATED review.")
        else:
            if status == "FINDINGS_OPEN":
                due = review["remediation_due_at"]
                if due is None or not (instant > due):
                    raise invalid_state(
                        "A FINDINGS_OPEN review is rejectable only once its "
                        "remediation deadline has passed.")
            elif status not in ("PREPARED", "REMEDIATED"):
                raise invalid_state("The review has already been decided.")
        # segregation of duties (15)
        if review["prepared_by_user_id"] is not None \
                and g.user_id == review["prepared_by_user_id"]:
            raise ApiError("ERR_SOD_SAME_ACTOR",
                           "The operator who prepared the review may not decide it.")
        partner = store.get("partners", review["partner_id"])
        before_state = _partner_state(partner)
        before_version = partner["version"]
        cert_credit, revenue, score, tier = calc.score_variant(
            partner, review["period_start"], review["period_end"], "FINAL")
        review["final_cert_credit"] = cert_credit
        review["final_revenue_cents"] = revenue
        review["final_score"] = score
        review["decided_by_user_id"] = g.user_id
        if decision == "APPROVE":
            review["status"] = "APPROVED"
            review["approved_tier"] = tier
            partner["tier"] = tier
            if not (partner["tier_status"] == "PROBATION"
                    and partner["standing_reason"] == "MARKETING_ATTAINMENT_SHORTFALL"):
                partner["tier_status"] = "COMPLIANT"
                partner["standing_reason"] = None
            calc.recompute_entitlement(partner)
        else:
            review["status"] = "REJECTED"
            partner["tier_status"] = "SUSPENDED"
            partner["standing_reason"] = "PROGRAM_REVIEW_REJECTED"
            calc.recompute_entitlement(partner)
        store.touch(review)
        _touch_once(partner, before_state, before_version)
        return object_response(serialize.review(review))
