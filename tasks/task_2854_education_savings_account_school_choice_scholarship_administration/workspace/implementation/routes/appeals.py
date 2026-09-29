"""Appeals against a denial, a clawback or a delisting, and their cascades."""
from flask import Blueprint

import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail, invalid
from routes.misuse_cases import append_clawback_entry
from store import by_seq, new_id, store
from validators import (APPEAL_STATUSES, APPEAL_SUBJECT_TYPES, authenticate,
                        body, paginate, q_enum, q_str, v_enum, v_str)

bp = Blueprint("appeals", __name__)

READ_ROLES = ("ProgramAdmin", "AppealsOfficer", "ComplianceOfficer",
              "EligibilityOfficer", "Guardian", "Provider")
APPEAL_ROUND_CAP = 2
DELISTING_OVERTURNED_REASON = "DELISTING_OVERTURNED_ON_APPEAL"


@bp.post("/appeals")
def create_appeal():
    user_id, _role = authenticate("Guardian", "Provider")
    payload = body()
    subject_type = v_enum(payload, "subject_type", APPEAL_SUBJECT_TYPES)
    grounds = v_str(payload, "grounds")
    application_id = v_str(payload, "application_id", required=False, default=None)
    misuse_case_id = v_str(payload, "misuse_case_id", required=False, default=None)
    provider_id = v_str(payload, "provider_id", required=False, default=None)

    required = {
        "APPLICATION_DENIAL": "application_id",
        "CLAWBACK": "misuse_case_id",
        "PROVIDER_DELISTING": "provider_id",
    }[subject_type]
    supplied = {
        "application_id": application_id,
        "misuse_case_id": misuse_case_id,
        "provider_id": provider_id,
    }
    if supplied[required] is None:
        invalid("%s is required when subject_type is %s" % (required, subject_type))
    for field, value in supplied.items():
        if field != required and value is not None:
            invalid("%s must be null when subject_type is %s"
                    % (field, subject_type))

    app = lookups.application(application_id) if application_id else None
    prov = lookups.provider(provider_id) if provider_id else None
    case = lookups.misuse_case(misuse_case_id) if misuse_case_id else None

    if subject_type == "APPLICATION_DENIAL":
        if app["student_id"] != user_id:
            fail("ERR_NOT_ACCOUNT_HOLDER",
                 "only the guardian behind this application may appeal")
    elif subject_type == "CLAWBACK":
        acct = store.accounts.get(case["account_id"])
        owner_app = store.applications.get(acct["application_id"]) if acct else None
        if owner_app is None or owner_app["student_id"] != user_id:
            fail("ERR_NOT_ACCOUNT_HOLDER",
                 "only the guardian behind this account may appeal the clawback")
    else:
        if prov["id"] != user_id:
            fail("ERR_NOT_ASSIGNED_PROVIDER",
                 "a provider may only appeal its own delisting")

    if subject_type == "APPLICATION_DENIAL":
        if app["status"] != "DENIED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a DENIED application may be appealed")
        if app["appeal_round_count"] >= APPEAL_ROUND_CAP:
            fail("ERR_APPEAL_ROUNDS_EXHAUSTED",
                 "the application has exhausted its appeal rounds")
        app["appeal_round_count"] += 1
        app["status"] = "UNDER_APPEAL"
        touch(app)
        round_number = app["appeal_round_count"]
    elif subject_type == "CLAWBACK":
        if case["status"] != "CLAWBACK_ISSUED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a CLAWBACK_ISSUED case may be appealed")
        round_number = len(lookups.appeals_of_subject("misuse_case_id",
                                                     case["id"])) + 1
        case["status"] = "UNDER_APPEAL"
        touch(case)
    else:
        if prov["status"] != "DELISTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a DELISTED provider may appeal")
        round_number = len(lookups.appeals_of_subject("provider_id",
                                                     prov["id"])) + 1

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "subject_type": subject_type,
        "application_id": application_id,
        "misuse_case_id": misuse_case_id,
        "provider_id": provider_id,
        "grounds": grounds,
        "status": "FILED",
        "filed_by_user_id": user_id,
        "decided_by_user_id": None,
        "rationale": None,
        "round_number": round_number,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.appeals[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/appeals/<apid>")
def read_appeal(apid):
    authenticate(*READ_ROLES)
    return object_response(public(lookups.appeal(apid)))


@bp.get("/appeals")
def list_appeals():
    authenticate(*READ_ROLES)
    application_id = q_str("application_id")
    misuse_case_id = q_str("misuse_case_id")
    provider_id = q_str("provider_id")
    subject_type = q_enum("subject_type", APPEAL_SUBJECT_TYPES)
    status = q_enum("status", APPEAL_STATUSES)
    rows = by_seq(list(store.appeals.values()))
    if application_id:
        rows = [a for a in rows if a["application_id"] == application_id]
    if misuse_case_id:
        rows = [a for a in rows if a["misuse_case_id"] == misuse_case_id]
    if provider_id:
        rows = [a for a in rows if a["provider_id"] == provider_id]
    if subject_type:
        rows = [a for a in rows if a["subject_type"] == subject_type]
    if status:
        rows = [a for a in rows if a["status"] == status]
    page, meta = paginate(rows)
    return list_response([public(a) for a in page], meta)


@bp.post("/appeals/<apid>/decision")
def decide_appeal(apid):
    user_id, _role = authenticate("AppealsOfficer")
    payload = body()
    decision = v_enum(payload, "decision", ("OVERTURNED", "UPHELD"))
    rationale = v_str(payload, "rationale")
    appeal = lookups.appeal(apid)
    if appeal["status"] != "FILED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a FILED appeal may be decided")

    subject_type = appeal["subject_type"]
    app = store.applications.get(appeal["application_id"] or "")
    case = store.misuse_cases.get(appeal["misuse_case_id"] or "")
    prov = store.providers.get(appeal["provider_id"] or "")

    # Segregation of duties is subject-specific (PRD 3.9).
    if subject_type == "APPLICATION_DENIAL" and app is not None:
        latest = lookups.latest_determination(app["id"])
        if latest is not None and latest["decided_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the officer who determined eligibility may not decide the appeal")
    elif subject_type == "CLAWBACK" and case is not None:
        if case.get("adjudicated_by_user_id") == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the officer who adjudicated the case may not decide the appeal")

    appeal["status"] = decision
    appeal["decided_by_user_id"] = user_id
    appeal["rationale"] = rationale
    touch(appeal)

    if decision == "OVERTURNED":
        if subject_type == "APPLICATION_DENIAL" and app is not None:
            app["status"] = "SUBMITTED"
            app["verified_income_band"] = None
            app["verified_category_flags"] = []
            app["annual_award_cents"] = 0
            app["priority_tier"] = 0
            app["priority_score"] = 0
            touch(app)
        elif subject_type == "CLAWBACK" and case is not None:
            acct = store.accounts.get(case["account_id"])
            debit = case.get("account_debit_cents") or 0
            case["status"] = "REVERSED"
            case["receivable_cents"] = 0
            touch(case)
            if acct is not None:
                append_clawback_entry(case, acct["id"], "REVERSAL", debit,
                                      "system")
                acct["balance_cents"] += debit
                acct["lifetime_clawed_back_cents"] -= debit
                touch(acct)
                if (acct["status"] == "SUSPENDED"
                        and not cascades.account_has_live_case(acct["id"])):
                    acct["status"] = "ACTIVE"
                    acct["suspension_reason"] = None
                    touch(acct)
        elif subject_type == "PROVIDER_DELISTING" and prov is not None:
            prov["status"] = "PROBATION"
            prov["sanction_reason"] = DELISTING_OVERTURNED_REASON
            touch(prov)
    else:
        if subject_type == "APPLICATION_DENIAL" and app is not None:
            app["status"] = "DENIED_FINAL"
            touch(app)
        elif subject_type == "CLAWBACK" and case is not None:
            case["status"] = "RESOLVED"
            touch(case)
        elif subject_type == "PROVIDER_DELISTING" and prov is not None:
            prov["status"] = "PERMANENTLY_BARRED"
            touch(prov)

    return object_response(public(appeal))
