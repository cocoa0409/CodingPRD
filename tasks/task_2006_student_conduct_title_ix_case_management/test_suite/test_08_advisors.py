"""Advisor appointments: eligibility, the university selector, convene gating."""
from test_helpers import (
    ApiErrorId,
    advisor_appointment_payload,
    appoint_advisor,
    appoint_both_advisors,
    convene_hearing,
    create_case,
    drive_to_hearing_preparation,
    make_cast,
    make_coordinator_headers,
    make_decision_maker_headers,
    make_party_headers,
    schedule_hearing,
    set_clock,
    university_appointment_payload,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestAdvisorEligibility:
    def test_advisor_appointment_opposing_party_ineligible(self, api):
        """PRD 3.4: "Eligibility is checked per §2.6 in spirit and precisely here:
        the advisor must not be the opposing party of the same case and must not
        hold any official function on it, failing as `ERR_ADVISOR_INELIGIBLE`
        (422); the `advisor_eligible` directory flag is *not* required for
        party-selected advisors."

        Design: Corner/validations/advisor_appointment_opposing_party_ineligible
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        resp = api.appoint_advisor(
            case["id"],
            advisor_appointment_payload("COMPLAINANT", cast["resp"]["id"]),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ADVISOR_INELIGIBLE)

    def test_appoint_university_empty_pool_rejected(self, api):
        """PRD 3.4: "An empty pool is rejected with `ERR_NO_ADVISOR_AVAILABLE`
        (422)."
        PRD 3.4: "A deterministic selector builds the pool: every directory
        profile with `advisor_eligible` true, excluding the case's two parties
        and everyone holding an official function on the case."

        Design: Corner/validations/appoint_university_empty_pool_rejected
        """
        # Nobody in the directory is advisor_eligible, so the pool is empty.
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        resp = api.appoint_university_advisor(
            case["id"], university_appointment_payload("COMPLAINANT"),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ADVISOR_AVAILABLE)


class TestAdvisorReplacement:
    def test_advisor_duplicate_and_replacement_cascade(self, api):
        """PRD 3.4: "The new appointment lands in `ACTIVE` with `source` set to
        `PARTY_SELECTED`, appends `ADVISOR_APPOINTED`, and increments the case
        `version`; any prior `ACTIVE` appointment for the same case and side is
        automatically replaced — moved to `REPLACED` with its
        `replaced_by_appointment_id` pointing at the newcomer and
        `ADVISOR_REPLACED` appended. Re-appointing the very same `advisor_id` for
        a side that already actively holds that advisor is a no-op rejection,
        `ERR_DUPLICATE_ADVISOR` (409)."

        Design: Corner/validations/advisor_duplicate_and_replacement_cascade
        """
        cast = make_cast("comp", "resp", "coord", "advc", "advr")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        first = appoint_advisor(case["id"], "COMPLAINANT", cast["advc"]["id"], cast["comp"]["id"])
        assert first["status"] == "ACTIVE" and first["source"] == "PARTY_SELECTED"

        # Same advisor for the same side: no-op rejection.
        duplicate = api.appoint_advisor(
            case["id"],
            advisor_appointment_payload("COMPLAINANT", cast["advc"]["id"]),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ADVISOR)

        # A different advisor cascades the replacement.
        second = appoint_advisor(case["id"], "COMPLAINANT", cast["advr"]["id"], cast["comp"]["id"])
        assert second["status"] == "ACTIVE" and second["source"] == "PARTY_SELECTED"

        old = validate_success(
            api.get_advisor_appointment(
                first["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert old["status"] == "REPLACED"
        assert old["replaced_by_appointment_id"] == second["id"]


class TestConveneAdvisorGate:
    def _scheduled_case_with_withdrawn_respondent_advisor(self, cast):
        """Drive to HEARING_PREPARATION, appoint both advisors, schedule the
        hearing, advance the clock to the hearing instant, then withdraw the
        respondent's advisor. Returns (case, hearing, respondent_appointment)."""
        case = create_case(cast, categories=["OTHER_SEX_BASED"])
        drive_to_hearing_preparation(case["id"], cast)
        comp_appt, resp_appt = appoint_both_advisors(case["id"], cast)
        hearing = schedule_hearing(case["id"], cast["coord"]["id"], cast["dm"]["id"])
        set_clock("2026-09-01T10:00:00Z")
        api_client.withdraw_advisor_appointment(
            resp_appt["id"], make_party_headers(cast["resp"]["id"])
        )
        return case, hearing, resp_appt

    def test_convene_fails_when_a_party_lacks_active_advisor(self, api):
        """PRD 3.4: "The decision-maker — and only that person; anyone else is
        rejected with `ERR_NOT_HEARING_DECISION_MAKER` (422) — **convenes** the
        hearing once the clock has reached `scheduled_at` and both parties each
        hold an `ACTIVE` advisor appointment on the case, the latter failing as
        `ERR_ADVISOR_REQUIRED` (422)."

        Design: Difficulty/cross_entity_state_dependency/hearing_convene_gated_on_both_advisors_active
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "adv3", "advr")
        case, hearing, _ = self._scheduled_case_with_withdrawn_respondent_advisor(cast)

        resp = api.convene_hearing(
            hearing["id"], make_decision_maker_headers(cast["dm"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ADVISOR_REQUIRED)
        after = validate_success(
            api.get_hearing(hearing["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert after["status"] == "SCHEDULED", "a rejected convene must not move the hearing"

    def test_university_selector_restores_convene_gate(self, api):
        """PRD 3.4: "A deterministic selector builds the pool: every directory
        profile with `advisor_eligible` true, excluding the case's two parties
        and everyone holding an official function on the case. The pool is ranked
        by fewest `ACTIVE` appointments across *all* cases, ascending, with ties
        broken by earliest `created_at` ascending, and the top profile is
        appointed with `source` set to `UNIVERSITY_APPOINTED`".

        Design: Difficulty/cross_entity_state_dependency/hearing_convene_gated_on_both_advisors_active
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "adv3", "advr")
        case, hearing, _ = self._scheduled_case_with_withdrawn_respondent_advisor(cast)
        dm_h = make_decision_maker_headers(cast["dm"]["id"])

        validate_error(
            api.convene_hearing(hearing["id"], dm_h), ApiErrorId.ERR_ADVISOR_REQUIRED
        )

        # Selector pool: advc (1 ACTIVE), advr (0 ACTIVE, created later), adv3
        # (0 ACTIVE, created earlier). The tie between advr and adv3 breaks on
        # earliest created_at, so adv3 is appointed.
        appointed = api.appoint_university_advisor(
            case["id"], university_appointment_payload("RESPONDENT"),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        appt = validate_success(appointed, 201)
        assert appt["advisor_id"] == cast["adv3"]["id"]
        assert appt["source"] == "UNIVERSITY_APPOINTED"
        assert appt["status"] == "ACTIVE"

        convened = api.convene_hearing(hearing["id"], dm_h)
        hearing_after = validate_success(convened, 200)
        assert hearing_after["status"] == "IN_SESSION"
