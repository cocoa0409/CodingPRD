"""Non-linear state machines: the certificate submission cycle and the proof cycle."""

import pytest

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

ROOT_PROOF_ONE = {
    "milk_kg": 900,
    "fat_kg": 40,
    "protein_kg": 30,
    "somatic_cell_score": 2.85,
    "fertility_pct": 1.5,
    "longevity_months": 2.0,
    "reliability_pct": 75,
    "progeny_daughter_count": 120,
    "effective_at": "2026-07-01T00:00:00Z",
}

ROOT_PROOF_TWO = {
    "milk_kg": 700,
    "fat_kg": 30,
    "protein_kg": 24,
    "somatic_cell_score": 2.95,
    "fertility_pct": 1.0,
    "longevity_months": 1.0,
    "reliability_pct": 98,
    "progeny_daughter_count": 60,
    "effective_at": "2026-07-20T00:00:00Z",
}


def _draft_certificate_for_a_released_lot(api):
    """A DRAFT certificate binding REG-B, his RELEASED lot and the CA rule set."""
    requirement = fx.register_country_requirement(
        api,
        country_code="CA",
        required_test_types=["BLUETONGUE", "IBR"],
        max_test_age_days=60,
        min_isolation_days=21,
        sexed_semen_allowed=True,
        embryo_allowed=False,
    )
    context = fx.released_lot(
        api,
        facility_overrides={
            "code": "F-IA-05",
            "housing_capacity": 2,
            "bench_capacity": 1,
            "approved_export_countries": ["CA"],
        },
        registration_code="REG-B",
        sire_overrides={
            "breed": "ANGUS",
            "birth_date": "2022-06-01",
            "acquisition_cost_cents": 900000,
        },
        product_line="CONVENTIONAL",
        straw_count=200,
        processing_cost_cents=250000,
    )
    context["country_requirement"] = requirement
    context["certificate"] = fx.draft_certificate(
        api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
    )
    return context


class TestCertificateSubmissionCycle:
    """SUBMITTED -> REJECTED -> SUBMITTED runs three times and then stops."""

    def test_the_counter_records_submissions_not_rejections(self, api):
        """The destination authority's refusal is recorded as
        `SUBMITTED -> REJECTED` with a `rejection_reason`, and it deliberately
        leaves `submission_round` unchanged — the counter records submissions,
        not rejections.

        Design: Difficulty/non_linear_state_machine/certificate_reject_resubmit_cycle_capped_at_three_rounds
        """
        context = _draft_certificate_for_a_released_lot(api)
        certificate = context["certificate"]
        assert certificate["submission_round"] == 0
        assert certificate["status"] == "DRAFT"

        first = fx.submit_certificate(api, certificate["id"])
        assert first["status"] == "SUBMITTED"
        assert first["submission_round"] == 1

        rejected = fx.reject_certificate(
            api, certificate["id"], rejection_reason="MISSING_HERD_ATTESTATION"
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "MISSING_HERD_ATTESTATION"
        assert rejected["submission_round"] == 1

        second = fx.submit_certificate(api, certificate["id"])
        assert second["status"] == "SUBMITTED"
        assert second["submission_round"] == 2
        assert second["rejection_reason"] is None

    def test_the_fourth_submission_is_refused_at_the_three_round_cap(self, api):
        """Its `submission_round` must be strictly below 3 at the moment of
        submission, because a certificate may enter `SUBMITTED` at most three
        times; a fourth attempt is refused with `ERR_RESUBMISSION_LIMIT`.

        Design: Difficulty/non_linear_state_machine/certificate_reject_resubmit_cycle_capped_at_three_rounds
        """
        context = _draft_certificate_for_a_released_lot(api)
        certificate_id = context["certificate"]["id"]

        for reason in (
            "MISSING_HERD_ATTESTATION",
            "WRONG_LOT_REFERENCE",
            "STALE_TEST_DATE",
        ):
            fx.submit_certificate(api, certificate_id)
            fx.reject_certificate(api, certificate_id, rejection_reason=reason)

        third_round = fx.read_certificate(api, certificate_id)
        assert third_round["submission_round"] == 3
        assert third_round["status"] == "REJECTED"

        validate_error(
            api.submit_export_certificate(
                certificate_id, factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            ApiErrorId.ERR_RESUBMISSION_LIMIT.value,
            422,
        )

        unchanged = fx.read_certificate(api, certificate_id)
        assert unchanged["status"] == "REJECTED"
        assert unchanged["submission_round"] == 3


class TestProofSupersessionCycle:
    """A single evaluation row may leave PUBLISHED and return to it."""

    @staticmethod
    def _two_proofs(api):
        bull = fx.register_sire(
            api,
            registration_code="REG-A",
            birth_date="2020-03-01",
            acquisition_cost_cents=0,
        )
        first = fx.published_proof(api, bull["id"], **ROOT_PROOF_ONE)
        second = fx.file_evaluation(api, bull["id"], **ROOT_PROOF_TWO)
        return bull, first, second

    def test_publication_supersedes_the_incumbent_proof(self, api):
        """On success `published_at` is stamped from the logical clock,
        `supersedes_evaluation_id` is set to the id of the bull's previously
        published evaluation — null when this is his first — and that previously
        published row moves `PUBLISHED -> SUPERSEDED`, stopping its contribution
        to the bull's published snapshot.

        Design: Difficulty/non_linear_state_machine/evaluation_superseded_then_reinstated_cycle
        """
        bull, first, second = self._two_proofs(api)
        assert first["composite_index"] == pytest.approx(62.37, abs=0.01)
        assert first["supersedes_evaluation_id"] is None
        assert second["composite_index"] == pytest.approx(34.95, abs=0.01)

        promoted = fx.publish_evaluation(api, second["id"])
        assert promoted["status"] == "PUBLISHED"
        assert promoted["supersedes_evaluation_id"] == first["id"]

        displaced = fx.read_evaluation(api, first["id"])
        assert displaced["status"] == "SUPERSEDED"

        sire = fx.read_sire(api, bull["id"])
        assert sire["published_composite_index"] == pytest.approx(34.95, abs=0.01)

    def test_rollback_reinstates_the_superseded_row_without_creating_one(self, api):
        """Compensating hop 1 reinstates the row named by
        `supersedes_evaluation_id` from `SUPERSEDED` back to `PUBLISHED` and
        refreshes the bull's published snapshot from it.

        Design: Difficulty/non_linear_state_machine/evaluation_superseded_then_reinstated_cycle
        """
        bull, first, second = self._two_proofs(api)
        fx.publish_evaluation(api, second["id"])

        withdrawn = fx.rollback_evaluation(api, second["id"])
        assert withdrawn["status"] == "ROLLED_BACK"

        reinstated = fx.read_evaluation(api, first["id"])
        assert reinstated["status"] == "PUBLISHED"

        sire = fx.read_sire(api, bull["id"])
        assert sire["published_composite_index"] == pytest.approx(62.37, abs=0.01)
        assert sire["published_production_index"] == pytest.approx(49.50, abs=0.01)
        assert sire["published_health_index"] == pytest.approx(99.00, abs=0.01)

        rows, meta = validate_paginated(
            api.list_genomic_evaluations(fx.DIRECTOR, {"sire_id": bull["id"]})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
