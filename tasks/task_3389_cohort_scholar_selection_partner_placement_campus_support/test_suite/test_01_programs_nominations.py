"""City programs, nominating partners, nomination windows and quotas (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    WINDOW_CLOSES,
    WINDOW_ONE_SECOND_PAST_CLOSE,
    advance_clock,
    assert_city_program,
    assert_nominee,
    assert_nominating_partner,
    create_city_program_payload,
    create_nominee_payload,
    create_nominating_partner_payload,
    create_partner,
    decide,
    get_nominee,
    make_nominator_headers,
    nominate,
    setup_city_program,
    setup_city_with_partner,
    submit_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]


class TestCityProgramCreation:
    def test_city_program_creation_stamps_system_fields(self, api):
        """PRD §4: "Endpoints that create a new resource respond with HTTP 201".
        PRD §2.5: "Every persisted resource carries an `id` — a server-minted
        UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC
        with three fractional digits."
        PRD §2.4: "The server boots with the logical clock at exactly
        2026-09-01T00:00:00Z, before any clock-set call has been made."

        Design: Corner/entities/city_program_creation_stamps_system_fields
        """
        resp = api.create_city_program(
            create_city_program_payload(), _ADMIN
        )
        data = validate_success(resp, 201)
        assert_city_program(data)
        assert data["code"] == "ATL"
        assert data["name"] == "Atlanta"
        assert isinstance(data["version"], int), "version is an integer (PRD §2.5)"
        assert data["created_at"].startswith("2026-09-01T00:00:00"), (
            f"created_at must be the logical-clock boot instant, got {data['created_at']}"
        )
        again = validate_success(api.get_city_program(data["id"], _ADMIN))
        assert again["id"] == data["id"] and again["name"] == "Atlanta", (
            "GET right after create returns the identical representation"
        )


class TestNomineeCreation:
    def test_nominee_create_missing_required_full_name(self, api):
        """PRD §2.7: "Required fields must be present, types must be valid, enum
        values must be in range ... Violations are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/nominee_create_missing_required_full_name
        """
        program, partner = setup_city_with_partner(quota=5)
        resp = api.create_nominee(
            {"city_program_id": program["id"]},
            make_nominator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        nominees, meta = validate_paginated(
            api.list_nominees(_ADMIN, params={"city_program_id": program["id"]})
        )
        assert meta["total_count"] == 0 and nominees == [], (
            "a rejected nomination creates nothing"
        )

    def test_nominee_first_generation_defaults_false(self, api):
        """PRD §3.1: "A nomination creates a `Nominee` with `full_name`, the
        target `city_program_id`, and an optional `first_generation` flag that
        defaults to false when omitted."

        Design: Corner/entities/nominee_first_generation_defaults_false
        """
        program, partner = setup_city_with_partner(quota=5)
        plain = nominate(program, partner, "No Flag", by_nominator=True)
        assert plain["first_generation"] is False, "omitted flag defaults to false"
        flagged = nominate(
            program, partner, "Flagged", by_nominator=True, first_generation=True
        )
        assert flagged["first_generation"] is True, "explicit true is honored"
        assert_nominee(plain)
        assert_nominee(flagged)


class TestPartnerQuotaBounds:
    def test_partner_quota_out_of_range_rejected(self, api):
        """PRD §2.7: "This tier owns the nomination-quota bounds (a
        `nomination_quota` below 1 or above 20 fails here)".
        PRD §3.1: "a `nomination_quota` bounding its live nominations to at
        least 1 and at most 20 per cycle."

        Design: Corner/entities/partner_quota_out_of_range_rejected
        """
        program = setup_city_program()
        resp0 = api.create_nominating_partner(
            create_nominating_partner_payload(
                program["id"], name="Zero Quota HS", nomination_quota=0
            ),
            _ADMIN,
        )
        validate_error(resp0, ApiErrorId.ERR_INVALID_REQUEST)
        resp21 = api.create_nominating_partner(
            create_nominating_partner_payload(
                program["id"], name="Big Quota HS", nomination_quota=21
            ),
            _ADMIN,
        )
        validate_error(resp21, ApiErrorId.ERR_INVALID_REQUEST)
        resp20 = api.create_nominating_partner(
            create_nominating_partner_payload(
                program["id"], name="Edge Quota HS", nomination_quota=20
            ),
            _ADMIN,
        )
        edge = validate_success(resp20, 201)
        assert_nominating_partner(edge)
        assert edge["nomination_quota"] == 20, "the inclusive upper bound is legal"


class TestNomineeListing:
    def test_nominees_list_paginates_and_filters(self, api):
        """PRD §2.3: "All list endpoints accept the optional query parameters
        `limit` and `offset`."
        PRD §2.9: "The nominee list filters by `city_program_id`,
        `nominator_id`, and `status`;".

        Design: Corner/entities/nominees_list_paginates_and_filters
        """
        program, partner = setup_city_with_partner(quota=5)
        for name in ("Nom One", "Nom Two", "Nom Three"):
            nominate(program, partner, name, by_nominator=True)

        page1, meta1 = validate_paginated(
            api.list_nominees(
                _ADMIN,
                params={"city_program_id": program["id"], "status": "NOMINATED", "limit": 2},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_nominees(
                _ADMIN,
                params={
                    "city_program_id": program["id"],
                    "status": "NOMINATED",
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        empty, meta3 = validate_paginated(
            api.list_nominees(
                _ADMIN,
                params={"city_program_id": program["id"], "status": "ROUND_1"},
            )
        )
        assert meta3["total_count"] == 0 and empty == [], (
            "the status filter composes with pagination metadata"
        )


class TestComputedFields:
    def test_partner_nominations_used_is_computed(self, api):
        """PRD §3.1: "A freshly registered partner starts with
        `nominations_used` at zero."
        PRD §3.2: "While fewer than 2 evaluations exist for the nominee in that
        round, the round score remains null. Once at least 2 evaluations exist,
        the round score becomes the round-half-up average of their
        `weighted_score` values, stored as an integer on the nominee as
        `round_1_score`, `round_2_score`, or `round_3_score`."

        Design: Corner/entities/partner_nominations_used_is_computed
        """
        program, partner = setup_city_with_partner(quota=5)
        assert partner["nominations_used"] == 0, "fresh partner starts at zero"

        nominee = nominate(program, partner, "Nom One", by_nominator=True)
        assert nominee["round_1_score"] is None, "no evaluations yet -> null"

        decide(nominee["id"], "ADVANCE")  # NOMINATED -> ROUND_1
        submit_evaluation(nominee["id"], 1, 60, 60, 60, "assessor-a")
        after_one = get_nominee(nominee["id"])
        assert after_one["round_1_score"] is None, (
            "still null after ONE evaluation — the input set requires >= 2"
        )
        submit_evaluation(nominee["id"], 1, 61, 59, 60, "assessor-b")
        after_two = get_nominee(nominee["id"])
        assert after_two["round_1_score"] == 601, (
            "weighted 600 and 601 -> round_half_up(600.5) == 601"
        )

        partners, _ = validate_paginated(
            api.list_partners(program["id"], _ADMIN)
        )
        assert partners[0]["nominations_used"] == 1, (
            "one live nominee drives nominations_used to 1"
        )

    def test_read_after_write_is_immediate(self, api):
        """PRD §2.9: "List endpoints double as reverse lookups over the
        references their resources carry."
        PRD §3.1: "A freshly registered partner starts with `nominations_used`
        at zero."

        Design: Corner/consistency_model/read_after_write_is_immediate
        """
        program = setup_city_program()
        partner = create_partner(program["id"], nomination_quota=5)
        partners, meta = validate_paginated(
            api.list_partners(program["id"], _ADMIN)
        )
        assert meta["total_count"] == 1
        assert partners[0]["id"] == partner["id"], (
            "the created partner is visible in the parent's list immediately"
        )
        assert partners[0]["nominations_used"] == 0
        assert partners[0]["name"] == "West High"
        assert partners[0]["kind"] == "HIGH_SCHOOL"


class TestNominationWindowAndQuota:
    def test_nomination_window_inclusive_boundaries(self, api):
        """PRD §3.1: "Both window bounds are inclusive: nominations are
        accepted from the opening instant through the closing instant."
        PRD §3.1: "a submission before the window opens or after it closes is
        rejected with `ERR_NOMINATION_WINDOW_CLOSED`."

        Design: Corner/validations/nomination_window_inclusive_boundaries
        """
        program, partner = setup_city_with_partner(quota=5)
        advance_clock(WINDOW_CLOSES)
        nominee = nominate(program, partner, "Last Second", by_nominator=True)
        assert nominee["status"] == "NOMINATED", (
            "a nomination at exactly the closing instant is accepted"
        )
        advance_clock(WINDOW_ONE_SECOND_PAST_CLOSE)
        resp = api.create_nominee(
            create_nominee_payload(program["id"], "Too Late"),
            make_nominator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOMINATION_WINDOW_CLOSED)
        partners, _ = validate_paginated(api.list_partners(program["id"], _ADMIN))
        assert partners[0]["nominations_used"] == 1

    def test_quota_exceeded_alone_rejected(self, api):
        """PRD §3.1: "Second, the partner must have quota left: if
        `nominations_used` already equals `nomination_quota`, the nomination is
        rejected with `ERR_NOMINATION_QUOTA_EXCEEDED`."

        Design: Corner/validations/quota_exceeded_alone_rejected
        """
        program, partner = setup_city_with_partner(quota=1)
        nominate(program, partner, "Nom One", by_nominator=True)
        resp = api.create_nominee(
            create_nominee_payload(program["id"], "Nom Two"),
            make_nominator_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOMINATION_QUOTA_EXCEEDED)
        partners, _ = validate_paginated(api.list_partners(program["id"], _ADMIN))
        assert partners[0]["nominations_used"] == 1, "the rejected nomination consumed no quota"


class TestNominateWithdrawQuotaInvariant:
    def test_nominations_used_walks_with_withdrawal(self, api):
        """PRD §3.1: "at all times, `nominations_used` plus the partner's
        remaining slots equals its `nomination_quota`."
        PRD §3.1: "it moves the nominee to `WITHDRAWN` and releases one quota
        slot, decreasing the partner's `nominations_used` by one."

        Design: Difficulty/compensating_invariant/nominate_then_withdraw_restores_quota
        """
        program, partner = setup_city_with_partner(quota=2)
        headers = make_nominator_headers(partner["id"])

        def used():
            partners, _ = validate_paginated(
                api.list_partners(program["id"], _ADMIN)
            )
            return partners[0]["nominations_used"]

        n1 = nominate(program, partner, "Nom One", by_nominator=True)
        assert used() == 1
        nominate(program, partner, "Nom Two", by_nominator=True)
        assert used() == 2
        resp = api.withdraw_nominee(n1["id"], headers)
        validate_success(resp)
        assert used() == 1, "withdrawal of a NOMINATED nominee releases one slot"
        # Invariant: used + remaining == quota at every step (remaining is
        # quota minus used); the walk 1 -> 2 -> 1 preserves it.

    def test_withdrawal_releases_slot_for_reuse(self, api):
        """PRD §3.1: "A nominee may be withdrawn only while still `NOMINATED`
        — withdrawal is impossible once the nominee has entered `ROUND_1`, and
        attempting it is rejected with `ERR_INVALID_STATE`. Withdrawal may be
        performed by the owning nominator or by a `ProgramAdmin`; it moves the
        nominee to `WITHDRAWN` and releases one quota slot, decreasing the
        partner's `nominations_used` by one."

        Design: Difficulty/compensating_invariant/nominate_then_withdraw_restores_quota
        """
        program, partner = setup_city_with_partner(quota=2)
        headers = make_nominator_headers(partner["id"])
        n1 = nominate(program, partner, "Nom One", by_nominator=True)
        nominate(program, partner, "Nom Two", by_nominator=True)
        validate_success(api.withdraw_nominee(n1["id"], headers))

        resp = api.create_nominee(
            create_nominee_payload(program["id"], "Nom Three"), headers
        )
        n3 = validate_success(resp, 201)
        assert n3["status"] == "NOMINATED", (
            "the slot freed by the withdrawal is genuinely reusable"
        )
        partners, _ = validate_paginated(api.list_partners(program["id"], _ADMIN))
        assert partners[0]["nominations_used"] == 2
        assert get_nominee(n1["id"])["status"] == "WITHDRAWN"


