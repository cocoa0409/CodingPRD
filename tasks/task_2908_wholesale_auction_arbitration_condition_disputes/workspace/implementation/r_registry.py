"""Registry routes: consignors, buying dealers and published arbitration policy."""
from flask import Blueprint

import services as S
import store as C
from authz import ALL_ROLES, authenticate
from envelope import created, obj, unpaginated
from errors import fail
from store import store
from util import public, public_list
from validators import (json_body, opt_int, present, req_bool, req_enum, req_int,
                        req_str)

bp = Blueprint("registry", __name__)


def _license_taken(license_no):
    for row in list(store.sellers.values()) + list(store.buyers.values()):
        if row["dealer_license_no"] == license_no:
            return True
    return False


@bp.route("/arbitration/sellers", methods=["POST"])
def create_seller():
    authenticate(["AuctionAdmin"])
    body = json_body()
    name = req_str(body, "name", 1, 120)
    license_no = req_str(body, "dealer_license_no", 4, 24)
    if _license_taken(license_no):
        fail("ERR_DUPLICATE_DEALER_LICENSE")
    row = {
        "name": name,
        "dealer_license_no": license_no,
        "policy_tier": "GOOD_STANDING",
        "rolling_arbitration_rate_bps": 0,
        "lifetime_arbitration_rate_bps": 0,
        "rolling_window_sales_count": 0,
        "rolling_window_upheld_count": 0,
        "lifetime_sales_count": 0,
        "lifetime_upheld_count": 0,
        "open_claim_count": 0,
        "blocked_at_utc": None,
        "reinstated_count": 0,
    }
    store.insert("sellers", row, mutable=True)
    return created(public(row))


@bp.route("/arbitration/sellers/<seller_id>", methods=["GET"])
def read_seller(seller_id):
    authenticate(ALL_ROLES)
    return obj(public(S.get_seller(seller_id)))


@bp.route("/arbitration/buyers", methods=["POST"])
def create_buyer():
    authenticate(["AuctionAdmin"])
    body = json_body()
    name = req_str(body, "name", 1, 120)
    license_no = req_str(body, "dealer_license_no", 4, 24)
    if _license_taken(license_no):
        fail("ERR_DUPLICATE_DEALER_LICENSE")
    row = {
        "name": name,
        "dealer_license_no": license_no,
        "claim_privilege_status": "ACTIVE",
        "frivolous_claim_count": 0,
        "frivolous_fee_balance_cents": 0,
        "open_claim_count": 0,
        "lifetime_claim_count": 0,
    }
    store.insert("buyers", row, mutable=True)
    return created(public(row))


@bp.route("/arbitration/buyers/<buyer_id>", methods=["GET"])
def read_buyer(buyer_id):
    authenticate(ALL_ROLES)
    return obj(public(S.get_buyer(buyer_id)))


@bp.route("/arbitration/policies", methods=["POST"])
def create_policy():
    authenticate(["AuctionAdmin"])
    body = json_body()
    defect_class = req_enum(body, "defect_class", C.DEFECT_CLASSES)
    min_claim = req_int(body, "min_claim_amount_cents", 0)
    requires_tpv = req_bool(body, "requires_third_party_verification")
    max_allowance_bps = req_int(body, "max_allowance_bps", 0, 10000)
    psi_extension_hours = req_int(body, "psi_extension_hours", 0)
    psi_clean_waives_rights = req_bool(body, "psi_clean_waives_rights")
    window_hours = opt_int(body, "window_hours", 1)
    mileage_limit = opt_int(body, "mileage_limit", 0)
    seller_response_hours = opt_int(body, "seller_response_hours", 1,
                                    default=C.DEFAULT_SELLER_RESPONSE_HOURS)
    if S.policy_for_defect_class(defect_class) is not None:
        fail("ERR_DUPLICATE_POLICY_DEFECT_CLASS")
    row = {
        "defect_class": defect_class,
        "window_hours": window_hours,
        "mileage_limit": mileage_limit,
        "min_claim_amount_cents": min_claim,
        "requires_third_party_verification": requires_tpv,
        "max_allowance_bps": max_allowance_bps,
        "psi_extension_hours": psi_extension_hours,
        "psi_clean_waives_rights": psi_clean_waives_rights,
        "seller_response_hours": seller_response_hours,
    }
    store.insert("policies", row, mutable=True)
    return created(public(row))


@bp.route("/arbitration/policies/<policy_id>", methods=["GET"])
def read_policy(policy_id):
    authenticate(ALL_ROLES)
    return obj(public(S.get_policy(policy_id)))


# --- buyer consequences ------------------------------------------------------

@bp.route("/arbitration/buyers/<buyer_id>/fee-payments", methods=["POST"])
def pay_fees(buyer_id):
    authenticate(["BuyerRep"])
    body = json_body()
    amount = req_int(body, "amount_cents", 0)
    expected_version = req_int(body, "expected_buyer_version")
    buyer = S.get_buyer(buyer_id)
    if expected_version != int(buyer["version"]):
        fail("ERR_STALE_BUYER_VERSION")
    if amount > int(buyer["frivolous_fee_balance_cents"]):
        fail("ERR_PAYMENT_EXCEEDS_BALANCE")
    buyer["frivolous_fee_balance_cents"] = int(buyer["frivolous_fee_balance_cents"]) - amount
    if (int(buyer["frivolous_fee_balance_cents"]) == 0
            and int(buyer["frivolous_claim_count"]) < C.FRIVOLOUS_SUSPENSION_COUNT
            and buyer["claim_privilege_status"] == "FEE_HOLD"):
        buyer["claim_privilege_status"] = "ACTIVE"
    S.touch(buyer)
    return obj(public(buyer))


@bp.route("/arbitration/buyers/<buyer_id>/frivolous-fees", methods=["GET"])
def list_buyer_fees(buyer_id):
    authenticate(ALL_ROLES)
    buyer = S.get_buyer(buyer_id)
    return unpaginated(public_list(S.children("fees", "buyer_id", buyer["id"])))


# --- seller consequences -----------------------------------------------------

@bp.route("/arbitration/sellers/<seller_id>/reinstate", methods=["POST"])
def reinstate_seller(seller_id):
    authenticate(["AuctionAdmin"])
    body = json_body()
    note = req_str(body, "reinstate_note")
    seller = S.get_seller(seller_id)
    if seller["policy_tier"] != "BLOCKED":
        fail("ERR_SELLER_NOT_BLOCKED")
    from_tier = seller["policy_tier"]
    seller["policy_tier"] = "PROBATION"
    seller["blocked_at_utc"] = None
    seller["reinstated_count"] = int(seller["reinstated_count"]) + 1
    S.append_policy_action(seller, None, "REINSTATE", from_tier, "PROBATION",
                           seller["rolling_arbitration_rate_bps"], note)
    for sale in S.store.rows("sales"):
        if sale["seller_id"] != seller["id"]:
            continue
        sale["settlement_hold"] = False
        S.touch(sale)
    S.touch(seller)
    return obj(public(seller))


@bp.route("/arbitration/sellers/<seller_id>/policy-actions", methods=["GET"])
def list_seller_actions(seller_id):
    authenticate(ALL_ROLES)
    seller = S.get_seller(seller_id)
    return unpaginated(public_list(S.children("policy_actions", "seller_id", seller["id"])))


@bp.route("/arbitration/sellers/<seller_id>/scorecard", methods=["GET"])
def read_scorecard(seller_id):
    authenticate(ALL_ROLES)
    seller = S.get_seller(seller_id)
    figures = S.compute_scorecard(seller)
    payload = {"seller_id": seller["id"]}
    for key in ("rolling_window_sales_count", "rolling_window_upheld_count",
                "rolling_arbitration_rate_bps", "lifetime_sales_count",
                "lifetime_upheld_count", "lifetime_arbitration_rate_bps", "policy_tier"):
        payload[key] = figures[key]
    payload["computed_at_utc"] = store.now_iso()
    return obj(payload)
