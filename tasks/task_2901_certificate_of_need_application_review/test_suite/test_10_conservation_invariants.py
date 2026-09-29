"""Conserved quantities: released beds and released dollars compensate exactly."""

from test_helpers import (
    api_client,
    assert_cycle_pool_invariant,
    get_success_data,
)
from test_helpers.constants import EXPECTED_CEILING_CENTS
from test_helpers.fixtures import (
    ADMIN,
    advance_appeal,
    decide_appeal,
    file_appeal,
    refresh_applicant,
    refresh_application,
    refresh_certificate,
    refresh_cycle,
    refresh_health_service_area,
    seed_decided_cycle,
    seed_issued_certificate,
    set_clock,
)

APPEAL_FILING_CLOCK = "2026-10-01T00:00:00Z"
PAST_MILESTONE_CLOCK = "2027-07-01T00:00:00Z"


def _heard_appeal_without_a_certificate():
    """An approved award under appeal, with no certificate anywhere in the chain."""
    world = seed_decided_cycle()
    set_clock(APPEAL_FILING_CLOCK)
    world["appeal"] = file_appeal(
        world["application"],
        world["applicant"],
        "Need methodology misapplied to this project",
    )
    advance_appeal(world["appeal"], "BRIEFING")
    world["appeal"] = advance_appeal(world["appeal"], "HEARD")
    return world


class TestBedNeedConservation:
    def test_the_award_debits_the_pool_by_exactly_the_allocated_count(self):
        """19 opens as 19 unallocated; a 12-bed award leaves 7 and 12 + 7 is 19.

        PRD §2.10: "A batching cycle's `unallocated_bed_need` starts equal to
        `unmet_bed_need_at_open` and holds the beds of that fixed pool not
        currently held by an approved application in the cycle."
        PRD §2.10: "The invariant checked after any allocation or release is that
        `unallocated_bed_need` plus the sum of `allocated_bed_count` over the
        cycle's applications whose status is `APPROVED` or
        `APPROVED_WITH_CONDITIONS` equals `unmet_bed_need_at_open`."

        Design: Difficulty/compensating_invariant/bed_need_conservation_across_award_and_appeal_release
        """
        world = seed_decided_cycle()
        cycle = refresh_cycle(world["cycle"]["id"])
        application = refresh_application(world["application"]["id"])

        assert cycle["unmet_bed_need_at_open"] == 19
        assert application["status"] == "APPROVED"
        assert application["allocated_bed_count"] == 12
        assert cycle["unallocated_bed_need"] == 7
        assert_cycle_pool_invariant(cycle, [application])

    def test_the_reversal_credits_back_exactly_what_the_award_debited(self):
        """The release restores 19 rather than recomputing need from scratch.

        PRD §2.10: "Every award debits it, and every release — a lapse, a
        revocation, a reversal, a remand — credits it back."
        PRD §2.10: "The invariant checked after any allocation or release is that
        `unallocated_bed_need` plus the sum of `allocated_bed_count` over the
        cycle's applications whose status is `APPROVED` or
        `APPROVED_WITH_CONDITIONS` equals `unmet_bed_need_at_open`."

        Design: Difficulty/compensating_invariant/bed_need_conservation_across_award_and_appeal_release
        """
        world = _heard_appeal_without_a_certificate()

        appeal = decide_appeal(
            world["appeal"], "REVERSED", "Need finding vacated on the record"
        )

        assert appeal["status"] == "REVERSED"
        application = refresh_application(world["application"]["id"])
        assert application["status"] == "DENIED"
        assert application["denial_reason"] == "APPEAL_REVERSED"
        assert application["allocated_bed_count"] == 0

        cycle = refresh_cycle(world["cycle"]["id"])
        assert cycle["unallocated_bed_need"] == 19
        assert cycle["unmet_bed_need_at_open"] == 19
        assert_cycle_pool_invariant(cycle, [application])

    def test_a_release_without_a_certificate_never_touches_the_bed_books(self):
        """No certificate was issued, so the planning area's beds never moved.

        PRD §2.10: "Issuing a certificate credits `approved_unimplemented_beds`;
        implementing the project moves the same count out of
        `approved_unimplemented_beds` and into `existing_licensed_beds`; revoking,
        lapsing or superseding a certificate debits `approved_unimplemented_beds`."

        Design: Difficulty/compensating_invariant/bed_need_conservation_across_award_and_appeal_release
        """
        world = _heard_appeal_without_a_certificate()

        decide_appeal(world["appeal"], "REVERSED", "Need finding vacated on the record")

        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["existing_licensed_beds"] == 70


class TestCapitalAuthorizationConservation:
    def test_issuance_charges_the_area_with_the_whole_approved_limit(self):
        """The committed sum runs from 0 to the certificate's own limit.

        PRD §2.10: "A planning area's `capital_authorization_committed_cents` is
        the sum of `approved_expenditure_limit_cents` over the certificates in
        that area whose `lifecycle_status` is `ISSUED`, `IMPLEMENTED` or
        `SUSPENDED`."
        PRD §3.8: "On the planning area, `approved_unimplemented_beds` is
        increased by the certificate's `authorized_bed_count` and
        `capital_authorization_committed_cents` is increased by its
        `approved_expenditure_limit_cents`."

        Design: Difficulty/compensating_invariant/capital_authorization_conservation_across_issue_and_lapse
        """
        world = seed_issued_certificate()

        certificate = world["certificate"]
        assert certificate["authorized_bed_count"] == 12
        assert certificate["latest_completion_pct"] == 0
        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["capital_authorization_committed_cents"] == 1000000000
        assert hsa["approved_unimplemented_beds"] == 12

    def test_the_lapse_sweep_credits_back_exactly_what_issuance_charged(self):
        """One certificate examined, one lapsed, and the committed sum back to 0.

        PRD §3.8: "A certificate lapses when its
        `implementation_milestone_date` is strictly earlier than the current date
        on the logical clock **and** its `latest_completion_pct` is strictly less
        than its `required_completion_pct_at_milestone`."
        PRD §3.8: "Each lapse sets `lifecycle_status` to `LAPSED` and increases
        the certificate's `version` by 1, then unwinds every commitment the
        issuance made: the planning area's `approved_unimplemented_beds` is
        decreased by the certificate's `authorized_bed_count`, its
        `capital_authorization_committed_cents` is decreased by the certificate's
        `approved_expenditure_limit_cents`, the cycle's `unallocated_bed_need` is
        increased by the `authorized_bed_count` while the underlying
        application's `allocated_bed_count` is set to 0, and the applicant's
        `compliance_strike_count` increases by 1 with the standing consequences
        already described."
        PRD §3.8: "The sweep reports what it did as `evaluated_count`, the number
        of certificates it examined, `lapsed_count`, the number it lapsed, and
        `lapsed_certificate_ids`, the identifiers of those certificates."

        Design: Difficulty/compensating_invariant/capital_authorization_conservation_across_issue_and_lapse
        """
        world = seed_issued_certificate()
        set_clock(PAST_MILESTONE_CLOCK)

        summary = get_success_data(api_client.run_lapse_sweep(ADMIN))

        assert summary["evaluated_count"] == 1
        assert summary["lapsed_count"] == 1
        assert summary["lapsed_certificate_ids"] == [world["certificate"]["id"]]

        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["lifecycle_status"] == "LAPSED"
        assert certificate["expenditure_ceiling_cents"] == EXPECTED_CEILING_CENTS

        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["capital_authorization_committed_cents"] == 0
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["existing_licensed_beds"] == 70

    def test_the_lapse_releases_the_beds_and_charges_one_strike(self):
        """The bed pool and the applicant's record move in the same sweep.

        PRD §2.10: "Every award debits it, and every release — a lapse, a
        revocation, a reversal, a remand — credits it back."
        PRD §3.1: "The two fields are linked by a fixed rule: `standing` flips to
        `RESTRICTED` when `compliance_strike_count` reaches 2 and to `BARRED` when
        it reaches 4."

        Design: Difficulty/compensating_invariant/capital_authorization_conservation_across_issue_and_lapse
        """
        world = seed_issued_certificate()
        set_clock(PAST_MILESTONE_CLOCK)

        api_client.run_lapse_sweep(ADMIN)

        application = refresh_application(world["application"]["id"])
        cycle = refresh_cycle(world["cycle"]["id"])
        assert application["allocated_bed_count"] == 0
        assert cycle["unallocated_bed_need"] == 19
        assert_cycle_pool_invariant(cycle, [application])

        applicant = refresh_applicant(world["applicant"]["id"])
        assert applicant["compliance_strike_count"] == 1
        assert applicant["standing"] == "GOOD"
