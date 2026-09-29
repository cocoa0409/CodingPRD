"""Provider assignments, the five-step fund waterfall and fiscal conservation.

Every test in this module translates exactly one instance of the difficulty or
corner design index; the trailing `Design:` line of each docstring names it.
"""

from test_helpers import (
    CANON_AUTHORIZED_AMOUNT_CENTS,
    CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT,
    CANON_BASE_COST_CENTS,
    CANON_BUDGET_CODE,
    CANON_COVERED_TOTAL_MINUTES,
    CANON_INDIRECT_COST_CENTS,
    CANON_SESSION_END,
    CANON_TOTAL_CHARGE_CENTS,
    ApiErrorId,
    assert_allocation_available_identity,
    assert_assignment,
    assert_pagination_meta,
    factories,
    fixtures,
    make_program_coordinator_headers,
    make_sped_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PC = make_program_coordinator_headers()
DIR = make_sped_director_headers()

LOCAL_ALLOCATION = {
    "fund_source": "LOCAL_GENERAL",
    "budget_code": "LOC-ESY-01",
    "authorized_amount_cents": 10000000,
}


def _assignment_count(api, commitment_id: str) -> int:
    _rows, meta = validate_paginated(
        api.list_provider_assignments_for_commitment(commitment_id, PC, {"limit": 100})
    )
    return meta["total_count"]


class TestFundWaterfallSelection:
    """Step two selects on base cost alone; step four never re-selects."""

    def test_the_indirect_overage_kills_the_request_without_re_selecting(self, api):
        """The federal bucket wins on base cost, then cannot absorb the indirect.

        The program carries an `IDEA_611_FEDERAL` allocation authorized at 210000
        cents and a `LOCAL_GENERAL` allocation authorized at 10000000 cents. The
        base cost of 206100 fits the federal bucket, and "Candidates are ordered
        by funding priority — `IDEA_611_FEDERAL` first, `IDEA_619_FEDERAL`
        second, `LOCAL_GENERAL` third — with `created_at` ascending as the only
        tie-break among allocations sharing a `fund_source`.", so "The selected
        allocation is the **first** candidate in that order whose
        `available_cents` is greater than or equal to `base_cost_cents`." picks
        the federal one. Adding the eight-percent indirect of 16488 takes the
        total to 222588, above that bucket's 210000, and "If `total_charge_cents`
        is greater than the selected allocation's `available_cents`, the request
        fails with `ERR_FUND_INDIRECT_OVERAGE`." The local bucket could have paid
        for the whole charge, which is exactly the outcome the PRD forbids:
        "Step two is not re-run: the request fails even in the case where a
        lower-priority `OPEN` allocation could comfortably have absorbed the
        whole of `total_charge_cents`."

        Design: Difficulty/combinatorial_formula/fund_waterfall_selection_pinned_on_base_cost_then_indirect_overage
        """
        context = fixtures.setup_baseline(
            api,
            allocation_overrides={"authorized_amount_cents": 210000},
            extra_allocations=[LOCAL_ALLOCATION],
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        federal, local = context["allocations"][0], context["allocations"][1]

        response = api.create_provider_assignment(
            factories.assignment_payload(
                commitment["id"], context["provider"]["id"], commitment["version"]
            ),
            PC,
        )
        validate_error(response, ApiErrorId.FUND_INDIRECT_OVERAGE, 422)

        federal_after = fixtures.refresh_allocation(
            api, context["program"]["id"], federal["id"]
        )
        local_after = fixtures.refresh_allocation(
            api, context["program"]["id"], local["id"]
        )
        assert federal_after["encumbered_amount_cents"] == 0
        assert federal_after["available_cents"] == 210000
        assert local_after["encumbered_amount_cents"] == 0
        assert local_after["available_cents"] == 10000000
        assert_allocation_available_identity(federal_after)
        assert_allocation_available_identity(local_after)

        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "PLANNED"
        assert commitment_after["version"] == commitment["version"]
        assert (
            fixtures.refresh_provider(api, context["provider"]["id"])[
                "assigned_weekly_minutes"
            ]
            == 0
        )
        assert _assignment_count(api, commitment["id"]) == 0

    def test_an_underfunded_federal_bucket_is_skipped_and_the_local_rate_applies(
        self, api
    ):
        """Selection walks past a federal bucket too small for the base cost.

        The federal allocation is authorized at 100000 cents, below the base cost
        of 206100, so it is not the first candidate that qualifies: "The selected
        allocation is the **first** candidate in that order whose
        `available_cents` is greater than or equal to `base_cost_cents`." The
        `LOCAL_GENERAL` bucket is selected instead, and the indirect rate follows
        the winner rather than the priority order, because
        "`indirect_cost_cents` is `base_cost_cents` multiplied by the
        indirect-cost rate of the *selected* allocation's `fund_source`, rounded
        half up to a whole cent." and "Both federal streams carry an
        eight-percent indirect rate; `LOCAL_GENERAL` carries fourteen and a half
        percent." Fourteen and a half percent of 206100 is 29884.5, which rounds
        half up to 29885, so the total is 235985 posted against the local code.

        Design: Difficulty/combinatorial_formula/fund_waterfall_selection_pinned_on_base_cost_then_indirect_overage
        """
        context = fixtures.setup_baseline(
            api,
            allocation_overrides={"authorized_amount_cents": 100000},
            extra_allocations=[LOCAL_ALLOCATION],
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        federal, local = context["allocations"][0], context["allocations"][1]

        assignment = validate_success(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], context["provider"]["id"], commitment["version"]
                ),
                PC,
            ),
            201,
        )
        assert_assignment(assignment)
        assert assignment["covered_total_minutes"] == CANON_COVERED_TOTAL_MINUTES
        assert assignment["base_cost_cents"] == CANON_BASE_COST_CENTS
        assert assignment["indirect_cost_cents"] == 29885
        assert assignment["total_charge_cents"] == 235985
        assert assignment["charged_fund_source"] == "LOCAL_GENERAL"
        assert assignment["charged_budget_code"] == "LOC-ESY-01"
        assert assignment["status"] == "ACTIVE"

        federal_after = fixtures.refresh_allocation(
            api, context["program"]["id"], federal["id"]
        )
        local_after = fixtures.refresh_allocation(
            api, context["program"]["id"], local["id"]
        )
        assert federal_after["encumbered_amount_cents"] == 0
        assert federal_after["available_cents"] == 100000
        assert local_after["encumbered_amount_cents"] == 235985
        assert local_after["available_cents"] == 10000000 - 235985
        assert_allocation_available_identity(local_after)


class TestStateBeatsFiscal:
    """Check 9 masks checks 33 and 34 on a doubly-invalid assignment create."""

    def test_an_active_commitment_reports_the_state_error_over_the_frozen_fund(
        self, api
    ):
        """Both gates fail at once and only the earlier one is reported.

        The commitment is `ACTIVE`, so no assignment-create transition exists —
        "The target commitment must currently be in `PLANNED` or `ASSIGNED`, and
        the chosen `weekday` must be a member of the program's
        `instructional_weekdays` — staffing a Friday block on a
        Monday-through-Thursday program is meaningless." — and the program's only
        allocation is `FROZEN`, so the waterfall has no candidate either:
        "At least one fund allocation of the program is `OPEN` — otherwise
        `ERR_FUND_FROZEN`." Because "The order below is normative; a check
        numbered lower always masks a check numbered higher.", the state check
        wins: "The target resource is in a state from which the requested
        transition exists, including the cross-entity state guards — otherwise
        `ERR_INVALID_STATE`." Thawing the fund leaves the state violation alone,
        which pins the state axis independently.

        Design: Difficulty/priority_pair_validation_conflict/assignment_invalid_commitment_state_beats_frozen_fund
        """
        context = fixtures.setup_baseline(api, with_canonical_logs=False)
        commitment = context["commitment"]
        allocation = context["allocation"]
        assert commitment["status"] == "ACTIVE"
        second_provider = fixtures.register_provider(api, full_name="Omar Diaz")

        validate_success(
            api.patch_fund_allocation(allocation["id"], {"status": "FROZEN"}, DIR)
        )
        payload = factories.assignment_payload(
            commitment["id"],
            second_provider["id"],
            commitment["version"],
            weekday="TUE",
        )
        validate_error(
            api.create_provider_assignment(payload, PC),
            ApiErrorId.INVALID_STATE,
            409,
        )

        validate_success(
            api.patch_fund_allocation(allocation["id"], {"status": "OPEN"}, DIR)
        )
        validate_error(
            api.create_provider_assignment(payload, PC),
            ApiErrorId.INVALID_STATE,
            409,
        )

        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "ACTIVE"
        assert commitment_after["version"] == commitment["version"]
        assert (
            fixtures.refresh_provider(api, second_provider["id"])[
                "assigned_weekly_minutes"
            ]
            == 0
        )
        allocation_after = fixtures.refresh_allocation(
            api, context["program"]["id"], allocation["id"]
        )
        assert allocation_after["encumbered_amount_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert _assignment_count(api, commitment["id"]) == 1

    def test_the_fiscal_only_control_reports_the_frozen_fund(self, api):
        """With the state gate satisfied the frozen-fund error surfaces alone.

        The commitment is still `PLANNED`, so check 9 has nothing to say, and the
        program's single allocation has been moved out of the candidate set:
        "The candidate set is every `FundAllocation` belonging to the charged
        program whose `status` reads `OPEN`; `FROZEN` and `CLOSED` allocations
        never enter the candidate set." The waterfall therefore stops at
        "If the program has fund allocations but not one of them is `OPEN`, the
        request fails with `ERR_FUND_FROZEN`; if `OPEN` allocations exist but
        none of them has enough `available_cents` to cover `base_cost_cents`, the
        request fails with `ERR_NO_FUND_WITH_CAPACITY`." and nothing is
        encumbered.

        Design: Difficulty/priority_pair_validation_conflict/assignment_invalid_commitment_state_beats_frozen_fund
        """
        context = fixtures.setup_baseline(
            api,
            allocation_overrides={
                "fund_source": "LOCAL_GENERAL",
                "budget_code": "LOC-ESY-02",
            },
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        allocation = context["allocation"]
        validate_success(
            api.patch_fund_allocation(allocation["id"], {"status": "FROZEN"}, DIR)
        )

        validate_error(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], context["provider"]["id"], commitment["version"]
                ),
                PC,
            ),
            ApiErrorId.FUND_FROZEN,
            409,
        )

        allocation_after = fixtures.refresh_allocation(
            api, context["program"]["id"], allocation["id"]
        )
        assert allocation_after["encumbered_amount_cents"] == 0
        assert allocation_after["available_cents"] == CANON_AUTHORIZED_AMOUNT_CENTS
        assert fixtures.refresh_commitment(api, commitment["id"])["status"] == "PLANNED"
        assert _assignment_count(api, commitment["id"]) == 0


class TestCredentialBeatsRoleMismatch:
    """Check 12 masks check 14, and the credential boundary is inclusive."""

    def test_an_expired_slp_reports_the_credential_before_the_role_mismatch(self, api):
        """Three providers separate the safety axis from the referential axis.

        An `SLP` whose credential lapses on 2027-07-01 assigned to a
        `SPECIALIZED_INSTRUCTION` commitment running to 2027-07-23 violates
        "The provider's `credential_expires_on` falls on or after the last date
        the work covers — otherwise `ERR_PROVIDER_CREDENTIAL_EXPIRED`." and
        "The provider's `role_type` must be permitted for the commitment's
        `service_type`: `SPECIALIZED_INSTRUCTION` accepts a `SPED_TEACHER` or a
        `PARAEDUCATOR`, `SPEECH` accepts only an `SLP`, `OT` accepts only an
        `OT`, `PT` accepts only a `PT`, and `COUNSELING` accepts only a
        `COUNSELOR`; anything else draws `ERR_PROVIDER_ROLE_MISMATCH`." at the
        same time, and the PRD says which one wins: "An expired speech-language
        pathologist assigned to a `SPECIALIZED_INSTRUCTION` commitment violates
        both the credential check and the role-match check; the credential check
        is earlier, so `ERR_PROVIDER_CREDENTIAL_EXPIRED` is returned." A
        valid-credential `SLP` isolates the role axis and an expired
        `SPED_TEACHER` isolates the credential axis.

        Design: Difficulty/priority_pair_validation_conflict/assignment_expired_credential_beats_role_mismatch
        """
        context = fixtures.setup_baseline(
            api,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        slp_expired = fixtures.register_provider(
            api,
            full_name="Owen Vale",
            role_type="SLP",
            credential_expires_on="2027-07-01",
        )
        slp_valid = fixtures.register_provider(
            api,
            full_name="Iris Mane",
            role_type="SLP",
            credential_expires_on="2028-06-30",
        )
        teacher_expired = fixtures.register_provider(
            api,
            full_name="Hal Brix",
            role_type="SPED_TEACHER",
            credential_expires_on="2027-07-01",
        )

        def attempt(provider_id):
            return api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], provider_id, commitment["version"]
                ),
                PC,
            )

        validate_error(
            attempt(slp_expired["id"]),
            ApiErrorId.PROVIDER_CREDENTIAL_EXPIRED,
            422,
        )
        validate_error(
            attempt(slp_valid["id"]), ApiErrorId.PROVIDER_ROLE_MISMATCH, 422
        )
        validate_error(
            attempt(teacher_expired["id"]),
            ApiErrorId.PROVIDER_CREDENTIAL_EXPIRED,
            422,
        )

        for provider in (slp_expired, slp_valid, teacher_expired):
            assert (
                fixtures.refresh_provider(api, provider["id"])[
                    "assigned_weekly_minutes"
                ]
                == 0
            )
        assert _assignment_count(api, commitment["id"]) == 0
        assert fixtures.refresh_commitment(api, commitment["id"])["status"] == "PLANNED"

    def test_a_credential_lapsing_on_the_last_covered_date_is_accepted(self, api):
        """The credential boundary is inclusive at `effective_to` itself.

        The provider's `credential_expires_on` is exactly the assignment's
        `effective_to` of 2027-07-23, which satisfies "The provider's
        `credential_expires_on` must fall on or after the assignment's
        `effective_to`, or the request draws `ERR_PROVIDER_CREDENTIAL_EXPIRED`."
        because a `credential_expires_on` is "a `credential_expires_on` date
        naming the last day the credential is valid inclusive". The create
        therefore prices and posts normally, and "If the commitment was in
        `PLANNED`, it advances to `ASSIGNED`."

        Design: Difficulty/priority_pair_validation_conflict/assignment_expired_credential_beats_role_mismatch
        """
        context = fixtures.setup_baseline(
            api,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        edge_provider = fixtures.register_provider(
            api, full_name="Rosa Kim", credential_expires_on=CANON_SESSION_END
        )

        assignment = validate_success(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], edge_provider["id"], commitment["version"]
                ),
                PC,
            ),
            201,
        )
        assert assignment["status"] == "ACTIVE"
        assert assignment["total_charge_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert assignment["charged_fund_source"] == "IDEA_611_FEDERAL"
        assert assignment["charged_budget_code"] == CANON_BUDGET_CODE

        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "ASSIGNED"
        assert commitment_after["version"] == commitment["version"] + 1
        assert (
            fixtures.refresh_provider(api, edge_provider["id"])[
                "assigned_weekly_minutes"
            ]
            == 229
        )
        assert _assignment_count(api, commitment["id"]) == 1


def _timetable_setup(api):
    """One provider, one funded PLANNING program and three PLANNED commitments."""
    fixtures.set_clock(api)
    program = fixtures.create_program(api)
    fixtures.authorize_allocation(api, program["id"])
    provider = fixtures.register_provider(api)
    commitments = []
    for index in (1, 2, 3):
        student = fixtures.make_eligible_student(
            api, student_overrides={"student_number": f"S-2841-00{index}"}
        )["student"]
        commitments.append(
            fixtures.create_commitment(api, program["id"], student["id"])
        )
    return program, provider, commitments


class TestProviderWeeklyTimetable:
    """Half-open clock windows, gated by inclusive date-range intersection."""

    def test_a_touching_endpoint_is_compatible_while_a_straddle_collides(self, api):
        """09:00-10:00 and 10:00-11:00 coexist; 09:45-10:15 does not.

        The PRD fixes the interval semantics: "Provider windows are
        **half-open**: the occupied interval runs from `start_time` up to but not
        including `end_time`." and "Two `ACTIVE` assignments of the same provider
        on the same `weekday` therefore collide only when the new block's start is
        strictly before the existing block's end **and** the existing block's
        start is strictly before the new block's end — so a 09:00-to-10:00 block
        and a 10:00-to-11:00 block do not collide, because touching endpoints are
        fine for a therapist walking between rooms." A third block from 09:45 to
        10:15 straddles both incumbents on intersecting dates, so
        "Only when both the time windows and the date ranges intersect is the
        request rejected with `ERR_PROVIDER_TIME_CONFLICT`." bites. Each accepted
        block is priced over the three ISO weeks its 2027-06-14 to 2027-06-30
        range touches, since "`covered_total_minutes` is the requested
        `covered_weekly_minutes` multiplied by the number of distinct ISO weeks in
        the inclusive range from `effective_from` to `effective_to` that contain
        at least one instructional date of the program."

        Design: Difficulty/resource_temporal_overlap/provider_weekly_slots_use_half_open_intervals_and_date_intersection
        """
        _program, provider, commitments = _timetable_setup(api)

        def book(commitment, start, end, effective_from="2027-06-14", effective_to="2027-06-30"):
            return api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"],
                    provider["id"],
                    commitment["version"],
                    weekday="MON",
                    start_time=start,
                    end_time=end,
                    effective_from=effective_from,
                    effective_to=effective_to,
                ),
                PC,
            )

        first = validate_success(book(commitments[0], "09:00", "10:00"), 201)
        assert first["status"] == "ACTIVE"
        assert first["covered_total_minutes"] == 687
        assert first["base_cost_cents"] == 103050
        assert first["indirect_cost_cents"] == 8244
        assert first["total_charge_cents"] == 111294

        second = validate_success(book(commitments[1], "10:00", "11:00"), 201)
        assert second["status"] == "ACTIVE"

        validate_error(
            book(commitments[2], "09:45", "10:15"),
            ApiErrorId.PROVIDER_TIME_CONFLICT,
            409,
        )

        third_after = fixtures.refresh_commitment(api, commitments[2]["id"])
        assert third_after["status"] == "PLANNED"
        assert third_after["version"] == commitments[2]["version"]
        for booked in (first, second):
            rows = fixtures.assignments_of_commitment(api, booked["commitment_id"])
            assert [row["status"] for row in rows] == ["ACTIVE"]
        assert (
            fixtures.refresh_provider(api, provider["id"])["assigned_weekly_minutes"]
            == 458
        )

    def test_the_same_clock_window_is_free_once_the_date_ranges_are_disjoint(self, api):
        """A colliding window becomes bookable when the dates stop intersecting.

        The rejected 09:45-to-10:15 block is retried over 2027-07-06 to
        2027-07-23 while the two incumbents end on 2027-06-30. The date test is
        "A collision additionally requires the two date ranges to intersect,
        tested inclusively: the new `effective_from` at or before the existing
        `effective_to`, and the existing `effective_from` at or before the new
        `effective_to`.", which now fails, so no conflict remains and the create
        succeeds.

        Design: Difficulty/resource_temporal_overlap/provider_weekly_slots_use_half_open_intervals_and_date_intersection
        """
        _program, provider, commitments = _timetable_setup(api)

        def book(commitment, start, end, effective_from, effective_to):
            return api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"],
                    provider["id"],
                    commitment["version"],
                    weekday="MON",
                    start_time=start,
                    end_time=end,
                    effective_from=effective_from,
                    effective_to=effective_to,
                ),
                PC,
            )

        validate_success(
            book(commitments[0], "09:00", "10:00", "2027-06-14", "2027-06-30"), 201
        )
        validate_success(
            book(commitments[1], "10:00", "11:00", "2027-06-14", "2027-06-30"), 201
        )
        validate_error(
            book(commitments[2], "09:45", "10:15", "2027-06-14", "2027-06-30"),
            ApiErrorId.PROVIDER_TIME_CONFLICT,
            409,
        )

        accepted = validate_success(
            book(commitments[2], "09:45", "10:15", "2027-07-06", CANON_SESSION_END), 201
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["effective_from"] == "2027-07-06"
        assert accepted["covered_total_minutes"] == 687
        assert fixtures.refresh_commitment(api, commitments[2]["id"])["status"] == (
            "ASSIGNED"
        )
        assert (
            fixtures.refresh_provider(api, provider["id"])["assigned_weekly_minutes"]
            == 687
        )


class TestFundEncumbranceConservation:
    """Creating and releasing an assignment must leave the money exactly as found."""

    def test_creating_an_assignment_encumbers_exactly_the_total_charge(self, api):
        """The forward leg posts 222588 cents and 229 weekly minutes.

        Before the create the allocation satisfies "At all times, and after every
        posting or reversal, an allocation's `available_cents` equals its
        `authorized_amount_cents` less its `encumbered_amount_cents` less its
        `expended_amount_cents`." with every ledger at zero. The create then runs
        step five, where "A provider assignment adds `total_charge_cents` to the
        selected allocation's `encumbered_amount_cents` and records the selection
        on the assignment as `charged_fund_source` and `charged_budget_code`.",
        and loads the provider because "On success, the provider's
        `assigned_weekly_minutes` is set to the recomputed sum." The expended
        book is untouched, proving encumbrance and expenditure are separate.

        Design: Difficulty/compensating_invariant/fund_encumbrance_conservation_survives_an_assignment_release
        """
        context = fixtures.setup_baseline(
            api,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        allocation = context["allocation"]
        assert allocation["encumbered_amount_cents"] == 0
        assert allocation["expended_amount_cents"] == 0
        assert allocation["compensatory_expended_cents"] == 0
        assert allocation["available_cents"] == CANON_AUTHORIZED_AMOUNT_CENTS
        assert_allocation_available_identity(allocation)

        assignment = validate_success(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], context["provider"]["id"], commitment["version"]
                ),
                PC,
            ),
            201,
        )
        assert assignment["covered_total_minutes"] == CANON_COVERED_TOTAL_MINUTES
        assert assignment["base_cost_cents"] == CANON_BASE_COST_CENTS
        assert assignment["indirect_cost_cents"] == CANON_INDIRECT_COST_CENTS
        assert assignment["total_charge_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert assignment["charged_fund_source"] == "IDEA_611_FEDERAL"
        assert assignment["charged_budget_code"] == CANON_BUDGET_CODE
        assert assignment["status"] == "ACTIVE"

        allocation_after = fixtures.refresh_allocation(
            api, context["program"]["id"], allocation["id"]
        )
        assert allocation_after["encumbered_amount_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert allocation_after["expended_amount_cents"] == 0
        assert allocation_after["available_cents"] == (
            CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT
        )
        assert_allocation_available_identity(allocation_after)

        assert (
            fixtures.refresh_provider(api, context["provider"]["id"])[
                "assigned_weekly_minutes"
            ]
            == 229
        )
        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "ASSIGNED"
        assert commitment_after["version"] == commitment["version"] + 1

    def test_releasing_the_assignment_restores_every_conserved_quantity(self, api):
        """The release reverses the stored figure, never a recomputed one.

        "The release moves it `ACTIVE → RELEASED` and reverses its footprint
        exactly: `total_charge_cents` is subtracted from the
        `encumbered_amount_cents` of the allocation identified by
        `charged_fund_source` and `charged_budget_code`, so `available_cents`
        returns to its pre-assignment value; `covered_weekly_minutes` is
        subtracted from the provider's `assigned_weekly_minutes`; and if the
        release leaves no `ACTIVE` assignment on a commitment whose `status`
        reads `ASSIGNED`, the commitment reverts to `PLANNED`." All three
        reversals are checked here, together with "Both the assignment's
        `version` and the commitment's `version` increment." The released row
        keeps its money fields for audit, and the expended book never moves.

        Design: Difficulty/compensating_invariant/fund_encumbrance_conservation_survives_an_assignment_release
        """
        context = fixtures.setup_baseline(
            api,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        allocation = context["allocation"]
        original_version = commitment["version"]

        assignment = validate_success(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], context["provider"]["id"], original_version
                ),
                PC,
            ),
            201,
        )

        released = validate_success(
            api.release_provider_assignment(
                assignment["id"], {"release_reason": "STAFF_REASSIGNED"}, PC
            )
        )
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "STAFF_REASSIGNED"
        assert released["version"] == assignment["version"] + 1
        assert released["total_charge_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert released["charged_budget_code"] == CANON_BUDGET_CODE

        allocation_after = fixtures.refresh_allocation(
            api, context["program"]["id"], allocation["id"]
        )
        assert allocation_after["encumbered_amount_cents"] == 0
        assert allocation_after["expended_amount_cents"] == 0
        assert allocation_after["compensatory_expended_cents"] == 0
        assert allocation_after["available_cents"] == CANON_AUTHORIZED_AMOUNT_CENTS
        assert_allocation_available_identity(allocation_after)

        assert (
            fixtures.refresh_provider(api, context["provider"]["id"])[
                "assigned_weekly_minutes"
            ]
            == 0
        )
        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "PLANNED"
        assert commitment_after["version"] == original_version + 2

        rows, meta = validate_paginated(
            api.list_provider_assignments_for_commitment(
                commitment["id"], PC, {"limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "RELEASED"


class TestFundAllocationUniqueness:
    """Budget codes are unique per program, not globally."""

    def test_a_repeated_budget_code_is_refused_inside_one_program_only(self, api):
        """The same code is a duplicate on P1 and perfectly legal on P2.

        The uniqueness scope is the pair, not the code: "The pair of `program_id`
        and `budget_code` must be unique across all allocations, and a repeat is
        refused with `ERR_DUPLICATE_BUDGET_CODE`; that uniqueness is what lets an
        auditor resolve a single allocation from the `charged_fund_source` and
        `charged_budget_code` recorded on a charge." Reusing 611-ESY-01 on the
        same program therefore trips check 29, "The `program_id` and
        `budget_code` pair is unique — otherwise `ERR_DUPLICATE_BUDGET_CODE`.",
        even under a different `fund_source`, while the identical code on a second
        program is authorized and starts fully available.

        Design: Corner/errors/duplicate_budget_code_within_one_program_rejected
        """
        fixtures.set_clock(api)
        first_program = fixtures.create_program(api)
        second_program = fixtures.create_program(
            api, name="Summer ESY 2027 Elementary", blackout_dates=[]
        )
        fixtures.authorize_allocation(api, first_program["id"])

        validate_error(
            api.create_fund_allocation(
                factories.fund_allocation_payload(
                    first_program["id"],
                    fund_source="LOCAL_GENERAL",
                    budget_code=CANON_BUDGET_CODE,
                    authorized_amount_cents=10000,
                ),
                DIR,
            ),
            ApiErrorId.DUPLICATE_BUDGET_CODE,
            409,
        )

        twin = validate_success(
            api.create_fund_allocation(
                factories.fund_allocation_payload(
                    second_program["id"],
                    budget_code=CANON_BUDGET_CODE,
                    authorized_amount_cents=10000,
                ),
                DIR,
            ),
            201,
        )
        assert twin["program_id"] == second_program["id"]
        assert twin["available_cents"] == 10000
        assert twin["status"] == "OPEN"

        _rows, meta = validate_paginated(
            api.list_program_fund_allocations(first_program["id"], DIR, {"limit": 10})
        )
        assert_pagination_meta(meta, 1, False, 10, 0)


class TestAssignmentSuitabilityAndCapacity:
    """The remaining single-violation gates on assignment creation."""

    def test_an_open_bucket_too_small_for_the_base_cost_is_no_bucket_at_all(self, api):
        """One OPEN allocation of 100000 cents cannot absorb a base cost of 206100.

        Step two filters on the base cost alone, and when every candidate falls
        short the waterfall stops: "If the program has fund allocations but not
        one of them is `OPEN`, the request fails with `ERR_FUND_FROZEN`; if `OPEN`
        allocations exist but none of them has enough `available_cents` to cover
        `base_cost_cents`, the request fails with `ERR_NO_FUND_WITH_CAPACITY`."
        Nothing is encumbered, the commitment does not advance and the provider
        picks up no load.

        Design: Corner/errors/assignment_with_no_fund_covering_the_base_cost_rejected
        """
        context = fixtures.setup_baseline(
            api,
            allocation_overrides={"authorized_amount_cents": 100000},
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]

        validate_error(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], context["provider"]["id"], commitment["version"]
                ),
                PC,
            ),
            ApiErrorId.NO_FUND_WITH_CAPACITY,
            422,
        )

        allocation_after = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation_after["encumbered_amount_cents"] == 0
        assert allocation_after["available_cents"] == 100000
        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "PLANNED"
        assert commitment_after["version"] == commitment["version"]
        assert (
            fixtures.refresh_provider(api, context["provider"]["id"])[
                "assigned_weekly_minutes"
            ]
            == 0
        )
        assert _assignment_count(api, commitment["id"]) == 0

    def test_a_provider_switched_off_the_roster_cannot_be_assigned(self, api):
        """An INACTIVE provider with a valid credential draws the status error.

        The credential runs to 2028-06-30 so check 12 passes cleanly, and the
        next gate is the one that fires: "The provider's `status` must read
        `ACTIVE`, or the request draws `ERR_PROVIDER_NOT_ACTIVE`." — check 13 in
        the global order, "The provider's `status` reads `ACTIVE` — otherwise
        `ERR_PROVIDER_NOT_ACTIVE`." The status change itself is permitted at any
        time, since "a coordinator may update `status`, `credential_expires_on` or
        `max_weekly_minutes` at any time, each field independently optional on the
        update".

        Design: Corner/errors/assignment_for_a_provider_no_longer_active_rejected
        """
        context = fixtures.setup_baseline(
            api,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        provider_id = context["provider"]["id"]
        validate_success(api.patch_provider(provider_id, {"status": "INACTIVE"}, PC))

        response = api.create_provider_assignment(
            factories.assignment_payload(
                commitment["id"], provider_id, commitment["version"]
            ),
            PC,
        )
        validate_error(response, ApiErrorId.PROVIDER_NOT_ACTIVE, 422)

        provider_after = fixtures.refresh_provider(api, provider_id)
        assert provider_after["status"] == "INACTIVE"
        assert provider_after["assigned_weekly_minutes"] == 0
        commitment_after = fixtures.refresh_commitment(api, commitment["id"])
        assert commitment_after["status"] == "PLANNED"
        assert commitment_after["version"] == commitment["version"]
        assert (
            fixtures.refresh_allocation(
                api, context["program"]["id"], context["allocation"]["id"]
            )["encumbered_amount_cents"]
            == 0
        )

    def test_the_weekly_ceiling_admits_a_load_that_lands_exactly_on_it(self, api):
        """229 minutes overruns a 200-minute contract; 200 minutes fits exactly.

        The ceiling test is a sum, not a per-booking test —
        "Contractual load is checked in aggregate rather than per booking." — and
        it rejects only a strict overrun: "Sum `covered_weekly_minutes` across all
        `ACTIVE` assignments the provider already holds, add the requested
        `covered_weekly_minutes`, and if that total is greater than the provider's
        `max_weekly_minutes`, reject with `ERR_PROVIDER_CAPACITY_EXCEEDED`." A
        request landing exactly on the ceiling is therefore accepted, and
        "On success, the provider's `assigned_weekly_minutes` is set to the
        recomputed sum."

        Design: Corner/errors/assignment_above_the_provider_weekly_ceiling_rejected
        """
        context = fixtures.setup_baseline(
            api,
            provider_overrides={"full_name": "Omar Diaz", "max_weekly_minutes": 200},
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        provider_id = context["provider"]["id"]

        validate_error(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], provider_id, commitment["version"]
                ),
                PC,
            ),
            ApiErrorId.PROVIDER_CAPACITY_EXCEEDED,
            422,
        )
        assert (
            fixtures.refresh_provider(api, provider_id)["assigned_weekly_minutes"] == 0
        )
        assert (
            fixtures.refresh_commitment(api, commitment["id"])["version"]
            == commitment["version"]
        )

        accepted = validate_success(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"],
                    provider_id,
                    commitment["version"],
                    covered_weekly_minutes=200,
                ),
                PC,
            ),
            201,
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["covered_weekly_minutes"] == 200
        assert (
            fixtures.refresh_provider(api, provider_id)["assigned_weekly_minutes"]
            == 200
        )
        assert (
            fixtures.refresh_commitment(api, commitment["id"])["status"] == "ASSIGNED"
        )

    def test_a_stale_expected_commitment_version_is_a_precondition_failure(self, api):
        """The first create bumps the version, so the echo goes stale.

        "Creating a provider assignment — `POST /esy/provider-assignments` —
        requires the non-optional field `expected_commitment_version`, carrying
        the client's last observed `version` of the target `ServiceCommitment`."
        and once the first assignment has advanced the commitment to `ASSIGNED`,
        the original echo no longer matches: "If that value does not match the
        commitment's current `version`, the create is rejected with
        `ERR_STALE_COMMITMENT_VERSION` (HTTP 412)." Re-reading the commitment and
        replaying the same request with the fresh `version` succeeds, proving the
        rejection was about the echo and nothing else.

        Design: Corner/cross_cutting_layers/stale_commitment_version_on_assignment_create_returns_412
        """
        context = fixtures.setup_baseline(
            api,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        commitment = context["commitment"]
        stale_version = commitment["version"]
        validate_success(
            api.create_provider_assignment(
                factories.assignment_payload(
                    commitment["id"], context["provider"]["id"], stale_version
                ),
                PC,
            ),
            201,
        )
        second_provider = fixtures.register_provider(api, full_name="Omar Diaz")
        payload = factories.assignment_payload(
            commitment["id"],
            second_provider["id"],
            stale_version,
            weekday="TUE",
        )

        validate_error(
            api.create_provider_assignment(payload, PC),
            ApiErrorId.STALE_COMMITMENT_VERSION,
            412,
        )
        assert (
            fixtures.refresh_provider(api, second_provider["id"])[
                "assigned_weekly_minutes"
            ]
            == 0
        )
        assert (
            fixtures.refresh_allocation(
                api, context["program"]["id"], context["allocation"]["id"]
            )["encumbered_amount_cents"]
            == CANON_TOTAL_CHARGE_CENTS
        )

        fresh = fixtures.refresh_commitment(api, commitment["id"])
        assert fresh["version"] != stale_version
        payload["expected_commitment_version"] = fresh["version"]
        validate_success(api.create_provider_assignment(payload, PC), 201)
