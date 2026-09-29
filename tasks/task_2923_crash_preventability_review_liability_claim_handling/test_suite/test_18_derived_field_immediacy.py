"""Derived values arrive with the write that causes them, never one read later.

Nothing in this API is backfilled: the body of the request that changes a fact
already carries every value re-derived from it, and the read that immediately
follows repeats that body rather than correcting it.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_cents, assert_instants_equal, assert_points_1dp
from test_helpers.constants import (
    ACTION_TIER_NONE,
    CLAIM_HANDLING_SETUP,
    DRIVER_STATUS_ACTIVE,
    EMPLOYMENT_DECISION_PENDING,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_TELEMATICS,
    PRESERVATION_PRESERVED,
    PRESERVATION_REQUESTED,
    PREVENTABILITY_REPORTED,
    REPORTING_STATUS_PENDING_FILING,
    RESERVE_STATUS_PROVISIONAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    STAFFING_POSTURE_OK,
    TENURE_OVER_36_MONTHS,
    TOW_REASON_DISABLING_DAMAGE,
)
from test_helpers.fixtures import (
    AUDITOR,
    CLAIMS_ADJUSTER,
    DISPATCHER,
    SAFETY_ADMIN,
    build_crash,
    build_driver,
    build_terminal,
)

RAVENNA_MILES = 2.0
RAVENNA_OCCURRED_AT = "2026-07-31T20:00:00Z"
RAVENNA_NOTIFIED_AT = "2026-07-31T20:30:00Z"
RAVENNA_DUE_AT = "2026-08-03T20:00:00Z"
DISABLING_TOW_CODE = "DISABLING_TOW"
MINOR_RESERVE_CENTS = 500_000
REPORTED_ON_A_COMPLETE_RECORD_SCORE = 5


def _ravenna_terminal(api: ApiClient) -> dict:
    """A terminal read back the instant it is registered."""
    created = build_terminal(
        api,
        name="Ravenna Terminal",
        terminal_code="RAV03",
        region_code="OH",
        annual_miles_millions=RAVENNA_MILES,
    )
    return created


def _ravenna_driver(api: ApiClient, terminal_id: str) -> dict:
    """One long-tenured driver, hired well over 1096 days before the clock."""
    return build_driver(
        api,
        terminal_id,
        employee_code="D-6601",
        full_name="Pelle Ostergaard",
        cdl_number="OH-CDL-6601",
        hire_date="2013-05-05",
    )


def _ravenna_crash(api: ApiClient, driver_id: str, terminal_id: str) -> dict:
    """A minor crash whose only recordability trigger is a disabling tow."""
    return build_crash(
        api,
        driver_id,
        terminal_id,
        occurred_at=RAVENNA_OCCURRED_AT,
        notified_at=RAVENNA_NOTIFIED_AT,
        location_text="SR-14 at the quarry",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )


class TestEveryDerivedFieldIsCurrentInTheWritingResponse:
    """Four writes, each checked against the read that follows it immediately."""

    def test_the_headcount_and_the_driver_bands_are_current_in_their_own_writes(
        self, api: ApiClient
    ):
        """The terminal counter moves on the hire, not on some later sweep.

        PRD: "A freshly registered terminal reports zero for every counter and an
        `OK` `staffing_posture`." and "`active_driver_count` counts every driver
        domiciled at the terminal whose `status` is anything other than
        `TERMINATED`"

        Design: Corner/consistency_model/every_derived_field_is_already_current_in_the_writing_response
        """
        terminal = _ravenna_terminal(api)
        assert terminal["active_driver_count"] == 0
        assert terminal["suspended_driver_count"] == 0
        assert terminal["preventable_crash_count"] == 0
        assert terminal["late_filing_count"] == 0
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK

        driver = _ravenna_driver(api, terminal["id"])
        assert driver["status"] == DRIVER_STATUS_ACTIVE
        assert driver["continued_employment_decision"] == EMPLOYMENT_DECISION_PENDING
        assert driver["tenure_band"] == TENURE_OVER_36_MONTHS
        assert_points_1dp(driver["preventable_points"], 0.0, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_NONE

        after_hire = validate_success(api.get_terminal(terminal["id"], SAFETY_ADMIN))
        assert after_hire["active_driver_count"] == 1
        assert after_hire["suspended_driver_count"] == 0
        assert after_hire["staffing_posture"] == STAFFING_POSTURE_OK

        read_driver = validate_success(api.get_driver(driver["id"], SAFETY_ADMIN))
        assert read_driver["tenure_band"] == driver["tenure_band"]
        assert_points_1dp(
            read_driver["preventable_points"],
            0.0,
            "preventable_points on the following read",
        )
        assert read_driver["required_action_tier"] == driver["required_action_tier"]

    def test_the_intake_response_already_carries_the_frozen_filing_dimension(
        self, api: ApiClient
    ):
        """Recordability, the deadline and the opening postures all land at once.

        PRD: "`report_due_at` is 24 hours after `occurred_at` when a
        hazardous-material release occurred, and 72 hours — three days — after
        `occurred_at` otherwise, and `reporting_status` starts at
        `PENDING_FILING`." and "Regardless of recordability, a new crash starts
        with `preventability_status` of `REPORTED`, an `evidence_posture` of
        `PARTIAL` and `appeals_exhausted` false."

        Design: Corner/consistency_model/every_derived_field_is_already_current_in_the_writing_response
        """
        terminal = _ravenna_terminal(api)
        driver = _ravenna_driver(api, terminal["id"])
        crash = _ravenna_crash(api, driver["id"], terminal["id"])

        assert crash["dot_recordable"] is True
        assert crash["recordability_codes"] == [DISABLING_TOW_CODE]
        assert_instants_equal(crash["report_due_at"], RAVENNA_DUE_AT, "report_due_at")
        assert crash["reporting_status"] == REPORTING_STATUS_PENDING_FILING
        assert crash["preventability_status"] == PREVENTABILITY_REPORTED
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL
        assert crash["appeals_exhausted"] is False

        read_back = validate_success(api.get_crash(crash["id"], AUDITOR))
        assert read_back["dot_recordable"] == crash["dot_recordable"]
        assert read_back["recordability_codes"] == crash["recordability_codes"]
        assert_instants_equal(
            read_back["report_due_at"], RAVENNA_DUE_AT, "report_due_at on the read"
        )
        assert read_back["reporting_status"] == crash["reporting_status"]
        assert read_back["evidence_posture"] == crash["evidence_posture"]
        assert read_back["version"] == crash["version"]

    def test_preserving_the_required_kind_moves_the_posture_in_that_same_request(
        self, api: ApiClient
    ):
        """A requested item leaves the posture partial; preservation completes it.

        PRD: "**Evidence posture** is the derived field that decides whether the
        committee may rule at all, and it is recomputed from scratch on every read
        of the crash and after every preservation or purge. The required kind set
        depends on `severity`: a `MINOR` crash requires a `TELEMATICS_SNAPSHOT`
        alone" and "A required kind counts as satisfied only by an item that is
        currently in `PRESERVED` state *and* whose data window brackets the crash
        instant"

        Design: Corner/consistency_model/every_derived_field_is_already_current_in_the_writing_response
        """
        terminal = _ravenna_terminal(api)
        driver = _ravenna_driver(api, terminal["id"])
        crash = _ravenna_crash(api, driver["id"], terminal["id"])

        requested = validate_success(
            api.create_evidence_item(
                crash["id"],
                factories.evidence_payload(
                    kind=EVIDENCE_TELEMATICS,
                    source_device_id="ECM-6601",
                    window_start_at="2026-07-31T19:00:00Z",
                    window_end_at="2026-07-31T21:00:00Z",
                    retention_deadline_at="2027-06-30T00:00:00Z",
                ),
                DISPATCHER,
            ),
            201,
        )
        assert requested["preservation_state"] == PRESERVATION_REQUESTED

        still_partial = validate_success(api.get_crash(crash["id"], AUDITOR))
        assert still_partial["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL

        preserved = validate_success(
            api.preserve_evidence_item(
                requested["id"],
                factories.preserve_payload(
                    preserved_copy_uri="s3://evidence/2923rav/ecm-6601.json",
                    evidence_hash="9a9a0b0b1c1c2d2d3e3e4f4f5a5a6b6b",
                ),
                DISPATCHER,
            )
        )
        assert preserved["preservation_state"] == PRESERVATION_PRESERVED
        assert preserved["version"] == requested["version"] + 1

        now_complete = validate_success(api.get_crash(crash["id"], AUDITOR))
        assert now_complete["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

    def test_the_claim_creation_response_already_carries_its_scored_money(
        self, api: ApiClient
    ):
        """The score, the multiplier band and all four money fields are populated.

        PRD: "`litigation_risk_score` starts from the crash's preventability: 30
        points when the crash has been found `PREVENTABLE`, 10 while it is still
        `UNDER_REVIEW`, 5 while it is merely `REPORTED`, and nothing at all once it
        has been found `NON_PREVENTABLE`. The crash's evidence posture adds 25
        points when the record is `COMPROMISED`, 5 when it is `PARTIAL` and nothing
        when it is `COMPLETE`."

        Design: Corner/consistency_model/every_derived_field_is_already_current_in_the_writing_response
        """
        terminal = _ravenna_terminal(api)
        driver = _ravenna_driver(api, terminal["id"])
        crash = _ravenna_crash(api, driver["id"], terminal["id"])
        preserved = validate_success(
            api.create_evidence_item(
                crash["id"],
                factories.evidence_payload(
                    kind=EVIDENCE_TELEMATICS,
                    source_device_id="ECM-6601",
                    window_start_at="2026-07-31T19:00:00Z",
                    window_end_at="2026-07-31T21:00:00Z",
                    retention_deadline_at="2027-06-30T00:00:00Z",
                ),
                DISPATCHER,
            ),
            201,
        )
        validate_success(
            api.preserve_evidence_item(
                preserved["id"],
                factories.preserve_payload(
                    preserved_copy_uri="s3://evidence/2923rav/ecm-6601.json",
                    evidence_hash="9a9a0b0b1c1c2d2d3e3e4f4f5a5a6b6b",
                ),
                DISPATCHER,
            )
        )

        claim = validate_success(
            api.create_claim(
                factories.claim_payload(crash["id"], claimant_notice_date="2026-08-01"),
                CLAIMS_ADJUSTER,
            ),
            201,
        )
        assert claim["handling_status"] == CLAIM_HANDLING_SETUP
        assert claim["reserve_status"] == RESERVE_STATUS_PROVISIONAL
        assert claim["litigation_risk_score"] == REPORTED_ON_A_COMPLETE_RECORD_SCORE
        assert claim["counsel_required"] is False
        assert claim["counsel_assigned"] is False
        for field in (
            "provisional_reserve_cents",
            "outstanding_reserve_cents",
            "total_incurred_cents",
            "claim_exposure_cents",
        ):
            assert_cents(claim[field], MINOR_RESERVE_CENTS, field)

        read_back = validate_success(api.get_claim(claim["id"], AUDITOR))
        assert read_back["litigation_risk_score"] == claim["litigation_risk_score"]
        assert read_back["counsel_required"] == claim["counsel_required"]
        assert read_back["version"] == claim["version"]
        for field in (
            "provisional_reserve_cents",
            "outstanding_reserve_cents",
            "total_incurred_cents",
            "claim_exposure_cents",
        ):
            assert_cents(read_back[field], MINOR_RESERVE_CENTS, f"{field} on the read")
