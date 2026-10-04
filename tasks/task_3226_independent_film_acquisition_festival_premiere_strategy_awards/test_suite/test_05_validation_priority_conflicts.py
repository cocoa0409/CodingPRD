"""Validation priority conflicts across error-category pairs.

Design: Difficulty/priority_pair_validation_conflict
"""
from test_helpers import (
    TEST_USERS, acquire_film, acquire_film_with_premiere,
    create_awards_campaign_payload, create_talent_obligation_payload,
    get_success_data, setup_active_campaign, setup_film, validate_error,
    validate_paginated, validate_success,
)
from test_helpers.api_errors import ApiErrorId

ACQ = TEST_USERS["acq_exec_headers"]
STRAT = TEST_USERS["awards_strat_headers"]
COORD = TEST_USERS["talent_coord_headers"]


class TestInvalidStateBeatsFiscal:
    def test_invalid_state_beats_fiscal_campaign_budget(self, api):
        """PRD §2.5: "Validation across the platform follows a fixed priority
        order so that the same bad request always fails the same way... then
        state-machine legality (`ERR_INVALID_STATE`, HTTP 409)... then
        campaign budget (`ERR_CAMPAIGN_BUDGET_EXCEEDED`, HTTP 402)... When
        multiple rules could fire on the same request, the earlier-priority
        rule wins."
        PRD §3.7: "Spend against a non-`ACTIVE` campaign is rejected with
        `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_fiscal_campaign_budget
        """
        film, offer, deal = acquire_film()
        campaign = get_success_data(api.create_awards_campaign(
            film["id"],
            create_awards_campaign_payload(
                deal_id=deal["id"], budget_total_cents=1_000_000,
            ),
            STRAT,
        ))
        # Campaign is PLANNING (not activated). A spend that would also blow
        # the budget must surface the state error, not the fiscal one.
        resp = api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 5_000_000,
             "incurred_at": "2026-10-01T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        )
        err = validate_error_is_one_of_state(resp)
        assert err in ("ERR_INVALID_STATE", "ERR_CAMPAIGN_NOT_ACTIVE")
        assert resp.status_code == 409, (
            f"state error wins over fiscal: expected 409, got "
            f"{resp.status_code} ({resp.json()})"
        )

    def test_active_campaign_budget_exceeded_reports_fiscal_error(self, api):
        """PRD §3.7: "The cumulative sum of `amount_cents` across all spends
        on the campaign plus the new spend must not exceed the campaign's
        `budget_total_cents`; if it would, the spend is rejected with
        `ERR_CAMPAIGN_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_fiscal_campaign_budget
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        campaign = setup_active_campaign(
            film, deal, {"budget_total_cents": 1_000_000},
        )
        # Only the fiscal rule can fail here (campaign is ACTIVE): the
        # over-budget spend surfaces ERR_CAMPAIGN_BUDGET_EXCEEDED.
        resp = api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 5_000_000,
             "incurred_at": "2026-10-01T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED)


class TestReferentialBeatsTemporal:
    def test_referential_beats_temporal_travel_buffer(self, api):
        """PRD §3.8: "The `talent_name` must appear in the film's
        `principal_cast` or match the film's `director_name`; otherwise the
        request is rejected with `ERR_TALENT_NOT_ON_FILM` (HTTP 422)."
        — talent membership is enforced at obligation creation, so a bogus
        talent name fails there regardless of the window shape.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_travel_buffer
        """
        setup_us_and_film = setup_film()  # principal_cast ["Jae Park"]
        film_id = setup_us_and_film["id"]

        ob1 = get_success_data(api.create_talent_obligation(
            film_id,
            create_talent_obligation_payload(
                talent_name="Jae Park",
                window_starts_at="2026-12-01T10:00:00Z",
                window_ends_at="2026-12-01T12:00:00Z", city_code="NY",
            ),
            COORD,
        ))
        validate_success(api.confirm_talent_obligation(film_id, ob1["id"], COORD))

        # Bogus talent with a same-city window 3h after the existing one —
        # would violate the travel buffer if the talent were valid; the
        # talent-membership check fires instead, at creation time.
        resp = api.create_talent_obligation(
            film_id,
            create_talent_obligation_payload(
                talent_name="Unknown Person", obligation_kind="TRAVEL",
                window_starts_at="2026-12-01T15:00:00Z",
                window_ends_at="2026-12-01T17:00:00Z", city_code="NY",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_TALENT_NOT_ON_FILM)

        # No obligation row is persisted for the bogus talent
        rows, _meta = validate_paginated(
            api.list_talent_obligations(
                film_id, COORD, params={"talent_name": "Unknown Person"},
            )
        )
        assert len(rows) == 0

    def test_talent_not_on_film_rejects_before_any_conflict_check(self, api):
        """PRD §3.8: "The `talent_name` must appear in the film's
        `principal_cast` or match the film's `director_name`; otherwise the
        request is rejected with `ERR_TALENT_NOT_ON_FILM` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_travel_buffer
        """
        film = setup_film()
        # Director name is legal even when not in principal_cast
        ok = api.create_talent_obligation(
            film["id"],
            create_talent_obligation_payload(talent_name="Ana Ruiz"),
            COORD,
        )
        validate_success(ok, expected_status=201)

        # A name that is neither cast nor director is rejected
        resp = api.create_talent_obligation(
            film["id"],
            create_talent_obligation_payload(talent_name="Stranger"),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_TALENT_NOT_ON_FILM)


def validate_error_is_one_of_state(resp):
    """Return the error_id for a state-tier failure (INVALID_STATE or the
    endpoint-specific NOT_ACTIVE synonym, both HTTP 409)."""
    body = resp.json()
    assert body.get("response_type") == "error", body
    return body["data"]["error_id"]
