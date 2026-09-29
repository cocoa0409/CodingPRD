"""The two optimistic-concurrency guards seen from both sides, and the counter
conservation that withdrawal completes inside the very request that performs it."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import MECHANICAL_POLICY
from test_helpers.factories import (
    build_case_world,
    build_sale_world,
    case_payload,
    create_evidence,
    create_transport_leg,
    transport_leg_payload,
    withdraw_case,
)
from test_helpers.test_users import admin_headers, buyer_rep_headers

YELLOW_SALE = {"light_channel": "YELLOW"}
MECHANICAL_CLAIM = {
    "defect_class": "MECHANICAL",
    "claim_amount_cents": 60000,
    "odometer_at_claim": 84100,
    "complaint_text": "Transmission slips under load",
}


def _case_bumped_by_evidence(api):
    """A SUBMITTED case read at version 1, then advanced to version 2 by one
    evidence append made behind the version the caller is still holding."""
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )
    stale_version = world["case"]["version"]
    evidence = create_evidence(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )
    world["stale_version"] = stale_version
    world["bumped_version"] = evidence["case_version_after"]
    return world


def test_a_transport_leg_carrying_the_pre_evidence_case_version_is_refused(api):
    """The evidence append moved the case out from under the caller, so the leg it
    then tries to price is refused on the version it carried and nothing is written.

    PRD: "If that value does not equal the case's current `version`, the request is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) and no leg is written."

    Design: Corner/complexity_layers/a_stale_expected_case_version_is_rejected_with_412
    """
    world = _case_bumped_by_evidence(api)
    assert world["stale_version"] == 1
    assert world["bumped_version"] == 2

    response = api.create_transport_leg(
        world["case"]["id"],
        transport_leg_payload(
            world["stale_version"],
            100,
            "INBOUND_TO_AUCTION",
            carrier_name="Blue Ridge Transport",
        ),
        admin_headers(),
    )

    validate_error(response, ApiErrorId.ERR_STALE_CASE_VERSION.value)
    assert response.status_code == 412

    legs, meta = validate_unpaginated(
        api.list_transport_legs(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert legs == []

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["version"] == 2


def test_the_observed_case_version_is_accepted_and_the_leg_advances_it_by_one(api):
    """Carrying the version the evidence append produced admits the leg, prices its
    100 miles at the dispatch fee plus the first band, and records the case version its
    own append produced.

    PRD: "A written leg records its `case_id` from the path, a `recorded_at_utc` from
    the logical clock, its computed `cost_cents`, and the `case_version_after` value
    produced by its own append; it is immutable and carries no `updated_at` and no
    `version`."

    Design: Corner/complexity_layers/the_current_case_version_is_accepted_and_the_write_bumps_it
    """
    world = _case_bumped_by_evidence(api)
    assert world["bumped_version"] == 2

    leg = create_transport_leg(
        api,
        world["case"]["id"],
        expected_case_version=world["bumped_version"],
        miles=100,
        leg_type="INBOUND_TO_AUCTION",
        carrier_name="Blue Ridge Transport",
    )

    assert leg["cost_cents"] == 27000
    assert leg["case_version_after"] == 3
    assert leg["leg_type"] == "INBOUND_TO_AUCTION"
    assert leg["miles"] == 100
    assert leg["case_id"] == world["case"]["id"]
    assert "version" not in leg
    assert "updated_at" not in leg

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["version"] == 3

    legs, meta = validate_unpaginated(
        api.list_transport_legs(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert legs[0]["id"] == leg["id"]


def test_a_fee_payment_carrying_the_pre_claim_bidder_version_is_refused(api):
    """Filing the claim bumped the bidder's version behind the caller's back, and that
    check runs ahead of the amount check the 1000 cents would also have failed.

    PRD: "`expected_buyer_version` equals the buyer's current `version` — else
    `ERR_STALE_BUYER_VERSION`. This guards fee payment, and it is checked *before* the
    payment-amount check."

    Design: Corner/complexity_layers/a_stale_expected_buyer_version_is_rejected_with_412
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], **YELLOW_SALE)
    buyer_id = world["buyer"]["id"]
    before = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    stale_version = before["version"]
    assert stale_version == 1

    validate_success(
        api.create_case(
            case_payload(world["sale"]["id"], **MECHANICAL_CLAIM),
            buyer_rep_headers(buyer_id),
        ),
        201,
    )

    response = api.pay_buyer_fee(
        buyer_id,
        {"amount_cents": 1000, "expected_buyer_version": stale_version},
        buyer_rep_headers(buyer_id),
    )

    validate_error(response, ApiErrorId.ERR_STALE_BUYER_VERSION.value)
    assert response.status_code == 412

    stored = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert stored["version"] == 2
    assert stored["frivolous_fee_balance_cents"] == 0
    assert stored["open_claim_count"] == 1
    assert stored["claim_privilege_status"] == "ACTIVE"


def test_withdrawal_releases_every_counter_inside_its_own_request(api):
    """The reads taken straight after the withdrawal already show all four aggregates
    back at their pre-claim values, so nothing waits on the deadline sweep.

    PRD: "File a claim and then withdraw it, and all four conditions return to their
    pre-claim values — including the sale's `arbitration_status` reverting from
    `ACTIVE` back to `NONE`."

    Design: Corner/consistency_model/withdraw_restores_every_counter_within_the_same_request
    """
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )
    before = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert before["open_case_count"] == 1
    assert before["arbitration_status"] == "ACTIVE"

    withdrawn = withdraw_case(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        reason="Buyer resold the unit as-is",
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == 2

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 0
    assert sale["arbitration_status"] == "NONE"

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["open_claim_count"] == 0
    assert buyer["lifetime_claim_count"] == 1

    seller = validate_success(api.get_seller(world["seller"]["id"], admin_headers()), 200)
    assert seller["open_claim_count"] == 0
    assert seller["policy_tier"] == "GOOD_STANDING"
