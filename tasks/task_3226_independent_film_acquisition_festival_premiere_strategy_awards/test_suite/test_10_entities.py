"""Corner — entities: creation shape, listing, not-found, required fields.

Design: Corner/entities
"""
from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, acquire_film, assert_film,
    assert_statement, create_film_payload, create_offer_payload,
    get_success_data, setup_film, validate_error, validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
ACQ = TEST_USERS["acq_exec_headers"]
ACCT = TEST_USERS["part_acct_headers"]


class TestFilmCreation:
    def test_film_create_returns_declared_fields_and_initial_state(self, api):
        """PRD §3.1: "On creation the film's three posture fields are
        initialized: `acquisition_status` is `SHOPPING`, `release_posture` is
        `PRE_ACQUISITION`, and `awards_posture` is `INELIGIBLE`."
        PRD §2.4: "`version` is an integer that starts at 1 and increments by
        one on every mutation to the resource."

        Design: Corner/entities/film_create_returns_declared_fields_and_initial_state
        """
        resp = api.create_film(create_film_payload(), ADMIN)
        film = validate_success(resp, expected_status=201)
        assert_film(film)
        assert film["acquisition_status"] == "SHOPPING"
        assert film["release_posture"] == "PRE_ACQUISITION"
        assert film["awards_posture"] == "INELIGIBLE"
        assert film["version"] == 1


class TestFilmListing:
    def test_film_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter controls the maximum number of
        items returned: it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter controls how many items to skip and
        defaults to 0... Paginated responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §3.1: "Films can be browsed via a list endpoint filtered by
        `acquisition_status`, `release_posture`, or `genre`."

        Design: Corner/entities/film_list_paginates_with_total_count_and_has_more
        """
        setup_film(title="F1", genre="DRAMA")
        setup_film(title="F2", genre="COMEDY")
        setup_film(title="F3", genre="HORROR")

        page1, meta1 = validate_paginated(
            api.list_films(ACQ, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_films(ACQ, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        all_rows, meta3 = validate_paginated(api.list_films(ACQ))
        assert len(all_rows) == 3
        assert meta3["limit"] == 10

        horror, meta4 = validate_paginated(
            api.list_films(ACQ, params={"genre": "HORROR"})
        )
        assert len(horror) == 1
        assert horror[0]["title"] == "F3"
        assert meta4["total_count"] == 1


class TestFilmRead:
    def test_film_get_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "The first segment that does not resolve to an existing
        row produces an `ERR_NOT_FOUND` (HTTP 404) and short-circuits the rest
        of the request."

        Design: Corner/entities/film_get_unknown_id_returns_not_found
        """
        resp = api.get_film(NON_EXISTENT_UUID, ACQ)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestFilmCreateValidation:
    def test_film_create_missing_runtime_returns_invalid_request(self, api):
        """PRD §3.1: "the final-cut `runtime_minutes` (which must be greater
        than zero)" — runtime_minutes is a required input; omitting it is a
        `ERR_INVALID_REQUEST` (HTTP 400).
        PRD §5: `ERR_INVALID_REQUEST` 400 — "Missing required field, malformed
        value, enum out of range".

        Design: Corner/entities/film_create_missing_runtime_returns_invalid_request
        """
        payload = create_film_payload()
        del payload["runtime_minutes"]
        resp = api.create_film(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(api.list_films(ADMIN))
        assert len(rows) == 0
        assert meta["total_count"] == 0

    def test_film_create_invalid_genre_enum_rejected(self, api):
        """PRD §3.1: "the `genre` (one of `DRAMA`, `COMEDY`, `HORROR`,
        `DOCUMENTARY`, or `THRILLER`)" — a value outside the closed enum is
        `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/film_create_invalid_genre_enum_rejected
        """
        resp = api.create_film(create_film_payload(genre="ROMANCE"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStatementImmutability:
    def test_statement_immutable_no_update_endpoint(self, api):
        """PRD §2.4: "`FilmmakerStatement` is the sole exception: it carries
        only `id` and `created_at`. Both `updated_at` and `version` are absent
        on statements, and statements therefore do not participate in
        optimistic concurrency."

        Design: Corner/entities/statement_immutable_no_update_endpoint
        """
        film, offer, deal = acquire_film(
            offer_overrides={"upfront_price_cents": 1_000_000,
                             "prints_advertising_commit_cents": 1_000_000},
        )
        st = validate_success(api.create_statement(
            film["id"],
            {"deal_id": deal["id"], "period_label": "Q1-2027",
             "basis": "GROSS_RECEIPTS", "gross_receipts_cents": 10_000_000},
            ACCT,
        ), expected_status=201)
        # assert_statement enforces absence of updated_at and version
        assert_statement(st)

        fetched = get_success_data(
            api.get_statement_nested(film["id"], st["id"], ACCT)
        )
        assert_statement(fetched)
        assert "updated_at" not in fetched
        assert "version" not in fetched
