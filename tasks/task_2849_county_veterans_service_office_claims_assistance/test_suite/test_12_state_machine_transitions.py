"""
Lifecycle transitions: entry states, cycles, terminal states and side effects.

The accreditation machine is the one lifecycle in the system that both cycles
and terminates, so most of these tests drive it directly and then read the row
back to see what the transition actually stored.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    SYSTEM_ADMIN_HEADERS,
    activate_action,
    assert_caseload_decomposition,
    assert_caseload_weight,
    assert_exact_whole,
    assert_fresh_row,
    assert_instant_equals,
    assert_versioned_shape,
    create_active_representative,
    create_veteran,
    hold_outreach_action,
    instant,
    lapse_action,
    make_county_officer_headers,
    open_outcome_report,
    plan_outreach_event,
    read_caseload,
    read_outcome_report,
    read_representative,
    read_veteran,
    register_representative,
    renew_action,
    revoke_accreditation_action,
    set_clock,
    set_clock_date,
    submit_discharge_document,
    validate_error,
    validate_success,
)


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


class TestAccreditationEntryTransition:
    """The one way into ACTIVE, and the fact that it does not run twice."""

    def test_activation_moves_the_pending_row_to_active(self, api):
        """
        "Activation, named by the `action` value `ACTIVATE`, is available only from `PENDING`; it sets `accreditation_status` to `ACTIVE` and recomputes `caseload_weight`, which on a freshly activated row is 0 because the representative holds nothing yet."

        Design: Corner/state_machines/corner_representative_activation_moves_pending_to_active
        """
        registered = register_representative(
            api, accreditation_expires_on="2029-12-31"
        )
        assert registered["accreditation_status"] == "PENDING"
        assert_fresh_row(registered)
        activated = validate_success(
            api.representative_accreditation(
                registered["id"], activate_action(), SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        assert activated["accreditation_status"] == "ACTIVE"
        assert_versioned_shape(activated, expected_version=2)
        assert_caseload_weight(
            read_representative(api, registered["id"])["caseload_weight"], 0
        )

    def test_a_second_activation_is_refused_and_the_version_stands_still(self, api):
        """
        "The addressed row is in a state from which the requested action is declared; any other from-state, and any action applied to a terminal state, is refused with `ERR_INVALID_STATE_TRANSITION` (409), on every action endpoint that drives a lifecycle."

        Design: Corner/state_machines/corner_second_activate_on_the_same_representative_is_refused
        """
        registered = register_representative(
            api, accreditation_expires_on="2029-12-31"
        )
        first = validate_success(
            api.representative_accreditation(
                registered["id"], activate_action(), SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        assert first["accreditation_status"] == "ACTIVE"
        assert_exact_whole(first["version"], 2, "version")
        validate_error(
            api.representative_accreditation(
                registered["id"], activate_action(), SYSTEM_ADMIN_HEADERS
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        stored = read_representative(api, registered["id"])
        assert stored["accreditation_status"] == "ACTIVE"
        assert_exact_whole(stored["version"], 2, "version")


class TestLapseAndRenewCycle:
    """Two full passes around the only cycle the roster machine offers."""

    @pytest.fixture
    def twice_renewed(self, api):
        """One representative taken around the lapse-and-renew loop twice."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        first_lapse = validate_success(
            api.representative_accreditation(
                rep["id"], lapse_action(), SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        first_renewal = validate_success(
            api.representative_accreditation(
                rep["id"],
                renew_action(ce_credits=12, accreditation_expires_on="2030-06-30"),
                SYSTEM_ADMIN_HEADERS,
            ),
            200,
        )
        second_lapse = validate_success(
            api.representative_accreditation(
                rep["id"], lapse_action(), SYSTEM_ADMIN_HEADERS
            ),
            200,
        )
        second_renewal = validate_success(
            api.representative_accreditation(
                rep["id"],
                renew_action(ce_credits=18, accreditation_expires_on="2033-06-30"),
                SYSTEM_ADMIN_HEADERS,
            ),
            200,
        )
        return {
            "rep_id": rep["id"],
            "first_lapse": first_lapse,
            "first_renewal": first_renewal,
            "second_lapse": second_lapse,
            "second_renewal": second_renewal,
        }

    def test_each_pass_returns_the_row_to_active(self, api, twice_renewed):
        """
        "Lapsing, named `LAPSE`, is available only from `ACTIVE` and is deliberately cascade-free — it touches no designation and no claim, so the *only* observable effect is that every subsequent write attempt by that representative is refused, which is precisely how the accreditation gate in §2.6 can be observed in isolation."
        "A representative may traverse the lapse-and-renew cycle any number of times."

        Design: Corner/state_machines/corner_accreditation_cycles_from_lapsed_back_to_active_twice
        """
        assert twice_renewed["first_lapse"]["accreditation_status"] == "LAPSED"
        assert twice_renewed["first_renewal"]["accreditation_status"] == "ACTIVE"
        assert twice_renewed["second_lapse"]["accreditation_status"] == "LAPSED"
        assert twice_renewed["second_renewal"]["accreditation_status"] == "ACTIVE"

    def test_the_second_renewal_overwrites_rather_than_accumulates(
        self, api, twice_renewed
    ):
        """
        "Renewal overwrites the stored `accreditation_expires_on` and copies the supplied credit count into `ce_credits_earned`."

        Design: Corner/state_machines/corner_accreditation_cycles_from_lapsed_back_to_active_twice
        """
        assert_exact_whole(
            twice_renewed["first_renewal"]["ce_credits_earned"], 12, "ce_credits_earned"
        )
        assert_exact_whole(
            twice_renewed["second_renewal"]["ce_credits_earned"], 18, "ce_credits_earned"
        )
        stored = read_representative(api, twice_renewed["rep_id"])
        assert stored["accreditation_expires_on"] == "2033-06-30"
        assert_exact_whole(stored["version"], 6, "version")


class TestRenewIsDeclaredOnlyFromLapsed:
    """A perfectly formed renewal body cannot rescue a wrong from-state."""

    def test_renew_on_an_active_row_is_an_invalid_transition(self, api):
        """
        "Renewal, named `RENEW`, returns a representative from `LAPSED` to `ACTIVE`, and it is the one accreditation action with substantive inputs of its own: the caller supplies `ce_credits`, which must be at least 12 to satisfy the biennial continuing-education requirement, and a fresh `accreditation_expires_on`, which must fall strictly after the logical-clock date."

        Design: Corner/state_machines/corner_renew_on_an_active_accreditation_is_an_invalid_transition
        """
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        validate_error(
            api.representative_accreditation(
                rep["id"],
                renew_action(ce_credits=12, accreditation_expires_on="2031-12-31"),
                SYSTEM_ADMIN_HEADERS,
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        stored = read_representative(api, rep["id"])
        assert stored["accreditation_status"] == "ACTIVE"
        assert_exact_whole(stored["ce_credits_earned"], 0, "ce_credits_earned")
        assert stored["accreditation_expires_on"] == "2029-12-31"
        assert_exact_whole(stored["version"], 2, "version")


class TestRevokedIsTerminal:
    """Nothing the roster machine offers survives a revocation."""

    @pytest.fixture
    def revoked_representative(self, api):
        """An activated row revoked for a recorded reason."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        revoked = validate_success(
            api.representative_accreditation(
                rep["id"],
                revoke_accreditation_action("FRAUD_FINDING"),
                SYSTEM_ADMIN_HEADERS,
            ),
            200,
        )
        return {"rep_id": rep["id"], "revoked": revoked}

    def test_no_later_action_is_accepted_on_a_revoked_row(
        self, api, revoked_representative
    ):
        """
        "The accreditation lifecycle runs `PENDING → ACTIVE`, cycles `ACTIVE → LAPSED → ACTIVE` as often as renewals occur, and terminates at `REVOKED`, which is a terminal state from which nothing further is possible."

        Design: Corner/state_machines/corner_revoked_accreditation_accepts_no_further_transitions
        """
        rep_id = revoked_representative["rep_id"]
        for body in (
            activate_action(),
            lapse_action(),
            revoke_accreditation_action("SECOND_ATTEMPT"),
        ):
            validate_error(
                api.representative_accreditation(rep_id, body, SYSTEM_ADMIN_HEADERS),
                "ERR_INVALID_STATE_TRANSITION",
                409,
            )

    def test_the_recorded_reason_and_version_survive_the_refusals(
        self, api, revoked_representative
    ):
        """
        "It is available from either `ACTIVE` or `LAPSED`, it requires a `reason` which is stored as `revocation_reason`, and it propagates through five hops in a single synchronous request."

        Design: Corner/state_machines/corner_revoked_accreditation_accepts_no_further_transitions
        """
        rep_id = revoked_representative["rep_id"]
        assert revoked_representative["revoked"]["accreditation_status"] == "REVOKED"
        api.representative_accreditation(rep_id, activate_action(), SYSTEM_ADMIN_HEADERS)
        api.representative_accreditation(rep_id, lapse_action(), SYSTEM_ADMIN_HEADERS)
        stored = read_representative(api, rep_id)
        assert stored["accreditation_status"] == "REVOKED"
        assert stored["revocation_reason"] == "FRAUD_FINDING"
        assert_exact_whole(stored["version"], 3, "version")


class TestDischargeDocumentInitialState:
    """Separation paperwork enters the queue and nothing else happens yet."""

    def test_a_fresh_document_waits_in_pending_verification(self, api):
        """
        "The row lands in `verification_status` `PENDING_VERIFICATION` with `resubmission_count` at 0 and `discrepancy_reason` unset, and submitting it also pushes the veteran's `discharge_doc_status` to `PENDING_VERIFICATION` and increments the veteran's `version`."

        Design: Corner/state_machines/corner_discharge_document_starts_in_pending_verification
        """
        veteran = create_veteran(api)
        document = submit_discharge_document(api, veteran["id"])
        assert document["verification_status"] == "PENDING_VERIFICATION"
        assert_exact_whole(document["resubmission_count"], 0, "resubmission_count")
        assert document["verified_at"] is None
        assert document.get("discrepancy_reason") is None
        assert_fresh_row(document)

    def test_the_veteran_mirror_moves_off_not_submitted(self, api):
        """
        "That mirror field always reflects the `verification_status` of the veteran's document with the greatest `created_at`, and reads `NOT_SUBMITTED` while the veteran has no document at all."
        "A brand-new intake record starts with `intake_status` at `INTAKE_STARTED`, `discharge_doc_status` at `NOT_SUBMITTED`, `character_of_service` at the placeholder `UNCHARACTERIZED` (meaning no verified document has yet established it), `wartime_service_days` at 0, `combined_rating_pct` at 0, `priority_group` at `P4`, `assigned_representative_id` unset and `date_of_death` unset."

        Design: Corner/state_machines/corner_discharge_document_starts_in_pending_verification
        """
        veteran = create_veteran(api)
        assert veteran["discharge_doc_status"] == "NOT_SUBMITTED"
        submit_discharge_document(api, veteran["id"])
        stored = read_veteran(api, veteran["id"])
        assert stored["discharge_doc_status"] == "PENDING_VERIFICATION"
        assert stored["character_of_service"] == "UNCHARACTERIZED"
        assert_exact_whole(stored["wartime_service_days"], 0, "wartime_service_days")
        assert_exact_whole(stored["version"], 2, "version")


class TestDischargeVerificationSideEffects:
    """One VERIFY call writes to the document and to the veteran at once."""

    @pytest.fixture
    def verified_paperwork(self, api):
        """A DD214 covering one full post-2001 enlistment, verified by an officer."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        veteran = create_veteran(api)
        document = submit_discharge_document(
            api,
            veteran["id"],
            claimed_service_start="2001-09-11",
            claimed_service_end="2005-09-10",
            claimed_character_of_service="HONORABLE",
        )
        reviewed = validate_success(
            api.review_discharge_document(
                document["id"], {"action": "VERIFY"}, officer_headers
            ),
            200,
        )
        return {
            "officer_id": officer["id"],
            "veteran_id": veteran["id"],
            "document_id": document["id"],
            "reviewed": reviewed,
        }

    def test_the_document_records_who_verified_it_and_when(self, api, verified_paperwork):
        """
        "It sets `verification_status` to `VERIFIED`, stamps `verified_at` with the logical-clock instant and `verified_by_representative_id` with the acting officer's `X-User-ID`, copies `claimed_character_of_service` onto the veteran's `character_of_service`, sets the veteran's `discharge_doc_status` to `VERIFIED`, recomputes the veteran's `wartime_service_days` from the document's claimed service interval, and increments both the document's and the veteran's `version`."

        Design: Corner/state_machines/corner_discharge_verification_applies_every_declared_side_effect
        """
        reviewed = verified_paperwork["reviewed"]
        assert reviewed["verification_status"] == "VERIFIED"
        assert reviewed["verified_by_representative_id"] == (
            verified_paperwork["officer_id"]
        )
        assert_instant_equals(reviewed["verified_at"], CLOCK_START_INSTANT)
        assert_versioned_shape(reviewed, expected_version=2)

    def test_the_veteran_gains_a_character_of_service_and_a_wartime_count(
        self, api, verified_paperwork
    ):
        """
        "The count is taken against three fixed statutory wartime windows, evaluated in this order: 28 February 1961 through 7 May 1975, 2 August 1990 through 11 April 1991, and 11 September 2001 through 30 August 2021."
        "If that later start is not after that earlier end, the overlap contributes the number of days from the start to the end plus one — the plus one making both ends inclusive — and otherwise contributes nothing."

        Design: Corner/state_machines/corner_discharge_verification_applies_every_declared_side_effect
        """
        stored = read_veteran(api, verified_paperwork["veteran_id"])
        assert stored["character_of_service"] == "HONORABLE"
        assert stored["discharge_doc_status"] == "VERIFIED"
        assert_exact_whole(stored["wartime_service_days"], 1461, "wartime_service_days")
        assert_exact_whole(stored["version"], 3, "version")


class TestOutcomeReportSubmitBeforeCompute:
    """The submission precondition is about the figures, not the from-state."""

    @pytest.fixture
    def uncomputed_report(self, api):
        """A report opened for a closed quarter and never scored."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        report = open_outcome_report(api, officer_headers, "2026Q2")
        return {"officer_headers": officer_headers, "report": report}

    def test_submitting_an_uncomputed_report_is_refused(self, api, uncomputed_report):
        """
        "The outcome report has been computed at least once, meaning its `weighting_basis` is not null, else `ERR_REPORT_NOT_COMPUTED` (409), on `POST /cvso/outcome-reports/{id}/submit`."

        Design: Corner/state_machines/corner_outcome_report_submit_before_compute_returns_report_not_computed
        """
        assert uncomputed_report["report"]["status"] == "OPEN"
        assert uncomputed_report["report"]["weighting_basis"] is None
        validate_error(
            api.submit_outcome_report(
                uncomputed_report["report"]["id"], uncomputed_report["officer_headers"]
            ),
            "ERR_REPORT_NOT_COMPUTED",
            409,
        )

    def test_the_refused_submission_certifies_nothing(self, api, uncomputed_report):
        """
        "Submission recomputes the quarter's numbers under the stored `weighting_basis`, sets `status` to `SUBMITTED`, stamps `submitted_at` with the logical-clock instant and `certified_by_representative_id` with the acting officer's `X-User-ID`, and increments `version` by 1."

        Design: Corner/state_machines/corner_outcome_report_submit_before_compute_returns_report_not_computed
        """
        api.submit_outcome_report(
            uncomputed_report["report"]["id"], uncomputed_report["officer_headers"]
        )
        stored = read_outcome_report(api, uncomputed_report["report"]["id"])
        assert stored["status"] == "OPEN"
        assert stored["weighting_basis"] is None
        assert stored["certified_by_representative_id"] is None
        assert_exact_whole(stored["version"], 1, "version")


class TestHoldingAnOutreachEventFreesTheCaseload:
    """A planned event is workload; a held one is history."""

    @pytest.fixture
    def held_event(self, api):
        """One planned clinic, held once the clock reaches the start instant."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(rep["id"])
        event = plan_outreach_event(
            api,
            rep["id"],
            instant("2026-09-10", "09:00:00"),
            instant("2026-09-10", "11:00:00"),
            event_type="RURAL_CLINIC",
        )
        before = read_caseload(api, rep["id"])
        set_clock_date(api, "2026-09-10", "10:00:00")
        held = validate_success(
            api.outreach_event_status(
                event["id"],
                hold_outreach_action(veterans_contacted=40, veterans_enrolled=9),
                officer_headers,
            ),
            200,
        )
        return {"rep_id": rep["id"], "before": before, "held": held}

    def test_the_planned_event_carried_two_points_of_workload(self, api, held_event):
        """
        "Each outreach event assigned to the representative that is still in `PLANNED` contributes 2 points."
        "A computed workload decomposition exposes exactly the terms the sum is built from: `representative_id`, `active_poa_count`, `open_claim_count` (how many claims under the representative's active designations sit in one of the four open stages), `planned_outreach_count` (how many of their outreach events are still `PLANNED`), the resulting `caseload_weight`, and `assignment_eligible` — a boolean stating whether this representative currently satisfies every filter the automatic assignment selector applies."

        Design: Corner/state_machines/corner_holding_an_outreach_event_adjusts_the_representative_caseload
        """
        assert_caseload_decomposition(
            held_event["before"],
            representative_id=held_event["rep_id"],
            active_poa_count=0,
            open_claim_count=0,
            planned_outreach_count=1,
            caseload_weight=2,
        )

    def test_the_hold_records_the_headcount_and_drops_the_planned_term(
        self, api, held_event
    ):
        """
        "Holding sets `status` to `HELD` and records both counts, which then feed the quarterly report's contact total, recomputes the assigned representative's `caseload_weight` because a held event leaves the planned-outreach set, and increments both the event's and the representative's `version` by 1."
        "Nothing else counts: a claim in `DRAFT`, `DECIDED` or `WITHDRAWN` contributes nothing, a claim whose `poa_id` is null contributes nothing even if the representative prepared it, and an outreach event that has been `HELD` or `CANCELLED` contributes nothing."

        Design: Corner/state_machines/corner_holding_an_outreach_event_adjusts_the_representative_caseload
        """
        assert held_event["held"]["status"] == "HELD"
        assert_exact_whole(
            held_event["held"]["veterans_contacted"], 40, "veterans_contacted"
        )
        assert_exact_whole(
            held_event["held"]["veterans_enrolled"], 9, "veterans_enrolled"
        )
        assert_caseload_decomposition(
            read_caseload(api, held_event["rep_id"]),
            representative_id=held_event["rep_id"],
            active_poa_count=0,
            open_claim_count=0,
            planned_outreach_count=0,
            caseload_weight=0,
        )
