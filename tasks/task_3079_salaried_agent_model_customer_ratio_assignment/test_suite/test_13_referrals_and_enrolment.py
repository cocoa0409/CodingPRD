"""Corner tests — referral settlement, capacity ceilings and enrolment gating (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    create_referral,
    reconcile_referral,
    create_listing,
    publish_listing,
    make_listing_agent_headers,
    set_clock,
    region_version,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_referral_fee_bps_above_the_ceiling_is_refused():
    """PRD §3.8: "The fee rate is expressed in basis points, must be greater than zero, and may not exceed the ceiling of 2500, or it is refused with `ERR_REFERRAL_FEE_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/referral_above_the_fee_ceiling_returns_referral_fee_exceeded
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Omar Overflow", service_area_code="98101")
    version = region_version(region["id"])

    resp = api_client.create_referral(
        {"client_id": client["id"], "partner_name": "Cascade Realty",
         "referral_fee_bps": 2501, "split_policy": "SPLIT_25_PARTNER",
         "expected_region_version": version},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_REFERRAL_FEE_EXCEEDED)
    assert data["error_id"] == "ERR_REFERRAL_FEE_EXCEEDED", data
    assert data["error_id"] != "ERR_REGION_CAPACITY_EXCEEDED", data


def test_referral_fee_bps_at_the_ceiling_is_admitted():
    """PRD §3.8: "A recorded referral starts at `settlement_status` `PENDING` and sets the client to `REFERRED` with `assignment_mode` `REFERRED_PARTNER`; the client's `assigned_agent_id` stays null."

    Design: Corner/validations/referral_above_the_fee_ceiling_returns_referral_fee_exceeded
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    client = create_client(full_name="Priya Overflow", service_area_code="98102")

    referral = create_referral(client["id"], region["id"], referral_fee_bps=2500,
                               split_policy="SPLIT_25_PARTNER")
    assert referral["settlement_status"] == "PENDING", referral

    listed = get_success_data(api_client.list_region_referrals(
        region["id"], PLATFORM_ADMIN, params={"limit": 50},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert len(rows) == 1, rows


def test_reconcile_without_a_contract_price_is_refused_and_moves_nothing():
    """PRD §3.8: "A referral in `PENDING` cannot be computed until a contract price exists for the referred client: an attempt without one is refused with `ERR_NO_CONTRACT_PRICE` (HTTP 409)".

    Design: Corner/state_machines/agent_referral_reconcile_requires_a_contract_price_before_computation
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    client = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(client["id"], region["id"])

    resp = api_client.reconcile_referral(
        referral["id"], {"contract_price_cents": 0}, TRANSACTION_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_NO_CONTRACT_PRICE)
    assert data["error_id"] == "ERR_NO_CONTRACT_PRICE", data

    unchanged = get_success_data(api_client.get_referral(referral["id"], PLATFORM_ADMIN))
    assert unchanged["settlement_status"] == "PENDING", unchanged


def test_reconcile_succeeds_once_a_contract_price_exists():
    """PRD §3.8: "Once a price exists, reconciling the referral recomputes `referral_fee_cents` through the split and moves `settlement_status` from `PENDING` to `COMPUTED`".

    Design: Corner/state_machines/agent_referral_reconcile_requires_a_contract_price_before_computation
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    client = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(client["id"], region["id"])

    computed = reconcile_referral(referral["id"], 100_000_000)
    assert computed["settlement_status"] == "COMPUTED", computed
    assert computed["referral_fee_cents"] == 15_000_000, computed


def test_settling_a_referral_removes_it_from_the_open_referral_ledger():
    """PRD §3.8: "Settling is terminal: it requires a `settlement_reference`, moves the status to `SETTLED`, freezes the fee, and leaves the ledger — `SETTLED` rows are excluded from `open_referral_count` forever and nothing re-adds them."
    PRD §2.5: "`open_referral_count` counts only the region's referrals whose `settlement_status` is `PENDING` or `COMPUTED`, so `SETTLED` rows leave the open-referral ledger".

    Design: Corner/calculations/region_open_referral_count_drops_when_a_referral_settles
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    client = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(client["id"], region["id"])
    reconcile_referral(referral["id"], 100_000_000)

    before = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert before["open_referral_count"] == 1, before

    settled = get_success_data(api_client.settle_referral(
        referral["id"], {"settlement_reference": "SETTLE-2026-0001"}, TRANSACTION_COORDINATOR,
    ))
    assert settled["settlement_status"] == "SETTLED", settled

    after = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert after["open_referral_count"] == 0, after
    assert after["referral_count"] == 1, after


def test_settled_referral_is_still_visible_in_the_settlement_filtered_list():
    """PRD §3.8: "`SETTLED` rows are excluded from `open_referral_count` forever and nothing re-adds them."

    Design: Corner/calculations/region_open_referral_count_drops_when_a_referral_settles
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    client = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(client["id"], region["id"])
    reconcile_referral(referral["id"], 100_000_000)
    get_success_data(api_client.settle_referral(
        referral["id"], {"settlement_reference": "SETTLE-2026-0001"}, TRANSACTION_COORDINATOR,
    ))

    listed = get_success_data(api_client.list_region_referrals(
        region["id"], PLATFORM_ADMIN, params={"settlement_status": "SETTLED"},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert len(rows) == 1, rows


def test_region_that_requires_enrolment_refuses_an_unacknowledged_registration():
    """PRD §3.6: "on a region that requires enrolment the same acknowledgement rule applies, and the window is only written when each adjacent window leaves no unregistered gap".
    PRD §3.8: "when a region requires enrolment and a partner acceptance arrives without the enrolment acknowledgement, it is refused with `ERR_ENROLMENT_NOT_CONFIRMED` (HTTP 409)".

    Design: Corner/errors/listing_registration_under_a_mandatory_enrolment_region_requires_acknowledgement
    """
    strict = create_region(target_client_ratio=4.0, enrolment_is_required=True)
    lead = create_lead_agent(strict["id"], home_zip="98101")
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])
    listing = create_listing(seller["id"], lead["id"], strict["id"])
    publish_listing(listing["id"], lead["id"])

    resp = api_client.register_listing_window(
        listing["id"], {"enrolment_acknowledged": False, "window_days": 14},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_ENROLMENT_NOT_CONFIRMED)
    assert data["error_id"] == "ERR_ENROLMENT_NOT_CONFIRMED", data


def test_enrolment_rule_is_inert_on_a_region_that_does_not_require_it():
    """PRD §2.5: "`enrolment_is_required` defaults to false, and only a region that sets it true enforces the benefit-enrolment acknowledgement".

    Design: Corner/errors/listing_registration_under_a_mandatory_enrolment_region_requires_acknowledgement
    """
    loose = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(loose["id"], home_zip="98102")
    seller = create_client(full_name="Tina Seller", service_area_code="98102", need_kind="SELL")
    assign_client(seller["id"])
    listing = create_listing(seller["id"], lead["id"], loose["id"])
    publish_listing(listing["id"], lead["id"])

    resp = api_client.register_listing_window(
        listing["id"], {"enrolment_acknowledged": False, "window_days": 14},
        make_listing_agent_headers(lead["id"]),
    )
    assert resp.status_code == 200, resp.text

    after = get_success_data(api_client.get_listing_agreement(listing["id"], PLATFORM_ADMIN))
    assert after["service_commitment_hours"] == 24, after