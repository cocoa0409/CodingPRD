"""837 intake: what the server mints, what it rejects, and how duplicates are screened."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_CLOCK_STAMP,
    claim_line_payload,
    create_claim_payload,
    lines_by_number,
    set_clock,
    setup_duplicate_pair,
    setup_imaging_environment,
    setup_open_plan_environment,
    submit_claim,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import CLAIMS_EXAMINER, CLAIMS_INTAKE


class TestDuplicateBilledTolerance:
    def test_a_gap_of_exactly_five_hundred_cents_is_a_duplicate(self, api):
        """PRD §3.4: "A prior claim matches when at least one of its service lines and at
        least one line of the incoming claim agree on all of the following: the same
        `procedure_code`; the same `modifier_code` after normalising a null modifier to the
        empty string, so that an absent modifier and an explicitly empty one are the same
        thing; the same `service_date`; the same `units`; and billed charges that differ by
        no more than five dollars — a tolerance of 500 cents, applied inclusively, so a gap
        of exactly 500 cents **is** a duplicate and a gap of 501 cents is not."
        PRD §3.4: "When a match is found, the incoming claim is still persisted — the point
        is that the rejection is auditable — but it moves straight
        `RECEIVED → DUPLICATE_REJECTED`, records the winner's identifier in
        `duplicate_of_claim_id`, stamps `deny_reason_code` with `DENY_DUPLICATE`, and appends
        an adjudication event of type `DUPLICATE_REJECT` at pass number zero."

        Design: Difficulty/boundary_precision_check/duplicate_billed_tolerance_is_inclusive_at_exactly_500_cents
        """
        env = setup_duplicate_pair(baseline_billed=10000, duplicate_billed=10500)
        assert env["baseline_claim"]["status"] == "RECEIVED"
        repeat = env["repeat_claim"]
        assert repeat["status"] == "DUPLICATE_REJECTED"
        assert repeat["duplicate_of_claim_id"] == env["baseline_claim"]["id"]
        assert repeat["deny_reason_code"] == "DENY_DUPLICATE"

    def test_a_gap_of_five_hundred_and_one_cents_is_not_a_duplicate(self, api):
        """PRD §3.4: "A prior claim matches when at least one of its service lines and at
        least one line of the incoming claim agree on all of the following: the same
        `procedure_code`; the same `modifier_code` after normalising a null modifier to the
        empty string, so that an absent modifier and an explicitly empty one are the same
        thing; the same `service_date`; the same `units`; and billed charges that differ by
        no more than five dollars — a tolerance of 500 cents, applied inclusively, so a gap
        of exactly 500 cents **is** a duplicate and a gap of 501 cents is not."
        PRD §3.4: "When no match is found, the claim stays at `RECEIVED` and an adjudication
        event of type `INTAKE` is appended instead."

        Design: Difficulty/boundary_precision_check/duplicate_billed_tolerance_is_inclusive_at_exactly_500_cents
        """
        env = setup_duplicate_pair(baseline_billed=10000, duplicate_billed=10500)
        outside = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "99213", 1, 10501, "2026-02-10")],
            "CLM-DUP-C",
        )
        assert outside["status"] == "RECEIVED", "501 cents is outside the tolerance"
        assert outside["duplicate_of_claim_id"] is None

    def test_claim_list_filtered_by_duplicate_of_claim_id_returns_the_rejected_claim(
        self, api
    ):
        """PRD §3.4: "Claim listings support narrowing by `member_id`, `provider_id`,
        `coverage_id`, `original_claim_id`, `duplicate_of_claim_id`, `status` and
        `claim_type`, which is how an operator walks the self-referential chains — from a
        duplicate back to the claim it duplicated, or from an adjustment back to the claim it
        replaced."

        Design: Corner/entities/get_claims_filtered_by_duplicate_of_claim_id_returns_only_the_rejected_claim
        """
        env = setup_duplicate_pair(baseline_billed=10000, duplicate_billed=10200)
        baseline, repeat = env["baseline_claim"], env["repeat_claim"]
        assert repeat["status"] == "DUPLICATE_REJECTED"

        rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"duplicate_of_claim_id": baseline["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == repeat["id"]
        assert rows[0]["status"] == "DUPLICATE_REJECTED"

        _rows, empty_meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"duplicate_of_claim_id": repeat["id"]})
        )
        assert empty_meta["total_count"] == 0, (
            "A duplicate-rejected claim never seeds a further duplicate of its own"
        )


class TestClaimIntakeShape:
    def test_a_new_claim_carries_only_server_minted_lifecycle_fields(self, api):
        """PRD §3.4: "A newly received claim opens at `status` `RECEIVED`, `payment_status`
        `NOT_REMITTED`, `claim_type` `ORIGINAL`, `adjudication_pass` zero, `pricing_variant`
        `UNPRICED`, and `original_claim_id`, `duplicate_of_claim_id`, `pend_reason_code`,
        `deny_reason_code` and `last_adjudicated_by_user_id` all null."
        PRD §3.4: "When `statement_from_date` is omitted it defaults to the earliest
        `service_date` among the submitted lines; when `statement_to_date` is omitted it
        defaults to the latest."
        PRD §2.4: "`version` is an integer that starts at `1` when the row is created and
        increases by exactly one on every mutation the server performs on that row, including
        mutations the row suffers as a side effect of an operation aimed at some other
        resource."

        Design: Corner/entities/claim_system_fields_received_at_status_and_version_are_server_minted
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "SF-1", "name": "System Fields Plan"},
            provider_overrides={"npi": "2000000002", "name": "SF Clinic"},
            member_overrides={"member_number": "M-SF-1"},
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-SF-1",
        )
        assert claim["received_at"] == TEST_CLOCK_STAMP, (
            "received_at is stamped from the logical clock with three fractional digits"
        )
        assert claim["status"] == "RECEIVED"
        assert claim["payment_status"] == "NOT_REMITTED"
        assert claim["claim_type"] == "ORIGINAL"
        assert claim["adjudication_pass"] == 0
        assert claim["pricing_variant"] == "UNPRICED"
        assert claim["version"] == 1
        assert claim["original_claim_id"] is None
        assert claim["duplicate_of_claim_id"] is None
        assert claim["pend_reason_code"] is None
        assert claim["deny_reason_code"] is None
        assert claim["last_adjudicated_by_user_id"] is None
        assert claim["coverage_id"] == env["coverage"]["id"]
        assert claim["statement_from_date"] == "2026-02-10"
        assert claim["statement_to_date"] == "2026-02-10"

    def test_line_money_fields_start_at_zero_while_the_billed_total_is_already_summed(
        self, api
    ):
        """PRD §3.4: "Every line is persisted with its owning `claim_id` filled in by the
        server and with `line_status` at `PENDING`; its computed money fields —
        `allowed_amount_cents`, `deductible_applied_cents`, `copay_cents`,
        `coinsurance_cents`, `member_liability_cents` and `plan_paid_cents` — all start at
        zero, and `authorization_id`, `bundled_into_line_number` and `edit_reason_code` all
        start null."
        PRD §3.4: "The claim's `total_billed_cents` is computed at intake as the sum of the
        submitted `billed_amount_cents` values, and `received_at` is stamped from the logical
        clock as an ISO 8601 UTC instant with three fractional digits."

        Design: Corner/entities/claim_line_computed_money_fields_are_zero_before_first_adjudication
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "CF-1", "name": "Computed Fields Plan"},
            provider_overrides={"npi": "2000000001", "name": "CF Clinic"},
            member_overrides={"member_number": "M-CF-1"},
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [
                claim_line_payload(1, "73721", 1, 40000, "2026-02-10"),
                claim_line_payload(2, "73721", 1, 50000, "2026-02-11"),
            ],
            "CLM-CF-1",
        )
        assert claim["total_billed_cents"] == 90000
        assert claim["total_allowed_cents"] == 0
        assert claim["pricing_variant"] == "UNPRICED"

        lines = lines_by_number(claim["id"])
        assert len(lines) == 2
        for number in (1, 2):
            line = lines[number]
            assert line["claim_id"] == claim["id"]
            assert line["line_status"] == "PENDING"
            assert line["allowed_amount_cents"] == 0
            assert line["deductible_applied_cents"] == 0
            assert line["copay_cents"] == 0
            assert line["coinsurance_cents"] == 0
            assert line["member_liability_cents"] == 0
            assert line["plan_paid_cents"] == 0
            assert line["authorization_id"] is None
            assert line["bundled_into_line_number"] is None
            assert line["edit_reason_code"] is None

    def test_an_unknown_body_member_id_returns_member_not_found(self, api):
        """PRD §2.8: "4. **Body foreign-key existence** — every foreign key supplied in a
        request body resolves to an existing row, reported as `ERR_PLAN_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND` or `ERR_PROVIDER_NOT_FOUND` with HTTP 404. This applies to
        member enrolment, contract drafting, authorization issuance and claim intake."

        Design: Corner/entities/claim_intake_with_unknown_member_id_returns_member_not_found
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "FK-1", "name": "FK Plan"},
            provider_overrides={"npi": "2000000004", "name": "FK Clinic"},
            with_member=False,
            coverages=None,
        )
        payload = create_claim_payload(
            "00000000-0000-4000-8000-000000000001",
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            claim_number="CLM-FK-1",
        )
        validate_error(api.create_claim(payload, CLAIMS_INTAKE), ApiErrorId.ERR_MEMBER_NOT_FOUND.value)

        _rows, meta = validate_paginated(api.list_claims(CLAIMS_EXAMINER))
        assert meta["total_count"] == 0, "No claim row may survive the rejected intake"

    def test_an_empty_lines_array_returns_claim_no_lines(self, api):
        """PRD §3.4: "An empty or absent `lines` array is rejected with `ERR_CLAIM_NO_LINES`
        and HTTP 422."

        Design: Corner/validations/claim_with_an_empty_lines_array_returns_claim_no_lines
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "VAL-1", "name": "Validation Plan One"},
            provider_overrides={"npi": "3000000001", "name": "VAL1 Clinic"},
            member_overrides={"member_number": "M-VAL-1"},
        )
        payload = create_claim_payload(
            env["member"]["id"], env["provider"]["id"], [], claim_number="CLM-VAL-1"
        )
        validate_error(api.create_claim(payload, CLAIMS_INTAKE), ApiErrorId.ERR_CLAIM_NO_LINES.value)

        _rows, meta = validate_paginated(api.list_claims(CLAIMS_EXAMINER))
        assert meta["total_count"] == 0

    def test_reusing_a_claim_number_returns_duplicate_claim_number(self, api):
        """PRD §3.4: "The submission carries the submitter-assigned control number as
        `claim_number`, which must be unique across every claim in the system
        (`ERR_DUPLICATE_CLAIM_NUMBER` otherwise), the `member_id` of the patient, the
        `provider_id` of the billing provider, and a `lines` array holding at least one
        service line."

        Design: Corner/validations/reusing_a_claim_number_returns_duplicate_claim_number
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "VAL-10", "name": "Validation Plan Ten"},
            provider_overrides={"npi": "3000000010", "name": "VAL10 Clinic"},
            member_overrides={"member_number": "M-VAL-10"},
            rates=[("99213", 10000, "2026-01-01")],
        )
        submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "99213", 1, 10000, "2026-02-10")],
            "CLM-VAL-10",
        )
        payload = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "99213", 2, 30000, "2026-02-20")],
            claim_number="CLM-VAL-10",
        )
        validate_error(
            api.create_claim(payload, CLAIMS_INTAKE), ApiErrorId.ERR_DUPLICATE_CLAIM_NUMBER.value
        )

        _rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"member_id": env["member"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_a_member_with_no_coverage_rows_cannot_have_a_claim_opened(self, api):
        """PRD §3.4: "**Coverage on file** then requires the member to have at least one
        coverage segment of any status whatsoever; a member with none at all cannot have a
        claim opened for them, and the attempt returns `ERR_MEMBER_NO_COVERAGE` with HTTP
        422."

        Design: Corner/validations/claim_for_a_member_with_no_coverage_rows_returns_member_no_coverage
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "VAL-8", "name": "Validation Plan Eight"},
            provider_overrides={"npi": "3000000008", "name": "VAL8 Clinic"},
            member_overrides={"member_number": "M-VAL-8"},
            coverages=None,
        )
        payload = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            claim_number="CLM-VAL-8",
        )
        validate_error(
            api.create_claim(payload, CLAIMS_INTAKE), ApiErrorId.ERR_MEMBER_NO_COVERAGE.value
        )

        _rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"member_id": env["member"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_timely_filing_accepts_exactly_ninety_days_and_refuses_ninety_one(self, api):
        """PRD §3.4: "**Timely filing** measures the whole-day distance between the claim's
        `statement_to_date` and the logical clock date at the moment of intake, and compares
        it against the plan's `timely_filing_days`. A distance exactly equal to the window is
        **accepted**; only a strictly greater distance is refused, with
        `ERR_TIMELY_FILING_EXCEEDED` and HTTP 422. On a plan left at its default, that means
        a claim whose statement period closed 90 days ago still files, and one whose
        statement period closed 91 days ago does not."

        Design: Corner/validations/timely_filing_at_exactly_ninety_days_is_accepted_and_ninety_one_is_rejected
        """
        env = setup_open_plan_environment(
            plan_overrides={
                "plan_code": "VAL-5",
                "name": "Validation Plan Five",
                "timely_filing_days": 90,
            },
            provider_overrides={"npi": "3000000005", "name": "VAL5 Clinic"},
            member_overrides={"member_number": "M-VAL-5"},
            rates=[("99213", 10000, "2026-01-01")],
            clock="2026-05-11T00:00:00Z",
        )
        on_time = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "99213", 1, 10000, "2026-02-10")],
            "CLM-VAL-5A",
        )
        assert on_time["status"] == "RECEIVED", "Exactly 90 whole days still files"

        set_clock("2026-05-12T00:00:00Z")
        payload = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "99213", 1, 20000, "2026-02-10")],
            claim_number="CLM-VAL-5B",
        )
        validate_error(
            api.create_claim(payload, CLAIMS_INTAKE), ApiErrorId.ERR_TIMELY_FILING_EXCEEDED.value
        )

        _rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"member_id": env["member"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_claim_listing_reports_total_count_and_has_more_across_pages(self, api):
        """PRD §2.3: "List responses set `response_type` to `"array"` and carry four
        pagination fields inside `meta`: `limit` and `offset` echo the effective values used
        for the page, `total_count` reports the number of rows matching the filter before the
        page window is applied, and `has_more` is true exactly when rows remain beyond the
        current window."

        Design: Corner/entities/list_claims_pagination_returns_total_count_and_has_more
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "PG-1", "name": "Pagination Plan"},
            provider_overrides={"npi": "2000000005", "name": "PG Clinic"},
            member_overrides={"member_number": "M-PG-1"},
        )
        for index, service_date in enumerate(("2026-02-10", "2026-02-11", "2026-02-12"), start=1):
            submit_claim(
                env["member"]["id"],
                env["provider"]["id"],
                [claim_line_payload(1, "73721", 1, 60000, service_date)],
                f"CLM-PG-{index}",
            )

        first_page, first_meta = validate_paginated(
            api.list_claims(
                CLAIMS_EXAMINER,
                params={"member_id": env["member"]["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_claims(
                CLAIMS_EXAMINER,
                params={"member_id": env["member"]["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
