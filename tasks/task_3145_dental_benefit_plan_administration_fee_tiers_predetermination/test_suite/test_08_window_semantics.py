"""Window conventions at the boundary.

Fee schedule windows are half-open — a retroactive insertion overlapping an
existing ACTIVE schedule is refused, while a successor starting exactly
where the predecessor ends is adjacent, not overlapping.  Frequency
windows, by contrast, are closed on both ends over a patient's paid
history.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_SCHEDULE_OVERLAP
from test_helpers.assertions import get_success_data, validate_error
from test_helpers.constants import (
    CATEGORY_PREVENTIVE,
    CDT_PERIODIC_EVAL,
    CLAIM_DENIED,
    DENIAL_FREQUENCY,
    SCHEDULE_ACTIVE,
    SCHEDULE_PENDING,
)
from test_helpers.fixtures import (
    claim_lines,
    create_active_fee_schedule,
    create_claim,
    create_fee_schedule,
    create_limitation_rule,
    pay_claim,
    read_fee_schedule,
    set_clock,
    standard_stack,
    subscriber_accumulators,
)
from test_helpers.test_users import NETWORK


class TestFeeScheduleWindowOverlapAndAdjacency:
    """Half-open [effective_from, effective_to) over the same tier."""

    def test_retroactive_insertion_overlapping_active_window_is_rejected(self, client):
        """A new window starting before the existing one cannot activate.

        PRD 2.8: "The mirror-image case is forbidden: activating a schedule
        that would overlap an existing `ACTIVE` same-tier schedule whose
        `effective_from` is strictly later than the new one's (a retroactive
        insertion) is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/fee_schedule_half_open_window_overlap_and_adjacency
        """
        set_clock(client, "2026-01-01T00:00:00Z")
        entries = [
            f.fee_schedule_entry_payload(cdt_code=CDT_PERIODIC_EVAL, allowed_cents=5000)
        ]
        schedule_a = create_active_fee_schedule(
            client,
            entries=entries,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-01T00:00:00Z",
        )
        retro = create_fee_schedule(
            client, entries=entries, effective_from="2025-06-01T00:00:00Z"
        )

        resp = client.activate_fee_schedule(retro["id"], headers=NETWORK)

        validate_error(resp, ERR_SCHEDULE_OVERLAP, expected_status=409)
        refreshed = read_fee_schedule(client, retro["id"])
        assert refreshed["status"] == SCHEDULE_PENDING, (
            "a rejected activation leaves the schedule PENDING"
        )

    def test_adjacent_window_activates_without_truncating(self, client):
        """A successor starting exactly at effective_to shares no instant.

        PRD 2.8: "a schedule applies to work whose anchor date falls on or
        after `effective_from` and strictly before `effective_to`."
        PRD 2.8: "When a `NetworkManager` activates a new schedule, any
        existing `ACTIVE` schedule for the same tier whose `effective_from`
        is on or before the new schedule's `effective_from` has its
        `effective_to` set to the new schedule's `effective_from` — its
        window is truncated but its status remains `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/fee_schedule_half_open_window_overlap_and_adjacency
        """
        set_clock(client, "2026-01-01T00:00:00Z")
        entries = [
            f.fee_schedule_entry_payload(cdt_code=CDT_PERIODIC_EVAL, allowed_cents=5000)
        ]
        schedule_a = create_active_fee_schedule(
            client,
            entries=entries,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-01T00:00:00Z",
        )
        adjacent = create_fee_schedule(
            client, entries=entries, effective_from="2026-06-01T00:00:00Z"
        )

        activated = get_success_data(
            client.activate_fee_schedule(adjacent["id"], headers=NETWORK)
        )

        assert activated["status"] == SCHEDULE_ACTIVE
        refreshed_a = read_fee_schedule(client, schedule_a["id"])
        assert refreshed_a["effective_to"] == "2026-06-01T00:00:00Z", (
            "adjacency shares no instant, so the predecessor is untouched"
        )
        assert refreshed_a["status"] == SCHEDULE_ACTIVE


class TestFrequencyWindowIsInclusiveOnBothEnds:
    """Two paid cleanings in six months; the third is denied."""

    def _to2_stack(self, client):
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-TO2"},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_PERIODIC_EVAL, allowed_cents=5000,
                    category=CATEGORY_PREVENTIVE,
                ),
            ],
            subscriber_overrides={
                "member_id": "M-TO2",
                "full_name": "Owen Prime",
                "effective_date": "2025-01-01T00:00:00Z",
            },
        )
        create_limitation_rule(
            client,
            stack["plan"]["id"],
            cdt_code=CDT_PERIODIC_EVAL,
            rule_kind="FREQUENCY",
            window_months=6,
            max_occurrences=2,
        )
        return stack

    def _paid_cleaning(self, client, stack, service_date, received_date):
        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            service_date=service_date,
            received_date=received_date,
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_PERIODIC_EVAL, tooth_number="",
                    submitted_amount_cents=5000,
                )
            ],
        )
        pay_claim(client, claim["id"])
        return claim

    def test_cleaning_exactly_six_months_after_the_prior_counts(self, client):
        """The left edge of the window counts toward the cap.

        PRD 3.7: "A `FREQUENCY` rule counts the patient's prior claim lines
        with the same `cdt_code` that sit on `PAID` claims in `PAYABLE`
        status and whose service dates fall within the rolling window — from
        `window_months` before this service date through this service date,
        inclusive on both ends; if adding this line would push the count
        past `max_occurrences`, the line is denied `FREQUENCY`."

        Design: Difficulty/resource_temporal_overlap/frequency_rolling_window_inclusive_both_ends
        """
        stack = self._to2_stack(client)
        self._paid_cleaning(client, stack, "2026-01-15T00:00:00Z", "2026-01-16T00:00:00Z")

        # The prior paid cleaning on 2026-01-15 sits exactly on the window's
        # left edge for a service on 2026-07-15 — it counts, so 1 + 1 <= 2.
        claim_2 = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            service_date="2026-07-15T00:00:00Z",
            received_date="2026-07-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_PERIODIC_EVAL, tooth_number="",
                    submitted_amount_cents=5000,
                )
            ],
        )

        line = claim_lines(client, claim_2["id"])[0]
        assert line["status"] == "PAYABLE", (
            "the second cleaning within the cap must pay, got %r" % line["status"]
        )

    def test_third_cleaning_inside_the_closed_window_is_denied(self, client):
        """Two priors inside the window push the third past the cap.

        PRD 3.7: "A `FREQUENCY` rule counts the patient's prior claim lines
        with the same `cdt_code` that sit on `PAID` claims in `PAYABLE`
        status and whose service dates fall within the rolling window — from
        `window_months` before this service date through this service date,
        inclusive on both ends; if adding this line would push the count
        past `max_occurrences`, the line is denied `FREQUENCY`."
        PRD 3.7: "When every line denies, the claim itself transitions
        `ADJUDICATED → DENIED` automatically and no accumulator changes
        attach to it."

        Design: Difficulty/resource_temporal_overlap/frequency_rolling_window_inclusive_both_ends
        """
        stack = self._to2_stack(client)
        self._paid_cleaning(client, stack, "2026-01-15T00:00:00Z", "2026-01-16T00:00:00Z")
        self._paid_cleaning(client, stack, "2026-07-15T00:00:00Z", "2026-07-16T00:00:00Z")

        claim_3 = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            service_date="2026-07-15T00:00:00Z",
            received_date="2026-07-16T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_PERIODIC_EVAL, tooth_number="",
                    submitted_amount_cents=5000,
                )
            ],
        )

        assert claim_3["status"] == CLAIM_DENIED
        line = claim_lines(client, claim_3["id"])[0]
        assert line["denial_code"] == DENIAL_FREQUENCY

        accumulators = subscriber_accumulators(client, stack["subscriber"]["id"])
        assert accumulators[0]["annual_max_used_cents"] == 10000, (
            "only the two paid cleanings drew against the maximum"
        )
