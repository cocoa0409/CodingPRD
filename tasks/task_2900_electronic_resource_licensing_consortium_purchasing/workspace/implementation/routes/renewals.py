"""Section 3.8 and 3.9 - renewal ballots, the three-way fork and execution."""

from flask import Blueprint, request

import auth
import calc
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("renewals", __name__)

OPEN_DECISION_STATUSES = ("DRAFT", "VOTING")


def _product_of(subscription):
    return store.products[subscription["product_id"]]


def _decisions_of(subscription_id):
    return store.sort_rows([
        d for d in store.renewal_decisions.values()
        if d["subscription_id"] == subscription_id
    ])


def _quorum_needed(confirmed_count):
    """ceil(confirmed * VOTE_QUORUM_PCT / 100) in exact integer arithmetic."""
    numerator = confirmed_count * calc.VOTE_QUORUM_PCT
    return -(-numerator // 100)


@bp.post("/erm/subscriptions/<subscription_id>/renewal-decisions")
def create_decision(subscription_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    subscription = auth.get_subscription(subscription_id)
    data = shape.body()
    recommended_action = shape.req_enum(data, "recommended_action", shape.DECISION_ACTIONS)
    vendor_requested_increase_pct = shape.req_number(
        data, "vendor_requested_increase_pct", minimum=0
    )
    expected = shape.req_int(data, "expected_subscription_version", minimum=0)
    titles_out = shape.opt_string_array(data, "titles_out", [])
    titles_in = shape.opt_string_array(data, "titles_in", [])

    # priority 7 - optimistic concurrency on the subscription aggregate
    if expected != subscription["version"]:
        raise ApiError("ERR_STALE_SUBSCRIPTION_VERSION")

    for decision in _decisions_of(subscription["id"]):
        if decision["status"] in OPEN_DECISION_STATUSES:
            store.mutate(decision, {"status": "SUPERSEDED"})

    row = store.new_row({
        "subscription_id": subscription["id"],
        "status": "DRAFT",
        "recommended_action": recommended_action,
        "resolved_action": None,
        "vendor_requested_increase_pct": vendor_requested_increase_pct,
        "capped_increase_pct": None,
        "cost_per_use_cents": None,
        "cost_per_use_band": None,
        "loyalty_credit_cents": 0,
        "sla_credit_applied_cents": 0,
        "offer_price_cents": None,
        "ballots": [],
        "yes_count": 0,
        "quorum_met": False,
        "titles_out": titles_out,
        "titles_in": titles_in,
        "delta_price_cents": None,
    })
    store.renewal_decisions[row["id"]] = row
    store.touch(subscription)
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/subscriptions/<subscription_id>/renewal-decisions")
def list_decisions(subscription_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN)
    subscription = auth.get_subscription(subscription_id)
    rows = [
        d for d in store.renewal_decisions.values()
        if d["subscription_id"] == subscription["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return envelope.paged(rows)


@bp.post("/erm/renewal-decisions/<decision_id>/open-vote")
def open_vote(decision_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    decision = auth.get_renewal_decision(decision_id)
    if decision["status"] != "DRAFT":
        raise ApiError("ERR_RENEWAL_INVALID_STATE")
    subscription = store.subscriptions[decision["subscription_id"]]
    if subscription["contract_status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")
    if not services.commitments_of_subscription(subscription["id"], ("CONFIRMED",)):
        raise ApiError(
            "ERR_COMMITMENT_INVALID_STATE",
            "No CONFIRMED commitment exists on the subscription, so there is nobody to vote.",
        )
    offer = calc.renewal_offer_price(subscription, decision, _product_of(subscription))
    changes = dict(offer)
    changes["status"] = "VOTING"
    store.mutate(decision, changes)
    return envelope.object_response(store.serialize(decision))


@bp.post("/erm/renewal-decisions/<decision_id>/vote")
def cast_ballot(decision_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    decision = auth.get_renewal_decision(decision_id)
    data = shape.body()
    if shape.present(data, "member_id"):
        auth.get_member(data["member_id"])
        auth.require_member_scope(data["member_id"])
    member_id = shape.req_string(data, "member_id")
    ballot = shape.req_string(data, "ballot")

    if decision["status"] != "VOTING":
        raise ApiError("ERR_RENEWAL_INVALID_STATE")

    # priority 21 - one ballot per member
    for entry in decision["ballots"]:
        if entry["member_id"] == member_id:
            raise ApiError("ERR_DUPLICATE_BALLOT")

    # priority 22 - only confirmed participants vote
    confirmed = services.commitments_of_subscription(
        decision["subscription_id"], ("CONFIRMED",)
    )
    if not any(c["member_id"] == member_id for c in confirmed):
        raise ApiError("ERR_MEMBER_NOT_PARTICIPANT")

    ballots = list(decision["ballots"])
    ballots.append({
        "member_id": member_id,
        "ballot": ballot,
        "cast_at": store.clock_iso(),
    })
    store.mutate(decision, {
        "ballots": ballots,
        "yes_count": len([b for b in ballots if b["ballot"] == "YES"]),
        "quorum_met": len(ballots) >= _quorum_needed(len(confirmed)),
    })
    return envelope.object_response(store.serialize(decision))


def _validate_title_swap(decision, delta_price_cents):
    titles_out = decision["titles_out"]
    titles_in = decision["titles_in"]
    if not titles_out or not titles_in:
        raise ApiError("ERR_TITLE_SWAP_INVALID")
    if len(set(titles_out)) != len(titles_out) or len(set(titles_in)) != len(titles_in):
        raise ApiError("ERR_TITLE_SWAP_INVALID")
    if set(titles_out) & set(titles_in):
        raise ApiError("ERR_TITLE_SWAP_INVALID")
    if delta_price_cents is None:
        raise ApiError("ERR_TITLE_SWAP_INVALID")


@bp.post("/erm/renewal-decisions/<decision_id>/decide")
def decide(decision_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    decision = auth.get_renewal_decision(decision_id)
    data = shape.body()
    resolved_action = shape.req_enum(data, "resolved_action", shape.DECISION_ACTIONS)
    delta_price_cents = shape.opt_int(data, "delta_price_cents")
    accept_capped_offer = shape.opt_bool(data, "accept_capped_offer", False)

    if decision["status"] != "VOTING":
        raise ApiError("ERR_RENEWAL_INVALID_STATE")
    subscription = store.subscriptions[decision["subscription_id"]]
    product = _product_of(subscription)
    if resolved_action == "CANCEL" and subscription["contract_status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")

    # priority 20 - quorum is the shared floor of all three branches
    if not decision["quorum_met"]:
        raise ApiError("ERR_VOTE_QUORUM_NOT_MET")

    if resolved_action == "RESTRUCTURE":
        _validate_title_swap(decision, delta_price_cents)
    if resolved_action == "RENEW":
        # priority 33 - the consortium either fits the cap or accepts it explicitly
        if calc.dec(decision["vendor_requested_increase_pct"]) > calc.dec(product["inflation_cap_pct"]) \
                and accept_capped_offer is not True:
            raise ApiError("ERR_INFLATION_CAP_EXCEEDED")

    if resolved_action == "RENEW":
        offer = calc.renewal_offer_price(subscription, decision, product)
        changes = dict(offer)
        changes["resolved_action"] = "RENEW"
        changes["status"] = "DECIDED_RENEW"
        store.mutate(decision, changes)
    elif resolved_action == "CANCEL":
        store.mutate(decision, {"resolved_action": "CANCEL", "status": "DECIDED_CANCEL"})
        store.mutate(subscription, {"contract_status": "NOTICE_GIVEN"})
    else:
        store.mutate(decision, {
            "resolved_action": "RESTRUCTURE",
            "delta_price_cents": delta_price_cents,
            "status": "DECIDED_RESTRUCTURE",
        })
    return envelope.object_response(store.serialize(decision))


def _execute_renew(decision, subscription, product):
    old_term_end = subscription["term_end"]
    new_term_end = calc.add_one_year(old_term_end)
    store.mutate(decision, {"status": "EXECUTED"})
    store.mutate(subscription, {
        "negotiated_price_cents": decision["offer_price_cents"],
        "term_start": calc.add_days(old_term_end, 1),
        "term_end": new_term_end,
        "notice_deadline_date": calc.add_days(
            new_term_end, -product["cancellation_notice_days"]
        ),
        "sla_credit_cents": 0,
        "degrade_count": 0,
        "renewal_term_count": subscription["renewal_term_count"] + 1,
    })
    services.reprice_confirmed_commitments(subscription)


def _execute_cancel(decision, subscription):
    # priority 14 - the archival evidence must exist
    verified = any(
        check["subscription_id"] == subscription["id"] and check["status"] == "VERIFIED"
        for check in store.archival_checks.values()
    )
    if not verified:
        raise ApiError("ERR_ARCHIVAL_DEPOSIT_UNVERIFIED")
    # priority 18 - executing on the deadline date itself is timely
    if store.clock_date() > subscription["notice_deadline_date"]:
        raise ApiError("ERR_NOTICE_DEADLINE_PASSED")

    store.mutate(decision, {"status": "EXECUTED"})
    access_status = "SUSPENDED" if subscription["perpetual_access_mode"] == "NONE" \
        else "POST_CANCELLATION"
    store.mutate(subscription, {
        "contract_status": "CANCELLED",
        "access_status": access_status,
    })
    services.release_commitments(subscription)


def _execute_restructure(decision, subscription):
    if subscription["access_status"] != "CONFIGURED":
        raise ApiError("ERR_SUBSCRIPTION_ACCESS_INVALID_STATE")
    resulting = subscription["entitled_title_count"] \
        - len(decision["titles_out"]) + len(decision["titles_in"])
    if resulting < calc.MIN_ENTITLED_TITLES:
        raise ApiError("ERR_TITLE_COUNT_FLOOR_BREACHED")
    store.mutate(decision, {"status": "EXECUTED"})
    store.mutate(subscription, {
        "entitled_title_count": resulting,
        "negotiated_price_cents": subscription["negotiated_price_cents"]
        + (decision["delta_price_cents"] or 0),
    })
    services.reprice_confirmed_commitments(subscription)


@bp.post("/erm/renewal-decisions/<decision_id>/execute")
def execute(decision_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    decision = auth.get_renewal_decision(decision_id)
    status = decision["status"]
    if status not in ("DECIDED_RENEW", "DECIDED_CANCEL", "DECIDED_RESTRUCTURE"):
        raise ApiError("ERR_RENEWAL_INVALID_STATE")
    subscription = store.subscriptions[decision["subscription_id"]]
    product = _product_of(subscription)

    if status == "DECIDED_RENEW":
        if subscription["contract_status"] != "ACTIVE":
            raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")
        _execute_renew(decision, subscription, product)
    elif status == "DECIDED_CANCEL":
        if subscription["contract_status"] != "NOTICE_GIVEN":
            raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")
        _execute_cancel(decision, subscription)
    else:
        if subscription["contract_status"] != "ACTIVE":
            raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")
        _execute_restructure(decision, subscription)
    return envelope.object_response(store.serialize(decision))


@bp.post("/erm/renewal-decisions/<decision_id>/revert-restructure")
def revert_restructure(decision_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    decision = auth.get_renewal_decision(decision_id)
    if decision["status"] != "EXECUTED" or decision["resolved_action"] != "RESTRUCTURE":
        raise ApiError("ERR_RENEWAL_INVALID_STATE")
    subscription = store.subscriptions[decision["subscription_id"]]
    if subscription["contract_status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_CONTRACT_INVALID_STATE")

    store.mutate(subscription, {
        "entitled_title_count": subscription["entitled_title_count"]
        + len(decision["titles_out"]) - len(decision["titles_in"]),
        "negotiated_price_cents": subscription["negotiated_price_cents"]
        - (decision["delta_price_cents"] or 0),
    })
    services.reprice_confirmed_commitments(subscription)
    store.mutate(decision, {"status": "REVERTED"})
    return envelope.object_response(store.serialize(decision))
