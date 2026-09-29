"""
The two formulas whose answer depends on the order the arithmetic is applied in:
the nested caps on a contractor's named-call and special-skill rights, and the
per-entry rounding of a traveler's reciprocal hours.
"""

from test_helpers import (
    DURATION_LONG_CALL,
    DURATION_SHORT_CALL,
    ERR_NAMED_CALL_ALLOWANCE_EXCEEDED,
    ERR_SPECIAL_SKILL_ALLOWANCE_EXCEEDED,
    LOCAL_KIND_SISTER,
    SKILL_WELDING_6G,
    expect_created,
    expect_error,
    factories as f,
    fixtures as fx,
    make_contractor_rep_headers,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The nested allowance caps ────────────────────────────────────────────────

JOURNEYWORKERS = 25
APPRENTICES = 5
TOTAL_REQUESTED = JOURNEYWORKERS + APPRENTICES
LONG_CALL_DAYS = 30
SHORT_CALL_DAYS = 4
ALLOWED_NAMED_CALLS = 4
ALLOWED_SKILL_SLOTS = 13
RATE_CENTS = 5100
REPORT_AT = "2026-09-20T07:00:00.000Z"
NAMED_MEMBER_NAMES = (
    "Named One",
    "Named Two",
    "Named Three",
    "Named Four",
    "Named Five",
)

# ─── The per-entry reciprocity rounding ───────────────────────────────────────

FIRST_RAW_HOURS = 1003
SECOND_RAW_HOURS = 1005
PER_ENTRY_ROUNDED_TOTAL = 1005  # 502 + 503
SUM_THEN_ROUND_TOTAL = 1004  # 501.5 + 502.5, the order the PRD forbids


def _allowance_hall(api):
    """
    Five journeyworkers on the books and one signatory contractor. Intake never
    consults the out-of-work lists, so no registration is needed.
    """
    fx.set_clock(api, CLOCK)
    home = fx.add_home_local(api)
    contractor = fx.add_contractor(api, name="Keystone Industrial")
    named = [
        fx.add_journeyworker(api, home["id"], full_name, 9000)
        for full_name in NAMED_MEMBER_NAMES
    ]
    return {"home": home, "contractor": contractor, "named": named}


def _intake_payload(contractor_id, named_ids, **overrides):
    """The one payload every allowance probe varies a single field of."""
    return f.job_request_payload(
        contractor_id,
        **{
            "job_site": "Unit 7 turnaround",
            "journeyworkers_requested": JOURNEYWORKERS,
            "apprentices_requested": APPRENTICES,
            "expected_duration_days": LONG_CALL_DAYS,
            "report_at": REPORT_AT,
            "hourly_rate_cents": RATE_CENTS,
            "required_skill_code": SKILL_WELDING_6G,
            "special_skill_slots_requested": ALLOWED_SKILL_SLOTS,
            "named_call_member_ids": named_ids,
            **overrides,
        },
    )


def _attempt_intake(api, contractor_id, payload):
    return api.create_job_request(payload, make_contractor_rep_headers(contractor_id))


def _reciprocity_hall(api):
    """A home local with no reciprocity factor and two sister locals at half."""
    fx.set_clock(api, CLOCK)
    fx.add_home_local(api)
    sister_46 = fx.add_sister_local(api)
    sister_9 = fx.add_local(
        api,
        f.local_payload(
            local_number=9,
            name="Local 9 (sister)",
            kind=LOCAL_KIND_SISTER,
            reciprocity_factor_bp=5000,
        ),
    )
    group_four = fx.add_list_group(api, f.group_four_payload())
    traveler = fx.add_journeyworker(api, sister_46["id"], "Val Ortiz", 0)
    return {
        "sister_46": sister_46,
        "sister_9": sister_9,
        "group_four": group_four,
        "traveler": traveler,
    }


class TestNamedCallAndSkillAllowanceCaps:
    """Both allowances are frozen at intake from the request's own fields."""

    def test_hard_ceiling_and_odd_count_correction_fix_the_two_allowances(self, api):
        """
        PRD §3.5: "For a long call, take the total headcount requested —
        journeyworkers plus apprentices — divide it by 5 discarding any
        remainder, take the greater of that quotient and 1, and then take the
        lesser of the result and a hard ceiling of 4."

        Design: Difficulty/combinatorial_formula/named_call_and_skill_allowance_nested_min_max
        """
        scene = _allowance_hall(api)
        four_named = [member["id"] for member in scene["named"][:4]]

        created = expect_created(
            _attempt_intake(
                api,
                scene["contractor"]["id"],
                _intake_payload(scene["contractor"]["id"], four_named),
            )
        )

        # The divisor alone would allow six named calls out of a headcount of
        # thirty; the ceiling of four is what binds.
        assert TOTAL_REQUESTED // 5 == 6
        assert created["duration_type"] == DURATION_LONG_CALL
        assert created["named_call_allowance"] == ALLOWED_NAMED_CALLS
        assert created["special_skill_allowance"] == ALLOWED_SKILL_SLOTS

    def test_special_skill_allowance_rounds_the_odd_journeyworker_count_up(self, api):
        """
        PRD §3.5: "Otherwise it is half the journeyworkers requested rounded up
        — computed as the journeyworker count multiplied by 5,000 basis points
        and divided by 10,000 discarding the remainder, plus 1 when the
        journeyworker count is odd — and then capped at the journeyworker count
        itself."

        Design: Difficulty/combinatorial_formula/named_call_and_skill_allowance_nested_min_max
        """
        scene = _allowance_hall(api)
        four_named = [member["id"] for member in scene["named"][:4]]

        created = expect_created(
            _attempt_intake(
                api,
                scene["contractor"]["id"],
                _intake_payload(scene["contractor"]["id"], four_named),
            )
        )

        halved = JOURNEYWORKERS * 5000 // 10000
        assert halved == 12
        assert created["special_skill_allowance"] == halved + (JOURNEYWORKERS % 2)
        assert created["special_skill_allowance"] == ALLOWED_SKILL_SLOTS
        assert created["special_skill_allowance"] <= JOURNEYWORKERS

    def test_a_fifth_named_member_exceeds_the_frozen_named_call_allowance(self, api):
        """
        PRD §3.5: "First, if the number of entries in `named_call_member_ids`
        exceeds `named_call_allowance`, the intake is refused with
        `ERR_NAMED_CALL_ALLOWANCE_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/named_call_and_skill_allowance_nested_min_max
        """
        scene = _allowance_hall(api)
        five_named = [member["id"] for member in scene["named"]]

        response = _attempt_intake(
            api,
            scene["contractor"]["id"],
            _intake_payload(
                scene["contractor"]["id"],
                five_named,
                job_site="Unit 7 turnaround (five named)",
            ),
        )

        expect_error(response, ERR_NAMED_CALL_ALLOWANCE_EXCEEDED)

    def test_a_fourteenth_skill_slot_exceeds_the_special_skill_allowance(self, api):
        """
        PRD §3.5: "Only then, if `special_skill_slots_requested` exceeds
        `special_skill_allowance`, the intake is refused with
        `ERR_SPECIAL_SKILL_ALLOWANCE_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/named_call_and_skill_allowance_nested_min_max
        """
        scene = _allowance_hall(api)
        four_named = [member["id"] for member in scene["named"][:4]]

        response = _attempt_intake(
            api,
            scene["contractor"]["id"],
            _intake_payload(
                scene["contractor"]["id"],
                four_named,
                job_site="Unit 7 turnaround (fourteen skill slots)",
                special_skill_slots_requested=ALLOWED_SKILL_SLOTS + 1,
            ),
        )

        expect_error(response, ERR_SPECIAL_SKILL_ALLOWANCE_EXCEEDED)

    def test_a_short_call_grants_no_named_call_at_all(self, api):
        """
        PRD §3.5: "The `named_call_allowance` is 0 for a short call."

        Design: Difficulty/combinatorial_formula/named_call_and_skill_allowance_nested_min_max
        """
        scene = _allowance_hall(api)
        one_named = [scene["named"][0]["id"]]

        # The headcount, the skill code and the slot count are all identical to
        # the accepted long call; only the duration moves.
        response = _attempt_intake(
            api,
            scene["contractor"]["id"],
            _intake_payload(
                scene["contractor"]["id"],
                one_named,
                job_site="Unit 7 four-day outage",
                expected_duration_days=SHORT_CALL_DAYS,
            ),
        )

        expect_error(response, ERR_NAMED_CALL_ALLOWANCE_EXCEEDED)

        skill_only = expect_created(
            _attempt_intake(
                api,
                scene["contractor"]["id"],
                _intake_payload(
                    scene["contractor"]["id"],
                    [],
                    job_site="Unit 7 four-day outage, unnamed",
                    expected_duration_days=SHORT_CALL_DAYS,
                ),
            )
        )
        assert skill_only["duration_type"] == DURATION_SHORT_CALL
        assert skill_only["named_call_allowance"] == 0


class TestTravelerReciprocityRounding:
    """Each reciprocity entry is rounded on its own before anything is summed."""

    def test_two_half_hour_entries_round_up_separately_then_sum(self, api):
        """
        PRD §3.3: "then walk the declared credits in the order they were supplied
        in the array, and for each one multiply its `raw_hours` by that sister
        local's `reciprocity_factor_bp`, divide by 10,000, and round the result
        half up to a whole hour; finally add those individually rounded per-entry
        results to the base."

        Design: Difficulty/combinatorial_formula/traveler_credit_rounds_per_entry_then_sums
        """
        scene = _reciprocity_hall(api)

        registration = fx.sign_book(
            api,
            scene["traveler"]["id"],
            scene["group_four"]["id"],
            headers=None,
            reciprocity_credits=[
                f.reciprocity_credit(scene["sister_46"]["id"], FIRST_RAW_HOURS),
                f.reciprocity_credit(scene["sister_9"]["id"], SECOND_RAW_HOURS),
            ],
        )

        assert scene["traveler"]["is_traveler"] is True
        assert registration["credited_seniority_hours"] == PER_ENTRY_ROUNDED_TOTAL
        assert registration["position_number"] == 1

    def test_the_forbidden_sum_then_round_order_is_one_hour_short(self, api):
        """
        PRD §3.3: "The rounding happens once per array entry, before the
        summation, never once over the total."

        Design: Difficulty/combinatorial_formula/traveler_credit_rounds_per_entry_then_sums
        """
        scene = _reciprocity_hall(api)

        registration = fx.sign_book(
            api,
            scene["traveler"]["id"],
            scene["group_four"]["id"],
            headers=None,
            reciprocity_credits=[
                f.reciprocity_credit(scene["sister_46"]["id"], FIRST_RAW_HOURS),
                f.reciprocity_credit(scene["sister_9"]["id"], SECOND_RAW_HOURS),
            ],
        )

        # Halving each entry gives 501.5 and 502.5; rounding each half up first
        # yields 502 + 503, while rounding only the total yields 1004.
        assert registration["credited_seniority_hours"] != SUM_THEN_ROUND_TOTAL
        assert registration["credited_seniority_hours"] == PER_ENTRY_ROUNDED_TOTAL

    def test_the_member_own_local_hours_are_the_base_the_credits_add_to(self, api):
        """
        PRD §3.3: "start from the member's `local_hours_in_trade`, which are
        hours under the home local's own agreement and are always credited in
        full"

        Design: Difficulty/combinatorial_formula/traveler_credit_rounds_per_entry_then_sums
        """
        scene = _reciprocity_hall(api)
        assert scene["traveler"]["local_hours_in_trade"] == 0

        registration = fx.sign_book(
            api,
            scene["traveler"]["id"],
            scene["group_four"]["id"],
            headers=None,
            reciprocity_credits=[
                f.reciprocity_credit(scene["sister_46"]["id"], FIRST_RAW_HOURS),
                f.reciprocity_credit(scene["sister_9"]["id"], SECOND_RAW_HOURS),
            ],
        )

        assert registration["credited_seniority_hours"] == (
            scene["traveler"]["local_hours_in_trade"] + PER_ENTRY_ROUNDED_TOTAL
        )
