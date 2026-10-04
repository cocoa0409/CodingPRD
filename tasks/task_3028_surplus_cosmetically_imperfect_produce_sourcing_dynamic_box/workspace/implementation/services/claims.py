"""§3.3 Make-Ready Outcomes, Claims and the Credit Ceiling."""

import clock
import common
import rules
import store
from common import ApiError
from services import centers, lots, suppliers


def claim_of(claim_id):
    claim = store.QUALITY_CLAIMS.get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404,
                       "No QualityClaim exists with the given id.")
    return claim


def cited_claim_is_earliest(claim):
    """§3.3: at least one OTHER claim on the same lot was upheld strictly earlier."""
    for other in store.QUALITY_CLAIMS.values():
        if other["id"] == claim["id"]:
            continue
        if other.get("supply_lot_id") != claim.get("supply_lot_id"):
            continue
        if not other.get("_upheld"):
            continue
        if store.created_before(other, claim):
            return True
    return False


def review(claim, outcome):
    """Adjudicate a claim, applying the §3.3 branch table."""
    item = store.BOX_BUILD_ITEMS.get(claim["box_build_item_id"])
    lot = store.SUPPLY_LOTS.get(claim.get("supply_lot_id"))
    order = store.BOX_ORDERS.get(claim["box_order_id"])
    status = claim["status"]

    # Rung 5: the from-state test runs before the rung 7 credibility rule.
    if status not in ("IN_REVIEW", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The claim is not in a state that admits a review.")
    # Rung 7: credibility runs before any lot quality assessment.
    if claim["requested_credit_cents"] == 0:
        raise ApiError("ERR_CLAIM_NOT_CREDIBLE", 422,
                       "A claim requesting nothing is not credible.")

    if status == "IN_REVIEW":
        return review_from_in_review(claim, outcome, item, lot, order)
    return review_from_under_review(claim, outcome, item, lot, order)


def review_from_in_review(claim, outcome, item, lot, order):
    if outcome == "UPHELD":
        if item is None or item["status"] != "INCLUDED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "The cited build item is not INCLUDED.")
        if lot is None or lot["quality_status"] != "PASS":
            raise ApiError("ERR_LOT_QUALITY_HOLD", 409,
                           "The cited lot's quality_status is not PASS.")
        claim["status"] = "UPHELD"
        claim["outcome"] = "UPHELD"
        claim["credited_cents"] = rules.cap_quality_credit(claim, item, lot)
        claim["_upheld"] = True
        store.touch(claim)
        suppliers.recompute_for_claim(claim)
        centers.refresh_claim_count(store.FULFILLMENT_CENTERS.get(
            _center_of_claim(claim)))
        _refresh_order(order)
        return claim

    # Rejected: the escalation branch needs both conditions together.
    escalation = (clock.parse_instant(claim["created_at"])
                  > clock.plus_days(clock.parse_instant(item["created_at"]),
                                    common.CLAIM_WINDOW_DAYS_ESCALATION)
                  if item is not None else False)
    prior_upheld = cited_claim_is_earliest(claim)
    if escalation and prior_upheld:
        claim["status"] = "UNDER_REVIEW"
        claim["outcome"] = None
        store.touch(claim)
        if lot is not None:
            lot["quality_status"] = "INVESTIGATION"
            store.touch(lot)
        _refresh_center(claim)
        return claim

    # §3.3 renders exactly two rejection branches, and the plain close is the
    # one that applies "when the claim is young enough that the escalation path
    # did not open" — so it is the complement of the escalation test, taken
    # whenever the claim is not older than the window (or lacks the upheld
    # sibling the escalation needs). §3.3 lists no third rejection outcome.
    claim_age_seconds = (
        clock.now() - clock.parse_instant(claim["created_at"])
    ).total_seconds()
    if claim_age_seconds < common.CLAIM_WINDOW_DAYS * 86400:
        claim["status"] = "CLOSED"
        claim["outcome"] = "REJECTED"
        claim["credited_cents"] = 0
        store.touch(claim)
        _refresh_center(claim)
        _refresh_order(order)
        return claim

    raise ApiError("ERR_INVALID_STATE", 409,
                   "A rejected review is not admitted on this claim at this time.")


def review_from_under_review(claim, outcome, item, lot, order):
    if outcome == "UPHELD":
        if order is None or order["status"] not in ("PACKED", "SHIPPED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "An upheld review requires a packed or shipped box.")
        claim["status"] = "UPHELD"
        claim["outcome"] = "UPHELD"
        claim["credited_cents"] = rules.cap_quality_credit(claim, item, lot)
        claim["_upheld"] = True
        store.touch(claim)
        if lot is not None:
            lot["quality_status"] = "PASS"
            store.touch(lot)
        suppliers.recompute_for_claim(claim)
        _refresh_center(claim)
        _refresh_order(order)
        return claim

    if lot is None or lot["quality_status"] != "INVESTIGATION":
        raise ApiError("ERR_LOT_QUALITY_HOLD", 409,
                       "The cited lot is not under investigation.")
    claim["status"] = "REJECTED"
    claim["outcome"] = "REJECTED"
    claim["credited_cents"] = 0
    store.touch(claim)
    # The terminal quality outcome: a second upheld-into-investigation lot.
    lot["quality_status"] = "REJECTED"
    store.touch(lot)
    lots.expiring_cascade(lot)
    _refresh_center(claim)
    _refresh_order(order)
    return claim


def reopen(claim):
    if claim["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a rejected claim can be reopened.")
    lot = store.SUPPLY_LOTS.get(claim.get("supply_lot_id"))
    if lot is not None and lot["status"] == "EXPIRED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The cited lot has expired; the claim cannot be reopened.")
    claim["status"] = "IN_REVIEW"
    claim["outcome"] = None
    store.touch(claim)
    _refresh_center(claim)
    return claim


def _center_of_claim(claim):
    lot = store.SUPPLY_LOTS.get(claim.get("supply_lot_id"))
    if lot is not None:
        return lot["fulfillment_center_id"]
    order = store.BOX_ORDERS.get(claim["box_order_id"])
    if order is not None:
        return order["fulfillment_center_id"]
    return None


def _refresh_center(claim):
    center_id = _center_of_claim(claim)
    if center_id is None:
        return
    center = store.FULFILLMENT_CENTERS.get(center_id)
    if center is None:
        return
    centers.refresh_claim_count(center)
    centers.refresh_posture(center)


def _refresh_order(order):
    if order is None:
        return
    from services import builds

    builds.refresh_order_derivations(order)
    store.touch(order)