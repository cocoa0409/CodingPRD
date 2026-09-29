"""
Endpoint behaviour: partial updates, link creation, computed reads and bulk work.

The reads here are taken after the write they describe, so what the endpoint
promised in its response is checked again against the stored row.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    NON_EXISTENT_UUID,
    STATE_AUDITOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    accept_designation,
    accept_report_action,
    assert_caseload_decomposition,
    assert_exact_whole,
    assert_instant_equals,
    assert_pct_1dp,
    assert_pct_2dp,
    assert_versioned_shape,
    compute_report_payload,
    conditions,
    create_active_representative,
    create_counseled_review,
    create_draft_claim,
    create_exam_site,
    create_represented_veteran,
    create_submitted_report,
    create_veteran,
    make_county_officer_headers,
    offer_designation,
    open_outcome_report,
    plan_outreach_event,
    poa_payload,
    read_caseload,
    read_claim,
    read_decision_review,
    read_exam_site,
    read_outcome_report,
    read_representative,
    register_representative,
    return_report_action,
    revoke_poa_payload,
    set_clock,
    set_clock_date,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


class TestRepresentativePatchTouchesOnlyTheSuppliedField:
    """A one-key correction rewrites one field and leaves the rest alone."""

    @pytest.fixture
    def registered(self, api):
        """A registry row still in PENDING, with every input known."""
        return register_representative(
            api,
            full_name="Dana Reyes",
            accreditation_number="ACC-2849-541",
            accreditation_type="COUNTY_CVSO",
            accreditation_expires_on="2029-12-31",
        )

    def test_the_patch_response_rewrites_the_name_and_bumps_the_version(
        self, api, registered
    ):
        """
        "Reusing an `accreditation_number` another representative already holds is refused with `ERR_DUPLICATE_ACCREDITATION_NUMBER`; the same uniqueness check runs again when registry details are corrected, and a correction may touch `full_name`, `accreditation_number`, `accreditation_type` or `accreditation_expires_on` but never a lifecycle field."

        Design: Corner/endpoints/corner_representative_patch_updates_only_the_supplied_fields
        """
        patched = validate_success(
            api.update_representative(
                registered["id"], {"full_name": "Dana Reyes-Okafor"}, SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        assert patched["full_name"] == "Dana Reyes-Okafor"
        assert_versioned_shape(patched, expected_version=2)

    def test_the_following_read_returns_the_patched_row_untouched_elsewhere(
        self, api, registered
    ):
        """
        "A fresh row lands in `accreditation_status` `PENDING` with `ce_credits_earned` at 0, `active_poa_count` at 0, `caseload_weight` at 0, and `revocation_reason` unset."
        A correction "may touch `full_name`, `accreditation_number`, `accreditation_type` or `accreditation_expires_on` but never a lifecycle field", so the lifecycle field the row started on still reads `PENDING`.

        Design: Corner/endpoints/corner_representative_patch_updates_only_the_supplied_fields
        """
        api.update_representative(
            registered["id"], {"full_name": "Dana Reyes-Okafor"}, SYSTEM_ADMIN_HEADERS
        )
        stored = read_representative(api, registered["id"])
        assert stored["full_name"] == "Dana Reyes-Okafor"
        assert stored["accreditation_number"] == "ACC-2849-541"
        assert stored["accreditation_type"] == "COUNTY_CVSO"
        assert stored["accreditation_expires_on"] == "2029-12-31"
        assert stored["accreditation_status"] == "PENDING"


class TestDesignationLinkNeedsBothEndpoints:
    """The instrument joins two rows, so both foreign keys must resolve."""

    def test_an_unused_representative_id_is_the_representative_specific_code(self, api):
        """
        "A `representative_id` in the path or body resolves to an existing representative, else `ERR_REPRESENTATIVE_NOT_FOUND` (404), on `GET /cvso/representatives/{id}`, `PATCH /cvso/representatives/{id}`, `POST /cvso/representatives/{id}/accreditation`, `GET /cvso/representatives/{id}/outreach-events`, `GET /cvso/representatives/{id}/caseload`, `POST /cvso/powers-of-attorney`, `POST /cvso/veterans/{id}/assign-representative` and `POST /cvso/outreach-events`."

        Design: Corner/endpoints/corner_designation_link_requires_both_endpoints_of_the_reference
        """
        veteran = create_veteran(api)
        validate_error(
            api.create_power_of_attorney(
                poa_payload(veteran["id"], NON_EXISTENT_UUID, executed_on="2026-08-01"),
                INTAKE_CLERK_HEADERS,
            ),
            "ERR_REPRESENTATIVE_NOT_FOUND",
            404,
        )
        _rows, meta = validate_paginated(
            api.list_powers_of_attorney(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_two_resolvable_ends_create_one_offered_instrument(self, api):
        """
        "The row starts in `status` `OFFERED` with `accepted_at` and `revoked_reason` unset."

        Design: Corner/endpoints/corner_designation_link_requires_both_endpoints_of_the_reference
        """
        veteran = create_veteran(api)
        representative = create_active_representative(api)
        api.create_power_of_attorney(
            poa_payload(veteran["id"], NON_EXISTENT_UUID, executed_on="2026-08-01"),
            INTAKE_CLERK_HEADERS,
        )
        created = validate_success(
            api.create_power_of_attorney(
                poa_payload(veteran["id"], representative["id"], executed_on="2026-08-01"),
                INTAKE_CLERK_HEADERS,
            ),
            201,
        )
        assert created["status"] == "OFFERED"
        assert created["veteran_id"] == veteran["id"]
        assert created["representative_id"] == representative["id"]
        assert created["accepted_at"] is None
        assert created["revoked_reason"] is None
        _rows, meta = validate_paginated(
            api.list_powers_of_attorney(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 1, "total_count")


class TestCaseloadReadDecomposesTheOutreachTerms:
    """A calendar with two planned events and nothing else weighs four points."""

    @pytest.fixture
    def travelling_representative(self, api):
        """An officer holding no designations and two PLANNED events on separate days."""
        representative = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        first = plan_outreach_event(
            api,
            representative["id"],
            "2026-08-05T09:00:00.000Z",
            "2026-08-05T11:00:00.000Z",
            event_type="RURAL_CLINIC",
            location_name="Grange Hall",
            underserved_flag=True,
        )
        second = plan_outreach_event(
            api,
            representative["id"],
            "2026-08-06T09:00:00.000Z",
            "2026-08-06T10:00:00.000Z",
            event_type="TRIBAL_OUTREACH",
            location_name="Tribal Center",
            underserved_flag=True,
        )
        return {
            "representative_id": representative["id"],
            "events": [first, second],
        }

    def test_the_read_exposes_every_term_of_the_sum(self, api, travelling_representative):
        """
        "A computed workload decomposition exposes exactly the terms the sum is built from: `representative_id`, `active_poa_count`, `open_claim_count` (how many claims under the representative's active designations sit in one of the four open stages), `planned_outreach_count` (how many of their outreach events are still `PLANNED`), the resulting `caseload_weight`, and `assignment_eligible` — a boolean stating whether this representative currently satisfies every filter the automatic assignment selector applies."

        Design: Corner/endpoints/corner_caseload_read_decomposes_the_outreach_terms
        """
        for event in travelling_representative["events"]:
            assert event["status"] == "PLANNED"
        assert_caseload_decomposition(
            read_caseload(api, travelling_representative["representative_id"]),
            travelling_representative["representative_id"],
            active_poa_count=0,
            open_claim_count=0,
            planned_outreach_count=2,
            caseload_weight=4,
            assignment_eligible=True,
        )

    def test_the_auditor_reads_the_same_two_events_at_two_points_each(
        self, api, travelling_representative
    ):
        """
        "Each outreach event assigned to the representative that is still in `PLANNED` contributes 2 points."

        Design: Corner/endpoints/corner_caseload_read_decomposes_the_outreach_terms
        """
        decomposition = validate_success(
            api.get_representative_caseload(
                travelling_representative["representative_id"], STATE_AUDITOR_HEADERS
            ),
            200,
        )
        assert_caseload_decomposition(
            decomposition,
            travelling_representative["representative_id"],
            active_poa_count=0,
            open_claim_count=0,
            planned_outreach_count=2,
            caseload_weight=4,
        )


class TestComputeIsGatedOnTheQuarterBeingClosed:
    """The identical request is refused in August and accepted in October."""

    @pytest.fixture
    def third_quarter_report(self, api):
        """A report labelled 2026Q3, opened while that quarter is still running."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        report = open_outcome_report(api, officer_headers, "2026Q3")
        return {"officer_headers": officer_headers, "report_id": report["id"]}

    def test_an_open_quarter_refuses_the_computation(self, api, third_quarter_report):
        """
        "Computing the quarter is a `CountyOfficer` action carrying `weighting_basis`, and it may only run once the quarter has closed: the logical-clock date must be strictly later than the last calendar day of the labelled quarter, else `ERR_QUARTER_NOT_CLOSED` at HTTP 409."

        Design: Corner/endpoints/corner_compute_is_gated_on_the_quarter_being_closed
        """
        validate_error(
            api.compute_outcome_report(
                third_quarter_report["report_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                third_quarter_report["officer_headers"],
            ),
            "ERR_QUARTER_NOT_CLOSED",
            409,
        )
        stored = read_outcome_report(api, third_quarter_report["report_id"])
        assert stored["weighting_basis"] is None
        assert_versioned_shape(stored, expected_version=1)

    def test_the_same_request_scores_the_quarter_once_it_has_closed(
        self, api, third_quarter_report
    ):
        """
        "The row starts in `status` `OPEN` with `weighting_basis` unset and `filed_claim_count`, `favorable_claim_count`, `performance_score`, `retro_dollars_cents` and `veterans_contacted_total` all at their empty values."
        "When `filed_claim_count` is 0 the score is 0.0: an empty reporting window is a scored outcome, not an error."

        Design: Corner/endpoints/corner_compute_is_gated_on_the_quarter_being_closed
        """
        api.compute_outcome_report(
            third_quarter_report["report_id"],
            compute_report_payload("CLAIM_WEIGHTED"),
            third_quarter_report["officer_headers"],
        )
        set_clock_date(api, "2026-10-01")
        scored = validate_success(
            api.compute_outcome_report(
                third_quarter_report["report_id"],
                compute_report_payload("CLAIM_WEIGHTED"),
                third_quarter_report["officer_headers"],
            ),
            200,
        )
        assert scored["weighting_basis"] == "CLAIM_WEIGHTED"
        assert scored["status"] == "OPEN"
        assert_exact_whole(scored["filed_claim_count"], 0, "filed_claim_count")
        assert_pct_1dp(scored["performance_score"], 0.0)
        assert_versioned_shape(scored, expected_version=2)


class TestExpirationSweepIsIdempotent:
    """The office-wide sweep expires a row once and then finds nothing."""

    @pytest.fixture
    def lapsed_review(self, api):
        """One COUNSELED review whose 365-day window closed yesterday."""
        ctx = create_counseled_review(api)
        review = read_decision_review(api, ctx["review"]["id"])
        assert review["deadline_on"] == "2027-08-01"
        assert_versioned_shape(review, expected_version=1)
        set_clock_date(api, "2027-08-02")
        return {"review_id": review["id"]}

    def test_the_first_sweep_expires_the_row_it_found(self, api, lapsed_review):
        """
        "A `SystemAdmin` runs an expiry sweep across the whole office; every review whose `status` is `COUNSELED` or `ELECTED` and whose `days_remaining` is strictly less than 0 at the current logical-clock position moves to `EXPIRED` with `closure_reason` set to the literal string `DEADLINE_SWEEP`, and each swept row's `version` is incremented by 1."
        "The sweep reports how many rows it expired as `expired_count` and lists their identifiers as `expired_review_ids`."

        Design: Corner/endpoints/corner_expiration_sweep_is_idempotent_across_repeated_calls
        """
        swept = validate_success(
            api.sweep_decision_review_expirations(SYSTEM_ADMIN_HEADERS), 200
        )
        assert_exact_whole(swept["expired_count"], 1, "expired_count")
        assert swept["expired_review_ids"] == [lapsed_review["review_id"]]
        stored = read_decision_review(api, lapsed_review["review_id"])
        assert stored["status"] == "EXPIRED"
        assert stored["closure_reason"] == "DEADLINE_SWEEP"
        assert_versioned_shape(stored, expected_version=2)

    def test_a_repeated_sweep_at_the_same_clock_position_expires_nothing(
        self, api, lapsed_review
    ):
        """
        "It is idempotent: `EXPIRED` rows are no longer in the candidate set, so a second call at an unchanged clock position expires nothing and reports zero."

        Design: Corner/endpoints/corner_expiration_sweep_is_idempotent_across_repeated_calls
        """
        api.sweep_decision_review_expirations(SYSTEM_ADMIN_HEADERS)
        again = validate_success(
            api.sweep_decision_review_expirations(SYSTEM_ADMIN_HEADERS), 200
        )
        assert_exact_whole(again["expired_count"], 0, "expired_count")
        assert again["expired_review_ids"] == []
        assert_versioned_shape(
            read_decision_review(api, lapsed_review["review_id"]), expected_version=2
        )


class TestPatchEndpointsTouchOnlyTheSuppliedFields:
    """A claim amendment and a site retune each move only their own keys."""

    def test_the_claim_amendment_rewrites_the_conditions_and_the_anchor_only(self, api):
        """
        "A claim may be amended while it is still in `DRAFT` or `EVIDENCE_DEVELOPMENT`, supplying `claimed_conditions` or `intent_to_file_date`; amending the condition list changes the required-points denominator and therefore immediately re-scores `evidence_completeness_pct`."

        Design: Corner/endpoints/corner_patch_endpoints_touch_only_the_supplied_fields_on_claims_and_sites
        """
        base = create_represented_veteran(api)
        claim = create_draft_claim(
            api,
            base["veteran"]["id"],
            base["poa"]["id"],
            base["officer_headers"],
            claimed_conditions=conditions("tinnitus"),
        )
        assert claim["intent_to_file_date"] is None
        patched = validate_success(
            api.update_claim(
                claim["id"],
                {
                    "claimed_conditions": conditions("tinnitus", "lumbar_strain"),
                    "intent_to_file_date": "2026-07-15",
                },
                base["officer_headers"],
            ),
            200,
        )
        assert patched["intent_to_file_date"] == "2026-07-15"
        assert patched["status"] == "DRAFT"
        assert patched["claim_type"] == "DISABILITY_COMPENSATION"
        assert_pct_2dp(patched["evidence_completeness_pct"], 0.00)
        assert_versioned_shape(patched, expected_version=2)
        stored = read_claim(api, claim["id"])
        stored_conditions = stored["claimed_conditions"]
        codes = [row["condition_code"] for row in stored_conditions]
        assert codes == ["tinnitus", "lumbar_strain"]
        _items, meta = validate_paginated(
            api.list_claim_evidence_items(claim["id"], base["officer_headers"])
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_the_site_retune_raises_the_capacity_and_leaves_the_buffer(self, api):
        """
        "A site's `name`, `county_code`, `concurrent_capacity` and `buffer_minutes` can all be retuned later; existing appointments are left exactly where they are, and the new values apply only to subsequent overlap evaluations."
        "Where the office does not state them, a site is understood to run a 15-minute turnaround buffer and a concurrent capacity of 2."

        Design: Corner/endpoints/corner_patch_endpoints_touch_only_the_supplied_fields_on_claims_and_sites
        """
        site = create_exam_site(api, name="County Contract Clinic", county_code="CV")
        patched = validate_success(
            api.update_exam_site(
                site["id"], {"concurrent_capacity": 3}, SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        assert_exact_whole(patched["concurrent_capacity"], 3, "concurrent_capacity")
        assert_exact_whole(patched["buffer_minutes"], 15, "buffer_minutes")
        assert_exact_whole(patched["booked_slot_count"], 0, "booked_slot_count")
        assert patched["name"] == "County Contract Clinic"
        assert_versioned_shape(patched, expected_version=2)
        assert read_exam_site(api, site["id"])["county_code"] == "CV"

    def test_a_representatives_travel_calendar_is_empty_until_an_event_is_planned(
        self, api
    ):
        """
        "A `representative_id` in the path or body resolves to an existing representative, else `ERR_REPRESENTATIVE_NOT_FOUND` (404), on `GET /cvso/representatives/{id}`, `PATCH /cvso/representatives/{id}`, `POST /cvso/representatives/{id}/accreditation`, `GET /cvso/representatives/{id}/outreach-events`, `GET /cvso/representatives/{id}/caseload`, `POST /cvso/powers-of-attorney`, `POST /cvso/veterans/{id}/assign-representative` and `POST /cvso/outreach-events`."

        Design: Corner/endpoints/corner_patch_endpoints_touch_only_the_supplied_fields_on_claims_and_sites
        """
        representative = create_active_representative(api)
        _events, meta = validate_paginated(
            api.list_representative_outreach_events(
                representative["id"], SYSTEM_ADMIN_HEADERS
            )
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")


RETURN_REASON = "Recompute the outreach totals"


class TestReturnedReportIsReopenedAndRecomputed:
    """The review cycle runs OPEN, SUBMITTED, RETURNED, OPEN and then ends."""

    @pytest.fixture
    def submitted_report(self, api):
        """A 2026Q2 report scored under claim weighting and certified once."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        report = create_submitted_report(api, officer_headers, "2026Q2", "CLAIM_WEIGHTED")
        return {
            "officer_headers": officer_headers,
            "officer_id": officer["id"],
            "report": report,
        }

    def test_the_auditor_returns_the_certified_report_with_a_reason(
        self, api, submitted_report
    ):
        """
        "Submission recomputes the quarter's numbers under the stored `weighting_basis`, sets `status` to `SUBMITTED`, stamps `submitted_at` with the logical-clock instant and `certified_by_representative_id` with the acting officer's `X-User-ID`, and increments `version` by 1."
        "**Returning** (`RETURN`) is also `StateAuditor` work from `SUBMITTED`, requires a `reason` stored as `return_reason`, and sets `status` to `RETURNED`."

        Design: Corner/endpoints/corner_returned_report_is_reopened_and_recomputed
        """
        report = submitted_report["report"]
        assert report["status"] == "SUBMITTED"
        assert report["certified_by_representative_id"] == submitted_report["officer_id"]
        assert_instant_equals(report["submitted_at"], CLOCK_START_INSTANT)
        assert_exact_whole(report["filed_claim_count"], 0, "filed_claim_count")
        assert_pct_1dp(report["performance_score"], 0.0)
        returned = validate_success(
            api.review_outcome_report(
                report["id"], return_report_action(RETURN_REASON), STATE_AUDITOR_HEADERS
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_reason"] == RETURN_REASON

    def test_reopening_clears_the_certification_and_keeps_the_figures(
        self, api, submitted_report
    ):
        """
        "**Reopening** is `SystemAdmin` work available only from `RETURNED`; it sets `status` back to `OPEN`, clears `certified_by_representative_id` and `submitted_at`, retains `return_reason` as the audit trail, and leaves the previously computed figures in place until the next computation overwrites them."

        Design: Corner/endpoints/corner_returned_report_is_reopened_and_recomputed
        """
        report_id = submitted_report["report"]["id"]
        api.review_outcome_report(
            report_id, return_report_action(RETURN_REASON), STATE_AUDITOR_HEADERS
        )
        reopened = validate_success(
            api.reopen_outcome_report(report_id, SYSTEM_ADMIN_HEADERS), 200
        )
        assert reopened["status"] == "OPEN"
        assert reopened["certified_by_representative_id"] is None
        assert reopened["submitted_at"] is None
        assert reopened["weighting_basis"] == "CLAIM_WEIGHTED"
        assert reopened["return_reason"] == RETURN_REASON
        assert_pct_1dp(reopened["performance_score"], 0.0)

    def test_the_second_pass_through_the_cycle_ends_in_the_terminal_state(
        self, api, submitted_report
    ):
        """
        "**Accepting** (`ACCEPT`) is `StateAuditor` work available only from `SUBMITTED` and sets `status` to the terminal `ACCEPTED`."
        "That closes the `OPEN → SUBMITTED → RETURNED → OPEN` cycle, which may run any number of times, while `ACCEPTED` ends it for good."

        Design: Corner/endpoints/corner_returned_report_is_reopened_and_recomputed
        """
        report_id = submitted_report["report"]["id"]
        assert_versioned_shape(submitted_report["report"], expected_version=3)
        api.review_outcome_report(
            report_id, return_report_action(RETURN_REASON), STATE_AUDITOR_HEADERS
        )
        api.reopen_outcome_report(report_id, SYSTEM_ADMIN_HEADERS)
        resubmitted = validate_success(
            api.submit_outcome_report(report_id, submitted_report["officer_headers"]), 200
        )
        assert resubmitted["status"] == "SUBMITTED"
        accepted = validate_success(
            api.review_outcome_report(
                report_id, accept_report_action(), STATE_AUDITOR_HEADERS
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert_versioned_shape(accepted, expected_version=7)


class TestDesignationRevocationReleasesTheRepresentativeSlot:
    """Revoking gives the point back; a second revoke has nothing to give."""

    @pytest.fixture
    def represented(self, api):
        """One ACTIVE designation held by an officer carrying nothing else."""
        representative = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        base = create_represented_veteran(api, designee=representative)
        base["representative_id"] = representative["id"]
        return base

    def test_the_revocation_returns_the_ledger_and_the_weight_to_zero(
        self, api, represented
    ):
        """
        "A `VeteranClient` revoking their own `ACTIVE` designation triggers the full representation cascade: `status` becomes `REVOKED` with the supplied `reason` stored as `revoked_reason`, the representative's `active_poa_count` is decremented by 1, every claim citing this designation whose `status` is `EVIDENCE_DEVELOPMENT`, `PEER_REVIEW` or `READY_TO_FILE` reverts to `DRAFT` with `poa_id` and `peer_reviewed_by_representative_id` both nulled, every `SCHEDULED` examination appointment of those claims moves to `CANCELLED` with `cancellation_reason` set to `REPRESENTATION_CASCADE`, each affected site's `booked_slot_count` is decremented by 1 per cancelled appointment, `caseload_weight` is recomputed, and `version` is incremented by 1 on the designation and on every representative, claim, appointment and site the cascade touched."

        Design: Corner/endpoints/corner_designation_revocation_releases_the_representative_slot
        """
        assert_caseload_decomposition(
            read_caseload(api, represented["representative_id"]),
            represented["representative_id"],
            active_poa_count=1,
            open_claim_count=0,
            planned_outreach_count=0,
            caseload_weight=1,
        )
        revoked = validate_success(
            api.revoke_power_of_attorney(
                represented["poa"]["id"],
                revoke_poa_payload("veteran changed representative"),
                represented["veteran_headers"],
            ),
            200,
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_reason"] == "veteran changed representative"
        assert_caseload_decomposition(
            read_caseload(api, represented["representative_id"]),
            represented["representative_id"],
            active_poa_count=0,
            open_claim_count=0,
            planned_outreach_count=0,
            caseload_weight=0,
        )

    def test_a_second_revoke_is_refused_and_a_fresh_designation_refills_the_slot(
        self, api, represented
    ):
        """
        "Both paths end in `REVOKED`, which is terminal."
        "Acceptance then sets `status` to `ACTIVE`, stamps `accepted_at` with the logical-clock instant, increments the designated representative's `active_poa_count` by 1, and increments the veteran's `version` by 1 — which is exactly why a client holding a stale version number loses the race."

        Design: Corner/endpoints/corner_designation_revocation_releases_the_representative_slot
        """
        api.revoke_power_of_attorney(
            represented["poa"]["id"],
            revoke_poa_payload("veteran changed representative"),
            represented["veteran_headers"],
        )
        validate_error(
            api.revoke_power_of_attorney(
                represented["poa"]["id"],
                revoke_poa_payload("duplicate request"),
                represented["veteran_headers"],
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        replacement = offer_designation(
            api,
            represented["veteran"]["id"],
            represented["representative_id"],
            scope="SPECIFIC_CLAIM",
            executed_on="2026-08-01",
        )
        accepted = accept_designation(
            api, replacement["id"], represented["veteran"]["id"]
        )
        assert accepted["status"] == "ACTIVE"
        assert_caseload_decomposition(
            read_caseload(api, represented["representative_id"]),
            represented["representative_id"],
            active_poa_count=1,
            open_claim_count=0,
            planned_outreach_count=0,
            caseload_weight=1,
        )
