"""Requests that break two rules at once, where only the higher-priority one may surface."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    AGREEMENT_STATUS_DRAFT,
    EXTENSION_DECISION_GRANT,
    EXTENSION_STATUS_REQUESTED,
    POSTING_EXTENSION_DEMONSTRATION,
    POSTING_STABILITY_ASSESSMENT,
    POSTURE_FROZEN,
)
from test_helpers.test_users import REGULATOR_HEADERS, UTILITY_ADMIN_HEADERS


def case_draft_agreement_with_a_tiny_commitment(api):
    """A DRAFT agreement committed to only 100 tons, on a unit holding 480,000."""
    world = fixtures.seed_unit(api, "IMP-0009")
    agreement = fixtures.draft_agreement(
        api,
        world,
        "AGR-0002",
        committed_tons=100,
        commitment_start_on="2026-01-01",
        commitment_end_on="2026-12-31",
    )
    world["agreement_id"] = agreement["id"]
    return world


def oversized_shipment(api, world):
    """A 500-ton shipment: five times the commitment, against a DRAFT agreement."""
    return api.create_reuse_shipment(
        factories.shipment_payload(
            world["agreement_id"],
            "SHP-0001",
            500,
            fixtures.unit_version(api, world["unit_id"]),
            "2026-08-01",
        ),
        UTILITY_ADMIN_HEADERS,
    )


def case_frozen_unit_with_a_pending_extension_request(api):
    """Two posting obligations left unmet until the clock passes both of them."""
    world = fixtures.seed_unit(api, "IMP-0010")
    fixtures.file_stability(api, world, "2026-07-15")
    request = fixtures.request_extension(api, world, 24)
    world["request_id"] = request["id"]
    fixtures.set_clock(api, "2026-09-15T00:00:00Z")
    return world


def grant_the_extension(api, world):
    return api.decide_extension_request(
        world["request_id"],
        factories.extension_decision_payload(
            EXTENSION_DECISION_GRANT,
            "2026-09-15",
            24,
            decision_note="Granted subject to quarterly progress reporting",
        ),
        REGULATOR_HEADERS,
    )


def test_the_agreements_lifecycle_state_is_refused_before_its_tonnage_ceiling(api):
    """A DRAFT agreement is rejected on state, never on the 100-ton commitment.

    PRD: 23. The reuse agreement's `status` admits the operation, else `ERR_INVALID_AGREEMENT_STATE`.
    PRD: 56. A shipment does not push an agreement past its committed tonnage, else `ERR_COMMITTED_TONS_EXCEEDED`.
    Design: Difficulty/priority_pair_validation_conflict/agreement_state_outranks_committed_tons_ceiling_on_shipment
    """
    world = case_draft_agreement_with_a_tiny_commitment(api)

    response = oversized_shipment(api, world)

    error = validate_error(response, ApiErrorId.INVALID_AGREEMENT_STATE.value)
    assert error["error_id"] != ApiErrorId.COMMITTED_TONS_EXCEEDED.value
    assert response.status_code != 422


def test_the_refused_shipment_leaves_the_ledger_and_the_ash_inventory_untouched(api):
    """No row, no tonnage, no mass-balance movement behind the refusal.

    PRD: Because the ledger is always re-derived from the original tonnage minus the shipped sum, a return restores the pre-shipment balance exactly with no drift.
    PRD: `ash_in_place_tons` starts equal to `original_ash_in_place_tons` and `ash_mass_balance_ok` starts true.
    Design: Difficulty/priority_pair_validation_conflict/agreement_state_outranks_committed_tons_ceiling_on_shipment
    """
    world = case_draft_agreement_with_a_tiny_commitment(api)

    oversized_shipment(api, world)

    agreement = get_success_data(
        api.get_reuse_agreement(world["agreement_id"], UTILITY_ADMIN_HEADERS)
    )
    assert agreement["status"] == AGREEMENT_STATUS_DRAFT
    assert agreement["shipped_tons_total"] == 0

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["ash_in_place_tons"] == 480000
    assert unit["ash_mass_balance_ok"] is True

    shipments, _ = fixtures.page(
        api.list_reuse_shipments(UTILITY_ADMIN_HEADERS, {"agreement_id": world["agreement_id"]})
    )
    assert shipments == []


def test_the_frozen_posture_is_refused_before_the_missing_demonstration(api):
    """Two overdue postings outrank the demonstration the grant would also need.

    PRD: 29. The owning unit is not `FROZEN` for a non-remedial write, else `ERR_UNIT_FROZEN`.
    PRD: 49. A posted extension demonstration exists at grant time, else `ERR_EXTENSION_DEMONSTRATION_MISSING`.
    Design: Difficulty/priority_pair_validation_conflict/unit_frozen_outranks_missing_extension_demonstration
    """
    world = case_frozen_unit_with_a_pending_extension_request(api)
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["compliance_posture"] == POSTURE_FROZEN
    assert unit["overdue_posting_types"] == [
        POSTING_STABILITY_ASSESSMENT,
        POSTING_EXTENSION_DEMONSTRATION,
    ]

    response = grant_the_extension(api, world)

    error = validate_error(response, ApiErrorId.UNIT_FROZEN.value)
    assert error["error_id"] != ApiErrorId.EXTENSION_DEMONSTRATION_MISSING.value
    assert response.status_code != 422


def test_the_refused_grant_moves_neither_the_request_nor_the_closure_deadline(api):
    """The deadline is still the base 60-month allowance off the cessation date.

    PRD: `granted_extension_months` starts at 0 and `closure_deadline_date` is computed from `cessation_date` by advancing the calendar by the base allowance for the unit type - 60 months for a surface impoundment, 30 months for a landfill - plus the current granted extension total, which at registration is nothing.
    Design: Difficulty/priority_pair_validation_conflict/unit_frozen_outranks_missing_extension_demonstration
    """
    world = case_frozen_unit_with_a_pending_extension_request(api)

    grant_the_extension(api, world)

    request = get_success_data(
        api.get_extension_request(world["request_id"], UTILITY_ADMIN_HEADERS)
    )
    assert request["status"] == EXTENSION_STATUS_REQUESTED
    assert request["granted_months"] == 0

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["granted_extension_months"] == 0
    a.assert_date(unit["closure_deadline_date"], "2031-03-31", "closure_deadline_date")
