"""Papering, issuing, countersigning and cancelling the group contract."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import charge_json, contract_json, reconciliation_json

bp = Blueprint("contracts", __name__)

CONTRACT_READ_ROLES = [ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
                       ROLE_ACCOUNTING_CLERK, ROLE_GROUP_CONTACT]


@bp.route("/group-sales/contracts", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN])
def create_contract():
    body = body_json()
    quote_id = v_id(body, "quote_id")
    threshold = v_number(body, "attrition_threshold_pct", minimum=0.5, maximum=1.0)
    basis = v_enum(body, "attrition_basis", ATTRITION_BASES)
    clause = v_enum(body, "force_majeure_clause", FORCE_MAJEURE_CLAUSES)
    cutoff_days = v_int(body, "cutoff_days_before_arrival", minimum=1, maximum=120)
    room_nights = v_int(body, "contracted_room_nights", minimum=1)
    peak_rooms = v_int(body, "contracted_peak_rooms", minimum=1)
    entries = v_allotments(body)
    quote = need_quote(quote_id)
    check_contiguous_distinct(entries)
    if quote["status"] != "ACCEPTED":
        fail("ERR_QUOTE_INVALID_STATE",
             "A contract may only be papered from an ACCEPTED quote; it is %s."
             % quote["status"])
    require_quote_live(quote)
    lead = need_lead(quote["lead_id"])
    require_displacement_cleared(lead["id"])
    entries = sorted(entries, key=lambda e: e["stay_date"])
    plan_rooms = [e["rooms"] for e in entries]
    if sum(plan_rooms) != room_nights:
        fail("ERR_ALLOTMENT_PLAN_MISMATCH",
             "The plan sums to %s room nights, not contracted_room_nights %s."
             % (sum(plan_rooms), room_nights))
    if max(plan_rooms) != peak_rooms:
        fail("ERR_ALLOTMENT_PLAN_MISMATCH",
             "The plan's largest night is %s rooms, not contracted_peak_rooms %s."
             % (max(plan_rooms), peak_rooms))
    expected_dates = stay_dates(lead["arrival_date"], lead["departure_date"])
    if [e["stay_date"] for e in entries] != expected_dates:
        fail("ERR_ALLOTMENT_PLAN_MISMATCH",
             "The plan's dates must be exactly the lead's half-open stay range.")
    if room_nights > quote["quoted_room_nights"]:
        fail("ERR_ALLOTMENT_PLAN_MISMATCH",
             "contracted_room_nights may not exceed the quote's %s."
             % quote["quoted_room_nights"])
    arrival = parse_date_str(lead["arrival_date"])
    departure = parse_date_str(lead["departure_date"])
    row = new_row({
        "quote_id": quote_id,
        "status": "DRAFT",
        "attrition_threshold_pct": threshold,
        "attrition_basis": basis,
        "force_majeure_clause": clause,
        "cutoff_days_before_arrival": cutoff_days,
        "contracted_room_nights": room_nights,
        "contracted_peak_rooms": peak_rooms,
        "nightly_allotments": [{"stay_date": iso_date(e["stay_date"]),
                                "rooms": e["rooms"]} for e in entries],
        "contracted_rate_cents": quote["effective_net_rate_cents"],
        "arrival_date": iso_date(arrival),
        "departure_date": iso_date(departure),
        "nights_count": whole_days(departure, arrival),
        "signed_by_user_id": None,
        "signed_at": None,
        "signature_name": None,
        "cancellation_reason": None,
        "assessed_damages_cents": 0,
        "ancillary_posted_cents": 0,
        "rebate_paid_cents": 0,
        "receivable_total_cents": 0,
    })
    store.contracts[row["id"]] = row
    return ok(contract_json(row), 201)


@bp.route("/group-sales/contracts/<contract_id>", methods=["GET"])
@endpoint(CONTRACT_READ_ROLES)
def read_contract(contract_id):
    contract = need_contract(contract_id)
    require_owner(owner_of_contract(contract))
    return ok(contract_json(contract))


@bp.route("/group-sales/contracts", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_ACCOUNTING_CLERK])
def list_contracts():
    limit, offset = q_pagination()
    quote_id = q_str("quote_id")
    status = q_enum("status", CONTRACT_STATUSES)
    rows = in_order(list(store.contracts.values()))
    if quote_id is not None:
        rows = [r for r in rows if r["quote_id"] == quote_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([contract_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/contracts/<contract_id>/send", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN])
def send_contract(contract_id):
    contract = need_contract(contract_id)
    if contract["status"] != "DRAFT":
        fail("ERR_CONTRACT_INVALID_STATE",
             "Send is declared only from DRAFT; the contract is %s."
             % contract["status"])
    quote = quote_of_contract(contract)
    if quote is None or quote["status"] != "ACCEPTED":
        fail("ERR_QUOTE_INVALID_STATE",
             "The underlying quote must still be ACCEPTED to issue the contract.")
    contract["status"] = "SENT"
    touch(contract)
    return ok(contract_json(contract))


@bp.route("/group-sales/contracts/<contract_id>/sign", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN])
def sign_contract(contract_id):
    body = body_json()
    signature_name = v_string(body, "signature_name", min_len=1, max_len=120)
    contract = need_contract(contract_id)
    if contract["status"] != "SENT":
        fail("ERR_CONTRACT_INVALID_STATE",
             "Countersignature is declared only from SENT; the contract is %s."
             % contract["status"])
    quote = quote_of_contract(contract)
    lead = lead_of_contract(contract)
    account = account_of_contract(contract)
    plan_dates = [e["stay_date"] for e in contract["nightly_allotments"]]
    require_calendar(plan_dates)
    check_group_ceiling([(e["stay_date"], e["rooms"])
                         for e in contract["nightly_allotments"]],
                        exclude_held=(quote["quoted_peak_rooms"]
                                      if quote is not None and quote["hold_placed"]
                                      else 0))
    if account is not None and account["credit_hold"]:
        fail("ERR_ACCOUNT_CREDIT_HOLD",
             "The client organization is on credit hold.")
    # ---- the countersignature cascade, one atomic step (PRD §3.5)
    contract["status"] = "SIGNED"
    contract["signed_by_user_id"] = actor()
    contract["signature_name"] = signature_name
    contract["signed_at"] = store.now_iso()
    arrival = parse_date_str(contract["arrival_date"])
    cutoff_date = arrival - timedelta(days=contract["cutoff_days_before_arrival"])
    master = new_row({
        "contract_id": contract["id"],
        "parent_block_id": None,
        "name": "MASTER",
        "inventory_status": "SETUP",
        "billing_status": "UNBILLED",
        "cutoff_date": iso_date(cutoff_date),
        "waived_by_user_id": None,
        "waiver_reason": None,
    })
    store.blocks[master["id"]] = master
    for entry in contract["nightly_allotments"]:
        night = new_row({
            "block_id": master["id"],
            "stay_date": entry["stay_date"],
            "rooms_allotted": entry["rooms"],
            "rooms_released": 0,
        })
        store.nights[night["id"]] = night
        move_committed(entry["stay_date"], entry["rooms"])
    if quote is not None:
        release_quote_hold(quote)
        touch(quote)
    if lead is not None:
        confirm_held_space(lead["id"])
    touch(contract)
    return ok(contract_json(contract))


@bp.route("/group-sales/contracts/<contract_id>/cancel", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN])
def cancel_contract(contract_id):
    body = body_json()
    reason = v_enum(body, "cancellation_reason", CANCELLATION_REASONS)
    v_string(body, "note", required=False, min_len=None, max_len=1000,
             allow_blank=True)
    contract = need_contract(contract_id)
    if contract["status"] not in ("SENT", "SIGNED"):
        fail("ERR_CONTRACT_INVALID_STATE",
             "Cancellation is declared from SENT or SIGNED; the contract is %s."
             % contract["status"])
    if store.today() >= parse_date_str(contract["arrival_date"]):
        fail("ERR_CONTRACT_INVALID_STATE",
             "The group has begun arriving; no cancellation transition is declared.")
    damages = cancellation_damages(contract, reason)
    contract["assessed_damages_cents"] = damages
    contract["cancellation_reason"] = reason
    contract["status"] = ("CANCELLED" if reason == "CLIENT_CANCEL"
                         else "TERMINATED_FORCE_MAJEURE")
    released = release_blocks_of_contract(contract)
    cancel_reservations_of_blocks(released)
    if reason == "FORCE_MAJEURE":
        void_all_charges(contract)
    recompute_receivable(contract)
    touch(contract)
    return ok(contract_json(contract))


@bp.route("/group-sales/contracts/<contract_id>/reconciliations", methods=["GET"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_ACCOUNTING_CLERK, ROLE_REVENUE_MANAGER])
def list_contract_reconciliations(contract_id):
    status = q_enum("status", RECONCILIATION_STATUSES)
    limit, offset = q_pagination()
    need_contract(contract_id)
    rows = reconciliations_of_contract(contract_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([reconciliation_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/contracts/<contract_id>/ancillary-charges", methods=["GET"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_ACCOUNTING_CLERK, ROLE_REVENUE_MANAGER,
           ROLE_GROUP_CONTACT])
def list_contract_charges(contract_id):
    category = q_enum("category", CHARGE_CATEGORIES)
    status = q_enum("status", CHARGE_STATUSES)
    limit, offset = q_pagination()
    contract = need_contract(contract_id)
    require_owner(owner_of_contract(contract))
    rows = charges_of_contract(contract_id)
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([charge_json(r) for r in page], limit, offset, total)
