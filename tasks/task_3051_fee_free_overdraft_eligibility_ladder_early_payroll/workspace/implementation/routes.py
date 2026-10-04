"""All API routes under /banking. Validation priority per PRD 2.11:
auth -> role/ownership -> existence -> body -> idempotency -> OCC ->
from-state -> terminal -> posture -> abuse-lock -> qualifying -> temporal ->
overlap -> uniqueness -> referential -> fiscal.
"""
from datetime import timedelta

from flask import Blueprint

import clock
import errors
from core import (
    ROLES, ACCOUNT_TYPES, CURRENCIES, ORIGINATOR_TYPES, RETURN_CODES,
    EVENT_TYPES, DISPUTE_TYPES, EVALUATION_MODES, DISPUTE_OUTCOMES,
    MEMBER_STATUSES, ADVANCE_STATUSES, DEPOSIT_STATUSES, ADJUSTMENT_STATUSES,
    RUN_STATUSES, CASE_STATUSES, ENTRY_TYPES, ENTRY_STATUSES,
    NOTICE_DAYS, WRITE_OFF_DAYS, QUALIFYING_MIN_CENTS,
    new_id, bump, get_body, _req_str, _opt_str, _req_int, _req_enum, _req_dt,
    require_occ, paginate,
    find_member, find_account, find_deposit, find_advance, find_adjustment,
    find_run, find_dispute,
    member_of_account, member_of_deposit, member_of_advance, member_of_dispute,
    account_of_deposit, account_of_advance, _consume_provisional,
    auth, require_roles, check_member_ownership, apply_time_transitions,
    tenure_days, account_computed,
    serialize_member, serialize_account, serialize_deposit,
    serialize_early_posting, serialize_return, serialize_advance,
    serialize_allocation, serialize_profile, serialize_adjustment,
    serialize_abuse_event, serialize_ledger_entry, serialize_run,
    serialize_dispute,
    create_ledger_entry, create_advance, run_waterfall,
    compute_score, compute_ladder_limit, add_business_days,
    discrepancy_blocks,
)
from db import store
from response import success_object, success_list

bp = Blueprint("banking", __name__, url_prefix="/banking")


# ===========================================================================
# Members
# ===========================================================================
@bp.post("/members")
def create_member():
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        body = get_body()
        external_ref = _req_str(body, "external_ref", 1, 128)
        full_name = _req_str(body, "full_name", 1, 200)
        enrolled_at = _req_dt(body, "enrolled_at")
        if enrolled_at > clock.now():
            raise errors.invalid_request("enrolled_at must not be in the future.")
        for m in store.members.values():
            if m["external_ref"] == external_ref:
                raise errors.duplicate("external_ref already exists.")
        now = clock.now()
        member = {
            "id": new_id(),
            "external_ref": external_ref,
            "full_name": full_name,
            "enrolled_at": enrolled_at,
            "status": "ENROLLED",
            "current_limit_cents": 0,
            "consecutive_on_time_repayments": 0,
            "restricted_consecutive_repayments": 0,
            "deposit_reroute_flag": False,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.members[member["id"]] = member
        return success_object(serialize_member(member), 201)


@bp.get("/members")
def list_members():
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        apply_time_transitions()
        from flask import request
        status = request.args.get("status")
        items = sorted(store.members.values(), key=lambda m: m["created_at"])
        if status is not None:
            items = [m for m in items if m["status"] == status]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_member(m) for m in page], limit, offset, total)


@bp.get("/members/<mid>")
def get_member(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        member = find_member(mid)
        check_member_ownership(uid, role, member["id"])
        apply_time_transitions()
        return success_object(serialize_member(member))


@bp.post("/members/<mid>/eligibility-evaluations")
def create_evaluation(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        member = find_member(mid)
        if member["status"] == "CLOSED":
            raise errors.already_terminal("Member is CLOSED.")
        body = get_body()
        mode = _req_enum(body, "evaluation_mode", EVALUATION_MODES)
        require_occ(body, "expected_member_version", member)

        parts = compute_score(member, mode)
        score = parts["score"]
        t_days = tenure_days(member)
        computed_limit = compute_ladder_limit(
            score, member["consecutive_on_time_repayments"], t_days)
        if member["status"] == "SUSPENDED" and mode == "BATCH":
            computed_limit = 0
        delta = computed_limit - member["current_limit_cents"]
        now = clock.now()

        profile = {
            "id": new_id(),
            "member_id": member["id"],
            "evaluation_mode": mode,
            "score": score,
            "regularity_points": parts["regularity_points"],
            "tenure_points": parts["tenure_points"],
            "repayment_points": parts["repayment_points"],
            "abuse_penalty": parts["abuse_penalty"],
            "computed_limit_cents": computed_limit,
            "delta_vs_current_cents": delta,
            "status": "CURRENT",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }

        if mode == "BATCH":
            # supersede prior CURRENT BATCH profile
            for p in store.profiles.values():
                if p["member_id"] == member["id"] and p["evaluation_mode"] == "BATCH" \
                        and p["status"] == "CURRENT":
                    p["status"] = "SUPERSEDED"
                    bump(p)
            # posture + limit adjustment
            if member["status"] == "ENROLLED":
                if score >= 200:
                    member["status"] = "ELIGIBLE"
                    member["current_limit_cents"] = computed_limit
                    _create_adjustment(member, 0, computed_limit, now)
                # score < 200: stay ENROLLED, no adjustment (delta from 0 handled below)
                elif computed_limit != 0:
                    # cannot happen in practice (score<200 -> score_cap=0 -> limit 0)
                    pass
            elif member["status"] in ("ELIGIBLE", "RESTRICTED", "SUSPENDED"):
                if delta != 0:
                    # supersede pending decreases
                    for adj in store.adjustments.values():
                        if adj["member_id"] == member["id"] \
                                and adj["status"] in ("PENDING_NOTICE", "NOTIFIED"):
                            adj["status"] = "SUPERSEDED"
                            bump(adj)
                    _create_adjustment(member, member["current_limit_cents"],
                                       computed_limit, now)
                    if computed_limit > member["current_limit_cents"] or \
                            member["status"] == "SUSPENDED":
                        member["current_limit_cents"] = computed_limit
        store.profiles[profile["id"]] = profile
        bump(member)
        return success_object(serialize_profile(profile), 201)


def _create_adjustment(member, old_limit, new_limit, now):
    if new_limit > old_limit:
        direction = "INCREASE"
    elif new_limit < old_limit:
        direction = "DECREASE"
    else:
        return None  # FLAT: no row
    if direction == "INCREASE":
        status = "EFFECTIVE"
        effective_at = now
    else:
        # SUSPENDED re-evaluation forces decrease EFFECTIVE immediately
        if member["status"] == "SUSPENDED":
            status = "EFFECTIVE"
            effective_at = now
        else:
            status = "PENDING_NOTICE"
            effective_at = now + timedelta(days=NOTICE_DAYS)
    adj = {
        "id": new_id(),
        "member_id": member["id"],
        "old_limit_cents": old_limit,
        "new_limit_cents": new_limit,
        "direction": direction,
        "status": status,
        "effective_at": effective_at,
        "notified_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.adjustments[adj["id"]] = adj
    return adj


@bp.get("/members/<mid>/eligibility-profiles")
def list_profiles(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        member = find_member(mid)
        check_member_ownership(uid, role, member["id"])
        from flask import request
        mode = request.args.get("evaluation_mode")
        items = [p for p in store.profiles.values() if p["member_id"] == mid]
        if mode is not None:
            items = [p for p in items if p["evaluation_mode"] == mode]
        items.sort(key=lambda p: p["created_at"], reverse=True)
        page, limit, offset, total = paginate(items)
        return success_list([serialize_profile(p) for p in page], limit, offset, total)


@bp.post("/members/<mid>/abuse-events")
def create_abuse_event(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        member = find_member(mid)
        if member["status"] == "CLOSED":
            raise errors.already_terminal("Member is CLOSED.")
        body = get_body()
        event_type = _req_enum(body, "event_type", EVENT_TYPES)
        evidence_note = _opt_str(body, "evidence_note", 500)
        require_occ(body, "expected_member_version", member)

        ev = {
            "id": new_id(),
            "member_id": member["id"],
            "event_type": event_type,
            "evidence_note": evidence_note,
            "created_at": clock.now(),
        }
        store.abuse_events[ev["id"]] = ev

        # posture cascade
        from core import abuse_counts
        _, abuse_90d = abuse_counts(member["id"])
        if member["status"] == "ELIGIBLE" and abuse_90d == 1:
            member["status"] = "RESTRICTED"
            member["restricted_consecutive_repayments"] = 0
            if event_type == "DEPOSIT_REROUTE":
                member["deposit_reroute_flag"] = True
        elif member["status"] == "RESTRICTED":
            member["status"] = "SUSPENDED"
            member["deposit_reroute_flag"] = True
        bump(member)
        return success_object(serialize_abuse_event(ev), 201)


@bp.get("/members/<mid>/abuse-events")
def list_abuse_events(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        find_member(mid)
        items = sorted(
            (e for e in store.abuse_events.values() if e["member_id"] == mid),
            key=lambda e: e["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_abuse_event(e) for e in page], limit, offset, total)


@bp.post("/members/<mid>/close")
def close_member(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        member = find_member(mid)
        if member["status"] == "CLOSED":
            raise errors.already_terminal("Member is already CLOSED.")
        if member["status"] != "SUSPENDED":
            raise errors.invalid_state("Only a SUSPENDED member may be closed.")
        member["status"] = "CLOSED"
        member["consecutive_on_time_repayments"] = 0
        for adv in store.advances.values():
            if adv["status"] in ("OPEN", "PARTIALLY_REPAID"):
                acct = store.accounts.get(adv["account_id"])
                if acct is not None and acct["member_id"] == mid:
                    adv["status"] = "WRITTEN_OFF"
                    adv["outstanding_cents"] = 0
                    bump(adv)
        bump(member)
        return success_object(serialize_member(member))


@bp.get("/members/<mid>/disputes")
def list_member_disputes(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "DisputesAgent"})
        member = find_member(mid)
        check_member_ownership(uid, role, member["id"])
        from flask import request
        case_status = request.args.get("case_status")
        items = sorted(
            (d for d in store.disputes.values() if d["member_id"] == mid),
            key=lambda d: d["created_at"])
        if case_status is not None:
            items = [d for d in items if d["case_status"] == case_status]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_dispute(d) for d in page], limit, offset, total)


@bp.get("/members/<mid>/limit-adjustments")
def list_member_adjustments(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        member = find_member(mid)
        check_member_ownership(uid, role, member["id"])
        apply_time_transitions()
        from flask import request
        status = request.args.get("status")
        items = sorted(
            (a for a in store.adjustments.values() if a["member_id"] == mid),
            key=lambda a: a["created_at"])
        if status is not None:
            items = [a for a in items if a["status"] == status]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_adjustment(a) for a in page], limit, offset, total)


# ===========================================================================
# Accounts
# ===========================================================================
@bp.post("/members/<mid>/accounts")
def create_account(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"SponsorBankOps"})
        member = find_member(mid)
        body = get_body()
        account_type = _req_enum(body, "account_type", ACCOUNT_TYPES)
        currency = body.get("currency", "USD")
        if currency not in CURRENCIES:
            raise errors.invalid_request("currency must be USD.")
        sponsor_bank_code = body.get("sponsor_bank_code", "SB-1")
        if not isinstance(sponsor_bank_code, str) or not (1 <= len(sponsor_bank_code) <= 32):
            raise errors.invalid_request("sponsor_bank_code must be 1..32 chars.")
        now = clock.now()
        account = {
            "id": new_id(),
            "member_id": member["id"],
            "account_type": account_type,
            "currency": currency,
            "sponsor_bank_code": sponsor_bank_code,
            "posted_balance_cents": 0,
            "holds_cents": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.accounts[account["id"]] = account
        return success_object(serialize_account(account), 201)


@bp.get("/members/<mid>/accounts")
def list_member_accounts(mid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "SponsorBankOps"})
        member = find_member(mid)
        check_member_ownership(uid, role, member["id"])
        apply_time_transitions()
        items = sorted(
            (a for a in store.accounts.values() if a["member_id"] == mid),
            key=lambda a: a["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_account(a) for a in page], limit, offset, total)


@bp.get("/accounts/<aid>")
def get_account(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "SponsorBankOps"})
        account = find_account(aid)
        check_member_ownership(uid, role, account["member_id"])
        apply_time_transitions()
        return success_object(serialize_account(account))


@bp.post("/accounts/<aid>/advances")
def create_member_advance(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member"})
        account = find_account(aid)
        check_member_ownership(uid, role, account["member_id"])
        member = member_of_account(account)
        if member is not None and member["status"] == "CLOSED":
            raise errors.already_terminal("Member is CLOSED.")
        body = get_body()
        amount = _req_int(body, "amount_cents", positive=True)
        idem_key = _req_str(body, "idempotency_key", 1)
        require_occ(body, "expected_account_version", account)

        # idempotency
        prior = store.advance_idempotency.get(idem_key)
        if prior is not None:
            prior_amount, prior_advance_id = prior
            if prior_amount != amount:
                raise errors.idempotency_conflict()
            return success_object(serialize_advance(store.advances[prior_advance_id]), 200)

        # posture gate
        if member is None or member["status"] != "ELIGIBLE":
            raise errors.member_posture("Advances require member status ELIGIBLE.")
        # abuse lock
        if member["deposit_reroute_flag"]:
            raise errors.abuse_lock()
        # fiscal: savings / limit / headroom
        if account["account_type"] != "SPENDING":
            raise errors.limit_exceeded("Only SPENDING accounts participate.")
        computed = account_computed(account)
        if member["current_limit_cents"] == 0 or amount > computed["usable_cushion_cents"]:
            raise errors.limit_exceeded("Advance exceeds usable cushion.")

        adv = create_advance(account["id"], "MEMBER_INITIATED", amount)
        account["posted_balance_cents"] += amount
        create_ledger_entry(account["id"], "ADVANCE_CREDIT", amount, "SETTLED")
        bump(account)
        store.advance_idempotency[idem_key] = (amount, adv["id"])
        return success_object(serialize_advance(adv), 201)


@bp.post("/accounts/<aid>/debits")
def create_debit(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member"})
        account = find_account(aid)
        check_member_ownership(uid, role, account["member_id"])
        member = member_of_account(account)
        if member is not None and member["status"] == "CLOSED":
            raise errors.already_terminal("Member is CLOSED.")
        body = get_body()
        amount = _req_int(body, "amount_cents", positive=True)
        _req_str(body, "merchant_ref", 1)
        require_occ(body, "expected_account_version", account)

        computed = account_computed(account)
        if amount > computed["available_optimistic_cents"]:
            raise errors.insufficient_funds()

        # A debit draws on settled funds, provisional early money, and usable
        # cushion together. Consume provisional early money first — it sits
        # outside posted_balance_cents — then the settled balance; only the
        # remainder beyond both converts to a member-owed advance.
        after_provisional = _consume_provisional(account, amount)
        posted_before = account["posted_balance_cents"]
        account["posted_balance_cents"] -= after_provisional
        if after_provisional > posted_before:
            excess = after_provisional - posted_before
            create_advance(account["id"], "MEMBER_INITIATED", excess)
            create_ledger_entry(account["id"], "ADVANCE_CREDIT", excess, "SETTLED")
        create_ledger_entry(account["id"], "ADJUSTMENT", -amount, "SETTLED")
        bump(account)
        # return the debit ledger entry
        entry = max(
            (le for le in store.ledger_entries.values()
             if le["account_id"] == account["id"]),
            key=lambda le: le["created_at"])
        return success_object(serialize_ledger_entry(entry), 201)


@bp.get("/accounts/<aid>/advances")
def list_account_advances(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        account = find_account(aid)
        check_member_ownership(uid, role, account["member_id"])
        from flask import request
        status = request.args.get("status")
        items = sorted(
            (a for a in store.advances.values() if a["account_id"] == aid),
            key=lambda a: a["created_at"])
        if status is not None:
            items = [a for a in items if a["status"] == status]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_advance(a) for a in page], limit, offset, total)


@bp.get("/accounts/<aid>/ledger-entries")
def list_account_ledger(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "SponsorBankOps"})
        account = find_account(aid)
        check_member_ownership(uid, role, account["member_id"])
        from flask import request
        entry_type = request.args.get("entry_type")
        status = request.args.get("status")
        items = sorted(
            (le for le in store.ledger_entries.values() if le["account_id"] == aid),
            key=lambda le: le["created_at"])
        if entry_type is not None:
            items = [le for le in items if le["entry_type"] == entry_type]
        if status is not None:
            items = [le for le in items if le["status"] == status]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_ledger_entry(le) for le in page], limit, offset, total)


@bp.get("/accounts/<aid>/deposits")
def list_account_deposits(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "SponsorBankOps"})
        account = find_account(aid)
        check_member_ownership(uid, role, account["member_id"])
        from flask import request
        status = request.args.get("status")
        originator_id = request.args.get("originator_id")
        items = sorted(
            (d for d in store.deposits.values() if d["account_id"] == aid),
            key=lambda d: d["created_at"])
        if status is not None:
            items = [d for d in items if d["status"] == status]
        if originator_id is not None:
            items = [d for d in items if d["originator_id"] == originator_id]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_deposit(d) for d in page], limit, offset, total)


@bp.post("/accounts/<aid>/deposits")
def create_deposit(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"SponsorBankOps"})
        account = find_account(aid)
        member = member_of_account(account)
        if member is not None and member["status"] == "CLOSED":
            raise errors.already_terminal("Member is CLOSED.")
        body = get_body()
        originator_id = _req_str(body, "originator_id", 1, 64)
        originator_type = _req_enum(body, "originator_type", ORIGINATOR_TYPES)
        amount = _req_int(body, "amount_cents", positive=True)
        settlement_date = _req_dt(body, "settlement_date")
        trace_id = _req_str(body, "trace_id", 1)

        # overlap window check (priority 12) before uniqueness (priority 13)
        three_days = timedelta(days=3)
        for d in store.deposits.values():
            if d["account_id"] == aid and d["originator_id"] == originator_id \
                    and d["status"] in ("RECEIVED_FILE", "POSTED_EARLY"):
                if abs(d["settlement_date"] - settlement_date) <= three_days:
                    raise errors.window_overlap(
                        "Conflicts with an in-flight deposit for the same account+originator.")
        # uniqueness: trace_id
        for d in store.deposits.values():
            if d["trace_id"] == trace_id:
                raise errors.duplicate("trace_id already exists.")

        now = clock.now()
        deposit = {
            "id": new_id(),
            "account_id": aid,
            "originator_id": originator_id,
            "originator_type": originator_type,
            "amount_cents": amount,
            "settlement_date": settlement_date,
            "trace_id": trace_id,
            "status": "RECEIVED_FILE",
            "qualifying": originator_type == "PAYROLL" and amount >= QUALIFYING_MIN_CENTS,
            "settled_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.deposits[deposit["id"]] = deposit
        return success_object(serialize_deposit(deposit), 201)


# ===========================================================================
# Advances
# ===========================================================================
@bp.get("/advances/<aid>")
def get_advance(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        adv = find_advance(aid)
        member = member_of_advance(adv)
        check_member_ownership(uid, role, member["id"] if member else None)
        apply_time_transitions()
        return success_object(serialize_advance(adv))


@bp.post("/advances/<aid>/write-off")
def write_off_advance(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        adv = find_advance(aid)
        body = get_body()
        _req_str(body, "reason", 1)
        if adv["status"] in ("REPAID", "WRITTEN_OFF"):
            raise errors.already_terminal("Advance is already terminal.")
        if adv["status"] not in ("OPEN", "PARTIALLY_REPAID"):
            raise errors.invalid_state("Advance cannot be written off from this state.")
        if clock.now() < adv["created_at"] + timedelta(days=WRITE_OFF_DAYS):
            raise errors.temporal_violation("Advance is younger than 60 days.")
        account = account_of_advance(adv)
        member = member_of_advance(adv)
        adv["status"] = "WRITTEN_OFF"
        adv["outstanding_cents"] = 0
        bump(adv)
        if member is not None:
            member["consecutive_on_time_repayments"] = 0
            bump(member)
        return success_object(serialize_advance(adv))


@bp.get("/advances/<aid>/repayment-allocations")
def list_advance_allocations(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        adv = find_advance(aid)
        member = member_of_advance(adv)
        check_member_ownership(uid, role, member["id"] if member else None)
        items = sorted(
            (al for al in store.allocations.values() if al["advance_id"] == aid),
            key=lambda al: al["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_allocation(al) for al in page], limit, offset, total)


# ===========================================================================
# Deposits
# ===========================================================================
@bp.get("/deposits/<did>")
def get_deposit(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "SponsorBankOps"})
        deposit = find_deposit(did)
        member = member_of_deposit(deposit)
        check_member_ownership(uid, role, member["id"] if member else None)
        return success_object(serialize_deposit(deposit))


@bp.post("/deposits/<did>/post-early")
def post_early(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        deposit = find_deposit(did)
        account = account_of_deposit(deposit)
        member = member_of_deposit(deposit)
        now = clock.now()

        if deposit["status"] == "RETURNED":
            raise errors.already_terminal("Deposit is RETURNED.")
        if deposit["status"] != "RECEIVED_FILE":
            raise errors.invalid_state("Only a RECEIVED_FILE deposit can be posted early.")
        if member is not None and member["status"] == "CLOSED":
            raise errors.already_terminal("Member is CLOSED.")
        # posture
        if member is None or member["status"] not in ("ELIGIBLE", "RESTRICTED"):
            raise errors.member_posture("Early posting requires ELIGIBLE or RESTRICTED.")
        # abuse lock
        if member["deposit_reroute_flag"]:
            raise errors.abuse_lock()
        # qualifying
        if not deposit["qualifying"]:
            raise errors.not_qualifying("Deposit does not qualify for early posting.")
        # temporal
        if now >= deposit["settlement_date"]:
            raise errors.temporal_violation("Cannot post early on or after settlement_date.")
        # referential: discrepancy gate
        if account is not None and discrepancy_blocks(account["sponsor_bank_code"]):
            raise errors.referential_block(
                "An unresolved reconciliation discrepancy blocks early posting.")

        amount = deposit["amount_cents"]
        deposit["status"] = "POSTED_EARLY"
        bump(deposit)

        ep = {
            "id": new_id(),
            "deposit_id": deposit["id"],
            "posted_amount_cents": amount,
            "reversal_window_end": deposit["settlement_date"] + timedelta(days=2),
            "status": "PROVISIONAL",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.early_postings[ep["id"]] = ep
        deposit["early_posting_id"] = ep["id"]

        total_allocated = run_waterfall(account, deposit)
        # The early-posted funds live in provisional_early_cents (via the
        # PROVISIONAL EarlyPosting), not in posted_balance_cents, until
        # settlement materializes them. The waterfall's clawback is added to
        # the settled balance at settle time.
        create_ledger_entry(account["id"], "EARLY_POSTING_CREDIT", amount, "PENDING")
        bump(account)
        return success_object(serialize_early_posting(ep), 200)


@bp.post("/deposits/<did>/settle")
def settle_deposit(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"SponsorBankOps"})
        deposit = find_deposit(did)
        account = account_of_deposit(deposit)
        now = clock.now()

        if deposit["status"] == "RETURNED":
            raise errors.already_terminal("Deposit is RETURNED.")
        if deposit["status"] not in ("RECEIVED_FILE", "POSTED_EARLY"):
            raise errors.invalid_state("Deposit cannot be settled from this state.")
        if now < deposit["settlement_date"]:
            raise errors.temporal_violation("Cannot settle before settlement_date.")

        amount = deposit["amount_cents"]
        if deposit["status"] == "RECEIVED_FILE":
            account["posted_balance_cents"] += amount
            deposit["settled_at"] = now
            total_allocated = run_waterfall(account, deposit)
            account["posted_balance_cents"] -= total_allocated
            create_ledger_entry(account["id"], "DEPOSIT_SETTLEMENT", amount, "SETTLED")
        else:  # POSTED_EARLY
            ep = store.early_postings.get(deposit.get("early_posting_id"))
            if ep is not None:
                ep["status"] = "CONFIRMED"
                bump(ep)
            repaid = sum(al["amount_cents"] for al in store.allocations.values()
                         if al["deposit_id"] == deposit["id"])
            # The unallocated remainder (credited as spendable provisional
            # money at post-early) materializes into the settled balance.
            account["posted_balance_cents"] += deposit["amount_cents"] - repaid
            deposit["settled_at"] = now
            for le in store.ledger_entries.values():
                if le["account_id"] == account["id"] \
                        and le["entry_type"] == "EARLY_POSTING_CREDIT" \
                        and le["status"] == "PENDING":
                    le["status"] = "SETTLED"
        deposit["status"] = "SETTLED"
        bump(deposit)
        bump(account)
        return success_object(serialize_deposit(deposit), 200)


@bp.post("/deposits/<did>/return")
def return_deposit(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"SponsorBankOps"})
        deposit = find_deposit(did)
        account = account_of_deposit(deposit)
        now = clock.now()
        body = get_body()
        return_code = _req_enum(body, "return_code", RETURN_CODES)

        if deposit["status"] == "RETURNED":
            raise errors.already_terminal("Deposit is already RETURNED.")
        if deposit["status"] not in ("POSTED_EARLY", "SETTLED"):
            raise errors.invalid_state("Only POSTED_EARLY or SETTLED deposits can be returned.")

        amount = deposit["amount_cents"]
        from_posted_early = deposit["status"] == "POSTED_EARLY"

        posted_before = account["posted_balance_cents"]
        if from_posted_early:
            ep = store.early_postings.get(deposit.get("early_posting_id"))
            if ep is not None and ep["status"] == "PROVISIONAL":
                ep["status"] = "REVERSED"
                bump(ep)
            # Only the still-provisional (unspent) portion is at reversal risk;
            # money the member already spent is not clawed back here.
            exposure = amount - (ep.get("spent_cents", 0) if ep is not None else 0)
            recoverable = min(exposure, max(0, posted_before))
            shortfall = exposure - recoverable
            account["posted_balance_cents"] -= recoverable
            # void the early posting credit — voiding the PENDING
            # EARLY_POSTING_CREDIT is the reversal; the DEPOSIT_RETURN_DEBIT
            # records the funds movement.
            for le in store.ledger_entries.values():
                if le["account_id"] == account["id"] \
                        and le["entry_type"] == "EARLY_POSTING_CREDIT" \
                        and le["status"] == "PENDING":
                    le["status"] = "VOIDED"
            create_ledger_entry(account["id"], "DEPOSIT_RETURN_DEBIT", -amount, "SETTLED")
        else:  # SETTLED -> RETURNED (late return)
            recoverable = min(amount, max(0, posted_before))
            shortfall = amount - recoverable
            account["posted_balance_cents"] -= amount  # may go negative
            create_ledger_entry(account["id"], "DEPOSIT_RETURN_DEBIT", -amount, "SETTLED")

        if shortfall > 0:
            create_advance(account["id"], "RECLAIM_SHORTFALL", shortfall)

        ret = {
            "id": new_id(),
            "deposit_id": deposit["id"],
            "return_code": return_code,
            "amount_cents": amount,
            "shortfall_cents": shortfall,
            "created_at": now,
        }
        store.returns[ret["id"]] = ret
        deposit["status"] = "RETURNED"
        bump(deposit)
        bump(account)
        return success_object(serialize_return(ret), 201)


@bp.get("/deposits/<did>/returns")
def list_deposit_returns(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps", "SponsorBankOps"})
        find_deposit(did)
        items = sorted(
            (r for r in store.returns.values() if r["deposit_id"] == did),
            key=lambda r: r["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_return(r) for r in page], limit, offset, total)


@bp.get("/deposits/<did>/early-postings")
def list_deposit_early_postings(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        find_deposit(did)
        items = sorted(
            (ep for ep in store.early_postings.values() if ep["deposit_id"] == did),
            key=lambda ep: ep["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_early_posting(ep) for ep in page], limit, offset, total)


@bp.get("/deposits/<did>/repayment-allocations")
def list_deposit_allocations(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        find_deposit(did)
        items = sorted(
            (al for al in store.allocations.values() if al["deposit_id"] == did),
            key=lambda al: al["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_allocation(al) for al in page], limit, offset, total)


@bp.get("/deposits/<did>/disputes")
def list_deposit_disputes(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "DisputesAgent"})
        deposit = find_deposit(did)
        member = member_of_deposit(deposit)
        check_member_ownership(uid, role, member["id"] if member else None)
        items = sorted(
            (d for d in store.disputes.values() if d["deposit_id"] == did),
            key=lambda d: d["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_dispute(d) for d in page], limit, offset, total)


# ===========================================================================
# Limit adjustments
# ===========================================================================
@bp.get("/limit-adjustments/<aid>")
def get_adjustment(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps"})
        adj = find_adjustment(aid)
        check_member_ownership(uid, role, adj["member_id"])
        apply_time_transitions()
        return success_object(serialize_adjustment(adj))


@bp.post("/limit-adjustments/<aid>/notify")
def notify_adjustment(aid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        adj = find_adjustment(aid)
        if adj["status"] != "PENDING_NOTICE":
            raise errors.invalid_state("Only a PENDING_NOTICE adjustment can be notified.")
        adj["status"] = "NOTIFIED"
        adj["notified_at"] = clock.now()
        bump(adj)
        return success_object(serialize_adjustment(adj), 200)


# ===========================================================================
# Reconciliation runs
# ===========================================================================
@bp.post("/reconciliation-runs")
def create_run():
    with store.lock:
        uid, role = auth()
        require_roles(role, {"SponsorBankOps"})
        body = get_body()
        sponsor_bank_code = _req_str(body, "sponsor_bank_code", 1, 32)
        period_start = _req_dt(body, "period_start")
        period_end = _req_dt(body, "period_end")
        bank_reported = _req_int(body, "bank_reported_net_cents")
        if period_end <= period_start:
            raise errors.invalid_request("period_end must be after period_start.")

        # overlap check: non-terminal runs for same sponsor bank
        for r in store.runs.values():
            if r["sponsor_bank_code"] != sponsor_bank_code:
                continue
            if r["status"] not in ("OPEN", "DISCREPANCY"):
                continue
            if r["period_start"] < period_end and period_start < r["period_end"]:
                raise errors.window_overlap("Window overlaps an existing non-terminal run.")

        # compute program net over SETTLED entries for accounts of this bank
        acct_ids = {a["id"] for a in store.accounts.values()
                    if a["sponsor_bank_code"] == sponsor_bank_code}
        program_net = 0
        bank_net = 0
        for le in store.ledger_entries.values():
            if le["account_id"] not in acct_ids:
                continue
            if le["status"] != "SETTLED":
                continue
            if period_start <= le["posted_at"] < period_end:
                program_net += le["program_leg_cents"]
                bank_net += le["bank_leg_cents"]
        discrepancy = program_net + bank_reported
        status = "BALANCED" if discrepancy == 0 else "DISCREPANCY"
        now = clock.now()
        run = {
            "id": new_id(),
            "sponsor_bank_code": sponsor_bank_code,
            "period_start": period_start,
            "period_end": period_end,
            "bank_reported_net_cents": bank_reported,
            "program_net_cents": program_net,
            "bank_net_cents": -bank_net,
            "discrepancy_cents": discrepancy,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.runs[run["id"]] = run
        return success_object(serialize_run(run), 201)


@bp.get("/reconciliation-runs")
def list_runs():
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps", "SponsorBankOps"})
        from flask import request
        status = request.args.get("status")
        bank = request.args.get("sponsor_bank_code")
        items = sorted(store.runs.values(), key=lambda r: r["created_at"])
        if status is not None:
            items = [r for r in items if r["status"] == status]
        if bank is not None:
            items = [r for r in items if r["sponsor_bank_code"] == bank]
        page, limit, offset, total = paginate(items)
        return success_list([serialize_run(r) for r in page], limit, offset, total)


@bp.get("/reconciliation-runs/<rid>")
def get_run(rid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps", "SponsorBankOps"})
        run = find_run(rid)
        return success_object(serialize_run(run))


@bp.post("/reconciliation-runs/<rid>/resolve")
def resolve_run(rid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        run = find_run(rid)
        body = get_body()
        _req_str(body, "resolution_note", 1)
        require_occ(body, "expected_run_version", run)
        if run["status"] != "DISCREPANCY":
            raise errors.invalid_state("Only a DISCREPANCY run can be resolved.")

        # oldest account (by created_at) of this bank with entries in the window
        acct_ids = {a["id"]: a for a in store.accounts.values()
                    if a["sponsor_bank_code"] == run["sponsor_bank_code"]}
        candidates = []
        for le in store.ledger_entries.values():
            if le["account_id"] in acct_ids \
                    and run["period_start"] <= le["posted_at"] < run["period_end"]:
                candidates.append(acct_ids[le["account_id"]])
        target = None
        if candidates:
            target = min(candidates, key=lambda a: a["created_at"])
        else:
            # fall back to the oldest account of the bank, if any
            bank_accounts = sorted(acct_ids.values(), key=lambda a: a["created_at"])
            target = bank_accounts[0] if bank_accounts else None
        if target is None:
            raise errors.invalid_state("No account available to post the adjustment.")

        discrepancy = run["discrepancy_cents"]
        create_ledger_entry(target["id"], "ADJUSTMENT", -discrepancy, "SETTLED",
                            run_id=run["id"])
        run["status"] = "RESOLVED"
        bump(run)
        return success_object(serialize_run(run), 200)


@bp.get("/reconciliation-runs/<rid>/ledger-entries")
def list_run_ledger_entries(rid):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps", "SponsorBankOps"})
        find_run(rid)
        items = sorted(
            (le for le in store.ledger_entries.values()
             if le["reconciliation_run_id"] == rid),
            key=lambda le: le["created_at"])
        page, limit, offset, total = paginate(items)
        return success_list([serialize_ledger_entry(le) for le in page], limit, offset, total)


# ===========================================================================
# Disputes
# ===========================================================================
@bp.post("/disputes")
def create_dispute():
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member"})
        body = get_body()
        deposit_id = body.get("deposit_id")
        if not isinstance(deposit_id, str) or not deposit_id:
            raise errors.invalid_request("deposit_id is required.")
        dispute_type = _req_enum(body, "dispute_type", DISPUTE_TYPES)
        amount = _req_int(body, "amount_cents", positive=True)
        statement = _req_str(body, "statement", 1, 1000)

        deposit = store.deposits.get(deposit_id)
        if deposit is None:
            raise errors.not_found("DirectDeposit not found.")
        member = member_of_deposit(deposit)
        # ownership: filing member must own the deposit
        if member is None or uid != member["id"]:
            raise errors.referential_block(
                "Dispute references a deposit not owned by the filing member.")
        if amount > deposit["amount_cents"]:
            raise errors.dispute_amount_exceeds()

        now = clock.now()
        dispute = {
            "id": new_id(),
            "member_id": member["id"],
            "deposit_id": deposit["id"],
            "dispute_type": dispute_type,
            "amount_cents": amount,
            "statement": statement,
            "case_status": "FILED",
            "provisional_status": "NONE",
            "provisional_due_at": add_business_days(now, 10),
            "resolution_due_at": now + timedelta(days=45),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.disputes[dispute["id"]] = dispute
        return success_object(serialize_dispute(dispute), 201)


@bp.get("/disputes/<did>")
def get_dispute(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"Member", "ProgramOps", "DisputesAgent"})
        dispute = find_dispute(did)
        check_member_ownership(uid, role, dispute["member_id"])
        return success_object(serialize_dispute(dispute))


@bp.post("/disputes/<did>/issue-provisional-credit")
def issue_provisional_credit(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"DisputesAgent"})
        dispute = find_dispute(did)
        now = clock.now()

        if dispute["case_status"] in ("RESOLVED_MEMBER", "RESOLVED_BANK"):
            raise errors.already_terminal("Dispute is already resolved.")
        if dispute["provisional_status"] != "NONE" \
                or dispute["case_status"] not in ("FILED", "UNDER_REVIEW"):
            raise errors.invalid_state("Provisional credit cannot be issued from this state.")
        deposit = store.deposits.get(dispute["deposit_id"])
        if deposit is None:
            raise errors.not_found("DirectDeposit not found.")
        if deposit["status"] not in ("POSTED_EARLY", "RETURNED"):
            raise errors.invalid_state(
                "Provisional credit exists only against early-posted or returned funds.")
        if now > dispute["provisional_due_at"]:
            raise errors.temporal_violation("Provisional credit deadline has passed.")

        account = account_of_deposit(deposit)
        account["holds_cents"] = account.get("holds_cents", 0) + dispute["amount_cents"]
        bump(account)
        create_ledger_entry(account["id"], "PROVISIONAL_CREDIT",
                            dispute["amount_cents"], "SETTLED")
        dispute["provisional_status"] = "PROVISIONAL_ISSUED"
        if dispute["case_status"] == "FILED":
            dispute["case_status"] = "UNDER_REVIEW"
        bump(dispute)
        return success_object(serialize_dispute(dispute), 200)


@bp.post("/disputes/<did>/resolve")
def resolve_dispute(did):
    with store.lock:
        uid, role = auth()
        require_roles(role, {"DisputesAgent"})
        dispute = find_dispute(did)
        now = clock.now()
        body = get_body()
        outcome = _req_enum(body, "outcome", DISPUTE_OUTCOMES)
        _req_str(body, "resolution_note", 1)

        if dispute["case_status"] in ("RESOLVED_MEMBER", "RESOLVED_BANK"):
            raise errors.already_terminal("Dispute is already resolved.")
        if dispute["case_status"] not in ("FILED", "UNDER_REVIEW"):
            raise errors.invalid_state("Dispute cannot be resolved from this state.")
        if now > dispute["resolution_due_at"]:
            raise errors.temporal_violation("Resolution deadline has passed.")

        deposit = store.deposits.get(dispute["deposit_id"])
        account = account_of_deposit(deposit) if deposit else None

        if outcome == "MEMBER":
            if dispute["provisional_status"] == "PROVISIONAL_ISSUED":
                dispute["provisional_status"] = "PROVISIONAL_MADE_FINAL"
                if account is not None:
                    account["holds_cents"] = account.get("holds_cents", 0) - dispute["amount_cents"]
                    account["posted_balance_cents"] += dispute["amount_cents"]
                    bump(account)
            else:
                if account is not None:
                    account["posted_balance_cents"] += dispute["amount_cents"]
                    bump(account)
                    create_ledger_entry(account["id"], "PROVISIONAL_CREDIT",
                                        dispute["amount_cents"], "SETTLED")
            dispute["case_status"] = "RESOLVED_MEMBER"
        else:  # BANK
            if dispute["provisional_status"] == "PROVISIONAL_ISSUED":
                dispute["provisional_status"] = "PROVISIONAL_RECLAIMED"
                if account is not None:
                    account["holds_cents"] = account.get("holds_cents", 0) - dispute["amount_cents"]
                    bump(account)
                    create_ledger_entry(account["id"], "PROVISIONAL_REVERSAL",
                                        -dispute["amount_cents"], "SETTLED")
            dispute["case_status"] = "RESOLVED_BANK"
        bump(dispute)
        return success_object(serialize_dispute(dispute), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    with store.lock:
        uid, role = auth()
        require_roles(role, {"ProgramOps"})
        body = get_body()
        target = _req_dt(body, "to_iso8601")
        clock.set_current(target)
        apply_time_transitions()
        return success_object({"current_utc": clock.fmt(clock.now())}, 200)
