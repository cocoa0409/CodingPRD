"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API, so a
test can start from an empty database and reach a deep state in one call.
Setup calls use the lenient validator so a broken precondition surfaces as a
"Setup step failed" message rather than a confusing assertion later on.
"""

import copy
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AFTER_TERM_END,
    DEFAULT_TIER_BREAKS,
    SEASON_START,
    WINDOW_END,
    WINDOW_START,
)
from .factories import (
    create_asset_booking_payload,
    create_contract_payload,
    create_entitlement_payload,
    create_inventory_asset_payload,
    create_property_payload,
    create_proof_payload,
    create_rate_card_line_payload,
    create_rate_card_payload,
    create_sponsor_payload,
    create_staff_assignment_payload,
    create_staff_member_payload,
    create_survey_payload,
)
from .test_users import (
    ACTIVATION_USER_ID,
    APPROVER_USER_ID,
    AUDITOR_USER_ID,
    PROPERTY_ADMIN_USER_ID,
    SELLER_USER_ID,
    TEST_USERS,
    make_activation_headers,
    make_approver_headers,
    make_auditor_headers,
    make_property_admin_headers,
    make_seller_headers,
    make_sponsor_contact_headers,
)

ADMIN = TEST_USERS["property_admin_headers"]
SELLER = TEST_USERS["seller_headers"]
APPROVER = TEST_USERS["approver_headers"]
ACTIVATION = TEST_USERS["activation_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --------------------------------------------------------------------------
# Canonical specifications reused by the composite setups
# --------------------------------------------------------------------------
DIGITAL_BOARD_LINE = {
    "asset_class": "DIGITAL_BOARD",
    "base_unit_price_cents": 250_000,
    "tier_breaks": list(DEFAULT_TIER_BREAKS),
    "exclusivity_multiplier": 1.25,
}
SIGNAGE_LINE = {
    "asset_class": "SIGNAGE",
    "base_unit_price_cents": 100_000,
    "exclusivity_multiplier": 1.10,
}
DIGITAL_BOARD_ASSET = {
    "name": "North LED Ribbon",
    "asset_class": "DIGITAL_BOARD",
    "capacity_units": 6,
    "changeover_buffer_minutes": 30,
}
SIGNAGE_ASSET = {
    "name": "South Fascia Board",
    "asset_class": "SIGNAGE",
    "capacity_units": 3,
}
DEFAULT_ENTITLEMENT = {
    "asset_index": 0,
    "clause_ref": "4.2(a)",
    "promised_units": 10,
}


# --------------------------------------------------------------------------
# Tier 0 -- single-call primitives
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str, user_id: str = PROPERTY_ADMIN_USER_ID) -> dict:
    return get_success_data(
        api_client.set_clock(
            {"to_iso8601": to_iso8601}, make_property_admin_headers(user_id)
        )
    )


def create_property(**overrides) -> dict:
    return get_success_data(
        api_client.create_property(create_property_payload(**overrides), ADMIN)
    )


def read_property(property_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_property(property_id, headers or APPROVER)
    )


def transition_property(property_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.transition_property(property_id, {"to_status": to_status}, ADMIN)
    )


def create_rate_card(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_card(
            property_id, create_rate_card_payload(**overrides), ADMIN
        )
    )


def add_rate_card_line(rate_card_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_card_line(
            rate_card_id, create_rate_card_line_payload(**overrides), ADMIN
        )
    )


def publish_rate_card(rate_card_id: str) -> dict:
    return get_success_data(api_client.publish_rate_card(rate_card_id, ADMIN))


def create_inventory_asset(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_asset(
            property_id, create_inventory_asset_payload(**overrides), ADMIN
        )
    )


def read_inventory_asset(asset_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_inventory_asset(asset_id, headers or ACTIVATION)
    )


def asset_version(asset_id: str) -> int:
    return read_inventory_asset(asset_id)["version"]


def create_sponsor(**overrides) -> dict:
    return get_success_data(
        api_client.create_sponsor(create_sponsor_payload(**overrides), SELLER)
    )


def read_sponsor(sponsor_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sponsor(sponsor_id, headers or APPROVER))


def create_contract(
    sponsor_id: str, property_id: str, user_id: str = SELLER_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(sponsor_id, property_id, **overrides),
            make_seller_headers(user_id),
        )
    )


def read_contract(contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers or APPROVER))


def add_entitlement(
    contract_id: str, inventory_asset_id: str, user_id: str = SELLER_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_entitlement(
            contract_id,
            create_entitlement_payload(inventory_asset_id, **overrides),
            make_seller_headers(user_id),
        )
    )


def read_entitlement(entitlement_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_entitlement(entitlement_id, headers or APPROVER)
    )


def submit_contract(contract_id: str, user_id: str = SELLER_USER_ID) -> dict:
    return get_success_data(
        api_client.submit_contract(contract_id, make_seller_headers(user_id))
    )


def return_contract(
    contract_id: str, reason: str = "revise", user_id: str = APPROVER_USER_ID
) -> dict:
    return get_success_data(
        api_client.return_contract(
            contract_id, {"reason": reason}, make_approver_headers(user_id)
        )
    )


def countersign_contract(
    contract_id: str, property_id: str, user_id: str = APPROVER_USER_ID
) -> dict:
    """Read the property's live version, then countersign with it."""
    headers = make_approver_headers(user_id)
    expected_property_version = get_success_data(
        api_client.get_property(property_id, headers)
    )["version"]
    return get_success_data(
        api_client.countersign_contract(
            contract_id,
            {"expected_property_version": expected_property_version},
            headers,
        )
    )


def activate_contract(contract_id: str, user_id: str = APPROVER_USER_ID) -> dict:
    return get_success_data(
        api_client.activate_contract(contract_id, make_approver_headers(user_id))
    )


def close_contract(contract_id: str, user_id: str = APPROVER_USER_ID) -> dict:
    return get_success_data(
        api_client.close_contract(contract_id, make_approver_headers(user_id))
    )


def terminate_contract(
    contract_id: str, reason: str = "Sponsor insolvency",
    user_id: str = APPROVER_USER_ID,
) -> dict:
    return get_success_data(
        api_client.terminate_contract(
            contract_id, {"reason": reason}, make_approver_headers(user_id)
        )
    )


def book_asset(
    entitlement_id: str,
    inventory_asset_id: str,
    expected_inventory_asset_version: Optional[int] = None,
    user_id: str = ACTIVATION_USER_ID,
    **overrides,
) -> dict:
    """Create a booking, reading the asset's live version when none is supplied."""
    if expected_inventory_asset_version is None:
        expected_inventory_asset_version = asset_version(inventory_asset_id)
    payload = create_asset_booking_payload(
        entitlement_id, inventory_asset_id, expected_inventory_asset_version,
        **overrides,
    )
    return get_success_data(
        api_client.create_asset_booking(payload, make_activation_headers(user_id))
    )


def read_booking(booking_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_asset_booking(booking_id, headers or ACTIVATION)
    )


def deliver_booking(booking_id: str, user_id: str = ACTIVATION_USER_ID) -> dict:
    return get_success_data(
        api_client.deliver_asset_booking(booking_id, make_activation_headers(user_id))
    )


def cancel_booking(
    booking_id: str, reason: str = "Creative not approved",
    user_id: str = ACTIVATION_USER_ID,
) -> dict:
    return get_success_data(
        api_client.cancel_asset_booking(
            booking_id, {"reason": reason}, make_activation_headers(user_id)
        )
    )


def create_staff_member(user_id: str = ACTIVATION_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_member(
            create_staff_member_payload(**overrides), make_activation_headers(user_id)
        )
    )


def assign_staff(
    booking_id: str, staff_member_id: str, user_id: str = ACTIVATION_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_staff_assignment(
            booking_id,
            create_staff_assignment_payload(staff_member_id, **overrides),
            make_activation_headers(user_id),
        )
    )


def read_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_staff_assignment(assignment_id, headers or ACTIVATION)
    )


def check_in(assignment_id: str, user_id: str = ACTIVATION_USER_ID) -> dict:
    return get_success_data(
        api_client.check_in_staff_assignment(
            assignment_id, make_activation_headers(user_id)
        )
    )


def capture_proof(
    booking_id: str, user_id: str = ACTIVATION_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api_client.create_proof(
            booking_id, create_proof_payload(**overrides),
            make_activation_headers(user_id),
        )
    )


def adjudicate_proof(
    proof_id: str, decision: str, reject_reason: Optional[str] = None,
    user_id: str = AUDITOR_USER_ID,
) -> dict:
    payload = {"decision": decision}
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    return get_success_data(
        api_client.adjudicate_proof(proof_id, payload, make_auditor_headers(user_id))
    )


def file_survey(contract_id: str, sponsor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_survey(
            contract_id, create_survey_payload(**overrides),
            make_sponsor_contact_headers(sponsor_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 1 -- the sellable estate: property + priced card + inventory assets
# --------------------------------------------------------------------------
def setup_property_estate(
    line_specs: Optional[List[dict]] = None,
    asset_specs: Optional[List[dict]] = None,
    property_overrides: Optional[dict] = None,
    publish: bool = True,
    advance_to: Optional[str] = "SELLING",
    rate_card_label: str = "2026 Season Card",
) -> dict:
    """Property + one rate card carrying `line_specs` + `asset_specs` assets.

    With `publish` the card reaches PUBLISHED; with `advance_to` the property is
    driven along its one-way path as far as the named status.
    """
    line_specs = copy.deepcopy(
        line_specs if line_specs is not None else [DIGITAL_BOARD_LINE]
    )
    asset_specs = copy.deepcopy(
        asset_specs if asset_specs is not None else [DIGITAL_BOARD_ASSET]
    )
    prop = create_property(**(property_overrides or {}))
    rate_card = create_rate_card(prop["id"], label=rate_card_label)
    lines = [add_rate_card_line(rate_card["id"], **spec) for spec in line_specs]
    if publish:
        rate_card = publish_rate_card(rate_card["id"])
    if advance_to in ("SELLING", "IN_SEASON"):
        prop = transition_property(prop["id"], "SELLING")
    assets = [create_inventory_asset(prop["id"], **spec) for spec in asset_specs]
    if advance_to == "IN_SEASON":
        set_clock(SEASON_START)
        prop = transition_property(prop["id"], "IN_SEASON")
    return {
        "property": prop,
        "rate_card": rate_card,
        "lines": lines,
        "assets": assets,
        "asset": assets[0] if assets else None,
    }


# --------------------------------------------------------------------------
# Tier 2 -- a whole deal walked to a named lifecycle stage
# --------------------------------------------------------------------------
def setup_contract_scenario(
    stage: str = "ACTIVE",
    line_specs: Optional[List[dict]] = None,
    asset_specs: Optional[List[dict]] = None,
    entitlement_specs: Optional[List[dict]] = None,
    sponsor_spec: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
    property_overrides: Optional[dict] = None,
    publish: bool = True,
    seller_user_id: str = SELLER_USER_ID,
    approver_user_id: str = APPROVER_USER_ID,
    activation_clock: str = SEASON_START,
) -> dict:
    """Walk one sponsorship deal to `stage`.

    stage is one of DRAFT, SUBMITTED, COUNTERSIGNED or ACTIVE. Entitlement
    specifications name the asset by index into `asset_specs`.
    """
    estate = setup_property_estate(
        line_specs=line_specs,
        asset_specs=asset_specs,
        property_overrides=property_overrides,
        publish=publish,
        advance_to="SELLING" if publish else None,
    )
    prop = estate["property"]
    sponsor = create_sponsor(**(sponsor_spec or {}))
    contract_kwargs = dict(contract_overrides or {})
    contract = create_contract(
        sponsor["id"], prop["id"], user_id=seller_user_id, **contract_kwargs
    )

    specs = copy.deepcopy(
        entitlement_specs if entitlement_specs is not None
        else [DEFAULT_ENTITLEMENT]
    )
    entitlements = []
    for spec in specs:
        spec = dict(spec)
        asset_index = spec.pop("asset_index", 0)
        entitlements.append(
            add_entitlement(
                contract["id"], estate["assets"][asset_index]["id"],
                user_id=seller_user_id, **spec,
            )
        )

    scenario = {
        "property": prop,
        "rate_card": estate["rate_card"],
        "lines": estate["lines"],
        "assets": estate["assets"],
        "asset": estate["assets"][0] if estate["assets"] else None,
        "sponsor": sponsor,
        "contract": contract,
        "entitlements": entitlements,
        "entitlement": entitlements[0] if entitlements else None,
    }
    if stage == "DRAFT":
        return scenario

    scenario["contract"] = submit_contract(contract["id"], user_id=seller_user_id)
    if stage == "SUBMITTED":
        return scenario

    scenario["contract"] = countersign_contract(
        contract["id"], prop["id"], user_id=approver_user_id
    )
    if stage == "COUNTERSIGNED":
        scenario["property"] = read_property(prop["id"])
        return scenario

    set_clock(activation_clock)
    scenario["property"] = transition_property(prop["id"], "IN_SEASON")
    scenario["contract"] = activate_contract(
        contract["id"], user_id=approver_user_id
    )
    return scenario


def setup_active_contract_with_booking(
    units_booked: int = 4,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    **scenario_kwargs,
) -> dict:
    """An ACTIVE deal with one SCHEDULED booking on its first entitlement."""
    scenario = setup_contract_scenario(stage="ACTIVE", **scenario_kwargs)
    scenario["booking"] = book_asset(
        scenario["entitlement"]["id"],
        scenario["asset"]["id"],
        window_start=window_start,
        window_end=window_end,
        units_booked=units_booked,
    )
    return scenario


def setup_delivered_booking(
    units_booked: int = 4,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    **scenario_kwargs,
) -> dict:
    """An ACTIVE deal whose single booking has been delivered.

    The logical clock is left at the booking's window_end.
    """
    scenario = setup_active_contract_with_booking(
        units_booked=units_booked,
        window_start=window_start,
        window_end=window_end,
        **scenario_kwargs,
    )
    set_clock(window_end)
    scenario["booking"] = deliver_booking(scenario["booking"]["id"])
    return scenario


def setup_closed_contract(
    units_booked: int = 4,
    close_clock: str = AFTER_TERM_END,
    **scenario_kwargs,
) -> dict:
    """A deal delivered in part and then closed after term end."""
    scenario = setup_delivered_booking(units_booked=units_booked, **scenario_kwargs)
    set_clock(close_clock)
    scenario["contract"] = close_contract(scenario["contract"]["id"])
    return scenario


# --------------------------------------------------------------------------
# Tier 3 -- multi-contract properties
# --------------------------------------------------------------------------
def setup_two_contract_property(activate_second: bool = True) -> dict:
    """One property carrying two countersigned deals for two sponsor categories.

    Contract one belongs to a BEVERAGE sponsor and holds CATEGORY exclusivity;
    contract two belongs to an AUTOMOTIVE sponsor and holds none, so no category
    clash arises. Contract one is always ACTIVE; contract two is activated only
    when `activate_second` is true.
    """
    estate = setup_property_estate()
    prop = estate["property"]
    asset = estate["assets"][0]

    sponsor_one = create_sponsor(
        name="Zephyr Cola", category="BEVERAGE", contact_email="ops@zephyr.example"
    )
    sponsor_two = create_sponsor(
        name="Nimbus Motors", category="AUTOMOTIVE",
        contact_email="ops@nimbus.example",
    )

    contract_one = create_contract(
        sponsor_one["id"], prop["id"], exclusivity_scope="CATEGORY"
    )
    entitlement_one = add_entitlement(
        contract_one["id"], asset["id"], clause_ref="4.2(a)", promised_units=10
    )
    submit_contract(contract_one["id"])
    contract_one = countersign_contract(contract_one["id"], prop["id"])

    contract_two = create_contract(
        sponsor_two["id"], prop["id"], exclusivity_scope="NONE"
    )
    entitlement_two = add_entitlement(
        contract_two["id"], asset["id"], clause_ref="2.1", promised_units=5
    )
    submit_contract(contract_two["id"])
    contract_two = countersign_contract(contract_two["id"], prop["id"])

    set_clock(SEASON_START)
    prop = transition_property(prop["id"], "IN_SEASON")
    contract_one = activate_contract(contract_one["id"])
    if activate_second:
        contract_two = activate_contract(contract_two["id"])

    return {
        "property": prop,
        "rate_card": estate["rate_card"],
        "asset": asset,
        "assets": estate["assets"],
        "sponsor_one": sponsor_one,
        "sponsor_two": sponsor_two,
        "contract_one": contract_one,
        "contract_two": contract_two,
        "entitlement_one": entitlement_one,
        "entitlement_two": entitlement_two,
    }


def setup_category_exclusivity_standoff() -> dict:
    """A property whose committed position and category are both already taken.

    'Harbor Arena' targets 7,000,000 cents, so its oversell ceiling is 7,700,000.
    The first BEVERAGE deal is countersigned at 3,881,250; the second BEVERAGE
    deal is submitted and, at 3,881,250, would breach both the category lock and
    the ceiling.
    """
    estate = setup_property_estate(
        property_overrides={
            "name": "Harbor Arena",
            "sport_code": "BASKETBALL",
            "inventory_target_value_cents": 7_000_000,
        },
        asset_specs=[
            {
                "name": "Center Hung Board",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 6,
                "changeover_buffer_minutes": 0,
            }
        ],
    )
    prop = estate["property"]
    asset = estate["assets"][0]

    sponsor_one = create_sponsor(
        name="Zephyr Cola", category="BEVERAGE", contact_email="ops@zephyr.example"
    )
    sponsor_two = create_sponsor(
        name="Cascade Water", category="BEVERAGE",
        contact_email="ops@cascade.example",
    )
    deal_shape = {
        "exclusivity_scope": "CATEGORY",
        "in_kind_declared_value_cents": 1_200_000,
        "in_kind_category": "PRODUCT",
    }

    contract_one = create_contract(sponsor_one["id"], prop["id"], **deal_shape)
    add_entitlement(
        contract_one["id"], asset["id"], clause_ref="4.2(a)", promised_units=10
    )
    submit_contract(contract_one["id"])
    contract_one = countersign_contract(contract_one["id"], prop["id"])

    contract_two = create_contract(sponsor_two["id"], prop["id"], **deal_shape)
    add_entitlement(
        contract_two["id"], asset["id"], clause_ref="4.2(a)", promised_units=10
    )
    submit_contract(contract_two["id"])

    return {
        "property": read_property(prop["id"]),
        "asset": asset,
        "sponsor_one": sponsor_one,
        "sponsor_two": sponsor_two,
        "contract_one": contract_one,
        "contract_two": contract_two,
    }


# --------------------------------------------------------------------------
# Tier 4 -- staffing setups
# --------------------------------------------------------------------------
def setup_staffed_booking(
    requires_staffing: bool = True,
    min_staff_count: int = 1,
    booking_units: int = 1,
    window_start: str = "2026-09-15T14:00:00Z",
    window_end: str = "2026-09-15T18:00:00Z",
) -> dict:
    """An ACTIVE deal on a staffing-gated activation space with one ASSIGNED shift.

    The logical clock is left at the booking's window_end so the delivery gate is
    open on every axis except staffing.
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        line_specs=[
            {
                "asset_class": "ACTIVATION_SPACE",
                "base_unit_price_cents": 150_000,
                # Stated in full so the payload factory's DIGITAL_BOARD defaults
                # (a break at 10 units and a 1.25 premium) cannot leak in and
                # silently reprice this clause.
                "tier_breaks": [],
                "exclusivity_multiplier": 1.00,
            }
        ],
        asset_specs=[
            {
                "name": "East Concourse Zone",
                "asset_class": "ACTIVATION_SPACE",
                "capacity_units": 2,
                "requires_staffing": requires_staffing,
                "min_staff_count": min_staff_count,
            }
        ],
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "6.1", "promised_units": 2}
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    scenario["booking"] = book_asset(
        scenario["entitlement"]["id"],
        scenario["asset"]["id"],
        window_start=window_start,
        window_end=window_end,
        units_booked=booking_units,
    )
    scenario["staff_member"] = create_staff_member()
    scenario["assignment"] = assign_staff(
        scenario["booking"]["id"],
        scenario["staff_member"]["id"],
        shift_start=window_start,
        shift_end=window_end,
    )
    set_clock(window_end)
    return scenario


def setup_back_to_back_shift_bookings() -> dict:
    """Two touching bookings of one deal, with the staffer already on the first.

    Booking one runs 14:00-18:00 and booking two 18:00-20:00 on 2026-09-15; the
    windows are half-open so they do not intersect. One staffer already holds the
    14:00-18:00 shift.
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        asset_specs=[
            {
                "name": "North LED Ribbon",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 6,
                "changeover_buffer_minutes": 30,
            }
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    scenario["booking_one"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-15T14:00:00Z",
        window_end="2026-09-15T18:00:00Z",
        units_booked=1,
    )
    scenario["booking_two"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-15T18:00:00Z",
        window_end="2026-09-15T20:00:00Z",
        units_booked=1,
    )
    scenario["staff_member"] = create_staff_member()
    scenario["assignment_one"] = assign_staff(
        scenario["booking_one"]["id"], scenario["staff_member"]["id"],
        shift_start="2026-09-15T14:00:00Z",
        shift_end="2026-09-15T18:00:00Z",
    )
    return scenario


# --------------------------------------------------------------------------
# Tier 5 -- evidence setups
# --------------------------------------------------------------------------
def setup_two_delivered_bookings_with_proofs() -> dict:
    """Two delivered bookings of one clause, each carrying one SUBMITTED proof."""
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    scenario["booking_one"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )
    scenario["booking_two"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-12T18:00:00Z",
        window_end="2026-09-12T21:00:00Z",
        units_booked=3,
    )
    set_clock("2026-09-12T21:00:00Z")
    scenario["booking_one"] = deliver_booking(scenario["booking_one"]["id"])
    scenario["booking_two"] = deliver_booking(scenario["booking_two"]["id"])
    scenario["proof_one"] = capture_proof(
        scenario["booking_one"]["id"], evidence_type="IMPRESSIONS",
        measured_value=500_000, media_uri="s3://pop/b1.json",
    )
    scenario["proof_two"] = capture_proof(
        scenario["booking_two"]["id"], evidence_type="IMPRESSIONS",
        measured_value=300_000, media_uri="s3://pop/b2.json",
    )
    return scenario


def setup_delivered_booking_with_mixed_evidence() -> dict:
    """One delivered booking carrying a VERIFIED proof and a still-SUBMITTED one.

    The deal declares 1,200,000 cents of PRODUCT trade, so its recognized total
    at signature is 3,881,250 cents.
    """
    scenario = setup_delivered_booking(
        units_booked=4,
        contract_overrides={
            "exclusivity_scope": "CATEGORY",
            "in_kind_declared_value_cents": 1_200_000,
            "in_kind_category": "PRODUCT",
        },
    )
    scenario["proof_verified"] = capture_proof(
        scenario["booking"]["id"], evidence_type="IMPRESSIONS",
        measured_value=500_000, media_uri="s3://pop/p1.json",
    )
    scenario["proof_submitted"] = capture_proof(
        scenario["booking"]["id"], evidence_type="IMPRESSIONS",
        measured_value=200_000, media_uri="s3://pop/p2.json",
    )
    scenario["proof_verified"] = adjudicate_proof(
        scenario["proof_verified"]["id"], "VERIFIED"
    )
    return scenario


def setup_exhausted_revision_contract() -> dict:
    """A DRAFT deal whose revision loop has been walked four full times.

    Submit and return are traversed four times on the same row, so the contract
    comes back at DRAFT with revision_round 4 and no recorded submitter.
    """
    scenario = setup_contract_scenario(
        stage="DRAFT", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    for revision_round in range(1, 5):
        submit_contract(scenario["contract"]["id"])
        scenario["contract"] = return_contract(
            scenario["contract"]["id"], reason=f"round {revision_round}"
        )
    return scenario


TWO_BREAK_DIGITAL_BOARD_LINE = {
    "asset_class": "DIGITAL_BOARD",
    "base_unit_price_cents": 250_000,
    "tier_breaks": [
        {"min_units": 10, "unit_price_cents": 225_000},
        {"min_units": 25, "unit_price_cents": 200_000},
    ],
    "exclusivity_multiplier": 1.25,
}


def setup_trade_leg_contract(
    in_kind_declared_value_cents: int = 1_200_000,
    in_kind_category: str = "PRODUCT",
    exclusivity_scope: str = "CATEGORY",
    promised_units: int = 10,
) -> dict:
    """An ACTIVE deal carrying a declared trade leg and no bookings at all.

    The property prices DIGITAL_BOARD at 250,000 cents with volume breaks at 10
    and 25 units and a 1.25 exclusivity premium, and also prices SIGNAGE. With a
    seasonality index of 1.20 the ten-unit clause is worth 337,500 cents a unit.
    """
    return setup_contract_scenario(
        stage="ACTIVE",
        line_specs=[TWO_BREAK_DIGITAL_BOARD_LINE, SIGNAGE_LINE],
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "4.2(a)",
             "promised_units": promised_units}
        ],
        contract_overrides={
            "exclusivity_scope": exclusivity_scope,
            "in_kind_declared_value_cents": in_kind_declared_value_cents,
            "in_kind_category": in_kind_category,
        },
    )


def setup_countersigned_contract_in_season(**scenario_kwargs) -> dict:
    """A COUNTERSIGNED deal on a property that has already opened its season.

    Everything the booking endpoint needs is in place except the contract's own
    move to ACTIVE.
    """
    scenario = setup_contract_scenario(stage="COUNTERSIGNED", **scenario_kwargs)
    set_clock(SEASON_START)
    scenario["property"] = transition_property(
        scenario["property"]["id"], "IN_SEASON"
    )
    return scenario


def setup_makegood_split_contract() -> dict:
    """An ACTIVE deal with two priced clauses and only one partly delivered.

    Clause A promises 10 DIGITAL_BOARD units at 337,500 cents each and receives
    4; clause B promises 3 SIGNAGE units at 132,000 cents each and receives none.
    The trade leg declares 1,600,000 cents of PRODUCT. The logical clock is left
    past term end so the deal can be closed straight away.
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        line_specs=[TWO_BREAK_DIGITAL_BOARD_LINE, SIGNAGE_LINE],
        asset_specs=[DIGITAL_BOARD_ASSET, SIGNAGE_ASSET],
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "4.2(a)", "promised_units": 10},
            {"asset_index": 1, "clause_ref": "4.2(b)", "promised_units": 3},
        ],
        contract_overrides={
            "exclusivity_scope": "CATEGORY",
            "in_kind_declared_value_cents": 1_600_000,
            "in_kind_category": "PRODUCT",
        },
    )
    scenario["booking"] = book_asset(
        scenario["entitlements"][0]["id"], scenario["assets"][0]["id"],
        window_start=WINDOW_START, window_end=WINDOW_END, units_booked=4,
    )
    set_clock(WINDOW_END)
    scenario["booking"] = deliver_booking(scenario["booking"]["id"])
    set_clock(AFTER_TERM_END)
    return scenario


def setup_closed_partial_delivery_contract() -> dict:
    """A trade-leg deal that delivered 4 of its 10 promised units and then closed.

    Its makegood pool is the whole 15 percent allowance on the cash leg, so the
    sponsor is rescored under the delivery-only weighting.
    """
    scenario = setup_trade_leg_contract()
    scenario["booking"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start=WINDOW_START, window_end=WINDOW_END, units_booked=4,
    )
    set_clock(WINDOW_END)
    scenario["booking"] = deliver_booking(scenario["booking"]["id"])
    set_clock(AFTER_TERM_END)
    scenario["contract"] = close_contract(scenario["contract"]["id"])
    return scenario


def setup_committed_value_conservation() -> dict:
    """One SELLING property with a countersigned deal and a submitted sibling.

    The first deal is worth 3,105,000 cents, so the property sits at 6.21 percent
    of its 50,000,000 cent target. The second deal is submitted and awaits the
    approver.
    """
    estate = setup_property_estate()
    prop = estate["property"]
    asset = estate["assets"][0]

    sponsor_one = create_sponsor(
        name="Zephyr Cola", category="BEVERAGE", contact_email="ops@zephyr.example"
    )
    sponsor_two = create_sponsor(
        name="Nimbus Motors", category="AUTOMOTIVE",
        contact_email="ops@nimbus.example",
    )

    contract_one = create_contract(
        sponsor_one["id"], prop["id"], exclusivity_scope="CATEGORY"
    )
    add_entitlement(
        contract_one["id"], asset["id"], clause_ref="4.2(a)", promised_units=10
    )
    submit_contract(contract_one["id"])
    contract_one = countersign_contract(contract_one["id"], prop["id"])

    contract_two = create_contract(
        sponsor_two["id"], prop["id"], exclusivity_scope="NONE"
    )
    add_entitlement(
        contract_two["id"], asset["id"], clause_ref="2.1", promised_units=5
    )
    contract_two = submit_contract(contract_two["id"])

    return {
        "property": read_property(prop["id"]),
        "asset": asset,
        "sponsor_one": sponsor_one,
        "sponsor_two": sponsor_two,
        "contract_one": contract_one,
        "contract_two": contract_two,
    }


def setup_fully_delivered_contract() -> dict:
    """An ACTIVE deal whose single clause has been delivered in full.

    The asset carries 10 units of capacity, so one booking satisfies the whole
    ten-unit promise. The clock is left past term end.
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        asset_specs=[
            {
                "name": "North LED Ribbon",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 10,
                "changeover_buffer_minutes": 30,
            }
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    scenario["booking"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start=WINDOW_START, window_end=WINDOW_END, units_booked=10,
    )
    set_clock(WINDOW_END)
    scenario["booking"] = deliver_booking(scenario["booking"]["id"])
    set_clock(AFTER_TERM_END)
    return scenario
