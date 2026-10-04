"""Workflows and cascades: the objection/resubmission version chain, variant
parallel dimensions, circular publish cascades, and agreement termination
cascades (PRD §3.3, §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    create_filing_payload,
    create_variant_payload,
    get_success_data,
    make_approved_form,
    make_insurer,
    make_agreement,
    make_objected_filing,
    set_clock,
    setup_adoption_scenario,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


class TestObjectionResubmissionCycle:
    """Cyclic version-chain machine: OBJECTED answers with a new DRAFT node."""

    def test_resubmission_creates_draft_node_at_next_chain_version(self, api):
        """PRD §3.3: "On success the new filing is created in `DRAFT` with
        `filing_version` equal to the superseded filing's version number plus
        1, while the superseded filing itself transitions from `OBJECTED` to
        `WITHDRAWN` (terminal) with its `version` incremented by 1."

        Design: Difficulty/non_linear_state_machine/filing_objection_resubmission_cycle_advances_version_chain
        """
        objected, _dept, _obj = make_objected_filing()
        resp = api.create_filing(
            create_filing_payload(
                trend_selection="EXPONENTIAL_LEAST_SQUARES",
                effective_date="2027-03-01T00:00:00Z",
                supersedes_filing_id=objected["id"],
                expected_superseded_version=objected["version"],
            ),
            ADMIN,
        )
        new_filing = validate_success(resp, expected_status=201)
        assert new_filing["filing_version"] == objected["filing_version"] + 1
        assert new_filing["filing_status"] == "DRAFT"
        assert new_filing["supersedes_filing_id"] == objected["id"]

    def test_superseded_filing_is_compensated_to_withdrawn_with_version_bump(self, api):
        """PRD §3.3: "An `OBJECTED` filing is answered by resubmission, and
        the cycle lives on the version chain rather than on the row."
        PRD §2.5: "Whenever a cascade described in §3 touches a parent
        resource — recomputing an insurer's quality score on submission
        disposition, superseding a filing on resubmission, advancing a class
        plan's current revision — that touch is itself a mutation: the
        parent's `updated_at` refreshes and its `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/filing_objection_resubmission_cycle_advances_version_chain
        """
        objected, _dept, _obj = make_objected_filing()
        resp = api.create_filing(
            create_filing_payload(
                effective_date="2027-03-01T00:00:00Z",
                supersedes_filing_id=objected["id"],
                expected_superseded_version=objected["version"],
            ),
            ADMIN,
        )
        validate_success(resp, expected_status=201)
        superseded = validate_success(api.get_filing(objected["id"], ADMIN))
        assert superseded["filing_status"] == "WITHDRAWN"
        assert superseded["version"] == objected["version"] + 1


class TestFormVariantParallelDimensions:
    """review_status and publication_status advance on independent triggers."""

    def test_publish_moves_only_publication_dimension_to_scheduled(self, api):
        """PRD §3.5: "when the parent form reaches `PUBLISHED` through
        circular publication, every variant of that form whose `review_status`
        is `CLEARED` transitions `publication_status` from `UNPUBLISHED` to
        `SCHEDULED`".
        PRD §3.5: "Publication is a cascade: the circular itself moves from
        `DRAFT` to `PUBLISHED`; every listed form that is `APPROVED` moves to
        `PUBLISHED`, which in turn schedules that form's `CLEARED` variants
        per the publication dimension above".

        Design: Difficulty/non_linear_state_machine/form_variant_parallel_dimensions_evolve_independently
        """
        form, variants = make_approved_form(
            [{"effective_from": "2026-10-01T00:00:00Z", "effective_to": None}]
        )
        variant = variants[0]
        # The review dimension moved alone before any publication.
        assert variant["review_status"] == "CLEARED"
        assert variant["publication_status"] == "UNPUBLISHED"
        circ = get_success_data(api.create_circular(
            {"circular_number": "CIR-2026-07", "subject": "Publication",
             "implementation_date": "2026-10-01T00:00:00Z", "form_ids": [form["id"]]},
            ADMIN,
        ))
        validate_success(api.publish_circular(circ["id"], ADMIN))
        after = validate_success(api.get_variant(variant["id"], ADMIN))
        assert after["publication_status"] == "SCHEDULED"
        assert after["review_status"] == "CLEARED"

    def test_clock_reaching_implementation_date_moves_scheduled_variant_live(self, api):
        """PRD §3.5: "when the logical clock reaches the publishing circular's
        `implementation_date`, each `SCHEDULED` variant transitions to `LIVE`,
        opening the licensed-use gate — insurers holding an `ACTIVE` license
        agreement covering that date may use the variant."
        PRD §3.5: "Publication is a cascade: the circular itself moves from
        `DRAFT` to `PUBLISHED`; every listed form that is `APPROVED` moves to
        `PUBLISHED`, which in turn schedules that form's `CLEARED` variants
        per the publication dimension above".

        Design: Difficulty/non_linear_state_machine/form_variant_parallel_dimensions_evolve_independently
        """
        form, variants = make_approved_form(
            [{"effective_from": "2026-10-01T00:00:00Z", "effective_to": None}]
        )
        variant = variants[0]
        circ = get_success_data(api.create_circular(
            {"circular_number": "CIR-2026-08", "subject": "Publication",
             "implementation_date": "2026-10-01T00:00:00Z", "form_ids": [form["id"]]},
            ADMIN,
        ))
        validate_success(api.publish_circular(circ["id"], ADMIN))
        set_clock("2026-10-01T00:00:00Z")
        after = validate_success(api.get_variant(variant["id"], ADMIN))
        assert after["publication_status"] == "LIVE"
        form_after = validate_success(api.get_form(form["id"], ADMIN))
        assert form_after["form_status"] == "PUBLISHED"


class TestCircularPublishCascade:
    """Depth-3 cascade: circular publish -> form PUBLISHED -> variant SCHEDULED."""

    def test_publish_cascades_to_listed_form(self, api):
        """PRD §3.5: "Publication is a cascade: the circular itself moves from
        `DRAFT` to `PUBLISHED`; every listed form that is `APPROVED` moves to
        `PUBLISHED`, which in turn schedules that form's `CLEARED` variants
        per the publication dimension above; and the superseded circular, if
        any, moves from `PUBLISHED` to `SUPERSEDED`."

        Design: Difficulty/transitive_cascade/circular_publish_cascades_form_then_variant
        """
        form, variants = make_approved_form()
        circ = get_success_data(api.create_circular(
            {"circular_number": "CIR-2026-11", "subject": "Publication",
             "implementation_date": "2026-11-01T00:00:00Z", "form_ids": [form["id"]]},
            ADMIN,
        ))
        resp = api.publish_circular(circ["id"], ADMIN)
        circular = validate_success(resp)
        assert circular["circular_status"] == "PUBLISHED"
        form_after = validate_success(api.get_form(form["id"], ADMIN))
        assert form_after["form_status"] == "PUBLISHED"

    def test_publish_cascades_to_cleared_variants_of_listed_form(self, api):
        """PRD §3.5: "when the parent form reaches `PUBLISHED` through
        circular publication, every variant of that form whose `review_status`
        is `CLEARED` transitions `publication_status` from `UNPUBLISHED` to
        `SCHEDULED`".

        Design: Difficulty/transitive_cascade/circular_publish_cascades_form_then_variant
        """
        form, variants = make_approved_form()
        circ = get_success_data(api.create_circular(
            {"circular_number": "CIR-2026-12", "subject": "Publication",
             "implementation_date": "2026-11-01T00:00:00Z", "form_ids": [form["id"]]},
            ADMIN,
        ))
        validate_success(api.publish_circular(circ["id"], ADMIN))
        variant_after = validate_success(api.get_variant(variants[0]["id"], ADMIN))
        assert variant_after["publication_status"] == "SCHEDULED"
        assert variant_after["review_status"] == "CLEARED"


class TestAgreementTerminateCascade:
    """Depth-2 cascade: agreement terminate -> pending adoptions WITHDRAWN."""

    def test_terminate_moves_agreement_to_terminated(self, api):
        """PRD §3.4: "Active termination by a `BureauAdmin` requires the
        insurer to hold zero `AUTHORIZED` adoptions; it moves the agreement's
        `agreement_status` from `ACTIVE` to `TERMINATED` and likewise
        withdraws every `PENDING` adoption of the insurer, marked
        `LICENCE_TERMINATED`."

        Design: Difficulty/transitive_cascade/agreement_terminate_cascades_to_pending_adoption_withdrawal
        """
        scenario = setup_adoption_scenario(
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
        )
        resp = api.terminate_agreement(scenario["agreement"]["id"], ADMIN)
        agreement = validate_success(resp)
        assert agreement["agreement_status"] == "TERMINATED"

    def test_terminate_withdraws_pending_adoptions_of_the_insurer(self, api):
        """PRD §3.4: "it moves the agreement's `agreement_status` from
        `ACTIVE` to `TERMINATED` and likewise withdraws every `PENDING`
        adoption of the insurer, marked `LICENCE_TERMINATED`."

        Design: Difficulty/transitive_cascade/agreement_terminate_cascades_to_pending_adoption_withdrawal
        """
        scenario = setup_adoption_scenario(
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
        )
        validate_success(api.terminate_agreement(scenario["agreement"]["id"], ADMIN))
        adoption = validate_success(api.get_adoption(scenario["adoption"]["id"], ADMIN))
        assert adoption["adoption_status"] == "WITHDRAWN"
