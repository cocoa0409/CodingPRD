"""SCAFFOLD §1.8 rule_id non_linear_state_machine: bounded cycles and reverse edges."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures  # noqa: E402
from test_helpers.api_errors import *  # noqa: F401,F403,E402
from test_helpers.test_users import (  # noqa: E402
    make_program_chair_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)


def test_self_study_revision_loop_bounded_at_two_returns(api):
    """DRAFT -> SUBMITTED -> DRAFT is traversable twice and the third RETURN is refused.

    §3.3 makes the self-study axis cyclic rather than linear: a return is
    permitted only while revision_round is below 2, so after two full laps the
    third RETURN is refused with ERR_REVISION_LIMIT_REACHED and the row is left in
    SUBMITTED at revision_round 2. The loop never advances the parent cycle, which
    stays in SELF_STUDY_OPEN throughout because only ACCEPT cascades upward.

    Design: Difficulty/non_linear_state_machine/self_study_revision_loop_bounded_at_two_returns
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]
    chair = make_program_chair_headers(program_id)

    # The clock sits a full month before the deadline, so the window guard never
    # competes with the loop bound.
    cycle = fixtures.open_cycle(
        api,
        program_id,
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1", "S2"],
    )
    assert cycle["state"] == "SELF_STUDY_OPEN"

    self_study = fixtures.create_self_study(
        api,
        cycle["id"],
        program_id,
        narrative="First draft narrative",
        section_codes=["S1", "S2"],
    )
    assert self_study["state"] == "DRAFT"
    assert self_study["revision_round"] == 0
    assert self_study["missing_section_codes"] == []
    self_study_id = self_study["id"]

    # Lap one.
    submitted = validate_success(
        api.transition_self_study(
            self_study_id, factories.self_study_submit_payload(), chair
        )
    )
    assert submitted["state"] == "SUBMITTED"
    returned = validate_success(
        api.transition_self_study(
            self_study_id,
            factories.self_study_return_payload("Expand the demand analysis"),
            coordinator,
        )
    )
    assert returned["state"] == "DRAFT"
    assert returned["revision_round"] == 1
    assert returned["submitted_at"] is None

    validate_success(
        api.patch_self_study(
            self_study_id,
            factories.self_study_patch_payload(
                narrative="Second draft narrative with demand analysis"
            ),
            chair,
        )
    )

    # Lap two.
    validate_success(
        api.transition_self_study(
            self_study_id, factories.self_study_submit_payload(), chair
        )
    )
    returned = validate_success(
        api.transition_self_study(
            self_study_id,
            factories.self_study_return_payload("Add the cost per credit hour table"),
            coordinator,
        )
    )
    assert returned["state"] == "DRAFT"
    assert returned["revision_round"] == 2

    validate_success(
        api.patch_self_study(
            self_study_id,
            factories.self_study_patch_payload(
                narrative="Third draft narrative with the cost table",
                attestation_note="Attested by the chair",
            ),
            chair,
        )
    )
    resubmitted = validate_success(
        api.transition_self_study(
            self_study_id, factories.self_study_submit_payload(), chair
        )
    )
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 2

    # Trigger: the third return exhausts the loop bound.
    refused = api.transition_self_study(
        self_study_id,
        factories.self_study_return_payload("One more pass please"),
        coordinator,
    )
    validate_error(refused, ERR_REVISION_LIMIT_REACHED, 409)

    # The cycle's self-study list is the only read channel for the document.
    rows, _meta = validate_paginated(api.list_self_studies(cycle["id"], coordinator))
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == self_study_id
    assert row["state"] == "SUBMITTED"
    assert row["revision_round"] == 2
    assert row["missing_section_codes"] == []

    # The refusal never advanced the parent.
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_OPEN"


def test_program_catalog_axis_reverse_edge_and_cross_axis_guard(api):
    """The catalog axis walks its reverse edge, then stalls on the cross-axis guard.

    §2.6 declares four catalog edges and no others. LISTED ->
    MARKETING_SUPPRESSED -> LISTED is a reverse edge no linear machine carries,
    and it runs while the lifecycle axis moves ACTIVE -> UNDER_REVIEW on a
    completely different trigger — opening a review cycle — without the two axes
    touching one another. ADMISSIONS_CLOSED -> CATALOG_WITHDRAWN is then refused
    with ERR_CATALOG_TRANSITION_INVALID because the catalog axis cannot reach its
    terminal state while the lifecycle axis is not terminal.

    Design: Difficulty/non_linear_state_machine/program_catalog_axis_reverse_edge_and_cross_axis_guard
    """
    registrar = make_registrar_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]
    assertions.assert_axes(program, lifecycle_state="ACTIVE", catalog_status="LISTED")

    suppressed = validate_success(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "MARKETING_SUPPRESSED",
                suppression_note="Pre-emptive pause on paid recruitment",
            ),
            registrar,
        )
    )
    assertions.assert_axes(
        suppressed, lifecycle_state="ACTIVE", catalog_status="MARKETING_SUPPRESSED"
    )

    # The reverse edge.
    relisted = validate_success(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "LISTED", suppression_note="Suppression lifted, recruitment resumed"
            ),
            registrar,
        )
    )
    assertions.assert_axes(relisted, lifecycle_state="ACTIVE", catalog_status="LISTED")

    # A different trigger moves the other axis only.
    cycle = fixtures.open_cycle(
        api,
        program_id,
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    after_cycle = fixtures.read_program(api, program_id)
    assertions.assert_axes(
        after_cycle, lifecycle_state="UNDER_REVIEW", catalog_status="LISTED"
    )

    validate_success(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "MARKETING_SUPPRESSED",
                suppression_note="Suppressed for the duration of the review",
            ),
            registrar,
        )
    )
    closed = validate_success(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "ADMISSIONS_CLOSED",
                suppression_note="No further admissions during the review",
            ),
            registrar,
        )
    )
    assertions.assert_axes(
        closed, lifecycle_state="UNDER_REVIEW", catalog_status="ADMISSIONS_CLOSED"
    )

    # Trigger: the terminal catalog state is gated on a terminal lifecycle state.
    refused = api.set_catalog_status(
        program_id,
        factories.catalog_status_payload(
            "CATALOG_WITHDRAWN",
            suppression_note="Attempting an early catalog withdrawal",
        ),
        registrar,
    )
    validate_error(refused, ERR_CATALOG_TRANSITION_INVALID, 409)

    final = fixtures.read_program(api, program_id)
    assertions.assert_axes(
        final, lifecycle_state="UNDER_REVIEW", catalog_status="ADMISSIONS_CLOSED"
    )
    # No decision cascade has run, so no pre-decision value was captured.
    assert final["catalog_status_pre_decision"] is None
    assert cycle["state"] == "SELF_STUDY_OPEN"
