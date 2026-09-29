"""Donor enrolment, health-history triage and the two risk scores.

Covers the declared creation defaults of a donor row, the shared base score and
the two figures derived from it — the pessimistic screening score that the
triage bands read and the time-discounted surveillance score that qualification
reads — the SCREENING/INFO_REQUESTED revision loop, the qualification gate
ladder, the terminal permanent deferral, the coupling between deferral_days and
deferral_type, bank-wide code uniqueness, and the monotonic logical clock.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    INTAKE_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_ID,
)

CLOCK = C.CLOCK_INTAKE
CLOCK_DATE = C.CLOCK_INTAKE_DATE


class TestTwoRiskScoresFromOneBase:
    """The screening and surveillance variants deliberately disagree."""

    def test_screening_and_surveillance_scores_diverge_on_identical_stored_data(self):
        """A donor with one expired temporary deferral and no serology on file
        carries a pessimistic 65 and a time-discounted 37 at the same moment: the
        screening variant adds the flat pending-serology penalty and charges the
        deferral at full weight, while the surveillance variant omits the penalty
        and halves the deferral every 180 days.

        PRD: "It never adds the serology penalty at all — serology is a hard precondition at qualification rather than a score term — and it discounts deferral history by age: each of the donor's temporary deferral events whose `status` is `ACTIVE` or `EXPIRED` contributes 15 points multiplied by one half raised to the power of (the whole number of calendar days from that event's `effective_from` to the current clock date, divided by 180)."
        Design: Difficulty/dual_variant_calc/donor_risk_screening_vs_surveillance_divergence
        """
        # The clock is never set, so it holds its startup value.
        donor = fx.enroll_donor(donor_code="DNR-1005", full_name="Eve Nolan", zone_code="Z1")
        fx.submit_questionnaire(donor["id"], **fx.CLEAN_QUESTIONNAIRE)
        fx.record_deferral(
            donor["id"],
            reason_code="ILLNESS",
            deferral_type="TEMPORARY",
            effective_from="2026-02-01",
            deferral_days=30,
            lookback_days=0,
            recall_scope="NONE",
        )
        fx.requalify(donor["id"])

        fx.submit_questionnaire(donor["id"], **fx.CLEAN_QUESTIONNAIRE)
        after = fx.get_donor(donor["id"])

        base = A.expected_base_risk_points(**fx.CLEAN_QUESTIONNAIRE)
        assert base == 30, "two flagged medications (16), three alcohol units (5) and fifteen months postpartum (9)"
        age_in_days = A.days_between("2026-02-01", A.date_part(C.CLOCK_STARTUP_INSTANT))
        assert age_in_days == 181, "2026-02-01 to the startup clock date 2026-08-01 is 181 days"

        assert after["screening_risk_score"] == 65, "base 30 + 20 pending serology + 15 for one deferral"
        assert after["screening_risk_score"] == A.expected_screening_score(base, False, 1)
        assert after["surveillance_risk_score"] == 37, "base 30 + 15 * 0.5 ** (181/180) = 37.47, rounded half up"
        assert after["surveillance_risk_score"] == A.expected_surveillance_score(base, [age_in_days])
        assert after["screening_risk_score"] != after["surveillance_risk_score"], (
            "the same stored data carries two different risk figures at once"
        )
        assert after["temporary_deferral_count"] == 1

    def test_the_pessimistic_screening_score_is_the_figure_the_triage_bands_read(self):
        """The questionnaire whose stored screening score is 65 is triaged
        INFO_REQUESTED and drags the donor into INFO_REQUESTED with it, even
        though the surveillance figure of 37 sits comfortably inside the
        accepting band.

        PRD: "Triage then assigns the questionnaire's own `status` from the pessimistic screening score against two bands."
        Design: Difficulty/dual_variant_calc/donor_risk_screening_vs_surveillance_divergence
        """
        donor = fx.enroll_donor(donor_code="DNR-1005", full_name="Eve Nolan", zone_code="Z1")
        fx.submit_questionnaire(donor["id"], **fx.CLEAN_QUESTIONNAIRE)
        fx.record_deferral(
            donor["id"],
            effective_from="2026-02-01",
            deferral_days=30,
            lookback_days=0,
            recall_scope="NONE",
        )
        fx.requalify(donor["id"])

        newest = fx.submit_questionnaire(donor["id"], **fx.CLEAN_QUESTIONNAIRE)

        assert newest["base_risk_points"] == 30
        assert newest["screening_risk_score"] == 65
        assert newest["status"] == "INFO_REQUESTED", "65 is above 60 and not above 85"
        assert A.expected_triage_status(65) == "INFO_REQUESTED"
        donor_after = fx.get_donor(donor["id"])
        assert donor_after["status"] == "INFO_REQUESTED"
        assert donor_after["surveillance_risk_score"] == 37, (
            "the accepting-band surveillance figure did not decide the triage"
        )


class TestHealthHistoryRevisionLoop:
    """SCREENING and INFO_REQUESTED form a cycle, not a funnel."""

    def test_a_revised_questionnaire_returns_the_donor_from_info_requested_to_screening(self):
        """A first questionnaire disclosing travel scores 61 and parks the donor
        in INFO_REQUESTED; a clean revision scores 0, re-enters SCREENING — a
        state the row had already left — and only that second traversal reaches
        QUALIFIED.

        PRD: "A questionnaire that lands `ACCEPTED` advances the donor to `SCREENING`, whether she was in `APPLICANT`, `SCREENING` or `INFO_REQUESTED` when it was taken; the `INFO_REQUESTED → SCREENING` direction is what makes health-history revision a genuine loop rather than a one-way funnel."
        Design: Difficulty/non_linear_state_machine/donor_info_requested_revision_cycle
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-1007", full_name="Gil Haddad", zone_code="Z1")
        first = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=2,
            travel_risk_flag=True,
            tobacco_use=False,
            alcohol_units_per_week=0,
            months_postpartum=12,
        )
        assert first["base_risk_points"] == 41, "two medications (16) plus disclosed travel (25)"
        assert first["screening_risk_score"] == 61, "41 plus the 20-point pending-serology penalty"
        assert first["status"] == "INFO_REQUESTED"
        assert fx.get_donor(donor["id"])["status"] == "INFO_REQUESTED"

        fx.record_serology(donor["id"], collected_on="2026-07-20")
        fx.record_approval(donor["id"], physician_npi="1234567893", approved_on="2026-07-15")

        second = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=0,
            travel_risk_flag=False,
            tobacco_use=False,
            alcohol_units_per_week=0,
            months_postpartum=12,
        )
        assert second["base_risk_points"] == 0
        assert second["screening_risk_score"] == 0, "an unexpired non-reactive panel removes the penalty"
        assert second["status"] == "ACCEPTED"
        mid = fx.get_donor(donor["id"])
        assert mid["status"] == "SCREENING", "the row re-entered a state it had already left"

        qualified = fx.qualify(donor["id"])
        assert qualified["status"] == "QUALIFIED"
        assert qualified["qualified_by_user_id"] == MEDICAL_DIRECTOR_ID
        A.assert_instant_equals(qualified["qualified_at"], CLOCK, "qualified_at")

    def test_the_superseded_first_questionnaire_keeps_its_own_scores_while_the_donor_qualifies(self):
        """The revision leaves two questionnaires on file: the travel disclosure
        SUPERSEDED at its original base 41 and screening 61, and the clean one
        ACCEPTED at 0, while the donor's own stored scores follow the newest row
        alone.

        PRD: "Whenever a donor submits a questionnaire while she already has one on file, that previous newest questionnaire's `status` becomes `SUPERSEDED` in the same request — a questionnaire is never deleted, and a superseded questionnaire no longer feeds any calculation."
        Design: Difficulty/non_linear_state_machine/donor_info_requested_revision_cycle
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-1007", full_name="Gil Haddad", zone_code="Z1")
        fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=2,
            travel_risk_flag=True,
            months_postpartum=12,
        )
        fx.record_serology(donor["id"], collected_on="2026-07-20")
        fx.record_approval(donor["id"], physician_npi="1234567893", approved_on="2026-07-15")
        fx.submit_questionnaire(donor["id"], medication_flag_count=0, months_postpartum=12)
        fx.qualify(donor["id"])

        rows, meta = validate_paginated(
            api_client.list_health_history(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        )
        assert meta["total_count"] == 2, "a questionnaire is never deleted"
        by_base = {row["base_risk_points"]: row for row in rows}
        assert set(by_base) == {41, 0}
        assert by_base[41]["status"] == "SUPERSEDED"
        assert by_base[41]["screening_risk_score"] == 61, "the superseded row keeps its own figures"
        assert by_base[0]["status"] == "ACCEPTED"
        assert by_base[0]["screening_risk_score"] == 0

        donor_after = fx.get_donor(donor["id"])
        assert donor_after["screening_risk_score"] == 0
        assert donor_after["surveillance_risk_score"] == 0
        assert donor_after["status"] == "QUALIFIED"


class TestDonorRowSurface:
    """Creation defaults, the paginated donor list and single reads."""

    def test_a_newly_enrolled_donor_carries_every_declared_default(self):
        """Enrolment supplies only the four client-writable fields, and the
        server answers with the whole declared opening position: APPLICANT, both
        risk scores at 0, an empty ledger, no lifetime volume, no deferrals, the
        three null qualification and deferral fields, and version 1.

        PRD: "The new donor begins her qualification lifecycle in `APPLICANT` with both risk scores at 0, a `reimbursement_balance_cents` ledger of 0, a `lifetime_accepted_volume_ml` of 0, a `temporary_deferral_count` of 0, a null `qualified_at`, a null `qualified_by_user_id`, a null `active_deferral_until_date` and `version` 1."
        Design: Corner/entities/donor_creation_returns_declared_defaults
        """
        fx.set_clock(CLOCK)
        response = api_client.create_donor(
            f.donor(donor_code="DNR-0001", full_name="Ana Ruiz", email="ana.ruiz@example.org", zone_code="Z2"),
            INTAKE_HEADERS,
        )
        body = response.json()
        assert body["response_type"] == "object"
        donor = validate_success(response, 201)

        assert is_valid_uuid(donor["id"]) or donor["id"]
        assert donor["donor_code"] == "DNR-0001"
        assert donor["full_name"] == "Ana Ruiz"
        assert donor["email"] == "ana.ruiz@example.org"
        assert donor["zone_code"] == "Z2"
        assert donor["status"] == "APPLICANT"
        assert donor["screening_risk_score"] == 0
        assert donor["surveillance_risk_score"] == 0
        assert donor["reimbursement_balance_cents"] == 0
        assert isinstance(donor["reimbursement_balance_cents"], int)
        assert donor["lifetime_accepted_volume_ml"] == 0
        assert donor["temporary_deferral_count"] == 0
        assert donor["active_deferral_until_date"] is None
        assert donor["qualified_at"] is None
        assert donor["qualified_by_user_id"] is None
        assert donor["version"] == 1
        A.assert_audit_fields(donor, expected_version=1)
        A.assert_instant_equals(donor["created_at"], CLOCK, "created_at")
        A.assert_instant_equals(donor["updated_at"], CLOCK, "updated_at")

    def test_the_donor_list_windows_rows_and_reports_total_count_and_has_more(self):
        """Three donors enrolled at one instant tie on the primary created_at
        ordering, so donor_code ascending breaks the tie; a limit of 2 returns
        the first two with has_more true and a total_count of 3, and the second
        window returns the remaining row with has_more false.

        PRD: "`limit` bounds the number of rows returned; it defaults to 10 when omitted, may not be lower than 1, and may not exceed 100."
        Design: Corner/entities/donor_listing_paginates_with_total_count_and_has_more
        """
        fx.set_clock(CLOCK)
        for code, name in (("DNR-0001", "Ana Ruiz"), ("DNR-0002", "Bea Ortiz"), ("DNR-0003", "Cyd Park")):
            fx.enroll_donor(donor_code=code, full_name=name)

        first_rows, first_meta = validate_paginated(
            api_client.list_donors(INTAKE_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert [row["donor_code"] for row in first_rows] == ["DNR-0001", "DNR-0002"]

        second_rows, second_meta = validate_paginated(
            api_client.list_donors(INTAKE_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2
        assert second_rows[0]["donor_code"] == "DNR-0003"

    def test_reading_a_donor_identifier_that_does_not_exist_is_a_resource_not_found(self):
        """A well-formed identifier that addresses no donor is refused by the
        existence step with the single not-found identifier, not by any later
        gate.

        PRD: "The leftmost missing reference wins, and the rejection is always `ERR_RESOURCE_NOT_FOUND` (HTTP 404) regardless of which reference was missing."
        Design: Corner/entities/donor_get_with_unknown_id_returns_resource_not_found
        """
        fx.set_clock(CLOCK)
        fx.enroll_donor(donor_code="DNR-0001")

        response = api_client.get_donor("00000000-0000-4000-8000-000000000000", INTAKE_HEADERS)
        validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND.value, 404)

    def test_qualification_stamps_the_actor_and_the_clock_and_the_client_cannot_forge_them(self):
        """A client-supplied status, score, qualified_at, qualified_by_user_id
        and version are ignored on enrolment; the qualification stamps that do
        appear are the server's own, carrying the acting director's identifier
        and the clock instant, and they survive a later read unchanged.

        PRD: "On success the recomputed surveillance score is stored, `qualified_at` is stamped with the clock instant, `qualified_by_user_id` is stamped with the acting director's `X-User-ID`, and the donor's `version` increases by 1."
        Design: Corner/entities/donor_system_fields_are_server_generated
        """
        fx.set_clock(CLOCK)
        created = validate_success(
            api_client.create_donor(
                f.donor(
                    donor_code="DNR-0001",
                    status="QUALIFIED",
                    screening_risk_score=99,
                    qualified_at="2020-01-01T00:00:00Z",
                    qualified_by_user_id="u-forged-1",
                    version=77,
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert created["status"] == "APPLICANT", "an unwritable field is ignored, never rejected"
        assert created["screening_risk_score"] == 0
        assert created["qualified_at"] is None
        assert created["qualified_by_user_id"] is None
        assert created["version"] == 1

        fx.submit_questionnaire(created["id"], **fx.CLEAN_QUESTIONNAIRE)
        fx.record_serology(created["id"], collected_on="2026-07-20")
        fx.record_approval(created["id"], physician_npi="1234567893", approved_on="2026-07-15")
        qualified = fx.qualify(created["id"])

        assert qualified["status"] == "QUALIFIED"
        assert qualified["qualified_by_user_id"] == MEDICAL_DIRECTOR_ID
        A.assert_instant_equals(qualified["qualified_at"], CLOCK, "qualified_at")
        assert qualified["version"] == 3, "enrolment, the questionnaire and qualification each add one"

        reread = fx.get_donor(created["id"])
        assert reread["id"] == created["id"], "the identifier is stable across reads"
        assert reread["qualified_by_user_id"] == MEDICAL_DIRECTOR_ID
        A.assert_instant_equals(reread["qualified_at"], CLOCK, "qualified_at")
        assert reread["version"] == 3


class TestDonorStateGates:
    """The lifecycle admits each operation from a named set of states only."""

    def test_a_permanently_deferred_donor_refuses_every_further_operation(self):
        """A reactive HIV result carries its own authority: it moves an APPLICANT
        straight to PERMANENTLY_DEFERRED behind a system-authored permanent
        deferral event, after which neither a fresh questionnaire nor
        requalification is admitted.

        PRD: "A donor in `PERMANENTLY_DEFERRED` accepts no operation at all: that state is terminal."
        Design: Corner/state_machines/permanently_deferred_donor_accepts_no_further_transition
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")
        fx.record_serology(donor["id"], collected_on="2026-07-20", hiv_result="REACTIVE")

        blocked_history = api_client.submit_health_history(
            donor["id"], f.health_history(), INTAKE_HEADERS
        )
        validate_error(blocked_history, ApiErrorId.DONOR_STATE_INVALID.value, 409)
        blocked_requalify = api_client.requalify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        validate_error(blocked_requalify, ApiErrorId.DONOR_STATE_INVALID.value, 409)

        after = fx.get_donor(donor["id"])
        assert after["status"] == "PERMANENTLY_DEFERRED"
        assert after["version"] == 2, "enrolment then the reactive panel; the two refusals wrote nothing"

        events, meta = validate_paginated(api_client.list_deferrals(donor["id"], MEDICAL_DIRECTOR_HEADERS))
        assert meta["total_count"] == 1
        event = events[0]
        assert event["reason_code"] == "REACTIVE_SEROLOGY"
        assert event["deferral_type"] == "PERMANENT"
        assert event["effective_from"] == CLOCK_DATE
        assert event["deferral_days"] == 0
        assert event["lookback_days"] == 365
        assert event["recall_scope"] == "FULL_CHAIN"
        assert event["status"] == "ACTIVE"
        assert event["recorded_by_user_id"] == C.SYSTEM_USER_ID
        A.assert_recall_counters(event)

        histories, history_meta = validate_paginated(
            api_client.list_health_history(donor["id"], INTAKE_HEADERS)
        )
        assert history_meta["total_count"] == 0
        assert histories == []

    def test_qualifying_an_applicant_reports_the_state_gate_not_the_missing_questionnaire(self):
        """An APPLICANT with serology and an approval on file but no
        questionnaire at all is refused by the state gate, which sits ahead of
        the accepted-questionnaire requirement in the qualification order.

        PRD: "Health-history submission is admitted only from `APPLICANT`, `SCREENING` or `INFO_REQUESTED`; qualification only from `SCREENING`; requalification only from `TEMPORARILY_DEFERRED`; deferral recording from `SCREENING`, `INFO_REQUESTED`, `QUALIFIED` or `TEMPORARILY_DEFERRED`."
        Design: Corner/state_machines/qualify_from_applicant_returns_donor_state_invalid
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")
        fx.record_serology(donor["id"], collected_on="2026-07-20")
        fx.record_approval(donor["id"], physician_npi="1234567893", approved_on="2026-07-15")

        response = api_client.qualify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        validate_error(response, ApiErrorId.DONOR_STATE_INVALID.value, 409)

        after = fx.get_donor(donor["id"])
        assert after["status"] == "APPLICANT", "the refusal left the donor where she was"
        assert after["qualified_at"] is None
        assert after["version"] == 1

    def test_an_auto_deferred_questionnaire_authors_a_system_deferral_in_the_same_request(self):
        """A questionnaire scoring 81 base points triages AUTO_DEFERRED once the
        pending-serology penalty caps its screening figure at 100, and the same
        request writes the AUTO_HIGH_RISK event, raises the deferral count, sets
        the ninety-day deferral horizon and recomputes the surveillance score.

        PRD: "The questionnaire is written with `status` `AUTO_DEFERRED`; that in turn creates a system-authored `DeferralEvent` whose `reason_code` is `AUTO_HIGH_RISK`, whose `deferral_type` is `TEMPORARY`, whose `effective_from` is the current clock date, whose `deferral_days` is 90, whose `lookback_days` is 0, whose `recall_scope` is `NONE` and whose `recorded_by_user_id` is the literal string `system`; that new event in turn increments the donor's `temporary_deferral_count` by 1 and sets her `active_deferral_until_date` to 90 days after its `effective_from`; and because the deferral count has changed, her `surveillance_risk_score` is recomputed once more before the request completes."
        Design: Corner/state_machines/auto_high_risk_questionnaire_creates_a_system_deferral_event
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")
        questionnaire = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=4,
            travel_risk_flag=True,
            tobacco_use=False,
            alcohol_units_per_week=4,
            months_postpartum=15,
        )
        assert questionnaire["base_risk_points"] == 81, "32 medication, 25 travel, 15 alcohol, 9 postpartum"
        assert questionnaire["screening_risk_score"] == 100, "81 plus 20 is capped at 100"
        assert questionnaire["status"] == "AUTO_DEFERRED"

        after = fx.get_donor(donor["id"])
        assert after["status"] == "TEMPORARILY_DEFERRED"
        assert after["temporary_deferral_count"] == 1
        assert after["screening_risk_score"] == 100
        assert after["surveillance_risk_score"] == 96, "81 plus a same-day deferral at full 15 points"
        assert after["active_deferral_until_date"] == A.add_days(CLOCK_DATE, 90) == "2026-11-03"

        events, meta = validate_paginated(api_client.list_deferrals(donor["id"], MEDICAL_DIRECTOR_HEADERS))
        assert meta["total_count"] == 1
        event = events[0]
        assert event["reason_code"] == "AUTO_HIGH_RISK"
        assert event["deferral_type"] == "TEMPORARY"
        assert event["effective_from"] == CLOCK_DATE
        assert event["deferral_days"] == 90
        assert event["lookback_days"] == 0
        assert event["recall_scope"] == "NONE"
        assert event["status"] == "ACTIVE"
        assert event["recorded_by_user_id"] == C.SYSTEM_USER_ID
        A.assert_recall_counters(event)


class TestBaseScoreConstants:
    """The alcohol tiers and the postpartum cap are read off the disclosures."""

    def test_the_alcohol_tier_boundary_and_the_postpartum_cap_both_bind(self):
        """Thirty months postpartum would earn 54 points uncapped but is charged
        30; dropping the weekly alcohol figure from 4 to 3 crosses a tier
        boundary and takes 10 points off the base, which is exactly what moves
        the questionnaire out of INFO_REQUESTED and into ACCEPTED.

        PRD: "Postpartum time is charged only beyond the first twelve months: subtract 12 from `months_postpartum`, treat any negative result as 0, multiply what remains by 3 points per month, and cap the resulting term at 30 points."
        Design: Corner/calculations/risk_alcohol_tier_and_postpartum_cap_constants_are_applied
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")

        first = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=0,
            travel_risk_flag=False,
            tobacco_use=False,
            alcohol_units_per_week=4,
            months_postpartum=30,
        )
        assert first["base_risk_points"] == 45, "15 for the 4-to-7 alcohol tier plus a postpartum term capped at 30"
        assert first["base_risk_points"] == A.expected_base_risk_points(
            alcohol_units_per_week=4, months_postpartum=30
        )
        assert first["screening_risk_score"] == 65
        assert first["status"] == "INFO_REQUESTED"

        second = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=0,
            travel_risk_flag=False,
            tobacco_use=False,
            alcohol_units_per_week=3,
            months_postpartum=30,
        )
        assert second["base_risk_points"] == 35, "the 1-to-3 tier is worth 5, still with the 30-point cap"
        assert second["base_risk_points"] == A.expected_base_risk_points(
            alcohol_units_per_week=3, months_postpartum=30
        )
        assert second["screening_risk_score"] == 55
        assert second["status"] == "ACCEPTED"

        after = fx.get_donor(donor["id"])
        assert after["status"] == "SCREENING"
        assert after["screening_risk_score"] == 55
        assert after["surveillance_risk_score"] == 35, "no deferral history and no serology term"
        assert after["version"] == 3

        _, meta = validate_paginated(api_client.list_health_history(donor["id"], INTAKE_HEADERS))
        assert meta["total_count"] == 2


class TestQualificationGateLadder:
    """The five qualification checks fire in a fixed order."""

    def test_qualification_reports_serology_then_approval_and_only_then_succeeds(self):
        """A SCREENING donor with neither clinical document on file reports the
        serology failure; once the panel is filed the very same call reports the
        approval failure instead; once the approval is filed the call succeeds.

        PRD: "**Qualifying a donor** enforces five checks in this order: the donor's own state gate first (`ERR_DONOR_STATE_INVALID`), then the accepted-questionnaire requirement (`ERR_HEALTH_HISTORY_INCOMPLETE`), then unexpired non-reactive serology (`ERR_SEROLOGY_MISSING_OR_EXPIRED`), then an active physician approval (`ERR_PHYSICIAN_APPROVAL_MISSING`), and only then the recomputed surveillance score ceiling (`ERR_RISK_SCORE_TOO_HIGH`)."
        Design: Corner/validations/qualification_gate_ladder_serology_then_approval_then_success
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")
        questionnaire = fx.submit_questionnaire(donor["id"], **fx.CLEAN_QUESTIONNAIRE)
        assert questionnaire["base_risk_points"] == 30
        assert questionnaire["screening_risk_score"] == 50
        assert questionnaire["status"] == "ACCEPTED"
        assert fx.get_donor(donor["id"])["status"] == "SCREENING"

        no_serology = api_client.qualify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        validate_error(no_serology, ApiErrorId.SEROLOGY_MISSING_OR_EXPIRED.value, 409)

        panel = fx.record_serology(donor["id"], collected_on="2026-07-20")
        assert panel["panel_status"] == "NON_REACTIVE"
        no_approval = api_client.qualify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        validate_error(no_approval, ApiErrorId.PHYSICIAN_APPROVAL_MISSING.value, 409)

        approval = fx.record_approval(donor["id"], physician_npi="1234567893", approved_on="2026-07-15")
        assert approval["status"] == "ACTIVE"
        qualified = fx.qualify(donor["id"])
        assert qualified["status"] == "QUALIFIED"
        A.assert_instant_equals(qualified["qualified_at"], CLOCK, "qualified_at")
        assert qualified["qualified_by_user_id"] == MEDICAL_DIRECTOR_ID
        assert qualified["surveillance_risk_score"] == 30
        assert qualified["screening_risk_score"] == 50

    def test_an_info_requested_questionnaire_outranks_the_score_ceiling(self):
        """A donor whose newest questionnaire is INFO_REQUESTED, and whose
        recomputed surveillance figure of 62 also exceeds the ceiling, is refused
        for the incomplete history: that check sits ahead of the score check.

        PRD: "The donor's newest questionnaire must have `status` `ACCEPTED` — an `INFO_REQUESTED` or `AUTO_DEFERRED` questionnaire as the current one is disqualifying, and having no questionnaire at all is equally disqualifying, both reported as `ERR_HEALTH_HISTORY_INCOMPLETE`."
        Design: Corner/validations/qualify_with_an_info_requested_questionnaire_returns_health_history_incomplete
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")
        questionnaire = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=4,
            travel_risk_flag=False,
            tobacco_use=False,
            alcohol_units_per_week=4,
            months_postpartum=12,
        )
        assert questionnaire["base_risk_points"] == 47, "32 medication points plus the 15-point alcohol tier"
        assert questionnaire["screening_risk_score"] == 67
        assert questionnaire["status"] == "INFO_REQUESTED"

        fx.record_serology(donor["id"], collected_on="2026-07-20")
        fx.record_approval(donor["id"], physician_npi="1234567893", approved_on="2026-07-15")
        deferred = fx.record_deferral(
            donor["id"], effective_from=CLOCK_DATE, deferral_days=1, lookback_days=0, recall_scope="NONE"
        )
        assert deferred["deferral_days"] == 1
        assert fx.get_donor(donor["id"])["active_deferral_until_date"] == "2026-08-06"

        fx.set_clock("2026-08-07T08:00:00Z")
        assert fx.requalify(donor["id"])["status"] == "SCREENING"

        response = api_client.qualify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        validate_error(response, ApiErrorId.HEALTH_HISTORY_INCOMPLETE.value, 409)

        after = fx.get_donor(donor["id"])
        assert after["status"] == "SCREENING"
        assert after["qualified_at"] is None
        assert after["screening_risk_score"] == 67, "the deferral recomputes only the surveillance figure"
        assert after["surveillance_risk_score"] == 62, "47 plus 15 * 0.5 ** (2/180), rounded half up"
        assert after["surveillance_risk_score"] == A.expected_surveillance_score(47, [2])
        assert after["active_deferral_until_date"] is None
        assert after["temporary_deferral_count"] == 1

        _, meta = validate_paginated(api_client.list_health_history(donor["id"], INTAKE_HEADERS))
        assert meta["total_count"] == 1

    def test_two_recent_deferrals_push_the_decayed_score_past_the_ceiling(self):
        """An ACCEPTED questionnaire at 40 base points is not enough on its own:
        two three-day-old temporary deferrals still carry almost their full 15
        points each, so the score recomputed at qualification time is 70 and the
        ceiling refuses the call.

        PRD: "And her `surveillance_risk_score`, recomputed fresh at this moment rather than read from the last write, must be 60 or less, failing which the answer is `ERR_RISK_SCORE_TOO_HIGH`."
        Design: Corner/validations/qualify_refused_when_the_decayed_surveillance_score_reaches_70
        """
        fx.set_clock(CLOCK)
        donor = fx.enroll_donor(donor_code="DNR-0001")
        questionnaire = fx.submit_questionnaire(
            donor["id"],
            medication_flag_count=2,
            travel_risk_flag=False,
            tobacco_use=False,
            alcohol_units_per_week=4,
            months_postpartum=15,
        )
        assert questionnaire["base_risk_points"] == 40
        assert questionnaire["screening_risk_score"] == 60
        assert questionnaire["status"] == "ACCEPTED"

        fx.record_serology(donor["id"], collected_on="2026-07-20")
        fx.record_approval(donor["id"], physician_npi="1234567893", approved_on="2026-07-15")
        fx.record_deferral(
            donor["id"],
            reason_code="ILLNESS",
            effective_from=CLOCK_DATE,
            deferral_days=1,
            lookback_days=0,
            recall_scope="NONE",
        )
        fx.record_deferral(
            donor["id"],
            reason_code="TRAVEL",
            effective_from=CLOCK_DATE,
            deferral_days=1,
            lookback_days=0,
            recall_scope="NONE",
        )

        fx.set_clock("2026-08-08T08:00:00Z")
        fx.requalify(donor["id"])
        response = api_client.qualify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        validate_error(response, ApiErrorId.RISK_SCORE_TOO_HIGH.value, 409)

        after = fx.get_donor(donor["id"])
        assert after["status"] == "SCREENING"
        assert after["qualified_at"] is None
        assert after["screening_risk_score"] == 60
        assert after["surveillance_risk_score"] == 70, "40 plus two terms of 15 * 0.5 ** (3/180)"
        assert after["surveillance_risk_score"] == A.expected_surveillance_score(40, [3, 3])
        assert after["temporary_deferral_count"] == 2
        assert after["active_deferral_until_date"] is None

        _, meta = validate_paginated(
            api_client.list_deferrals(donor["id"], MEDICAL_DIRECTOR_HEADERS, params={"status": "EXPIRED"})
        )
        assert meta["total_count"] == 2


class TestClockAndCodeUniqueness:
    """Two bank-wide invariants that guard every later write."""

    def test_the_clock_accepts_a_repeated_instant_but_refuses_to_move_backwards(self):
        """Setting the clock one second earlier than its current value is refused
        as non-monotonic; setting it to exactly its current value is admitted,
        because monotonic forbids only a fall back; and a row written after the
        next advance carries the new instant on both audit fields.

        PRD: "An administrative test-driving capability sets the clock to a supplied `current_utc` instant; the clock is monotonic, so a requested instant earlier than the current one is refused with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 409)."
        Design: Corner/validations/clock_may_repeat_an_instant_but_never_moves_backwards
        """
        fx.set_clock(CLOCK)

        backwards = api_client.set_clock("2026-08-05T07:59:59Z", ADMIN_HEADERS)
        validate_error(backwards, ApiErrorId.CLOCK_NOT_MONOTONIC.value, 409)

        repeated = api_client.set_clock(CLOCK, ADMIN_HEADERS)
        assert repeated.status_code == 200, "an equal instant is not earlier, so it is admitted"
        validate_success(repeated, 200)

        forwards = api_client.set_clock("2026-08-06T00:00:00Z", ADMIN_HEADERS)
        validate_success(forwards, 200)

        donor = fx.enroll_donor(donor_code="DNR-0001")
        A.assert_instant_equals(donor["created_at"], "2026-08-06T00:00:00Z", "created_at")
        A.assert_instant_equals(donor["updated_at"], "2026-08-06T00:00:00Z", "updated_at")

    def test_business_codes_are_unique_bank_wide_while_container_labels_are_per_cooler(self):
        """A second donor claiming an enrolled donor_code and a second cooler
        claiming a registered tracking_code are both duplicates; a container
        label is scoped to its own cooler, so repeating it inside the same
        shipment is a duplicate while the same label in a different shipment is
        admitted.

        PRD: "Step 8 reports `ERR_DUPLICATE_CODE` (HTTP 409) when `donor_code`, `tracking_code`, `pool_code`, `program_code` or `prescription_code` is already present anywhere in the bank, or when `container_label` repeats inside the same cooler."
        Design: Corner/validations/duplicate_codes_are_global_except_container_labels_which_are_per_shipment
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001")
        first_cooler = fx.accepted_cooler(
            donor["id"], tracking_code="TRK-0001", container_count=2, declared_volume_ml=1400
        )
        fx.log_container(
            first_cooler["id"], container_label="C1", volume_ml=700, expressed_on="2026-07-05"
        )
        second_cooler = fx.accepted_cooler(
            donor["id"],
            tracking_code="TRK-0002",
            container_count=1,
            declared_volume_ml=700,
            shipped_on="2026-08-03",
        )

        duplicate_donor = api_client.create_donor(f.donor(donor_code="DNR-0001", full_name="Bea Ortiz"), INTAKE_HEADERS)
        validate_error(duplicate_donor, ApiErrorId.DUPLICATE_CODE.value, 409)

        duplicate_cooler = api_client.create_shipment(
            f.shipment(donor["id"], tracking_code="TRK-0001", declared_volume_ml=700, shipped_on="2026-08-03"),
            INTAKE_HEADERS,
        )
        validate_error(duplicate_cooler, ApiErrorId.DUPLICATE_CODE.value, 409)

        duplicate_label = api_client.log_donation(
            first_cooler["id"],
            f.donation(
                fx.shipment_version(first_cooler["id"]),
                container_label="C1",
                volume_ml=700,
                expressed_on="2026-07-05",
            ),
            INTAKE_HEADERS,
        )
        validate_error(duplicate_label, ApiErrorId.DUPLICATE_CODE.value, 409)

        reused_label = validate_success(
            api_client.log_donation(
                second_cooler["id"],
                f.donation(
                    fx.shipment_version(second_cooler["id"]),
                    container_label="C1",
                    volume_ml=700,
                    expressed_on="2026-07-05",
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert reused_label["container_label"] == "C1", "the label is scoped to its own cooler"
        assert reused_label["shipment_id"] == second_cooler["id"]
        assert reused_label["volume_ml"] == 700
        assert reused_label["remaining_ml"] == 700
        assert reused_label["status"] == "ELIGIBLE"

        _, first_meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": first_cooler["id"]})
        )
        assert first_meta["total_count"] == 1, "the refused duplicate wrote nothing"
        _, donor_meta = validate_paginated(api_client.list_donors(INTAKE_HEADERS))
        assert donor_meta["total_count"] == 1
