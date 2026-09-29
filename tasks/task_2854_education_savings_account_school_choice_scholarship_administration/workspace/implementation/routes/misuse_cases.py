"""Misuse cases, adjudication and the clawback ledger."""
from flask import Blueprint

import calc
import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail
from store import by_seq, new_id, store
from validators import (DETECTION_RULES, MISUSE_STATUSES, authenticate, body,
                        paginate, q_enum, q_str, v_enum, v_int, v_str)

bp = Blueprint("misuse_cases", __name__)

READ_ROLES = ("ProgramAdmin", "ComplianceOfficer", "AppealsOfficer",
              "ExpenseReviewer", "Guardian")
MISUSE_SUBSTANTIATED_REASON = "MISUSE_SUBSTANTIATED"


def append_clawback_entry(case, account_id, entry_type, amount_cents, user_id):
    entry = {
        "id": new_id(),
        "misuse_case_id": case["id"],
        "account_id": account_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "created_by_user_id": user_id,
        "created_at": store.next_created_at(),
        "_seq": store.next_seq(),
    }
    store.clawback_entries[entry["id"]] = entry
    return entry


@bp.post("/misuse-cases")
def create_misuse_case():
    user_id, _role = authenticate("ComplianceOfficer")
    payload = body()
    account_id = v_str(payload, "account_id")
    detection_rule = v_enum(payload, "detection_rule", DETECTION_RULES)
    disallowed_principal_cents = v_int(payload, "disallowed_principal_cents",
                                       minimum=1)
    narrative = v_str(payload, "narrative")
    purchase_request_id = v_str(payload, "purchase_request_id", required=False,
                                default=None)
    lookups.account(account_id)
    if purchase_request_id is not None:
        lookups.purchase_request(purchase_request_id)

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "purchase_request_id": purchase_request_id,
        "detection_rule": detection_rule,
        "disallowed_principal_cents": disallowed_principal_cents,
        "narrative": narrative,
        "status": "OPEN",
        "opened_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "adjudicated_by_user_id": None,
        "penalty_rate": None,
        "penalty_cents": None,
        "clawback_total_cents": None,
        "account_debit_cents": None,
        "receivable_cents": None,
        "auto_opened": False,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.misuse_cases[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/misuse-cases/<mid>")
def read_misuse_case(mid):
    authenticate(*READ_ROLES)
    return object_response(public(lookups.misuse_case(mid)))


@bp.get("/misuse-cases")
def list_misuse_cases():
    authenticate(*READ_ROLES)
    account_id = q_str("account_id")
    purchase_request_id = q_str("purchase_request_id")
    status = q_enum("status", MISUSE_STATUSES)
    rows = by_seq(list(store.misuse_cases.values()))
    if account_id:
        rows = [c for c in rows if c["account_id"] == account_id]
    if purchase_request_id:
        rows = [c for c in rows
                if c["purchase_request_id"] == purchase_request_id]
    if status:
        rows = [c for c in rows if c["status"] == status]
    page, meta = paginate(rows)
    return list_response([public(c) for c in page], meta)


@bp.post("/misuse-cases/<mid>/review")
def review_misuse_case(mid):
    user_id, _role = authenticate("ComplianceOfficer")
    case = lookups.misuse_case(mid)
    if case["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an OPEN case may be taken under review")
    case["status"] = "UNDER_REVIEW"
    case["reviewed_by_user_id"] = user_id
    touch(case)
    return object_response(public(case))


@bp.post("/misuse-cases/<mid>/adjudication")
def adjudicate_misuse_case(mid):
    user_id, _role = authenticate("ComplianceOfficer")
    payload = body()
    outcome = v_enum(payload, "outcome", ("SUBSTANTIATED", "DISMISSED"))
    v_str(payload, "rationale")
    case = lookups.misuse_case(mid)
    if case["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an UNDER_REVIEW case may be adjudicated")

    pr = None
    if case["purchase_request_id"]:
        pr = store.purchase_requests.get(case["purchase_request_id"])

    if outcome == "DISMISSED":
        case["status"] = "DISMISSED"
        case["adjudicated_by_user_id"] = user_id
        touch(case)
        return object_response(public(case))

    if pr is not None and pr.get("approved_by_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the reviewer who approved the spend may not substantiate the case")

    case["status"] = "SUBSTANTIATED"
    case["adjudicated_by_user_id"] = user_id
    touch(case)

    acct = store.accounts.get(case["account_id"])
    if acct is not None and acct["status"] == "ACTIVE":
        cascades.suspend_account(acct, MISUSE_SUBSTANTIATED_REASON)

    if pr is not None:
        prov = store.providers.get(pr["provider_id"])
        if prov is not None:
            prov["substantiated_case_count"] += 1
            cascades.recompute_surveillance(prov)

    return object_response(public(case))


@bp.post("/misuse-cases/<mid>/clawbacks")
def issue_clawback(mid):
    user_id, _role = authenticate("ComplianceOfficer")
    case = lookups.misuse_case(mid)
    if case["status"] != "SUBSTANTIATED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a SUBSTANTIATED case may issue a clawback")
    acct = store.accounts.get(case["account_id"])
    if acct is None or acct["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "the account must be SUSPENDED to issue a clawback")

    figures = calc.clawback_assessment(case["disallowed_principal_cents"],
                                      acct["balance_cents"])
    case["penalty_rate"] = figures["penalty_rate"]
    case["penalty_cents"] = figures["penalty_cents"]
    case["clawback_total_cents"] = figures["clawback_total_cents"]
    case["account_debit_cents"] = figures["account_debit_cents"]
    case["receivable_cents"] = figures["receivable_cents"]
    case["status"] = "CLAWBACK_ISSUED"
    touch(case)

    entry_ids = [append_clawback_entry(case, acct["id"], "ACCOUNT_DEBIT",
                                       figures["account_debit_cents"],
                                       user_id)["id"]]
    if figures["receivable_cents"] > 0:
        entry_ids.append(append_clawback_entry(case, acct["id"], "RECEIVABLE",
                                               figures["receivable_cents"],
                                               user_id)["id"])

    acct["balance_cents"] -= figures["account_debit_cents"]
    acct["lifetime_clawed_back_cents"] += figures["account_debit_cents"]
    touch(acct)

    if case["purchase_request_id"]:
        pr = store.purchase_requests.get(case["purchase_request_id"])
        if pr is not None and pr["settlement_status"] == "PAID":
            pr["settlement_status"] = "REVERSED"
            acct["lifetime_spent_cents"] -= (pr["paid_amount_cents"] or 0)
            touch(pr)
            touch(acct)

    return object_response({
        "misuse_case_id": case["id"],
        "misuse_case_status": case["status"],
        "penalty_rate": figures["penalty_rate"],
        "penalty_cents": figures["penalty_cents"],
        "clawback_total_cents": figures["clawback_total_cents"],
        "account_debit_cents": figures["account_debit_cents"],
        "receivable_cents": figures["receivable_cents"],
        "account_balance_cents": acct["balance_cents"],
        "clawback_entry_ids": entry_ids,
    })


@bp.get("/misuse-cases/<mid>/clawback-entries")
def list_case_clawback_entries(mid):
    authenticate("ProgramAdmin", "ComplianceOfficer", "AppealsOfficer",
                 "Guardian")
    lookups.misuse_case(mid)
    rows = by_seq([e for e in store.clawback_entries.values()
                   if e["misuse_case_id"] == mid])
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)
