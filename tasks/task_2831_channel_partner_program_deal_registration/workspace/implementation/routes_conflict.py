"""ConflictCase endpoints: discovery, escalation and resolution."""
from flask import g

import calc
import serialize
import store
import validate as v
from auth import acting_partner_scope, endpoint
from constants import MAX_ESCALATION_LEVEL
from errors import ApiError
from guards import find, invalid_state
from response import filtered, listing, object_response

TERMINAL = ("RESOLVED_PARTNER", "RESOLVED_DIRECT", "RESOLVED_SPLIT")


def register(app):
    @app.route("/conflict-cases", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def list_conflicts():
        rows = store.ordered(store.all_rows("conflicts"))
        rows = filtered(rows, [("account_id", "account_id"),
                               ("subject_registration_id", "subject_registration_id"),
                               ("counter_registration_id", "counter_registration_id"),
                               ("status", "status"),
                               ("conflict_type", "conflict_type")])
        return listing(rows, serialize.conflict)

    @app.route("/conflict-cases/<case_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "DirectSalesRep", "Partner")
    def read_conflict(case_id):
        row = find("conflicts", case_id)
        return object_response(serialize.conflict(row))

    @app.route("/conflict-cases/<case_id>/escalate", methods=["POST"])
    @endpoint("Partner", "DirectSalesRep")
    def escalate_conflict(case_id):
        case = find("conflicts", case_id)
        subject = store.get("registrations", case["subject_registration_id"])
        if subject is not None:
            acting_partner_scope(subject["partner_id"])
        body = v.body()
        note = v.req_string(body, "escalation_note", non_empty=False)
        if case["status"] in TERMINAL:
            raise invalid_state("A resolved case cannot be escalated.")
        if case["escalation_level"] >= MAX_ESCALATION_LEVEL:
            # PRD 2.8 step 26: nothing whatsoever is written.
            raise ApiError("ERR_CONFLICT_ESCALATION_LIMIT",
                           "The escalation ladder is already at its top rung.")
        if g.role == "Partner":
            if case["status"] != "OPEN":
                raise invalid_state("A partner escalates only a case in OPEN.")
            case["status"] = "ESCALATED_TIER1"
            case["escalation_level"] = 1
        else:
            if case["status"] != "ESCALATED_TIER1":
                raise invalid_state(
                    "Direct sales escalates only a case in ESCALATED_TIER1.")
            case["status"] = "ESCALATED_TIER2"
            case["escalation_level"] = 2
        case["resolution_note"] = note
        store.touch(case)
        return object_response(serialize.conflict(case))

    @app.route("/conflict-cases/<case_id>/resolve", methods=["POST"])
    @endpoint("ChannelDirector")
    def resolve_conflict(case_id):
        case = find("conflicts", case_id)
        body = v.body()
        resolution = v.req_enum(body, "resolution", ("PARTNER", "DIRECT", "SPLIT"))
        note = v.req_string(body, "resolution_note")
        if case["status"] not in ("OPEN", "ESCALATED_TIER1", "ESCALATED_TIER2"):
            raise invalid_state("This case has already been resolved.")
        if resolution == "SPLIT" and case["conflict_type"] == "PARTNER_VS_DIRECT":
            raise invalid_state("A partner-versus-direct conflict cannot be split.")
        subject = store.get("registrations", case["subject_registration_id"])
        account = store.get("accounts", case["account_id"])
        partner = store.get("partners", subject["partner_id"]) if subject else None

        case["resolution_note"] = note
        case["resolved_by_user_id"] = g.user_id

        if resolution == "PARTNER":
            case["status"] = "RESOLVED_PARTNER"
            store.touch(case)
            if case["conflict_type"] == "PARTNER_VS_PARTNER":
                subject["status"] = "SUBMITTED"
                subject["closure_reason"] = None
                store.touch(subject)
            else:
                subject["closure_reason"] = None
                store.touch(subject)
                if account is not None:
                    account["direct_pursuit_owner_id"] = None
                    store.touch(account)
        elif resolution == "DIRECT":
            case["status"] = "RESOLVED_DIRECT"
            store.touch(case)
            subject["status"] = "REJECTED"
            subject["closure_reason"] = "RESOLVED_DIRECT"
            subject["registration_margin_uplift_pct"] = calc.q4("0")
            store.touch(subject)
            if account is not None:
                account["coverage_state"] = "DIRECT_LOCKED"
                account["protected_until"] = None
                account["protected_partner_id"] = None
                account["protected_product_line"] = None
                store.touch(account)
        else:
            case["status"] = "RESOLVED_SPLIT"
            store.touch(case)
            instant = store.now()
            days = calc.protection_days_for(partner["tier"], halved=True)
            subject["status"] = "APPROVED"
            subject["approved_at"] = instant
            subject["protection_days"] = days
            subject["exclusivity_start_at"] = instant
            subject["exclusivity_end_at"] = store.plus_days(instant, days)
            subject["registration_margin_uplift_pct"] = calc.q4("0.02")
            store.touch(subject)
            if account is not None:
                account["coverage_state"] = "CHANNEL_PROTECTED"
                existing = account["protected_until"]
                new_end = subject["exclusivity_end_at"]
                account["protected_until"] = (new_end if existing is None or new_end > existing
                                              else existing)
                store.touch(account)

        if partner is not None:
            calc.clear_conflict_probation(partner)
        return object_response(serialize.conflict(case))
