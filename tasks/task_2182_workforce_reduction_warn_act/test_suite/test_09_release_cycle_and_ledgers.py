"""Issuing, signing and revoking the release, and both plan ledgers."""

from test_helpers import (
    ALICE,
    BEN_CLASS_B,
    CARLA,
    TEST_USERS,
    ApiErrorId,
    issue_offer,
    make_separating_employee_headers,
    price_offer,
    read_employee,
    read_offer,
    read_plan,
    revoke_offer,
    set_clock,
    setup_issued_offer_scenario,
    setup_offer_ready_scenario,
    setup_priced_offer_scenario,
    sign_offer,
    validate_error,
)

BENEFITS = TEST_USERS["benefits_headers"]


class TestOfferCycleClosesBackToIssued:
    """ISSUED -> SIGNED -> REVOKED -> ISSUED is a legitimate loop."""

    def test_the_first_pass_issues_signs_and_revokes(self, api):
        """PRD 3.9: "Issuance stamps `issued_utc` from the logical clock, sets
        `consideration_days_applied`, derives `consideration_deadline_utc`,
        increments `issue_count` by 1, adds the offer's
        `total_separation_cost_cents` to the plan's `severance_reserve_cents`, and
        increments the offer's `version` by 1."
        PRD 3.9: "The revocation window is likewise age-driven: for an employee
        aged 40 or over the deadline is `signed_utc` plus 7 days, the statutory
        seven-day revocation right; for an employee under 40 it is `signed_utc`
        itself, leaving no revocation window at all."

        Design: Difficulty/non_linear_state_machine/severance_offer_issue_sign_revoke_reissue_cycle_closes
        """
        scn = setup_priced_offer_scenario()
        offer_id = scn["offer"]["id"]
        employee_id = scn["employees"][0]["id"]

        issued = issue_offer(offer_id)
        assert issued["status"] == "ISSUED"
        assert issued["issue_count"] == 1
        assert issued["consideration_deadline_utc"] == "2026-08-22T00:00:00.000Z"

        signed = sign_offer(offer_id, employee_id)
        assert signed["status"] == "SIGNED"
        assert signed["revocation_deadline_utc"] == "2026-08-08T00:00:00.000Z"

        set_clock("2026-08-05T00:00:00.000Z")
        revoked = revoke_offer(offer_id, employee_id, "Reconsidered the release.")
        assert revoked["status"] == "REVOKED"

    def test_the_second_pass_reissues_with_a_freshly_stamped_deadline(self, api):
        """PRD 3.9: "Issuance is admissible from `DRAFT` and — this is the cycle
        that makes the domain interesting — again from `REVOKED`, so the sequence
        `ISSUED → SIGNED → REVOKED → ISSUED` is a legitimate loop."
        PRD 3.9: "A re-issuance from `REVOKED` re-stamps `issued_utc` and
        recomputes `consideration_deadline_utc` from that fresh issuance rather
        than carrying the old deadline forward."
        PRD 3.9: "`severance_reserve_cents` is the sum of
        `total_separation_cost_cents` across the plan's offers whose `status` is
        `ISSUED`, `SIGNED` or `EFFECTIVE`; offers sitting in `DRAFT`, `REVOKED` or
        `EXPIRED` contribute nothing."

        Design: Difficulty/non_linear_state_machine/severance_offer_issue_sign_revoke_reissue_cycle_closes
        """
        scn = setup_priced_offer_scenario()
        offer_id = scn["offer"]["id"]
        employee_id = scn["employees"][0]["id"]

        issue_offer(offer_id)
        sign_offer(offer_id, employee_id)
        set_clock("2026-08-05T00:00:00.000Z")
        revoke_offer(offer_id, employee_id, "Reconsidered the release.")
        set_clock("2026-08-07T00:00:00.000Z")

        reissued = issue_offer(offer_id)
        assert reissued["status"] == "ISSUED"
        assert reissued["issue_count"] == 2
        assert reissued["consideration_deadline_utc"] == "2026-08-28T00:00:00.000Z"
        assert reissued["consideration_days_applied"] == 21
        assert reissued["total_separation_cost_cents"] == 3553428

        plan = read_plan(scn["plan"]["id"])
        assert plan["severance_reserve_cents"] == 3553428
        assert plan["benefit_liability_cents"] == 0
        assert (
            read_employee(employee_id)["benefit_continuation_status"] == "TERMINATED"
        )


class TestStateCheckOutranksTheBudgetCheck:
    """One request breaches both rule 9 and rule 34; rule 9 decides."""

    @staticmethod
    def _scenario():
        return setup_issued_offer_scenario(budget=4000000)

    def test_reissuing_an_issued_offer_answers_the_state_error(self, api):
        """PRD 3.9: "Attempting to issue from any other status is refused with
        `ERR_INVALID_OFFER_STATE`."
        PRD 2.6: "When a request violates more than one rule, exactly one error
        is returned, and it is always the violation with the lowest priority
        number in the ladder below. This ordering is normative: a test that
        supplies a request breaching both rule 12 and rule 23 must receive rule
        12's error identifier."
        PRD 2.6: "Severance budget headroom — `ERR_SEVERANCE_BUDGET_EXCEEDED`
        (422) on `POST /severance-offers/{id}/issue`."

        Design: Difficulty/priority_pair_validation_conflict/state_check_beats_budget_check_when_reissuing_an_already_issued_offer
        """
        scn = self._scenario()

        response = api.issue_severance_offer(scn["offer"]["id"], BENEFITS)
        error = validate_error(response, ApiErrorId.ERR_INVALID_OFFER_STATE.value)
        assert response.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_SEVERANCE_BUDGET_EXCEEDED.value

    def test_the_refused_reissue_moves_neither_the_offer_nor_the_ledger(self, api):
        """PRD 3.9: "Every issuance requires that the underlying selection is
        still `SELECTED`, that the offer's `issue_count` is below 3, and that the
        plan has budget headroom: the plan's `severance_reserve_cents` plus this
        offer's `total_separation_cost_cents` must be no greater than its
        `severance_budget_cents`."
        PRD 3.9: "`severance_reserve_cents` is the sum of
        `total_separation_cost_cents` across the plan's offers whose `status` is
        `ISSUED`, `SIGNED` or `EFFECTIVE`; offers sitting in `DRAFT`, `REVOKED` or
        `EXPIRED` contribute nothing."

        Design: Difficulty/priority_pair_validation_conflict/state_check_beats_budget_check_when_reissuing_an_already_issued_offer
        """
        scn = self._scenario()

        api.issue_severance_offer(scn["offer"]["id"], BENEFITS)

        offer = read_offer(scn["offer"]["id"])
        assert offer["issue_count"] == 1
        assert offer["status"] == "ISSUED"
        assert read_plan(scn["plan"]["id"])["severance_reserve_cents"] == 3553428


class TestOfferWindowIsClosedPlusAOneDayCooldown:
    """The blocking interval runs through the end instant plus one day."""

    @staticmethod
    def _revoked_offer():
        scn = setup_priced_offer_scenario()
        offer_id = scn["offer"]["id"]
        employee_id = scn["employees"][0]["id"]
        issue_offer(offer_id)
        sign_offer(offer_id, employee_id)
        set_clock("2026-08-05T00:00:00.000Z")
        scn["offer"] = revoke_offer(offer_id, employee_id, "Reconsidered the release.")
        return scn

    def test_reissue_exactly_one_day_after_the_window_end_is_refused(self, api):
        """PRD 3.9: "concretely, the request is refused with
        `ERR_OFFER_WINDOW_CONFLICT` while the logical clock stands at or before
        that other offer's `blocking_window_end_utc` plus one day."
        PRD 3.9: "The `blocking_window_end_utc` follows the offer's own status:
        it is `consideration_deadline_utc` while the offer is `ISSUED`,
        `revocation_deadline_utc` while it is `SIGNED`, `revoked_utc` once it is
        `REVOKED`, `consideration_deadline_utc` once it is `EXPIRED`, and null
        while it is `DRAFT` or `EFFECTIVE`."
        PRD 3.9: "Re-issuing after a revocation carries one extra condition: the
        logical clock must have advanced strictly past the offer's
        `blocking_window_end_utc` plus one day."

        Design: Difficulty/resource_temporal_overlap/offer_window_on_employee_is_closed_plus_a_one_day_cooldown
        """
        scn = self._revoked_offer()
        assert scn["offer"]["blocking_window_end_utc"] == "2026-08-05T00:00:00.000Z"

        set_clock("2026-08-06T00:00:00.000Z")
        response = api.issue_severance_offer(scn["offer"]["id"], BENEFITS)
        validate_error(response, ApiErrorId.ERR_OFFER_WINDOW_CONFLICT.value)
        assert response.status_code == 409

    def test_reissue_the_day_after_the_cooldown_is_admitted(self, api):
        """PRD 3.9: "Re-issuing after a revocation carries one extra condition:
        the logical clock must have advanced strictly past the offer's
        `blocking_window_end_utc` plus one day."
        PRD 3.9: "Issuance stamps `issued_utc` from the logical clock, sets
        `consideration_days_applied`, derives `consideration_deadline_utc`,
        increments `issue_count` by 1, adds the offer's
        `total_separation_cost_cents` to the plan's `severance_reserve_cents`, and
        increments the offer's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/offer_window_on_employee_is_closed_plus_a_one_day_cooldown
        """
        scn = self._revoked_offer()

        set_clock("2026-08-06T00:00:00.000Z")
        api.issue_severance_offer(scn["offer"]["id"], BENEFITS)

        set_clock("2026-08-07T00:00:00.000Z")
        reissued = issue_offer(scn["offer"]["id"])
        assert reissued["status"] == "ISSUED"
        assert reissued["issue_count"] == 2
        assert reissued["issued_utc"] == "2026-08-07T00:00:00.000Z"
        assert reissued["consideration_deadline_utc"] == "2026-08-28T00:00:00.000Z"
        assert read_plan(scn["plan"]["id"])["severance_reserve_cents"] == 3553428


class TestBothLedgersRoundTripToZero:
    """Issue, sign, revoke must restore the world to the cent."""

    def test_the_reserve_returns_to_its_pre_issue_value(self, api):
        """PRD 2.9: "Likewise, issuing an offer, having it signed and then having
        it revoked must leave the plan's `severance_reserve_cents` at exactly its
        pre-issue value and its `benefit_liability_cents` at exactly its
        pre-signature value. Drift of any size is a defect."
        PRD 3.9: "`severance_reserve_cents` is the sum of
        `total_separation_cost_cents` across the plan's offers whose `status` is
        `ISSUED`, `SIGNED` or `EFFECTIVE`; offers sitting in `DRAFT`, `REVOKED` or
        `EXPIRED` contribute nothing."

        Design: Difficulty/compensating_invariant/plan_severance_reserve_returns_to_zero_after_issue_sign_revoke
        """
        scn = setup_priced_offer_scenario()
        offer_id = scn["offer"]["id"]
        employee_id = scn["employees"][0]["id"]

        before = read_plan(scn["plan"]["id"])
        assert before["severance_reserve_cents"] == 0
        assert before["benefit_liability_cents"] == 0

        issue_offer(offer_id)
        assert read_plan(scn["plan"]["id"])["severance_reserve_cents"] == 3553428

        sign_offer(offer_id, employee_id)
        assert read_plan(scn["plan"]["id"])["severance_reserve_cents"] == 3553428

        set_clock("2026-08-05T00:00:00.000Z")
        revoke_offer(offer_id, employee_id, "Exercised the seven-day revocation right.")

        after = read_plan(scn["plan"]["id"])
        assert after["severance_reserve_cents"] == 0
        assert after["severance_reserve_cents"] == before["severance_reserve_cents"]
        assert read_offer(offer_id)["total_separation_cost_cents"] == 3553428

    def test_the_liability_and_the_employee_record_unwind_exactly(self, api):
        """PRD 3.9: "The second hop reaches the plan: because that employee's
        benefit continuation became active, the employee's
        `benefit_subsidy_cents` is added to the plan's `benefit_liability_cents`."
        PRD 3.9: "The employee's `release_signed` returns to false, their
        `benefit_continuation_status` moves `ACTIVE → TERMINATED`, their
        `benefit_subsidy_months` and `benefit_subsidy_cents` reset to 0 and their
        `outplacement_tier` to `NONE`; the plan's `benefit_liability_cents` has
        exactly the subsidy the signature added subtracted back out; and the
        plan's `severance_reserve_cents` has the offer's
        `total_separation_cost_cents` subtracted back out."

        Design: Difficulty/compensating_invariant/plan_severance_reserve_returns_to_zero_after_issue_sign_revoke
        """
        scn = setup_priced_offer_scenario()
        offer_id = scn["offer"]["id"]
        employee_id = scn["employees"][0]["id"]

        issue_offer(offer_id)
        sign_offer(offer_id, employee_id)
        assert read_plan(scn["plan"]["id"])["benefit_liability_cents"] == 526500

        set_clock("2026-08-05T00:00:00.000Z")
        revoked = revoke_offer(
            offer_id, employee_id, "Exercised the seven-day revocation right."
        )
        assert revoked["status"] == "REVOKED"

        assert read_plan(scn["plan"]["id"])["benefit_liability_cents"] == 0
        employee = read_employee(employee_id)
        assert employee["release_signed"] is False
        assert employee["benefit_continuation_status"] == "TERMINATED"
        assert employee["benefit_subsidy_cents"] == 0
        assert employee["outplacement_tier"] == "NONE"


def test_issuance_beyond_the_budget_ceiling_is_refused(api):
    """PRD 3.9: "Every issuance requires that the underlying selection is still
    `SELECTED`, that the offer's `issue_count` is below 3, and that the plan has
    budget headroom: the plan's `severance_reserve_cents` plus this offer's
    `total_separation_cost_cents` must be no greater than its
    `severance_budget_cents`. A fourth issuance is refused with
    `ERR_OFFER_REISSUE_LIMIT`, and an issuance that would push the reserve past
    the ceiling is refused with `ERR_SEVERANCE_BUDGET_EXCEEDED`."
    PRD 3.8: "The offer is persisted with `status` of `DRAFT`, an `issue_count`
    of 0, and `issued_utc`, `signed_utc`, `revoked_utc`,
    `consideration_deadline_utc`, `revocation_deadline_utc` and
    `blocking_window_end_utc` all null."

    Design: Corner/errors/error_severance_budget_exceeded_on_the_first_issuance
    """
    scn = setup_priced_offer_scenario(budget=3000000)
    assert scn["offer"]["total_separation_cost_cents"] == 3553428

    response = api.issue_severance_offer(scn["offer"]["id"], BENEFITS)
    validate_error(response, ApiErrorId.ERR_SEVERANCE_BUDGET_EXCEEDED.value)
    assert response.status_code == 422

    offer = read_offer(scn["offer"]["id"])
    assert offer["status"] == "DRAFT"
    assert offer["issue_count"] == 0
    assert offer["issued_utc"] is None
    assert read_plan(scn["plan"]["id"])["severance_reserve_cents"] == 0


def test_only_the_offer_recipient_may_sign(api):
    """PRD 2.1: "concretely, signing or revoking a severance offer requires that
    `X-User-ID` equal the `employee_id` of the `Selection` that offer was priced
    for, and a mismatch is rejected with `ERR_NOT_OFFER_RECIPIENT` (HTTP 403)."
    PRD 3.9: "Signing is the separating employee's act, and only theirs:
    `X-User-ID` must equal the `employee_id` of the offer's selection."

    Design: Corner/errors/error_offer_signed_by_an_employee_who_is_not_the_recipient
    """
    scn = setup_issued_offer_scenario(people=(ALICE, BEN_CLASS_B))
    intruder_id = scn["employees"][1]["id"]

    response = api.sign_severance_offer(
        scn["offer"]["id"], make_separating_employee_headers(intruder_id)
    )
    validate_error(response, ApiErrorId.ERR_NOT_OFFER_RECIPIENT.value)
    assert response.status_code == 403

    offer = read_offer(scn["offer"]["id"])
    assert offer["status"] == "ISSUED"
    assert offer["signed_utc"] is None
    assert read_employee(scn["employees"][0]["id"])["release_signed"] is False
    assert read_employee(intruder_id)["release_signed"] is False
    assert read_plan(scn["plan"]["id"])["benefit_liability_cents"] == 0


def test_expired_consideration_and_closed_revocation_windows(api):
    """PRD 3.9: "A sign attempt made after that deadline fails with
    `ERR_CONSIDERATION_PERIOD_EXPIRED` and leaves the offer in `EXPIRED` — the
    attempt is rejected but the offer's own lifecycle has ended, its
    `total_separation_cost_cents` is subtracted back out of the plan's
    `severance_reserve_cents`, and its `version` increments by 1."
    PRD 3.9: "Revoking is also the separating employee's act alone, is
    admissible only from `SIGNED`, and only while the logical clock stands at or
    before `revocation_deadline_utc`; a later attempt is refused with
    `ERR_REVOCATION_WINDOW_CLOSED`."

    Design: Corner/errors/error_consideration_period_expires_and_revocation_window_closes
    """
    scn = setup_offer_ready_scenario(
        people=(ALICE, CARLA),
        select_indexes=(0, 1),
        propose_only_indexes=(),
        via_batch=True,
        notify_indexes=(0, 1),
    )
    alice_id = scn["employees"][0]["id"]
    carla_id = scn["employees"][1]["id"]

    alice_offer = price_offer(scn["selection_by_index"][0]["id"], "STANDARD")
    carla_offer = price_offer(scn["selection_by_index"][1]["id"], "STANDARD")

    issued_alice = issue_offer(alice_offer["id"])
    assert issued_alice["consideration_deadline_utc"] == "2026-09-15T00:00:00.000Z"
    issue_offer(carla_offer["id"])
    signed_carla = sign_offer(carla_offer["id"], carla_id)
    assert signed_carla["revocation_deadline_utc"] == "2026-08-08T00:00:00.000Z"

    set_clock("2026-09-16T00:00:00.000Z")

    expired = api.sign_severance_offer(
        alice_offer["id"], make_separating_employee_headers(alice_id)
    )
    validate_error(expired, ApiErrorId.ERR_CONSIDERATION_PERIOD_EXPIRED.value)
    assert expired.status_code == 422

    closed = api.revoke_severance_offer(
        carla_offer["id"],
        {"revocation_reason": "Changed my mind."},
        make_separating_employee_headers(carla_id),
    )
    validate_error(closed, ApiErrorId.ERR_REVOCATION_WINDOW_CLOSED.value)
    assert closed.status_code == 422

    assert read_offer(alice_offer["id"])["status"] == "EXPIRED"
    carla_final = read_offer(carla_offer["id"])
    assert carla_final["status"] == "SIGNED"
    assert carla_final["total_separation_cost_cents"] == 2241000

    plan = read_plan(scn["plan"]["id"])
    assert plan["severance_reserve_cents"] == 2241000
    assert plan["benefit_liability_cents"] == 351000
    assert read_employee(carla_id)["benefit_continuation_status"] == "ACTIVE"


def test_the_fourth_issuance_hits_the_reissue_cap(api):
    """PRD 3.9: "Every issuance requires that the underlying selection is still
    `SELECTED`, that the offer's `issue_count` is below 3, and that the plan has
    budget headroom: the plan's `severance_reserve_cents` plus this offer's
    `total_separation_cost_cents` must be no greater than its
    `severance_budget_cents`. A fourth issuance is refused with
    `ERR_OFFER_REISSUE_LIMIT`, and an issuance that would push the reserve past
    the ceiling is refused with `ERR_SEVERANCE_BUDGET_EXCEEDED`."

    Design: Corner/errors/error_offer_reissue_limit_on_the_fourth_issuance
    """
    scn = setup_priced_offer_scenario()
    offer_id = scn["offer"]["id"]
    employee_id = scn["employees"][0]["id"]

    issue_offer(offer_id)
    sign_offer(offer_id, employee_id)
    set_clock("2026-08-05T00:00:00.000Z")
    revoke_offer(offer_id, employee_id, "First revocation.")

    set_clock("2026-08-07T00:00:00.000Z")
    issue_offer(offer_id)
    sign_offer(offer_id, employee_id)
    set_clock("2026-08-10T00:00:00.000Z")
    revoke_offer(offer_id, employee_id, "Second revocation.")

    set_clock("2026-08-12T00:00:00.000Z")
    third = issue_offer(offer_id)
    assert third["issue_count"] == 3
    sign_offer(offer_id, employee_id)
    set_clock("2026-08-15T00:00:00.000Z")
    revoke_offer(offer_id, employee_id, "Third revocation.")

    set_clock("2026-08-17T00:00:00.000Z")
    response = api.issue_severance_offer(offer_id, BENEFITS)
    validate_error(response, ApiErrorId.ERR_OFFER_REISSUE_LIMIT.value)
    assert response.status_code == 422

    offer = read_offer(offer_id)
    assert offer["status"] == "REVOKED"
    assert offer["issue_count"] == 3
    assert offer["revoked_utc"] == "2026-08-15T00:00:00.000Z"

    plan = read_plan(scn["plan"]["id"])
    assert plan["severance_reserve_cents"] == 0
    assert plan["benefit_liability_cents"] == 0
