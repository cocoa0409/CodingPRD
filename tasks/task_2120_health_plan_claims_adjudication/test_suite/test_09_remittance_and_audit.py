"""Remittance issue, the append-only audit trail, the logical clock and immediate reads."""
import pytest

from test_helpers import (
    DEFAULT_LOGICAL_CLOCK_STAMP,
    assert_adjudication_event,
    claim_line_payload,
    finalize,
    get_accumulator,
    get_events,
    lines_by_number,
    setup_auth_gated_environment,
    setup_environment,
    setup_imaging_environment,
    submit_and_adjudicate,
    submit_claim,
    validate_paginated,
)
from test_helpers.fixtures import CLAIMS_EXAMINER


class TestAdjudicationEventLog:
    def test_the_event_log_reads_oldest_first_across_intake_adjudicate_and_finalize(
        self, api
    ):
        """PRD §2.3: "A claim's adjudication event log is returned oldest first, so the log
        reads as a chronological narrative."
        PRD §3.9: "Every lifecycle movement of a claim appends one immutable adjudication
        event, and the log for a claim may be read by any role with claim visibility,
        filtered by `pass_number` or by `event_type`."

        Design: Corner/endpoints/claim_event_log_is_returned_oldest_first_after_intake_adjudicate_and_finalize
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "EP-1", "name": "Endpoint Plan One"},
            provider_overrides={"npi": "4000000001", "name": "EP1 Clinic"},
            member_overrides={"member_number": "M-EP-1"},
        )
        adjudicated = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], "CLM-EP-1"
        )
        finalize(adjudicated["id"])

        events, meta = validate_paginated(api.list_events(adjudicated["id"], CLAIMS_EXAMINER))
        assert meta["total_count"] == 3
        assert [event["event_type"] for event in events] == [
            "INTAKE",
            "ADJUDICATE",
            "FINALIZE",
        ]
        assert events[0]["pass_number"] == 0
        assert events[0]["to_status"] == "RECEIVED"
        assert events[1]["pass_number"] == 1
        assert events[1]["from_status"] == "RECEIVED"
        assert events[1]["to_status"] == "ADJUDICATED"
        assert events[2]["from_status"] == "ADJUDICATED"
        assert events[2]["to_status"] == "FINALIZED"

        _rows, filtered_meta = validate_paginated(
            api.list_events(adjudicated["id"], CLAIMS_EXAMINER, params={"event_type": "FINALIZE"})
        )
        assert filtered_meta["total_count"] == 1

    def test_an_event_row_carries_no_version_and_no_updated_at(self, api):
        """PRD §2.4: "One resource is deliberately leaner. An adjudication event is an
        append-only audit record: it carries `id` and `created_at` and nothing else from the
        common set. It has no `updated_at` and no `version`, because it is never mutated
        after it is appended."

        Design: Corner/entities/adjudication_event_log_rows_are_immutable_and_carry_no_version_field
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "IMM-1", "name": "Immutability Plan"},
            provider_overrides={"npi": "2000000003", "name": "IMM Clinic"},
            member_overrides={"member_number": "M-IMM-1"},
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-IMM-1",
        )
        events = get_events(claim["id"])
        assert len(events) == 1
        event = events[0]
        assert_adjudication_event(event)
        assert event["event_type"] == "INTAKE"
        assert event["to_status"] == "RECEIVED"
        assert event["pass_number"] == 0
        assert event["claim_id"] == claim["id"]
        assert "version" not in event
        assert "updated_at" not in event


class TestLogicalClock:
    def test_the_clock_reads_its_startup_default_before_any_set_call(self, api):
        """PRD §2.4: "Before the clock has ever been set, it reads exactly
        `2026-08-01T00:00:00Z`; the engine must never fall back to real wall-clock time for
        these comparisons."
        PRD §3.4: "`received_at` is stamped from the logical clock as an ISO 8601 UTC instant
        with three fractional digits."

        Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "EP-2", "name": "Endpoint Plan Two"},
            provider_overrides={"npi": "4000000002", "name": "EP2 Clinic"},
            member_overrides={"member_number": "M-EP-2"},
            clock=None,
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-07-15")],
            "CLM-EP-2",
        )
        assert claim["received_at"] == DEFAULT_LOGICAL_CLOCK_STAMP
        assert claim["status"] == "RECEIVED", (
            "17 whole days is comfortably inside the 90-day filing window"
        )
        events = get_events(claim["id"])
        assert len(events) == 1
        assert events[0]["event_type"] == "INTAKE"


class TestClaimLineCrossReferences:
    def test_claim_lines_can_be_narrowed_to_the_grant_they_are_holding_units_for(self, api):
        """PRD §3.9: "and individual service lines are readable both singly and as a filtered
        list narrowed by `claim_id`, `authorization_id` or `line_status` — the latter being
        how an operator finds every line a given authorization is holding units for."

        Design: Corner/endpoints/list_claim_lines_filtered_by_authorization_id_returns_only_linked_lines
        """
        env = setup_auth_gated_environment(
            authorized_units=4,
            plan_overrides={"plan_code": "EP-3", "name": "Endpoint Plan Three"},
            provider_overrides={"npi": "4000000003", "name": "EP3 Imaging"},
            member_overrides={"member_number": "M-EP-3"},
            rule_code="MP-73721-AUTH-EP3",
            rates=[("73721", 40000, "2026-01-01"), ("99213", 10000, "2026-01-01")],
        )
        gated = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 2, 100000, "2026-02-10")], "CLM-EP-3A"
        )
        ungated = submit_and_adjudicate(
            env, [claim_line_payload(1, "99213", 1, 20000, "2026-02-11")], "CLM-EP-3B"
        )

        rows, meta = validate_paginated(
            api.list_claim_lines(
                CLAIMS_EXAMINER, params={"authorization_id": env["authorization"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["claim_id"] == gated["id"]
        assert rows[0]["line_status"] == "PRICED"
        assert rows[0]["authorization_id"] == env["authorization"]["id"]

        ungated_lines = lines_by_number(ungated["id"])
        assert ungated_lines[1]["authorization_id"] is None


class TestImmediateConsistencyAtFinalization:
    def test_finalize_is_immediately_visible_in_the_remittance_and_the_accumulator(
        self, api
    ):
        """PRD §3.9: "The remittance's `remit_number` is deterministic rather than random: it
        is formatted as `RA-` followed by the claim's `claim_number`, followed by a hyphen and
        the 1-based count of remittances previously issued for that claim, so the first
        remittance on claim `C-1001` is `RA-C-1001-1`."
        PRD §3.9: "From `ADJUDICATED`, finalizing applies `ADJUDICATED → FINALIZED` and
        creates one remittance advice in `status` `ISSUED` that snapshots the claim's figures:
        its `total_allowed_cents`, `total_plan_paid_cents` and `total_member_liability_cents`
        are copied from the claim, its `total_other_payer_paid_cents` is copied from the
        claim's `other_payer_paid_cents` and is recorded as 0 when that value is null, its
        `claim_id` names the claim, and its `issued_at` is stamped from the logical clock."
        PRD §3.9: "Every service line standing at `PRICED` flips `PRICED → PAID`, freezing its
        money fields as snapshotted."

        Design: Corner/consistency_model/finalize_response_and_immediate_reads_reflect_the_posted_accumulator
        """
        env = setup_environment(
            plan_overrides={
                "plan_code": "CM-1",
                "name": "Consistency Plan One",
                "deductible_individual_cents": 40000,
                "oop_max_individual_cents": 300000,
                "coinsurance_member_pct": 0.20,
            },
            provider_overrides={"npi": "7000000001", "name": "CM1 Clinic"},
            member_overrides={"member_number": "M-CM-1"},
            rates=[("73721", 50000, "2026-01-01")],
        )
        adjudicated = submit_and_adjudicate(
            env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], "CLM-CM-1"
        )
        assert adjudicated["total_deductible_applied_cents"] == 40000
        assert adjudicated["total_member_liability_cents"] == 42000
        assert adjudicated["total_plan_paid_cents"] == 8000

        finalized = finalize(adjudicated["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["payment_status"] == "REMITTED"

        remittances, remit_meta = validate_paginated(
            api.list_remittances(adjudicated["id"], CLAIMS_EXAMINER)
        )
        assert remit_meta["total_count"] == 1
        remittance = remittances[0]
        assert remittance["remit_number"] == "RA-CLM-CM-1-1"
        assert remittance["status"] == "ISSUED"
        assert remittance["total_plan_paid_cents"] == 8000
        assert remittance["total_member_liability_cents"] == 42000
        assert remittance["total_allowed_cents"] == 50000
        assert remittance["total_other_payer_paid_cents"] == 0

        accumulator = get_accumulator(env["member"]["id"])
        assert accumulator["deductible_applied_cents"] == 40000
        assert accumulator["oop_applied_cents"] == 42000
        assert accumulator["remitted_claim_count"] == 1

        assert lines_by_number(adjudicated["id"])[1]["line_status"] == "PAID"
