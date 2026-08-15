"""Validation enforcement: authentication, existence ordering, business
constraints, fiscal guards, conditional required fields, and request shape."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_conflict_check_payload,
    create_letter,
    create_matter,
    create_party,
    fund_deposit,
    get_deposit,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_responsible_attorney_headers,
    record_credit_assessment,
    run_conflict_check,
    setup_basic_matter,
    setup_matter_with_issued_letter,
    setup_matter_with_waiver,
    transition_deposit_payload,
    validate_error,
    validate_success,
)

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestMissingAuthHeadersUnauthenticated:
    def test_request_without_headers_rejected_401(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the caller's
        operational capacity. A request in which either header is missing or
        empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/c_missing_auth_headers_unauthenticated
        """
        resp = api_client.list_matters(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestExistenceBeforeStatePriority:
    def test_review_nonexistent_hit_returns_not_found(self):
        """PRD §2.11: "Requests that address nested resources resolve path
        identifiers strictly left to right — the matter first, then the letter,
        waiver, wall, deposit, hit, party, or attorney beneath it — and the
        first identifier that does not resolve fails the whole request with
        `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.11: "The ordering is observable: a stale-version rejection at
        tier 6 masks a clearance problem at tier 7 on the same request, and a
        malformed payload addressed to a nonexistent matter returns
        `ERR_NOT_FOUND`, never `ERR_INVALID_REQUEST`."

        Design: Corner/validations/c_existence_before_state_priority
        """
        atty = create_attorney()
        resp = api_client.review_conflict_hit(
            "00000000-0000-4000-8000-000000000000",
            {"decision": "CONFIRMED"},
            make_responsible_attorney_headers(atty["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestWaiverActiveExistsAlone:
    def test_second_active_waiver_for_same_hit_rejected(self):
        """PRD §3.6: "At most one waiver per hit may be active at a time, where
        active means `DRAFT`, `SENT`, `CONSENTED`, or `APPROVED`; a second
        attempt against the same hit fails with `ERR_WAIVER_ACTIVE_EXISTS`."

        Design: Corner/validations/c_waiver_active_exists_alone
        """
        p_x, p_y, atty, m1, hit, waiver = setup_matter_with_waiver(
            "Active Waiver X Inc", "Active Waiver Y Corp"
        )
        assert waiver["status"] == "DRAFT"
        # The producing check is still COMPLETED (no supersede), so the sole
        # failing rule is the one-active-waiver constraint.
        resp = api_client.create_waiver_request(
            m1["id"],
            {"conflict_hit_id": hit["id"], "proposed_terms": "w2"},
            make_responsible_attorney_headers(atty["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_ACTIVE_EXISTS)


class TestPartyAlreadyOnMatter:
    def test_adding_same_party_twice_rejected(self):
        """PRD §3.3: "Roster rows bind parties to the matter. Adding one takes
        a `party_id` and a `role_in_matter` of `ADVERSE`, `WITNESS`, or
        `RELATED`, and stores the row with its `matter_id`; adding a party
        already on the roster fails with `ERR_PARTY_ALREADY_ON_MATTER`."

        Design: Corner/validations/c_party_already_on_matter
        """
        p_x = create_party("Dup Party Inc")
        p_y = create_party("Dup Client Corp")
        atty = create_attorney()
        matter = create_matter(p_y["id"], atty["id"], matter_title="M")
        first = add_roster_party(matter["id"], p_x["id"], "ADVERSE")
        assert first["id"]

        resp = api_client.add_matter_party(
            matter["id"], {"party_id": p_x["id"], "role_in_matter": "WITNESS"},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_ALREADY_ON_MATTER)


class TestRefundExceedsBalance:
    def test_refund_above_received_balance_rejected_and_balance_unchanged(self):
        """PRD §3.8: "A refund must likewise be greater than zero and may not
        exceed the held balance — an amount above `received_cents` fails with
        `ERR_REFUND_EXCEEDS_BALANCE`; it adds to `refunded_total_cents` and
        re-derives status, cycling `FUNDED` → `PENDING` or `PARTIALLY_FUNDED` →
        `PENDING` when the full balance is returned, and dropping `FUNDED` →
        `PARTIALLY_FUNDED` on a partial refund."

        Design: Corner/validations/c_refund_exceeds_balance
        """
        # Fee 1.0h x 100c = 100; with no assessment, required clamps to 50000.
        _, _, matter, _, deposit = setup_matter_with_issued_letter(
            "Refund Client Inc", score=None,
            fee_lines=[{"description": "f", "hours": 1.0, "rate_cents": 100}],
        )
        funded = fund_deposit(deposit["id"], 100000)
        assert funded["status"] == "FUNDED"
        assert funded["received_cents"] == 100000

        resp = api_client.transition_retainer_deposit(
            deposit["id"], transition_deposit_payload("REFUND", 100001), BILLING
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_BALANCE)

        after = get_deposit(matter["id"])
        assert after["received_cents"] == 100000, (
            "failed refund leaves the balance unchanged"
        )


class TestMatchThresholdOutOfRange:
    def test_match_threshold_101_rejected(self):
        """PRD §3.4: "The caller chooses a `search_variant` of `STRICT` or
        `PHONETIC` and may supply a `match_threshold` — an integer from 0 to
        100 inclusive, defaulting to 60 — below which candidates are
        discarded."
        PRD §2.11: "and (12) request shape, failing as `ERR_INVALID_REQUEST`.
        The ordering is observable: a stale-version rejection at tier 6 masks a
        clearance problem at tier 7 on the same request, and a malformed payload
        addressed to a nonexistent matter returns `ERR_NOT_FOUND`, never
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/c_match_threshold_out_of_range
        """
        _, _, matter = setup_basic_matter("Range Client Inc")
        resp = api_client.create_conflict_check(
            matter["id"],
            {"search_variant": "STRICT", "match_threshold": 101},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLateralMissingFields400:
    def test_lateral_without_employment_fields_rejected(self):
        """PRD §3.2: "When `hire_type` is `LATERAL`, three further inputs are
        required: `lateral_employed_from` and `lateral_employed_to`, calendar
        dates in year-month-day form whose last day counts as inclusive in
        every overlap test, and `prior_client_names`, a list of prior-firm
        client name strings that must be present though it may be empty.
        Omitting any of the three fails with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/c_lateral_missing_fields_400
        """
        resp = api_client.create_attorney(
            {
                "full_name": "Larry Lateral",
                "bar_number": "BAR009",
                "practice_group": "LITIGATION",
                "hire_type": "LATERAL",
            },
            FIRM_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLateralPendingNotAssignable:
    def test_lateral_pending_attorney_cannot_be_responsible(self):
        """PRD §3.3: "First, the referenced attorney's `status` must be
        `ACTIVE`; assigning a `LATERAL_PENDING` attorney is rejected with
        `ERR_ATTORNEY_NOT_ACTIVE`."

        Design: Corner/errors/c_lateral_pending_not_assignable
        """
        p_x = create_party("Pending Match Corp")
        p_y = create_party("New Client LLC")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")

        lateral = create_attorney(
            full_name="Larry Lateral",
            bar_number="BAR009",
            hire_type="LATERAL",
            lateral_employed_from="2024-01-01",
            lateral_employed_to="2026-08-15",
            prior_client_names=["Pending Match"],
        )
        assert lateral["status"] == "LATERAL_PENDING"

        resp = api_client.create_matter(
            {
                "client_party_id": p_y["id"],
                "responsible_attorney_id": lateral["id"],
                "practice_group": "LITIGATION",
                "matter_title": "M1",
            },
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_ATTORNEY_NOT_ACTIVE)
