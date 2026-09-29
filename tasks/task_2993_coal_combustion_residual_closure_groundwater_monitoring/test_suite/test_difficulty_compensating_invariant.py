"""Compensating writes that must restore two derived ledgers to their exact prior values."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    AGREEMENT_STATUS_ACTIVE,
    EXTENSION_DECISION_GRANT,
    EXTENSION_STATUS_GRANTED,
    EXTENSION_STATUS_RESCINDED,
    POSTING_EXTENSION_DEMONSTRATION,
    POSTING_STATUS_POSTED,
    SHIPMENT_STATUS_RETURNED,
    SHIPMENT_STATUS_SHIPPED,
)
from test_helpers.test_users import REGULATOR_HEADERS, UTILITY_ADMIN_HEADERS

RETURN_REASON = "Offtaker rejected the load for excess moisture at the plant gate"
RESCISSION_REASON = "Alternative permitted capacity became available, so the relief is withdrawn"


def case_active_agreement_over_a_full_inventory(api):
    """One clean unit holding 480,000 tons and one ACTIVE offtake agreement."""
    world = fixtures.seed_unit(api, "IMP-0018")
    fixtures.seed_active_agreement(
        api,
        world,
        "AGR-BAL-1",
        "2026-08-01",
        commitment_start_on="2026-01-01",
        commitment_end_on="2026-12-31",
    )
    return world


def read_agreement(api, agreement_id):
    return get_success_data(api.get_reuse_agreement(agreement_id, UTILITY_ADMIN_HEADERS))


def read_shipment(api, shipment_id):
    return get_success_data(api.get_reuse_shipment(shipment_id, UTILITY_ADMIN_HEADERS))


def case_granted_extension_of_twenty_four_months(api):
    """A unit whose 24-month relief has been granted over a complete demonstration."""
    world = fixtures.seed_unit(api, "IMP-0019")
    world["deadline_before"] = world["unit"]["closure_deadline_date"]
    request = fixtures.request_extension(
        api,
        world,
        24,
        narrative="No permitted disposal capacity is available within the base closure period for the volume in this impoundment",
    )
    world["request_id"] = request["id"]
    world["posting"] = fixtures.post_document(
        api,
        world,
        POSTING_EXTENSION_DEMONSTRATION,
        "2026-08-01",
        community_meeting_held_on="2026-07-20",
    )
    world["granted"] = fixtures.decide_extension(
        api,
        request["id"],
        EXTENSION_DECISION_GRANT,
        "2026-08-01",
        24,
        decision_note="Capacity demonstration accepted; 24 months granted",
    )
    return world


def rescind(api, world, reason=RESCISSION_REASON):
    return api.rescind_extension_request(
        world["request_id"],
        factories.rescind_extension_payload("2026-08-01", reason),
        REGULATOR_HEADERS,
    )


def test_a_shipment_draws_the_same_tonnage_out_of_both_derived_ledgers(api):
    """12,000 tons leave the unit's inventory and land on the agreement's total.

    PRD: The unit's `ash_in_place_tons` is its `original_ash_in_place_tons` less the sum of `tons` over every shipment in `SHIPPED` status belonging to any agreement of that unit
    Design: Difficulty/compensating_invariant/shipment_return_restores_the_ash_inventory_and_the_agreement_ledger_exactly
    """
    world = case_active_agreement_over_a_full_inventory(api)
    before = fixtures.read_unit(api, world["unit_id"])
    assert before["ash_in_place_tons"] == 480000
    assert before["ash_mass_balance_ok"] is True

    shipment = fixtures.ship_load(api, world, "SHP-BAL-1", 12000, "2026-07-01")

    assert shipment["status"] == SHIPMENT_STATUS_SHIPPED
    mid = fixtures.read_unit(api, world["unit_id"])
    assert mid["ash_in_place_tons"] == 468000
    assert mid["ash_mass_balance_ok"] is True
    assert mid["version"] > before["version"]
    assert read_agreement(api, world["agreement_id"])["shipped_tons_total"] == 12000


def test_the_return_restores_both_ledgers_to_their_exact_pre_shipment_values(api):
    """The compensation is a forward write that lands back on 480,000 exactly.

    PRD: The return reverses every tonnage effect of the original shipment: the agreement's `shipped_tons_total` decreases by the load's tonnage, a `COMPLETED` agreement is pulled back `COMPLETED` -> `ACTIVE` because its commitment is no longer fully shipped, the unit's `ash_in_place_tons` is re-derived and rises by the returned tonnage, `ash_mass_balance_ok` is re-derived, and the unit's `version` increments by 1.
    PRD: Because the ledger is always re-derived from the original tonnage minus the shipped sum, a return restores the pre-shipment balance exactly with no drift.
    Design: Difficulty/compensating_invariant/shipment_return_restores_the_ash_inventory_and_the_agreement_ledger_exactly
    """
    world = case_active_agreement_over_a_full_inventory(api)
    shipment = fixtures.ship_load(api, world, "SHP-BAL-1", 12000, "2026-07-01")
    mid = fixtures.read_unit(api, world["unit_id"])

    returned = fixtures.return_load(api, world, shipment["id"], "2026-07-15", reason=RETURN_REASON)

    assert returned["status"] == SHIPMENT_STATUS_RETURNED
    a.assert_date(returned["returned_on"], "2026-07-15", "returned_on")
    after = fixtures.read_unit(api, world["unit_id"])
    assert after["ash_in_place_tons"] == 480000
    assert after["ash_mass_balance_ok"] is True
    assert after["version"] > mid["version"]
    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["shipped_tons_total"] == 0
    assert agreement["status"] == AGREEMENT_STATUS_ACTIVE


def test_the_grant_moves_the_deadline_and_the_rescission_puts_it_back_byte_for_byte(api):
    """The deadline is re-derived from the cessation date, so it lands on 2031-03-31 again.

    PRD: A unit's `closure_deadline_date` is always derived, never accumulated: it is `cessation_date` advanced by the base allowance for its `unit_type` - 5 years for a surface impoundment, two and a half years for a landfill - plus the unit's *current* `granted_extension_months` total, using the same day-clamping calendar arithmetic described in §3.1. Because it is always re-derived from those two inputs rather than nudged incrementally, granting and then rescinding an extension restores the previous date exactly, with no drift.
    PRD: the request moves `GRANTED` -> `RESCINDED`, its `granted_months` returns to 0, and the unit's `granted_extension_months` is reduced by the months that had been granted, after which `closure_deadline_date` is re-derived and lands exactly on its pre-grant value.
    Design: Difficulty/compensating_invariant/extension_rescission_restores_the_closure_deadline_from_cessation_date_not_by_subtraction
    """
    world = case_granted_extension_of_twenty_four_months(api)
    a.assert_date(world["deadline_before"], "2031-03-31", "closure_deadline_date")
    assert world["posting"]["status"] == POSTING_STATUS_POSTED
    a.assert_date(
        world["posting"]["community_meeting_held_on"], "2026-07-20", "community_meeting_held_on"
    )
    assert world["granted"]["status"] == EXTENSION_STATUS_GRANTED
    assert world["granted"]["granted_months"] == 24
    granted_unit = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(granted_unit["closure_deadline_date"], "2033-03-31", "closure_deadline_date")
    assert granted_unit["granted_extension_months"] == 24

    rescinded = get_success_data(rescind(api, world))

    assert rescinded["status"] == EXTENSION_STATUS_RESCINDED
    assert rescinded["granted_months"] == 0
    a.assert_date(rescinded["rescinded_on"], "2026-08-01", "rescinded_on")
    restored = fixtures.read_unit(api, world["unit_id"])
    assert restored["closure_deadline_date"] == world["deadline_before"]
    assert restored["granted_extension_months"] == 0


def test_a_second_rescission_is_refused_and_leaves_the_restored_deadline_alone(api):
    """RESCINDED is terminal, so the compensation cannot be applied twice.

    PRD: `RESCINDED` is terminal, and a request in any status other than the one the operation requires is `ERR_INVALID_EXTENSION_STATE` (HTTP 409).
    Design: Difficulty/compensating_invariant/extension_rescission_restores_the_closure_deadline_from_cessation_date_not_by_subtraction
    """
    world = case_granted_extension_of_twenty_four_months(api)
    get_success_data(rescind(api, world))

    response = rescind(api, world, "Duplicate rescission attempt against a terminal request")

    validate_error(response, ApiErrorId.INVALID_EXTENSION_STATE.value)
    unit = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(unit["closure_deadline_date"], "2031-03-31", "closure_deadline_date")
    assert unit["granted_extension_months"] == 0
