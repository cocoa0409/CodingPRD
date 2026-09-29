"""The economics of handing a deliverable to a writer.

Assignment is where planning turns into work, and it is priced: a six-step
formula converts pages, complexity, and information-architecture intent into
load points, valued against the seniority of the writer receiving them.  This
module covers that formula and its step order, the writer's committed-load
ledger as a conserved quantity, the half-open authoring window with its
leading-edge handoff buffer, the inclusive capacity ceiling, and the fixed
precedence between those last two guards.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_committed_load_points,
    assert_plan_item,
    assign_plan_item,
    assign_plan_item_payload,
    cancel_plan_item_payload,
    create_plan_item,
    create_release_train,
    create_reviewer,
    create_revision,
    create_topic,
    create_writer,
    decide_signoff,
    expected_load_points,
    plan_item_context,
    read_plan_item,
    read_release_train,
    read_reviewer,
    read_topic,
    read_writer,
    request_signoff,
    set_clock,
    submit_topic,
    validate_error,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"

#: A release train whose planning window stays open for every window used below.
TRAIN = {
    "product_key": "ATLAS",
    "doc_freeze_date": "2026-08-20",
    "ga_date": "2026-09-01",
    "support_end_date": "2027-09-01",
    "localization_budget_cap_cents": 5000000,
}

#: 6 planned pages, 10 complexity points, a new topic for a STANDARD audience.
STANDARD_ITEM = {
    "ia_placement": "NEW_TOPIC",
    "audience_tier": "STANDARD",
    "planned_page_count": 6,
    "complexity_points": 10,
}

#: A small internal update: 2 planned pages, 4 complexity points.
INTERNAL_ITEM = {
    "ia_placement": "EXISTING_TOPIC_UPDATE",
    "audience_tier": "INTERNAL",
    "planned_page_count": 2,
    "complexity_points": 4,
}

#: A one-page internal note, deliberately cheap enough to hit the load floor.
TINY_ITEM = {
    "ia_placement": "EXISTING_TOPIC_UPDATE",
    "audience_tier": "INTERNAL",
    "planned_page_count": 1,
    "complexity_points": 1,
}


class TestAssignmentTransition:
    """One assign call moves the deliverable, prices it, and credits the writer."""

    def test_assignment_prices_the_deliverable_and_credits_the_writer_ledger(
        self, api, docs_lead_headers
    ):
        """Six planned pages at STANDARD for a SENIOR writer are worth 26.00 points.

        PRD §3.2: "Assigning a deliverable to a writer is what turns planning
        into work, and it moves the item from `DRAFTED` to `ASSIGNED`."

        PRD §3.2: "First, size points are 2 points for each planned page — twice
        `planned_page_count`."

        PRD §3.2: "Second, depth points are `complexity_points` or 20, whichever
        is smaller; the cap is applied here, before any multiplier, so complexity
        above 20 contributes nothing extra."

        PRD §3.2: "Third, information-architecture points are 4 for `NEW_TOPIC`,
        1 for `EXISTING_TOPIC_UPDATE`, and 6 for `CONCEPT_HUB`."

        PRD §3.2: "Fourth, those three figures are added together, the sum is
        multiplied by the audience multiplier — 1.5 for `CRITICAL`, 1.0 for
        `STANDARD`, 0.75 for `INTERNAL` — and the product is then divided by the
        seniority divisor of the *target writer* — 1.25 for `PRINCIPAL`, 1.0 for
        `SENIOR`, 0.80 for `ASSOCIATE`; the audience multiplication happens
        before the seniority division."

        PRD §3.2: "A writer's `committed_load_points` is the sum of `load_points`
        over the plan items assigned to them whose status is `ASSIGNED`,
        `IN_AUTHORING`, `IN_REVIEW`, `IN_REVISION`, or `APPROVED_CONTENT`,
        rounded half up to two decimal places, and `assignment_count` is the
        number of items in that same set."

        Design: Corner/state_machines/plan_item_assign_transition_writes_load_points_and_writer_ledger
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 40.0},
            feature_key="feature-a",
            **STANDARD_ITEM,
        )

        response = api.assign_plan_item(
            bundle["plan_item_id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date="2026-08-03",
                window_end_date="2026-08-17",
            ),
            docs_lead_headers,
        )
        item = validate_success(response)

        assert_plan_item(item)
        assert item["status"] == "ASSIGNED"
        assert item["assigned_writer_id"] == bundle["writer_id"]
        assert item["window_start_date"] == "2026-08-03"
        assert item["window_end_date"] == "2026-08-17"
        # Hand computation: size 2*6 = 12, depth min(10, 20) = 10, IA NEW_TOPIC 4;
        # (12 + 10 + 4) * 1.0 / 1.0 = 26.00, above the 3.0 floor, no rework yet.
        assert item["load_points"] == pytest.approx(26.00, abs=0.01)
        assert item["load_points"] == pytest.approx(
            expected_load_points(6, 10, "NEW_TOPIC", "STANDARD", "SENIOR"), abs=0.01
        )

        writer = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        assert_committed_load_points(writer, 26.00)
        assert writer["assignment_count"] == 1

        train = read_release_train(bundle["train_id"])
        assert train["approved_topic_ratio"] == pytest.approx(0.00, abs=0.01)
        assert train["doc_readiness_posture"] == "OPEN"


class TestLoadFloorAndReworkStepOrder:
    """The floor lands on the rounded raw figure, and rework points land after
    the floor — an order that produces two numbers a reordered formula cannot."""

    def test_a_cheap_deliverable_is_lifted_to_the_load_floor(self, api, docs_lead_headers):
        """A raw 2.40 becomes a stored 3.00, because the floor is a floor.

        PRD §3.2: "Fifth, that raw figure is rounded half up to two decimal
        places and then compared against a floor of 3.0 points, and the larger of
        the two becomes the base load — note that the floor is applied to the
        *rounded* value, not the unrounded one."

        Design: Corner/calculations/writer_load_points_floor_applied_before_rework_points
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={
                "person_key": "w-paul",
                "full_name": "Paul Nkemdi",
                "seniority_tier": "PRINCIPAL",
                "capacity_points": 40.0,
            },
            feature_key="feature-tiny",
            **TINY_ITEM,
        )

        item = validate_success(
            api.assign_plan_item(
                bundle["plan_item_id"],
                assign_plan_item_payload(
                    bundle["writer_id"],
                    window_start_date="2026-08-03",
                    window_end_date="2026-08-17",
                ),
                docs_lead_headers,
            )
        )

        # Hand computation: size 2*1 = 2, depth min(1, 20) = 1, IA update 1;
        # (2 + 1 + 1) * 0.75 / 1.25 = 2.40 raw, lifted to the 3.0 floor.
        assert item["load_points"] == pytest.approx(3.00, abs=0.01)
        assert item["load_points"] != pytest.approx(2.40, abs=0.01)
        assert item["load_points"] == pytest.approx(
            expected_load_points(1, 1, "EXISTING_TOPIC_UPDATE", "INTERNAL", "PRINCIPAL"), abs=0.01
        )
        assert item["rework_count"] == 0

        writer = read_writer(bundle["writer_id"])
        assert_committed_load_points(writer, 3.00)
        assert writer["assignment_count"] == 1

    def test_a_rework_cycle_adds_its_point_on_top_of_the_floored_base(
        self, api, docs_lead_headers
    ):
        """One changes-requested cycle takes 3.00 to 4.00, never to 3.40.

        PRD §3.2: "Sixth and last, `load_points` is the base load plus 1.0 point
        for each unit of the item's `rework_count`, rounded half up to two decimal
        places; because the rework points are added *after* the floor, they always
        raise the total."

        PRD §3.5: "**Hop three**, caused by hop two, moves the plan item from
        `IN_REVIEW` to `IN_REVISION`, increases its `rework_count` by 1, raises
        its `load_points` by 1.0 point for that additional rework unit, and
        recomputes the assigned writer's `committed_load_points` so the conserved
        quantity still equals the sum over the writer's counted items."

        Design: Corner/calculations/writer_load_points_floor_applied_before_rework_points
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={
                "person_key": "w-paul",
                "full_name": "Paul Nkemdi",
                "seniority_tier": "PRINCIPAL",
                "capacity_points": 40.0,
            },
            feature_key="feature-tiny",
            **TINY_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        topic = create_topic(
            bundle["plan_item_id"],
            bundle["writer_id"],
            slug="atlas-feature-tiny",
            title="Tiny internal note",
        )
        create_revision(
            topic["id"],
            bundle["writer_id"],
            body_word_count=120,
            used_terms=[],
            summary="First pass at the internal note",
        )
        submit_topic(topic["id"], bundle["writer_id"])
        reviewer = create_reviewer(
            person_key="r-erin", full_name="Erin Cole", discipline="ENGINEERING"
        )
        signoff = request_signoff(topic["id"], reviewer["id"])

        decide_signoff(
            signoff["id"],
            reviewer["id"],
            "CHANGES_REQUESTED",
            comment="Please add the migration caveat",
        )

        item = read_plan_item(bundle["plan_item_id"])
        assert item["rework_count"] == 1
        # 3.00 floored base + 1.0 rework point = 4.00; flooring after the
        # rework addition would have produced 3.40.
        assert item["load_points"] == pytest.approx(4.00, abs=0.01)
        assert item["load_points"] != pytest.approx(3.40, abs=0.01)
        assert item["load_points"] == pytest.approx(
            expected_load_points(
                1, 1, "EXISTING_TOPIC_UPDATE", "INTERNAL", "PRINCIPAL", rework_count=1
            ),
            abs=0.01,
        )
        assert item["status"] == "IN_REVISION"

        writer = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        assert_committed_load_points(writer, 4.00)
        assert writer["assignment_count"] == 1
        assert read_topic(topic["id"])["review_state"] == "CHANGES_REQUESTED"


class TestCapacityCeiling:
    """The ceiling is inclusive: a writer may be filled to the brim, and only the
    next point over is refused."""

    def test_committed_load_exactly_equal_to_capacity_is_admitted(
        self, api, docs_lead_headers
    ):
        """A 26.00-point deliverable fits a 26-point writer exactly.

        PRD §3.2: "The capacity ceiling is checked at assignment time by adding
        the freshly computed `load_points` to the writer's current
        `committed_load_points` and comparing the total against `capacity_points`:
        equality is accepted and only a strict excess is rejected, with
        `ERR_WRITER_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/writer_capacity_equality_admitted_then_strict_excess_rejected
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 26.0},
            feature_key="atlas-billing",
            **STANDARD_ITEM,
        )

        item = validate_success(
            api.assign_plan_item(
                bundle["plan_item_id"],
                assign_plan_item_payload(
                    bundle["writer_id"],
                    window_start_date="2026-08-03",
                    window_end_date="2026-08-14",
                ),
                docs_lead_headers,
            )
        )

        # (2*6 + 10 + 4) * 1.0 / 1.0 = 26.00, exactly the writer's ceiling.
        assert item["load_points"] == pytest.approx(26.00, abs=0.01)
        assert item["status"] == "ASSIGNED"

        writer = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        assert_committed_load_points(writer, 26.00)
        assert writer["committed_load_points"] == pytest.approx(
            writer["capacity_points"], abs=0.01
        ), "the equality case must be admitted, not rejected"
        assert writer["assignment_count"] == 1

    def test_one_point_of_excess_is_refused_when_the_window_gap_clears_the_buffer(
        self, api, docs_lead_headers
    ):
        """26.00 + 6.75 against 26 points is a strict excess, and nothing else fires.

        PRD §3.2: "The capacity ceiling is checked at assignment time by adding
        the freshly computed `load_points` to the writer's current
        `committed_load_points` and comparing the total against `capacity_points`:
        equality is accepted and only a strict excess is rejected, with
        `ERR_WRITER_CAPACITY_EXCEEDED`."

        PRD §3.2: "Because of the buffer, two windows that merely touch — one
        ending exactly on the day the next begins — still collide, and so does a
        one-day gap; a gap of exactly two days is accepted."

        Design: Difficulty/boundary_precision_check/writer_capacity_equality_admitted_then_strict_excess_rejected
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 26.0},
            feature_key="atlas-billing",
            **STANDARD_ITEM,
        )
        first = assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        assert first["load_points"] == pytest.approx(26.00, abs=0.01)
        second_item = create_plan_item(
            bundle["train_id"], feature_key="atlas-internal-notes", **INTERNAL_ITEM
        )

        response = api.assign_plan_item(
            second_item["id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date="2026-08-16",
                window_end_date="2026-08-26",
            ),
            docs_lead_headers,
        )
        # (2*2 + 4 + 1) * 0.75 / 1.0 = 6.75, and 26.00 + 6.75 = 32.75 > 26.
        assert expected_load_points(
            2, 4, "EXISTING_TOPIC_UPDATE", "INTERNAL", "SENIOR"
        ) == pytest.approx(6.75, abs=0.01)
        validate_error(response, ApiErrorId.WRITER_CAPACITY_EXCEEDED, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.WRITER_WINDOW_OVERLAP.value

        refused = read_plan_item(second_item["id"])
        assert refused["status"] == "DRAFTED"
        assert refused["assigned_writer_id"] is None
        assert refused["load_points"] == pytest.approx(0.00, abs=0.01)

        writer = read_writer(bundle["writer_id"])
        assert_committed_load_points(writer, 26.00)
        assert writer["assignment_count"] == 1


class TestAuthoringWindowHandoffBuffer:
    """A writer's window is half open, but padded by two days on its leading
    edge, so the tipping point sits two days past the previous window's end."""

    @pytest.mark.parametrize("requested_start", ["2026-08-14", "2026-08-15"])
    def test_a_window_inside_the_handoff_buffer_collides(
        self, api, docs_lead_headers, requested_start
    ):
        """Touching the previous end, and a one-day gap, both still collide.

        PRD §2.10: "A writer's authoring window is **half open**: it runs from
        `window_start_date` inclusive up to `window_end_date` exclusive, so a
        window ending on the 10th does not occupy the 10th."

        PRD §3.2: "The **window-collision rule** treats the requested interval as
        half open, from `window_start_date` inclusive to `window_end_date`
        exclusive, and extends it by a two-day handoff buffer on the **leading
        edge only**."

        PRD §3.2: "Because of the buffer, two windows that merely touch — one
        ending exactly on the day the next begins — still collide, and so does a
        one-day gap; a gap of exactly two days is accepted."

        Design: Difficulty/resource_temporal_overlap/writer_window_half_open_with_leading_handoff_buffer
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 100.0},
            feature_key="atlas-first",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        second_item = create_plan_item(
            bundle["train_id"], feature_key="atlas-second", **STANDARD_ITEM
        )

        response = api.assign_plan_item(
            second_item["id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date=requested_start,
                window_end_date="2026-08-26",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.WRITER_WINDOW_OVERLAP, 409)

        refused = read_plan_item(second_item["id"])
        assert refused["status"] == "DRAFTED"
        assert refused["window_start_date"] is None

    def test_a_gap_of_exactly_two_days_is_admitted(self, api, docs_lead_headers):
        """The buffer is two days wide, so 2026-08-16 clears a window ending 08-14.

        PRD §3.2: "Concretely, the requested window collides with an
        already-occupied window of the same writer when the requested start date
        falls earlier than two days after that existing window's end date **and**
        the requested end date falls later than that existing window's start date;
        a collision is rejected with `ERR_WRITER_WINDOW_OVERLAP`."

        PRD §3.2: "Because of the buffer, two windows that merely touch — one
        ending exactly on the day the next begins — still collide, and so does a
        one-day gap; a gap of exactly two days is accepted."

        Design: Difficulty/resource_temporal_overlap/writer_window_half_open_with_leading_handoff_buffer
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 100.0},
            feature_key="atlas-first",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        second_item = create_plan_item(
            bundle["train_id"], feature_key="atlas-second", **STANDARD_ITEM
        )

        accepted = validate_success(
            api.assign_plan_item(
                second_item["id"],
                assign_plan_item_payload(
                    bundle["writer_id"],
                    window_start_date="2026-08-16",
                    window_end_date="2026-08-26",
                ),
                docs_lead_headers,
            )
        )

        assert accepted["window_start_date"] == "2026-08-16"
        assert accepted["status"] == "ASSIGNED"
        assert accepted["load_points"] == pytest.approx(26.00, abs=0.01)

        writer = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        # 26.00 + 26.00 = 52.00 against a 100-point ceiling: capacity never binds.
        assert_committed_load_points(writer, 52.00)
        assert writer["assignment_count"] == 2

    def test_refused_attempts_leave_the_ledger_and_the_earlier_window_untouched(
        self, api, docs_lead_headers
    ):
        """Two rejected retries change nothing, so the same row can be retried.

        PRD §3.2: "Concretely, the requested window collides with an
        already-occupied window of the same writer when the requested start date
        falls earlier than two days after that existing window's end date **and**
        the requested end date falls later than that existing window's start date;
        a collision is rejected with `ERR_WRITER_WINDOW_OVERLAP`."

        PRD §2.8: "A create followed by its compensating cancel must return each
        affected ledger to precisely its pre-create value."

        Design: Difficulty/resource_temporal_overlap/writer_window_half_open_with_leading_handoff_buffer
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 100.0},
            feature_key="atlas-first",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        second_item = create_plan_item(
            bundle["train_id"], feature_key="atlas-second", **STANDARD_ITEM
        )

        for requested_start in ("2026-08-14", "2026-08-15"):
            validate_error(
                api.assign_plan_item(
                    second_item["id"],
                    assign_plan_item_payload(
                        bundle["writer_id"],
                        window_start_date=requested_start,
                        window_end_date="2026-08-26",
                    ),
                    docs_lead_headers,
                ),
                ApiErrorId.WRITER_WINDOW_OVERLAP,
                409,
            )

        writer = read_writer(bundle["writer_id"])
        assert_committed_load_points(writer, 26.00)
        assert writer["assignment_count"] == 1
        assert read_plan_item(bundle["plan_item_id"])["window_end_date"] == "2026-08-14"

        retried = validate_success(
            api.assign_plan_item(
                second_item["id"],
                assign_plan_item_payload(
                    bundle["writer_id"],
                    window_start_date="2026-08-16",
                    window_end_date="2026-08-26",
                ),
                docs_lead_headers,
            )
        )
        assert retried["status"] == "ASSIGNED"
        assert_committed_load_points(read_writer(bundle["writer_id"]), 52.00)


class TestCollisionOutranksCapacity:
    """When a request breaks the scheduling rule and the fiscal rule at once,
    both answer 409 and only the error id says which one was consulted."""

    def test_a_request_that_both_collides_and_overruns_reports_the_collision(
        self, api, docs_lead_headers
    ):
        """Scheduling is checked first, so capacity never gets to speak.

        PRD §3.2: "Then the window-collision check runs, and only if it passes is
        the capacity ceiling evaluated last."

        PRD §3.2: "Because this check runs after the window-collision check, an
        assignment that both collides and overruns reports the overlap."

        PRD §2.5: "And an assignment request that both collides with an existing
        authoring window and would overrun the writer's capacity reports the
        overlap."

        Design: Difficulty/priority_pair_validation_conflict/writer_window_overlap_beats_capacity_exceeded_rejected
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 30.0},
            feature_key="atlas-roles",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        second_item = create_plan_item(
            bundle["train_id"], feature_key="atlas-scopes", **STANDARD_ITEM
        )

        # 2026-08-10 falls inside 2026-08-03..2026-08-14, and 26.00 + 26.00 =
        # 52.00 would also break the 30-point ceiling.
        response = api.assign_plan_item(
            second_item["id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date="2026-08-10",
                window_end_date="2026-08-20",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.WRITER_WINDOW_OVERLAP, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.WRITER_CAPACITY_EXCEEDED.value

    def test_the_doubly_invalid_request_leaves_both_deliverables_as_they_were(
        self, api, docs_lead_headers
    ):
        """The refusal is total: no window stored, no points booked, nothing moved.

        PRD §2.5: "Checks are evaluated in the following order, and the first
        check that fails determines the response; no later check is evaluated once
        an earlier one has failed."

        PRD §3.2: "A writer's `committed_load_points` is the sum of `load_points`
        over the plan items assigned to them whose status is `ASSIGNED`,
        `IN_AUTHORING`, `IN_REVIEW`, `IN_REVISION`, or `APPROVED_CONTENT`,
        rounded half up to two decimal places, and `assignment_count` is the
        number of items in that same set."

        Design: Difficulty/priority_pair_validation_conflict/writer_window_overlap_beats_capacity_exceeded_rejected
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={"seniority_tier": "SENIOR", "capacity_points": 30.0},
            feature_key="atlas-roles",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        second_item = create_plan_item(
            bundle["train_id"], feature_key="atlas-scopes", **STANDARD_ITEM
        )

        validate_error(
            api.assign_plan_item(
                second_item["id"],
                assign_plan_item_payload(
                    bundle["writer_id"],
                    window_start_date="2026-08-10",
                    window_end_date="2026-08-20",
                ),
                docs_lead_headers,
            ),
            ApiErrorId.WRITER_WINDOW_OVERLAP,
            409,
        )

        refused = read_plan_item(second_item["id"])
        assert refused["status"] == "DRAFTED"
        assert refused["assigned_writer_id"] is None
        assert refused["window_start_date"] is None
        assert refused["load_points"] == pytest.approx(0.00, abs=0.01)

        writer = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        assert_committed_load_points(writer, 26.00)
        assert writer["assignment_count"] == 1

        held = read_plan_item(bundle["plan_item_id"])
        assert held["load_points"] == pytest.approx(26.00, abs=0.01)
        assert held["window_start_date"] == "2026-08-03"


class TestLedgerConservationAcrossAHandoff:
    """A deliverable handed from a senior writer to an associate and then cut
    must leave both ledgers exactly where they started."""

    def test_reassignment_moves_the_load_from_the_old_writer_to_the_new_one(
        self, api, docs_lead_headers
    ):
        """The old writer is debited by the old figure, the new one credited afresh.

        PRD §3.2: "When a `DocsLead` re-issues an assignment naming a different
        `writer_id`, the previous writer's `committed_load_points` decreases by
        the item's old `load_points` and their `assignment_count` decreases by 1;
        `load_points` is then recomputed from scratch against the new writer's
        seniority tier; and the new writer's `committed_load_points` increases by
        the freshly computed figure while their `assignment_count` increases by 1."

        PRD §3.2: "A writer's `committed_load_points` is the sum of `load_points`
        over the plan items assigned to them whose status is `ASSIGNED`,
        `IN_AUTHORING`, `IN_REVIEW`, `IN_REVISION`, or `APPROVED_CONTENT`,
        rounded half up to two decimal places, and `assignment_count` is the
        number of items in that same set."

        Design: Difficulty/compensating_invariant/writer_load_points_conserved_across_assign_reassign_cancel
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={
                "person_key": "w-sam",
                "full_name": "Sam Senior",
                "seniority_tier": "SENIOR",
                "capacity_points": 100.0,
            },
            feature_key="atlas-handoff",
            **STANDARD_ITEM,
        )
        associate = create_writer(
            person_key="w-alex",
            full_name="Alex Associate",
            seniority_tier="ASSOCIATE",
            capacity_points=100.0,
        )
        assert associate["committed_load_points"] == pytest.approx(0.00, abs=0.01)

        first = assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        assert first["load_points"] == pytest.approx(26.00, abs=0.01)
        assert_committed_load_points(read_writer(bundle["writer_id"]), 26.00)
        assert read_writer(bundle["writer_id"])["assignment_count"] == 1
        assert_committed_load_points(read_writer(associate["id"]), 0.00)

        assign_plan_item(
            bundle["plan_item_id"],
            associate["id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )

        senior_after = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        assert_committed_load_points(senior_after, 0.00)
        assert senior_after["assignment_count"] == 0

        associate_after = validate_success(api.get_writer(associate["id"], docs_lead_headers))
        assert_committed_load_points(associate_after, 32.50)
        assert associate_after["assignment_count"] == 1

    def test_the_same_deliverable_is_revalued_against_the_new_writers_seniority(
        self, api, docs_lead_headers
    ):
        """26.00 to a SENIOR writer is 32.50 to an ASSOCIATE, on the same window.

        PRD §3.2: "The seniority divisor means the same deliverable is genuinely
        worth different load points to different writers, which is why
        reassignment is a two-sided operation."

        PRD §3.2: "Fourth, those three figures are added together, the sum is
        multiplied by the audience multiplier — 1.5 for `CRITICAL`, 1.0 for
        `STANDARD`, 0.75 for `INTERNAL` — and the product is then divided by the
        seniority divisor of the *target writer* — 1.25 for `PRINCIPAL`, 1.0 for
        `SENIOR`, 0.80 for `ASSOCIATE`; the audience multiplication happens
        before the seniority division."

        PRD §3.2: "The comparison is made against the windows of the writer's
        other counted plan items only: reassigning the same plan item never
        collides with the window it currently occupies itself."

        Design: Difficulty/compensating_invariant/writer_load_points_conserved_across_assign_reassign_cancel
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={
                "person_key": "w-sam",
                "full_name": "Sam Senior",
                "seniority_tier": "SENIOR",
                "capacity_points": 100.0,
            },
            feature_key="atlas-handoff",
            **STANDARD_ITEM,
        )
        associate = create_writer(
            person_key="w-alex",
            full_name="Alex Associate",
            seniority_tier="ASSOCIATE",
            capacity_points=100.0,
        )
        senior_valuation = assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )

        reassigned = validate_success(
            api.assign_plan_item(
                bundle["plan_item_id"],
                assign_plan_item_payload(
                    associate["id"],
                    window_start_date="2026-08-03",
                    window_end_date="2026-08-14",
                ),
                docs_lead_headers,
            )
        )

        # (2*6 + 10 + 4) * 1.0 = 26.00 before the divisor; 26.00 / 0.80 = 32.50.
        assert senior_valuation["load_points"] == pytest.approx(26.00, abs=0.01)
        assert reassigned["load_points"] == pytest.approx(32.50, abs=0.01)
        assert reassigned["load_points"] == pytest.approx(
            expected_load_points(6, 10, "NEW_TOPIC", "STANDARD", "ASSOCIATE"), abs=0.01
        )
        assert reassigned["assigned_writer_id"] == associate["id"]
        assert reassigned["status"] == "ASSIGNED"
        assert reassigned["window_start_date"] == "2026-08-03"
        assert reassigned["window_end_date"] == "2026-08-14"

    def test_cancelling_after_the_handoff_returns_the_ledger_to_its_opening_value(
        self, api, docs_lead_headers
    ):
        """The compensating cancel leaves the associate at exactly 0.00 and 0.

        PRD §3.2: "The cancellation records the reason, clears
        `assigned_writer_id`, decreases the assigned writer's
        `committed_load_points` by the item's `load_points` and their
        `assignment_count` by 1, moves every sign-off on the item's topics that is
        not already `SUPERSEDED` to `SUPERSEDED`, returns each of those topics to
        `review_state` `NOT_SUBMITTED`, decrements the train's `plan_item_count`
        by 1, and recomputes the train's ratio and posture."

        PRD §2.8: "A create followed by its compensating cancel must return each
        affected ledger to precisely its pre-create value."

        PRD §3.1: "Third, `approved_topic_ratio` is `1.00` when `plan_item_count`
        is zero — a train with no counted deliverables is vacuously ready, not
        zero and not null — and otherwise the approved count divided by the total
        count, rounded half up to two decimal places."

        Design: Difficulty/compensating_invariant/writer_load_points_conserved_across_assign_reassign_cancel
        """
        set_clock(CLOCK)
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={
                "person_key": "w-sam",
                "full_name": "Sam Senior",
                "seniority_tier": "SENIOR",
                "capacity_points": 100.0,
            },
            feature_key="atlas-handoff",
            **STANDARD_ITEM,
        )
        associate = create_writer(
            person_key="w-alex",
            full_name="Alex Associate",
            seniority_tier="ASSOCIATE",
            capacity_points=100.0,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        assign_plan_item(
            bundle["plan_item_id"],
            associate["id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-14",
        )
        assert_committed_load_points(read_writer(associate["id"]), 32.50)

        cancelled = validate_success(
            api.cancel_plan_item(
                bundle["plan_item_id"],
                cancel_plan_item_payload(cancel_reason="feature cut from the release"),
                docs_lead_headers,
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["assigned_writer_id"] is None
        assert cancelled["cancel_reason"] == "feature cut from the release"

        released = validate_success(api.get_writer(associate["id"], docs_lead_headers))
        assert_committed_load_points(released, 0.00)
        assert released["assignment_count"] == 0
        assert_committed_load_points(read_writer(bundle["writer_id"]), 0.00)
        assert read_writer(bundle["writer_id"])["assignment_count"] == 0

        train = read_release_train(bundle["train_id"])
        assert train["plan_item_count"] == 0
        assert train["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)
        assert train["doc_readiness_posture"] == "OPEN"


class TestLedgerVisibility:
    """Every denormalised figure a write touches is already correct in that
    write's own response, not merely on some later read."""

    def test_every_derived_figure_is_correct_in_the_response_that_produced_it(
        self, api, docs_lead_headers
    ):
        """Create responses, the assign response, and the next read all agree.

        PRD §2.8: "Three fields in this system are **conserved quantities**: a
        writer's `committed_load_points`, a locale profile's
        `committed_source_words`, and a release train's
        `localization_committed_cents`."

        PRD §2.8: "Each is defined as an aggregate over a precisely specified set
        of child records, and each must, at every observable moment, equal exactly
        what a full recomputation over that set would produce."

        PRD §3.2: "A new plan item opens with `status` `DRAFTED`, `load_points` of
        `0.00`, and `rework_count` of 0, and its creation increments the train's
        `plan_item_count` and triggers a readiness recomputation."

        Design: Corner/consistency_model/writer_ledger_is_visible_in_the_same_response_that_changed_it
        """
        set_clock(CLOCK)

        train = create_release_train(**TRAIN)
        assert train["plan_item_count"] == 0

        writer = create_writer(
            person_key="w-anna",
            full_name="Anna Reyes",
            seniority_tier="SENIOR",
            capacity_points=40.0,
        )
        assert writer["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert writer["assignment_count"] == 0

        item = create_plan_item(train["id"], feature_key="feature-a", **STANDARD_ITEM)
        assert item["status"] == "DRAFTED"
        assert item["load_points"] == pytest.approx(0.00, abs=0.01)

        assert read_release_train(train["id"])["plan_item_count"] == 1

        assigned = validate_success(
            api.assign_plan_item(
                item["id"],
                assign_plan_item_payload(
                    writer["id"],
                    window_start_date="2026-08-03",
                    window_end_date="2026-08-17",
                ),
                docs_lead_headers,
            )
        )
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_writer_id"] == writer["id"]
        assert assigned["load_points"] == pytest.approx(26.00, abs=0.01)

        first_read = validate_success(api.get_writer(writer["id"], docs_lead_headers))
        assert_committed_load_points(first_read, 26.00)
        assert first_read["assignment_count"] == 1

        second_read = validate_success(api.get_writer(writer["id"], docs_lead_headers))
        assert second_read["committed_load_points"] == pytest.approx(
            first_read["committed_load_points"], abs=0.01
        ), "the ledger must not drift or converge late between two identical reads"
        assert second_read["assignment_count"] == first_read["assignment_count"]


class TestCancellationReleasesTheWriter:
    """One cancel call is the compensating half of assignment, and it has to
    settle the writer's ledger, the page's review slate, and the train at once."""

    def _deliverable_in_review_with_two_pending_signoffs(self) -> dict:
        bundle = plan_item_context(
            train_overrides=TRAIN,
            writer_overrides={
                "person_key": "w-anna",
                "full_name": "Anna Reyes",
                "seniority_tier": "SENIOR",
                "capacity_points": 40.0,
            },
            feature_key="feature-a",
            **STANDARD_ITEM,
        )
        assign_plan_item(
            bundle["plan_item_id"],
            bundle["writer_id"],
            window_start_date="2026-08-03",
            window_end_date="2026-08-17",
        )
        topic = create_topic(
            bundle["plan_item_id"],
            bundle["writer_id"],
            slug="atlas-feature-a",
            title="Feature A guide",
        )
        create_revision(
            topic["id"],
            bundle["writer_id"],
            body_word_count=1200,
            used_terms=["dashboard"],
            summary="First draft of the feature A guide",
        )
        submit_topic(topic["id"], bundle["writer_id"])
        engineering = create_reviewer(
            person_key="r-erin", full_name="Erin Cole", discipline="ENGINEERING"
        )
        product = create_reviewer(
            person_key="r-dana", full_name="Dana Ruiz", discipline="PRODUCT"
        )
        bundle.update(
            topic_id=topic["id"],
            engineering_reviewer=engineering,
            product_reviewer=product,
            engineering_signoff=request_signoff(topic["id"], engineering["id"]),
            product_signoff=request_signoff(topic["id"], product["id"]),
        )
        return bundle

    def test_cancelling_a_deliverable_in_review_releases_its_writer(
        self, api, docs_lead_headers
    ):
        """The writer's ledger returns to zero while the item keeps its price.

        PRD §3.2: "The cancellation records the reason, clears
        `assigned_writer_id`, decreases the assigned writer's
        `committed_load_points` by the item's `load_points` and their
        `assignment_count` by 1, moves every sign-off on the item's topics that is
        not already `SUPERSEDED` to `SUPERSEDED`, returns each of those topics to
        `review_state` `NOT_SUBMITTED`, decrements the train's `plan_item_count`
        by 1, and recomputes the train's ratio and posture."

        PRD §3.2: "Items that are `PUBLISHED` or `CANCELLED` are excluded, because
        publishing and cancelling both *release* capacity."

        Design: Corner/endpoints/plan_item_cancel_action_supersedes_signoffs_and_releases_the_writer
        """
        set_clock(CLOCK)
        bundle = self._deliverable_in_review_with_two_pending_signoffs()
        before = read_writer(bundle["writer_id"])
        assert_committed_load_points(before, 26.00)
        assert before["assignment_count"] == 1

        cancelled = validate_success(
            api.cancel_plan_item(
                bundle["plan_item_id"],
                cancel_plan_item_payload(cancel_reason="Feature pulled from the release"),
                docs_lead_headers,
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["assigned_writer_id"] is None
        assert cancelled["cancel_reason"] == "Feature pulled from the release"
        assert cancelled["load_points"] == pytest.approx(26.00, abs=0.01), (
            "the price of the cancelled deliverable is retained as history"
        )

        released = validate_success(api.get_writer(bundle["writer_id"], docs_lead_headers))
        assert_committed_load_points(released, 0.00)
        assert released["assignment_count"] == 0

    def test_cancelling_supersedes_every_open_signoff_and_resets_the_page(
        self, api, docs_lead_headers
    ):
        """Both pending sign-offs are superseded and both reviewers freed.

        PRD §3.5: "Sign-offs also reach `SUPERSEDED` without any reviewer acting,
        driven by the system rather than a request: a new source revision on the
        topic supersedes every sign-off in state `PENDING` or `APPROVED`, a sibling
        reviewer's changes-requested decision supersedes the others, and cancelling
        the plan item supersedes all of them."

        PRD §3.5: "In every such case `pinned_revision_number` is cleared, and
        where the prior state was `PENDING` the reviewer's `open_signoff_count`
        decreases by 1; where the prior state was `APPROVED` there is no open count
        to adjust, since it was already released when the approval was recorded."

        PRD §3.2: "The cancellation records the reason, clears
        `assigned_writer_id`, decreases the assigned writer's
        `committed_load_points` by the item's `load_points` and their
        `assignment_count` by 1, moves every sign-off on the item's topics that is
        not already `SUPERSEDED` to `SUPERSEDED`, returns each of those topics to
        `review_state` `NOT_SUBMITTED`, decrements the train's `plan_item_count`
        by 1, and recomputes the train's ratio and posture."

        Design: Corner/endpoints/plan_item_cancel_action_supersedes_signoffs_and_releases_the_writer
        """
        set_clock(CLOCK)
        bundle = self._deliverable_in_review_with_two_pending_signoffs()
        assert bundle["engineering_signoff"]["state"] == "PENDING"
        assert bundle["product_signoff"]["state"] == "PENDING"

        validate_success(
            api.cancel_plan_item(
                bundle["plan_item_id"],
                cancel_plan_item_payload(cancel_reason="Feature pulled from the release"),
                docs_lead_headers,
            )
        )

        for key in ("engineering_signoff", "product_signoff"):
            signoff = validate_success(
                api.get_signoff(bundle[key]["id"], docs_lead_headers)
            )
            assert signoff["state"] == "SUPERSEDED"
            assert signoff["pinned_revision_number"] is None

        assert read_reviewer(bundle["engineering_reviewer"]["id"])["open_signoff_count"] == 0
        assert read_reviewer(bundle["product_reviewer"]["id"])["open_signoff_count"] == 0

        topic = read_topic(bundle["topic_id"])
        assert topic["review_state"] == "NOT_SUBMITTED"
        assert topic["publication_state"] == "UNPUBLISHED"

        train = read_release_train(bundle["train_id"])
        assert train["plan_item_count"] == 0
        assert train["approved_plan_item_count"] == 0
        assert train["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)
