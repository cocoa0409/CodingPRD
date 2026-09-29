"""Regulator inquiry responses, their admissibility gates and adequacy scoring."""

from test_helpers import (
    CLOCK_TEST_INSTANT,
    MANDATORY_COVERAGE_EVENT_TYPES,
    NON_EXISTENT_UUID,
    RESPONSE_GRACE_DAYS,
    TEST_USERS,
    ApiErrorId,
    add_disclosures,
    api_client,
    assert_instant_equals,
    assert_regulator_inquiry,
    assert_score_equals,
    audit_event_ids_by_type,
    days_after,
    fetch_broker,
    fetch_inquiry,
    list_audit_events,
    onboard_broker,
    open_draft_registration,
    open_inquiry,
    respond_to_inquiry,
    set_clock,
    validate_error,
    validate_success,
)

PLATFORM_ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
REGULATOR_HEADERS = TEST_USERS["regulator_headers"]

# Four event types that a plain onboarding-plus-filing trail carries, none of
# which is one of the three mandatory coverage types, so the coverage bonus
# cannot apply to a response citing them.
NON_COVERAGE_EVENT_TYPES = [
    "BROKER_REGISTERED",
    "FEE_DEPOSITED",
    "REGISTRATION_CREATED",
    "DISCLOSURE_ADDED",
]


def _setup_inquiry_with_four_non_coverage_citations():
    """Broker whose trail holds exactly the four non-coverage event types, plus one
    OPEN inquiry whose deadline is 30 days after the pinned clock instant.

    Returns the onboarding context extended with inquiry, inquiry_id and the four
    audit-event ids offered as evidence, in the order they are cited.
    """
    assert not set(NON_COVERAGE_EVENT_TYPES) & set(MANDATORY_COVERAGE_EVENT_TYPES), (
        "Setup requires citations that cannot earn the coverage bonus"
    )
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT)
    registration = open_draft_registration(ctx["broker_id"], ctx["broker_headers"])
    add_disclosures(
        registration["id"], ctx["broker_headers"], categories=["SOURCES"]
    )
    ctx["inquiry"] = open_inquiry(
        ctx["broker_id"], response_due_at=days_after(CLOCK_TEST_INSTANT, 30)
    )
    ctx["inquiry_id"] = ctx["inquiry"]["id"]
    ctx["cited_audit_event_ids"] = audit_event_ids_by_type(
        ctx["broker_id"], ctx["broker_headers"], NON_COVERAGE_EVENT_TYPES
    )
    return ctx


def _setup_open_inquiry_with_one_citable_event(deposit_cents=0, **broker_overrides):
    """Broker onboarded at the pinned clock instant with one OPEN inquiry against it
    and one citable audit event from its own trail."""
    ctx = onboard_broker(
        clock=CLOCK_TEST_INSTANT, deposit_cents=deposit_cents, **broker_overrides
    )
    ctx["inquiry"] = open_inquiry(
        ctx["broker_id"], response_due_at=days_after(CLOCK_TEST_INSTANT, 30)
    )
    ctx["inquiry_id"] = ctx["inquiry"]["id"]
    ctx["event_id"] = audit_event_ids_by_type(
        ctx["broker_id"], ctx["broker_headers"], ["BROKER_REGISTERED"]
    )[0]
    return ctx


class TestAdequacyScoring:
    """The three pinned scoring steps of a regulator response."""

    def test_deficiency_penalty_is_keyed_on_the_step_one_evidence_score(self):
        """PRD §3.8: "The evidence score is 15.00 per credited citation, plus 15.00
        when the coverage bonus applies, capped at 100.00 and rounded half up to two
        decimal places."
        PRD §3.8: "**Step 2** selects `deficiency_penalty` from a tier table keyed on
        the step-1 `evidence_score`, evaluated exactly once: the penalty is 0.00 when
        `evidence_score` is at least 80.00, 8.00 when it is at least 60.00 and below
        80.00, 20.00 when it is at least 40.00 and below 60.00, and 35.00 otherwise."
        PRD §3.8: "The key is the step-1 evidence score and never the final
        `adequacy_score`, and the tier lookup is never iterated to a fixed point even
        though the tier table is expressed in the same nought-to-hundred band that
        `adequacy_score` lives in."
        PRD §3.8: "An `evidence_score` of 60.00 selects a penalty of 8.00 and produces
        an `adequacy_score` of 52.00; keying the tier on the adequacy score instead —
        that is, re-reading the table at 52.00 and taking 20.00 — would produce 40.00
        and is wrong."
        PRD §3.8: "`late_response_penalty` is 10.00 when the current clock instant is
        strictly after `response_due_at`, and 0.00 otherwise"
        PRD §3.8: "`adequacy_score` is `evidence_score` minus `deficiency_penalty`
        minus `late_response_penalty`, floored at 0.00 and rounded half up to two
        decimal places."
        PRD §3.8: "`adequacy_verdict` is `ADEQUATE` when `adequacy_score` is at least
        65.00 and `DEFICIENT` when it is below."

        Design: Difficulty/combinatorial_formula/regulator_adequacy_penalty_keyed_on_evidence_not_adequacy
        """
        ctx = _setup_inquiry_with_four_non_coverage_citations()

        inquiry = validate_success(
            api_client.respond_to_inquiry(
                ctx["inquiry_id"],
                {"cited_audit_event_ids": ctx["cited_audit_event_ids"]},
                ctx["broker_headers"],
            )
        )

        assert_regulator_inquiry(inquiry)
        assert_score_equals(inquiry["evidence_score"], "60.00", "evidence_score")
        assert_score_equals(
            inquiry["deficiency_penalty"], "8.00", "deficiency_penalty"
        )
        assert_score_equals(
            inquiry["late_response_penalty"], "0.00", "late_response_penalty"
        )
        assert_score_equals(inquiry["adequacy_score"], "52.00", "adequacy_score")
        assert inquiry["adequacy_verdict"] == "DEFICIENT", (
            "an adequacy_score of 52.00 is below 65.00 and must read DEFICIENT, "
            f"got {inquiry['adequacy_verdict']!r}"
        )

    def test_response_stores_the_citation_set_and_moves_the_inquiry_to_responded(self):
        """PRD §3.8: "`cited_event_count` is the supplied array length, duplicated ids
        included, and the credited citations are the smaller of `cited_event_count` and
        5; only the first five entries are credited, taken in the order supplied."
        PRD §3.8: "`coverage_bonus_applied` is true when each of the three mandatory
        coverage event types — `DELETION_REQUEST_RECEIVED`, `DELETION_EXECUTED`, and
        `SUPPRESSION_CREATED` — appears at least once among the cited events'
        `event_type` values."
        PRD §3.8: "An accepted response stores `cited_audit_event_ids` in the order
        supplied along with every derived field, sets `responded_at` to the current
        clock instant, moves the inquiry to `RESPONDED`, and appends an
        `INQUIRY_RESPONDED` audit event."

        Design: Difficulty/combinatorial_formula/regulator_adequacy_penalty_keyed_on_evidence_not_adequacy
        """
        ctx = _setup_inquiry_with_four_non_coverage_citations()

        respond_to_inquiry(
            ctx["inquiry_id"], ctx["cited_audit_event_ids"], ctx["broker_headers"]
        )

        inquiry = fetch_inquiry(ctx["inquiry_id"], ctx["broker_headers"])
        assert inquiry["cited_event_count"] == 4, (
            "cited_event_count is the supplied array length, expected 4, got "
            f"{inquiry['cited_event_count']}"
        )
        assert inquiry["cited_audit_event_ids"] == ctx["cited_audit_event_ids"], (
            "cited_audit_event_ids must be stored in the order supplied"
        )
        assert inquiry["coverage_bonus_applied"] is False, (
            "no mandatory coverage event type was cited, so the bonus must not apply"
        )
        assert inquiry["status"] == "RESPONDED", (
            f"expected status RESPONDED, got {inquiry['status']!r}"
        )
        assert_instant_equals(
            inquiry["responded_at"], CLOCK_TEST_INSTANT, "responded_at"
        )
        responded_events = list_audit_events(
            ctx["broker_id"], ctx["broker_headers"], event_type="INQUIRY_RESPONDED"
        )
        assert len(responded_events) == 1, (
            "an accepted response appends exactly one INQUIRY_RESPONDED event, got "
            f"{len(responded_events)}"
        )

    def test_deficient_verdict_opens_a_breach_and_forces_delinquent_standing(self):
        """PRD §3.8: "An `evidence_score` of 60.00 selects a penalty of 8.00 and
        produces an `adequacy_score` of 52.00; keying the tier on the adequacy score
        instead — that is, re-reading the table at 52.00 and taking 20.00 — would
        produce 40.00 and is wrong."
        PRD §3.8: "When the verdict is `DEFICIENT`, the broker's `open_breach_count`
        increases by one and registry standing is re-derived, which forces
        `DELINQUENT`."

        Design: Difficulty/combinatorial_formula/regulator_adequacy_penalty_keyed_on_evidence_not_adequacy
        """
        ctx = _setup_inquiry_with_four_non_coverage_citations()

        inquiry = respond_to_inquiry(
            ctx["inquiry_id"], ctx["cited_audit_event_ids"], ctx["broker_headers"]
        )

        assert_score_equals(inquiry["adequacy_score"], "52.00", "adequacy_score")
        assert inquiry["adequacy_verdict"] == "DEFICIENT", (
            f"expected verdict DEFICIENT, got {inquiry['adequacy_verdict']!r}"
        )
        broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
        assert broker["open_breach_count"] == 1, (
            "a DEFICIENT verdict raises open_breach_count by one, got "
            f"{broker['open_breach_count']}"
        )
        assert broker["registry_standing"] == "DELINQUENT", (
            "a non-zero open_breach_count forces DELINQUENT, got "
            f"{broker['registry_standing']!r}"
        )


class TestCitationAdmissibility:
    """The gates a citation set must clear before a response is scored."""

    def test_response_citing_an_unknown_audit_event_is_rejected(self):
        """PRD §3.8: "Every id must resolve to an existing audit event, or
        `ERR_AUDIT_EVENT_NOT_FOUND` answers"
        PRD §2.6: "Every id listed in `cited_audit_event_ids` resolves to an existing
        audit event — otherwise `ERR_AUDIT_EVENT_NOT_FOUND` (404). Applies to
        `POST /regulator-inquiries/{id}/respond`."

        Design: Corner/validations/inquiry_response_citing_an_unknown_audit_event_rejected
        """
        ctx = _setup_open_inquiry_with_one_citable_event()

        response = api_client.respond_to_inquiry(
            ctx["inquiry_id"],
            {"cited_audit_event_ids": [ctx["event_id"], NON_EXISTENT_UUID]},
            ctx["broker_headers"],
        )

        validate_error(response, ApiErrorId.ERR_AUDIT_EVENT_NOT_FOUND.value, 404)
        inquiry = fetch_inquiry(ctx["inquiry_id"], ctx["broker_headers"])
        assert inquiry["status"] == "OPEN", (
            f"a refused response leaves the inquiry OPEN, got {inquiry['status']!r}"
        )
        assert inquiry["cited_event_count"] == 0, (
            "no citation is stored by a refused response, got "
            f"{inquiry['cited_event_count']}"
        )
        assert inquiry["cited_audit_event_ids"] == [], (
            f"expected an empty citation set, got {inquiry['cited_audit_event_ids']!r}"
        )
        assert inquiry["responded_at"] is None, (
            f"expected responded_at null, got {inquiry['responded_at']!r}"
        )
        assert inquiry["adequacy_verdict"] == "UNRATED", (
            f"expected verdict UNRATED, got {inquiry['adequacy_verdict']!r}"
        )

    def test_response_citing_another_brokers_audit_event_is_rejected(self):
        """PRD §3.8: "every cited event must carry a `broker_id` equal to the inquiry's
        `broker_id`, or `ERR_AUDIT_EVENT_FOREIGN` answers, because a broker may not
        answer with another broker's trail"
        PRD §2.6: "Every audit event named in `cited_audit_event_ids` carries a
        `broker_id` equal to the inquiry's `broker_id`; an inquiry may not be answered
        with another broker's trail — otherwise `ERR_AUDIT_EVENT_FOREIGN` (422)."

        Design: Corner/validations/inquiry_response_citing_another_brokers_audit_event_rejected
        """
        alpha = _setup_open_inquiry_with_one_citable_event(
            legal_name="Alpha Attribute Works",
            primary_contact_email="office@alpha.example",
        )
        beta = onboard_broker(
            clock=None,
            deposit_cents=0,
            legal_name="Beta Household Index",
            primary_contact_email="office@beta.example",
        )
        beta_events = list_audit_events(
            beta["broker_id"], PLATFORM_ADMIN_HEADERS, event_type="BROKER_REGISTERED"
        )
        assert beta_events, "Setup expected Beta's BROKER_REGISTERED event"

        response = api_client.respond_to_inquiry(
            alpha["inquiry_id"],
            {"cited_audit_event_ids": [beta_events[0]["id"]]},
            alpha["broker_headers"],
        )

        validate_error(response, ApiErrorId.ERR_AUDIT_EVENT_FOREIGN.value, 422)
        inquiry = fetch_inquiry(alpha["inquiry_id"], alpha["broker_headers"])
        assert inquiry["status"] == "OPEN", (
            f"a refused response leaves the inquiry OPEN, got {inquiry['status']!r}"
        )
        assert inquiry["cited_event_count"] == 0, (
            "no citation is stored by a refused response, got "
            f"{inquiry['cited_event_count']}"
        )
        assert_score_equals(inquiry["evidence_score"], "0.00", "evidence_score")

    def test_response_citing_an_audit_event_past_retention_is_rejected(self):
        """PRD §2.10: "`retention_expires_at` is the event's `created_at` plus 2555
        days — a seven-year retention floor."
        PRD §3.8: "no cited event may have passed its `retention_expires_at` at the
        current clock instant, or `ERR_CITED_EVENT_EXPIRED` answers, because an event
        past retention is no longer admissible."

        Design: Corner/validations/inquiry_response_citing_an_audit_event_past_retention_rejected
        """
        ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=0)
        events = list_audit_events(
            ctx["broker_id"], ctx["broker_headers"], event_type="BROKER_REGISTERED"
        )
        assert events, "Setup expected a BROKER_REGISTERED event"
        old_event = events[0]
        assert_instant_equals(
            old_event["retention_expires_at"],
            "2033-08-30T00:00:00Z",
            "retention_expires_at",
        )
        set_clock("2033-09-01T00:00:00Z")
        inquiry = open_inquiry(
            ctx["broker_id"], response_due_at="2033-10-01T00:00:00Z"
        )

        response = api_client.respond_to_inquiry(
            inquiry["id"],
            {"cited_audit_event_ids": [old_event["id"]]},
            ctx["broker_headers"],
        )

        validate_error(response, ApiErrorId.ERR_CITED_EVENT_EXPIRED.value, 422)
        refreshed = fetch_inquiry(inquiry["id"], ctx["broker_headers"])
        assert refreshed["status"] == "OPEN", (
            f"a refused response leaves the inquiry OPEN, got {refreshed['status']!r}"
        )
        assert refreshed["cited_event_count"] == 0, (
            "no citation is stored by a refused response, got "
            f"{refreshed['cited_event_count']}"
        )

    def test_response_after_the_thirty_day_grace_window_is_rejected(self):
        """PRD §3.8: "it must land while the response window is still open: the current
        clock instant must be at or before `response_due_at` advanced by a 30-day
        grace, or `ERR_RESPONSE_WINDOW_CLOSED` answers."
        PRD §2.6: "The current clock instant is at or before `response_due_at` plus a
        30-day grace; past that the inquiry can no longer be answered and must be
        escalated instead — otherwise `ERR_RESPONSE_WINDOW_CLOSED` (409)."

        Design: Corner/validations/inquiry_response_after_the_grace_window_rejected
        """
        ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=0)
        event_id = audit_event_ids_by_type(
            ctx["broker_id"], ctx["broker_headers"], ["BROKER_REGISTERED"]
        )[0]
        response_due_at = days_after(CLOCK_TEST_INSTANT, 9)
        inquiry = open_inquiry(ctx["broker_id"], response_due_at=response_due_at)
        set_clock(days_after(response_due_at, RESPONSE_GRACE_DAYS + 1))

        response = api_client.respond_to_inquiry(
            inquiry["id"],
            {"cited_audit_event_ids": [event_id]},
            ctx["broker_headers"],
        )

        validate_error(response, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED.value, 409)
        refreshed = fetch_inquiry(inquiry["id"], ctx["broker_headers"])
        assert refreshed["status"] == "OPEN", (
            f"a refused response leaves the inquiry OPEN, got {refreshed['status']!r}"
        )
        assert refreshed["responded_at"] is None, (
            f"expected responded_at null, got {refreshed['responded_at']!r}"
        )
        assert refreshed["cited_event_count"] == 0, (
            "no citation is stored by a refused response, got "
            f"{refreshed['cited_event_count']}"
        )
        assert_score_equals(
            refreshed["late_response_penalty"], "0.00", "late_response_penalty"
        )


def test_closing_an_inquiry_whose_verdict_is_deficient_is_rejected():
    """PRD §3.8: "The evidence score is 15.00 per credited citation, plus 15.00 when
    the coverage bonus applies, capped at 100.00 and rounded half up to two decimal
    places."
    PRD §3.8: "**Step 2** selects `deficiency_penalty` from a tier table keyed on the
    step-1 `evidence_score`, evaluated exactly once: the penalty is 0.00 when
    `evidence_score` is at least 80.00, 8.00 when it is at least 60.00 and below 80.00,
    20.00 when it is at least 40.00 and below 60.00, and 35.00 otherwise."
    PRD §3.8: "`adequacy_score` is `evidence_score` minus `deficiency_penalty` minus
    `late_response_penalty`, floored at 0.00 and rounded half up to two decimal
    places."
    PRD §3.8: "`adequacy_verdict` is `ADEQUATE` when `adequacy_score` is at least 65.00
    and `DEFICIENT` when it is below."
    PRD §3.8: "A `Regulator` closes a `RESPONDED` inquiry, and only when its
    `adequacy_verdict` is `ADEQUATE`, or `ERR_RESPONSE_INADEQUATE` answers"
    PRD §2.6: "An inquiry may only be closed when its `adequacy_verdict` is `ADEQUATE`
    — otherwise `ERR_RESPONSE_INADEQUATE` (422)."
    PRD §3.8: "An `INQUIRY_CLOSED` audit event is appended, and `CLOSED` is terminal."

    Design: Corner/validations/closing_a_deficient_inquiry_rejected
    """
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT)
    cited_ids = audit_event_ids_by_type(
        ctx["broker_id"], ctx["broker_headers"], ["BROKER_REGISTERED", "FEE_DEPOSITED"]
    )
    inquiry = open_inquiry(
        ctx["broker_id"], response_due_at=days_after(CLOCK_TEST_INSTANT, 30)
    )
    responded = respond_to_inquiry(inquiry["id"], cited_ids, ctx["broker_headers"])
    assert responded["cited_event_count"] == 2, (
        f"expected two stored citations, got {responded['cited_event_count']}"
    )
    assert responded["coverage_bonus_applied"] is False, (
        "no mandatory coverage event type was cited, so the bonus must not apply"
    )
    assert_score_equals(responded["evidence_score"], "30.00", "evidence_score")
    assert_score_equals(responded["deficiency_penalty"], "35.00", "deficiency_penalty")
    assert_score_equals(
        responded["late_response_penalty"], "0.00", "late_response_penalty"
    )
    assert_score_equals(responded["adequacy_score"], "0.00", "adequacy_score")
    assert responded["adequacy_verdict"] == "DEFICIENT", (
        f"expected verdict DEFICIENT, got {responded['adequacy_verdict']!r}"
    )

    response = api_client.close_inquiry(inquiry["id"], REGULATOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_RESPONSE_INADEQUATE.value, 422)
    refreshed = fetch_inquiry(inquiry["id"], ctx["broker_headers"])
    assert refreshed["status"] == "RESPONDED", (
        f"a refused close leaves the inquiry RESPONDED, got {refreshed['status']!r}"
    )
    closed_events = list_audit_events(
        ctx["broker_id"], ctx["broker_headers"], event_type="INQUIRY_CLOSED"
    )
    assert closed_events == [], (
        f"a refused close appends no INQUIRY_CLOSED event, got {closed_events!r}"
    )
