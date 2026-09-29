"""The observable surface of the bureau's records: what a row carries.

Every resource the bureau persists is read back here as the API actually
serialises it — the fixed envelope around it, the fields it declares, the
system and computed fields the server mints for itself, the defaults it
applies when an optional input is omitted, the closed enumerations it refuses
to widen, the leaner shape of the two append-only history records, and the
parent linkage a child row may never cross.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_absent_or_none,
    assert_append_only_identity,
    assert_field_values,
    assert_full_identity,
    assert_pct_2dp,
    assert_row_count,
    assert_strict_instant,
    find_by_id,
    ids_of,
)
from test_helpers.test_users import (
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
SPOOFED_UUID = "11111111-1111-4111-8111-111111111111"


NORTHLINE = {
    "name": "Northline Mail Group",
    "client_code": "NORTH",
    "service_fee_rate_per_thousand_cents": 1400,
    "billing_terms": "NET_15",
    "commingle_opt_in": True,
}


class TestClientCreationSurface:
    """Registering a mailer and reading back everything the row carries."""

    def test_registering_a_mailer_returns_the_fixed_envelope_and_its_declared_fields(
        self, api
    ):
        """The created row comes back inside the standard single-resource envelope.

        "Creating a new resource returns HTTP 201 with the created resource in
        `data`", and the envelope around it is fixed: "The `api_request_id` is a
        server-generated unique identifier for the request that starts with
        `req_`." and "The `api_request_timestamp` is a server-generated ISO 8601
        UTC timestamp with three fractional digits." A single record is announced
        as such, because "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Registration itself is the four declared commercial inputs:
        "Registration takes the mailer's legal `name` — between 1 and 120
        characters and not blank — and a short operator-facing `client_code` of 2
        to 16 characters drawn only from uppercase letters and digits, which must
        be globally unique across all clients".

        Design: Corner/entities/creation_client_returns_envelope_with_all_declared_fields
        """
        response = api.create_client(dict(NORTHLINE), BUREAU_ADMIN)
        client = validate_success(response, expected_status=201)

        body = response.json()
        assert body["response_type"] == "object", (
            "a single created resource is announced as an object, not an array"
        )
        assert body["meta"]["api_request_id"].startswith("req_")
        assert_strict_instant(
            body["meta"]["api_request_timestamp"], "api_request_timestamp"
        )

        assert_field_values(
            client,
            {
                "name": "Northline Mail Group",
                "client_code": "NORTH",
                "service_fee_rate_per_thousand_cents": 1400,
                "billing_terms": "NET_15",
                "commingle_opt_in": True,
            },
        )

    def test_registering_a_mailer_materialises_its_system_and_computed_fields(
        self, api
    ):
        """The ledgers and the trading status are on the row from the first read.

        "A newly registered client opens in `ACTIVE` status with
        `suspension_reason` null, and with both of its running ledgers at zero:
        `unbilled_postage_cents`, which tracks postage already verified and
        charged to a permit account but not yet placed on an invoice, and
        `lifetime_pieces_mailed`, which counts accepted pieces on the client's
        jobs that have reached `MAILED`."

        Design: Corner/entities/creation_client_returns_envelope_with_all_declared_fields
        """
        client = validate_success(
            api.create_client(dict(NORTHLINE), BUREAU_ADMIN), expected_status=201
        )

        assert client["status"] == "ACTIVE"
        assert_absent_or_none(client, ["suspension_reason"])
        assert_field_values(
            client,
            {"unbilled_postage_cents": 0, "lifetime_pieces_mailed": 0},
        )

        stored = validate_success(api.get_client(client["id"], BUREAU_ADMIN))
        assert_field_values(
            stored,
            {
                "status": "ACTIVE",
                "unbilled_postage_cents": 0,
                "lifetime_pieces_mailed": 0,
            },
        )

    def test_registering_a_mailer_mints_a_bare_uuid_strict_instants_and_version_one(
        self, api
    ):
        """Identity, timestamps and the revision counter are the server's own.

        "Every resource the API persists carries a server-minted `id`: a UUID
        string, with no type prefix and no embedded meaning." and "Every resource
        also carries `created_at`, an ISO 8601 UTC timestamp with exactly three
        fractional digits, stamped once when the row is written and never
        modified." The counter starts where the contract says it starts:
        "`version` is an integer that starts at 1 when the resource is created
        and increases by exactly 1 on every mutation of that resource".

        Design: Corner/entities/creation_client_returns_envelope_with_all_declared_fields
        """
        client = validate_success(
            api.create_client(dict(NORTHLINE), BUREAU_ADMIN), expected_status=201
        )

        assert_full_identity(client, expected_version=1)
        assert ":" not in client["id"] and "_" not in client["id"], (
            f"the id must carry no type prefix, got {client['id']!r}"
        )


class TestClientOptionalInputDefaults:
    """The two optional commercial inputs, omitted and supplied."""

    def test_omitting_the_two_optional_inputs_persists_their_declared_defaults(
        self, api
    ):
        """An omitted payment term and an omitted pooling consent are not null.

        "`billing_terms` is the payment term printed on the mailer's invoices and
        is either `NET_15` or `NET_30`; when omitted it defaults to `NET_30`." and
        "`commingle_opt_in` is a boolean that defaults to true when omitted, and a
        mailer that sets it false has chosen to keep its mail out of shared pools."

        Design: Corner/entities/defaults_billing_terms_and_commingle_opt_in_applied
        """
        created = validate_success(
            api.create_client(
                {
                    "name": "Default Terms Co",
                    "client_code": "DEFCO",
                    "service_fee_rate_per_thousand_cents": 1000,
                },
                BUREAU_ADMIN,
            ),
            expected_status=201,
        )
        assert_field_values(
            created, {"billing_terms": "NET_30", "commingle_opt_in": True}
        )

        stored = validate_success(api.get_client(created["id"], BUREAU_ADMIN))
        assert_field_values(
            stored, {"billing_terms": "NET_30", "commingle_opt_in": True}
        )
        assert_field_values(stored, {"status": "ACTIVE", "version": 1})

    def test_supplying_the_two_optional_inputs_keeps_the_supplied_values(self, api):
        """An explicit opt-out is honoured rather than overwritten by the default.

        "`billing_terms` is the payment term printed on the mailer's invoices and
        is either `NET_15` or `NET_30`; when omitted it defaults to `NET_30`." A
        mailer that declines pooling says so explicitly: "`commingle_opt_in` is a
        boolean that defaults to true when omitted, and a mailer that sets it
        false has chosen to keep its mail out of shared pools."

        Design: Corner/entities/defaults_billing_terms_and_commingle_opt_in_applied
        """
        created = validate_success(
            api.create_client(
                {
                    "name": "Opted Out Co",
                    "client_code": "OPTOUT",
                    "service_fee_rate_per_thousand_cents": 1000,
                    "billing_terms": "NET_15",
                    "commingle_opt_in": False,
                },
                BUREAU_ADMIN,
            ),
            expected_status=201,
        )
        assert_field_values(
            created, {"billing_terms": "NET_15", "commingle_opt_in": False}
        )

        stored = validate_success(api.get_client(created["id"], BUREAU_ADMIN))
        assert_field_values(
            stored,
            {
                "billing_terms": "NET_15",
                "commingle_opt_in": False,
                "status": "ACTIVE",
                "version": 1,
            },
        )


class TestServerMintedClientFields:
    """Identity, trading status and the ledgers are not caller-supplied inputs."""

    def test_supplying_identity_state_or_ledger_fields_is_rejected_outright(self, api):
        """A registration that tries to dictate the server's own fields fails.

        "Clients never supply an `id`; a body that includes one is rejected as an
        unknown field." The request-shape rung is explicit about the whole class
        of them: "the body parses, contains every field the endpoint requires,
        every field holds the declared type, and every enumerated field holds a
        declared member. Unknown fields are rejected. Violation:
        `ERR_INVALID_REQUEST` (400)."

        A rejected registration must leave nothing behind, because "A partial
        cascade is never an acceptable outcome: if any precondition of the driving
        operation fails, nothing at all changes." The proof is the reused
        `client_code`: it is unique, and "a collision is rejected with
        `ERR_DUPLICATE_CLIENT_CODE`", so a second clean registration under the
        same code could only succeed if no row was written.

        Design: Corner/entities/system_fields_client_supplied_id_and_version_are_ignored
        """
        spoofed = validate_error(
            api.create_client(
                {
                    "name": "Spoofer Mail",
                    "client_code": "SPOOF",
                    "service_fee_rate_per_thousand_cents": 1200,
                    "id": SPOOFED_UUID,
                    "version": 99,
                    "status": "SUSPENDED",
                    "unbilled_postage_cents": 500000,
                },
                BUREAU_ADMIN,
            ),
            e.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        assert spoofed["error_id"] == e.ERR_INVALID_REQUEST

        clean = validate_success(
            api.create_client(
                {
                    "name": "Spoofer Mail",
                    "client_code": "SPOOF",
                    "service_fee_rate_per_thousand_cents": 1200,
                },
                BUREAU_ADMIN,
            ),
            expected_status=201,
        )
        assert clean["client_code"] == "SPOOF"

    def test_the_clean_registration_mints_identity_status_and_ledgers_itself(
        self, api
    ):
        """What the rejected body tried to dictate, the server sets for itself.

        "Every resource the API persists carries a server-minted `id`: a UUID
        string, with no type prefix and no embedded meaning." The state and the
        ledgers are equally the server's: "A newly registered client opens in
        `ACTIVE` status with `suspension_reason` null, and with both of its
        running ledgers at zero: `unbilled_postage_cents`, which tracks postage
        already verified and charged to a permit account but not yet placed on an
        invoice, and `lifetime_pieces_mailed`, which counts accepted pieces on the
        client's jobs that have reached `MAILED`." And the counter is minted too:
        "`version` is an integer that starts at 1 when the resource is created and
        increases by exactly 1 on every mutation of that resource".

        Design: Corner/entities/system_fields_client_supplied_id_and_version_are_ignored
        """
        validate_error(
            api.create_client(
                {
                    "name": "Spoofer Mail",
                    "client_code": "SPOOF",
                    "service_fee_rate_per_thousand_cents": 1200,
                    "id": SPOOFED_UUID,
                    "version": 99,
                    "status": "SUSPENDED",
                    "unbilled_postage_cents": 500000,
                },
                BUREAU_ADMIN,
            ),
            e.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        clean = validate_success(
            api.create_client(
                {
                    "name": "Spoofer Mail",
                    "client_code": "SPOOF",
                    "service_fee_rate_per_thousand_cents": 1200,
                },
                BUREAU_ADMIN,
            ),
            expected_status=201,
        )

        assert clean["id"] != SPOOFED_UUID, (
            "the server mints the identifier and never adopts a supplied one"
        )
        assert_full_identity(clean, expected_version=1)
        assert clean["status"] == "ACTIVE"
        assert_absent_or_none(clean, ["suspension_reason"])
        assert_field_values(
            clean, {"unbilled_postage_cents": 0, "lifetime_pieces_mailed": 0}
        )


def _northline_with_permit(api):
    """Northline Mail Group and its own metered permit account."""
    return fx.setup_client_with_permit(
        api,
        name="Northline Mail Group",
        client_code="NORTH",
        service_fee_rate_per_thousand_cents=1400,
        permit_number="PI-700700",
        payment_method="METER",
    )


class TestMailJobRetrievalSurface:
    """A later read of a cleaned job returns what was written, not a re-run."""

    def test_reading_a_cleaned_job_returns_the_mirrored_hygiene_measures(self, api):
        """The three derived measures sit on the job itself after the pass.

        "Those three derived measures are then **mirrored onto the job** from the
        run with the highest `run_index` — always the newest run. The job's
        `accepted_piece_count` is set to that run's `net_piece_count`, its
        `address_quality_pct` to that run's `address_quality_pct`, and its
        `move_update_compliant` to that run's `move_update_compliant`."

        The run itself derives them: "Its `net_piece_count` is the
        `submitted_piece_count` less the `undeliverable_removed_count`." and "Its
        `address_quality_pct` is the `cass_matched_count` multiplied by one hundred
        and divided by the `submitted_piece_count`, rounded half up to two decimal
        places." and "Its `move_update_compliant` is true when
        `move_update_age_days` is less than or equal to the maximum permitted age
        of 95 days, so a data set exactly 95 days old is compliant while one 96
        days old is not."

        Design: Corner/entities/retrieval_mail_job_returns_stored_values
        """
        owner = _northline_with_permit(api)
        cleared = fx.setup_cleared_job(
            api,
            owner.client_id,
            owner.permit_id,
            declared_piece_count=1250,
            declared_weight_oz_per_piece=1.2,
            submitted_piece_count=1250,
            cass_matched_count=1235,
            ncoa_move_updated_count=40,
            undeliverable_removed_count=50,
            move_update_age_days=30,
        )

        job = validate_success(api.get_mail_job(cleared.job_id, PRESORT_OPERATOR))

        assert_field_values(
            job,
            {
                "id": cleared.job_id,
                "client_id": owner.client_id,
                "permit_account_id": owner.permit_id,
                "declared_piece_count": 1250,
                "accepted_piece_count": 1200,
                "move_update_compliant": True,
            },
        )
        assert_pct_2dp(job, "address_quality_pct", 98.80)

    def test_reading_a_cleaned_job_returns_its_counters_and_its_null_pointers(
        self, api
    ):
        """One pass clears the job and leaves everything downstream untouched.

        "Recording a pass on a job in `RECEIVED` drives it `RECEIVED →
        HYGIENE_CLEARED`". The run is counted once: "Its `run_index` is a
        zero-based ordinal equal to the job's `hygiene_run_count` as it stood
        immediately *before* this run was counted, so a job's very first pass
        carries `run_index` 0; the job's `hygiene_run_count` is then incremented by
        one."

        Nothing after hygiene has happened yet, and the contract fixes those
        opening values: "Its `hygiene_run_count` and `rework_count` both start at
        0, its `address_quality_pct` and `postage_due_cents` both start at 0, its
        `move_update_compliant` starts false, and its `commingle_batch_id`,
        `mailed_at_utc` and `cancel_reason` all start null." Postage in particular
        stays at zero, because "postage is not attributed to a job until an
        acceptance clerk accepts the statement covering it."

        Design: Corner/entities/retrieval_mail_job_returns_stored_values
        """
        owner = _northline_with_permit(api)
        cleared = fx.setup_cleared_job(
            api,
            owner.client_id,
            owner.permit_id,
            declared_piece_count=1250,
            declared_weight_oz_per_piece=1.2,
            submitted_piece_count=1250,
            cass_matched_count=1235,
            ncoa_move_updated_count=40,
            undeliverable_removed_count=50,
            move_update_age_days=30,
        )

        job = validate_success(api.get_mail_job(cleared.job_id, PRESORT_OPERATOR))

        assert_field_values(
            job,
            {
                "status": "HYGIENE_CLEARED",
                "hygiene_run_count": 1,
                "rework_count": 0,
                "postage_due_cents": 0,
            },
        )
        assert_absent_or_none(job, ["commingle_batch_id", "mailed_at_utc"])


class TestMailJobNotFoundSurface:
    """An unknown identifier is an entity-specific 404, not a blank success."""

    def test_an_unknown_mail_job_identifier_yields_the_job_specific_404(self, api):
        """The path identifier decides which not-found error comes back.

        "The mapping from an unresolvable identifier to its error is fixed: a
        `client_id` yields `ERR_CLIENT_NOT_FOUND`, a `permit_account_id` yields
        `ERR_PERMIT_ACCOUNT_NOT_FOUND`, a `mail_job_id` yields
        `ERR_MAIL_JOB_NOT_FOUND`". Those are all one status: "All of these are
        HTTP 404."

        The error envelope is as fixed as the success envelope: "The `error_id` is
        a unique, machine-readable string that identifies the specific error." and
        "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/not_found_unknown_mail_job_id
        """
        response = api.get_mail_job(UNKNOWN_UUID, PRESORT_OPERATOR)
        error = validate_error(
            response, e.ERR_MAIL_JOB_NOT_FOUND, expected_status=404
        )

        assert response.json()["response_type"] == "error"
        assert error["error_id"] == e.ERR_MAIL_JOB_NOT_FOUND
        assert error["message"].strip(), "the error must carry a readable message"


def _two_client_job_table(api):
    """Northline with two tendered jobs and Southgate with one, all RECEIVED."""
    world = fx.World()
    world.north = fx.create_client(
        api,
        f.client_payload(
            name="Northline Mail Group",
            client_code="NORTH",
            service_fee_rate_per_thousand_cents=1400,
        ),
    )
    world.south = fx.create_client(
        api,
        f.client_payload(
            name="Southgate Mailers",
            client_code="SOUTH",
            service_fee_rate_per_thousand_cents=1600,
        ),
    )
    world.permit_north = fx.create_permit_account(
        api,
        f.permit_account_payload(
            world.north["id"], permit_number="PI-700700", payment_method="METER"
        ),
    )
    world.permit_south = fx.create_permit_account(
        api,
        f.permit_account_payload(
            world.south["id"], permit_number="PI-800800", payment_method="METER"
        ),
    )
    world.job_n1 = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.north["id"],
            world.permit_north["id"],
            mail_class="MARKETING_MAIL",
            processing_category="LETTERS",
            declared_piece_count=500,
            declared_weight_oz_per_piece=1.0,
        ),
    )
    world.job_n2 = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.north["id"],
            world.permit_north["id"],
            mail_class="MARKETING_MAIL",
            processing_category="FLATS",
            declared_piece_count=600,
            declared_weight_oz_per_piece=2.0,
        ),
    )
    world.job_s1 = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.south["id"],
            world.permit_south["id"],
            mail_class="FIRST_CLASS",
            processing_category="LETTERS",
            declared_piece_count=700,
            declared_weight_oz_per_piece=0.8,
        ),
    )
    return world


class TestMailJobListingSurface:
    """Filtering happens before the page window, not after it."""

    def test_the_filters_narrow_the_population_the_page_window_is_cut_from(self, api):
        """Two of three jobs match, so the counted population is two.

        "The list accepts optional `client_id`, `permit_account_id`,
        `commingle_batch_id` and `status` filters — the last matching against any
        of `RECEIVED`, `HYGIENE_CLEARED`, `POOLED`, `PRESORTED`, `REWORK`,
        `MAILED`, `BILLED` or `CANCELLED` — together with `limit` and `offset`."

        What that count means is fixed: "Every list response carries all four
        pagination fields inside `meta`: `limit` and `offset` echo the effective
        values actually applied, `total_count` is the number of records matching
        the request before the page window is applied, and `has_more` is true
        exactly when records remain beyond the current window." A list is also
        announced as a list: "List responses set `response_type` to `"array"`;
        single-resource responses set it to `"object"`."

        Design: Corner/entities/listing_mail_jobs_filters_and_paginates
        """
        world = _two_client_job_table(api)
        query = {
            "client_id": world.north["id"],
            "status": "RECEIVED",
            "limit": 1,
            "offset": 0,
        }

        response = api.list_mail_jobs(POSTAGE_MANAGER, query)
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert_row_count(rows, 1, "filtered first page rows")
        assert_field_values(
            meta, {"total_count": 2, "limit": 1, "offset": 0, "has_more": True}
        )

    def test_the_second_page_finishes_the_population_and_excludes_the_other_client(
        self, api
    ):
        """The remainder is one row, and another mailer's job is never in it.

        "`offset` controls the starting position: it defaults to 0 and may not be
        below 0." The window is cut from the filtered population, so "`total_count`
        is the number of records matching the request before the page window is
        applied, and `has_more` is true exactly when records remain beyond the
        current window."

        The order the window walks is fixed: "every list is ordered by `created_at`
        ascending — oldest record first — and pagination is applied to that
        ordering." And the filter is a boundary the pages never cross: "The list
        accepts optional `client_id`, `permit_account_id`, `commingle_batch_id` and
        `status` filters".

        Design: Corner/entities/listing_mail_jobs_filters_and_paginates
        """
        world = _two_client_job_table(api)
        base = {"client_id": world.north["id"], "status": "RECEIVED", "limit": 1}

        first_rows, _first_meta = validate_paginated(
            api.list_mail_jobs(POSTAGE_MANAGER, dict(base, offset=0))
        )
        second_rows, second_meta = validate_paginated(
            api.list_mail_jobs(POSTAGE_MANAGER, dict(base, offset=1))
        )

        assert_row_count(second_rows, 1, "filtered second page rows")
        assert_field_values(
            second_meta, {"total_count": 2, "offset": 1, "has_more": False}
        )
        assert second_rows[0]["id"] != first_rows[0]["id"], (
            "the second page must advance past the first page's row"
        )

        seen = ids_of(first_rows) + ids_of(second_rows)
        assert seen == [world.job_n1["id"], world.job_n2["id"]], (
            "the two pages must cover exactly this client's jobs, oldest first"
        )
        assert world.job_s1["id"] not in seen, (
            "another mailer's job must never appear under this client's filter"
        )

    def test_an_unfiltered_list_applies_the_default_page_window(self, api):
        """With no query at all the whole table is counted at the default window.

        "`limit` controls page size: it defaults to 10 when omitted, may not be
        below 1, and may not exceed 100." and "`offset` controls the starting
        position: it defaults to 0 and may not be below 0." The echoed values are
        the effective ones: "`limit` and `offset` echo the effective values
        actually applied".

        Design: Corner/entities/listing_mail_jobs_filters_and_paginates
        """
        world = _two_client_job_table(api)

        rows, meta = validate_paginated(api.list_mail_jobs(POSTAGE_MANAGER))

        assert_field_values(
            meta, {"limit": 10, "offset": 0, "total_count": 3, "has_more": False}
        )
        assert_row_count(rows, 3, "unfiltered rows")
        assert set(ids_of(rows)) == {
            world.job_n1["id"],
            world.job_n2["id"],
            world.job_s1["id"],
        }


class TestMailJobRequiredFields:
    """A missing required input is a request-shape failure, not arithmetic."""

    def test_omitting_the_declared_piece_count_is_a_request_shape_rejection(self, api):
        """The count has no default, so its absence is a malformed body.

        Tendering states the count outright: a `PresortOperator` tenders mail
        "stating both a `declared_piece_count` of at least 1 and a
        `declared_weight_oz_per_piece` that is strictly greater than zero and
        carries at most three decimal places." A body that leaves a required field
        out fails the shape rung: "the body parses, contains every field the
        endpoint requires, every field holds the declared type, and every
        enumerated field holds a declared member. Unknown fields are rejected.
        Violation: `ERR_INVALID_REQUEST` (400)."

        That is a different rejection from the arithmetic rung, which polices the
        value rather than its presence — that rung requires that
        "`declared_piece_count` is at least 1" and reports
        "Violation: `ERR_INVALID_PIECE_COUNT` (400)."

        Nothing is written by the refusal, since "A partial cascade is never an
        acceptable outcome: if any precondition of the driving operation fails,
        nothing at all changes."

        Design: Corner/entities/required_fields_missing_declared_piece_count_on_mail_job
        """
        owner = _northline_with_permit(api)

        error = validate_error(
            api.create_mail_job(
                {
                    "client_id": owner.client_id,
                    "permit_account_id": owner.permit_id,
                    "mail_class": "MARKETING_MAIL",
                    "processing_category": "LETTERS",
                    "declared_weight_oz_per_piece": 1.2,
                },
                PRESORT_OPERATOR,
            ),
            e.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        assert error["error_id"] != e.ERR_INVALID_PIECE_COUNT, (
            "an absent field is a shape failure, not a piece-count failure"
        )

        _rows, meta = validate_paginated(
            api.list_client_mail_jobs(owner.client_id, PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 0, "the refused tender must leave no job behind"


class TestMailJobEnumeratedFields:
    """A near-miss value outside a closed enumeration is refused, not stored."""

    @pytest.mark.parametrize(
        "field, rejected_value",
        [
            ("mail_class", "STANDARD_MAIL"),
            ("processing_category", "PARCELS"),
        ],
    )
    def test_a_value_outside_a_closed_enumeration_is_rejected(
        self, api, field, rejected_value
    ):
        """Both postal enumerations are closed sets, and neither is widened.

        Tendering declares them from fixed lists: a job is tendered "declaring the
        postal `mail_class` as one of `FIRST_CLASS`, `MARKETING_MAIL` or
        `PERIODICALS`, declaring the physical `processing_category` as either
        `LETTERS` or `FLATS`". A value outside either list fails the shape rung:
        "every field holds the declared type, and every enumerated field holds a
        declared member. Unknown fields are rejected. Violation:
        `ERR_INVALID_REQUEST` (400)."

        Nothing may be stored by the refusal, because "A partial cascade is never
        an acceptable outcome: if any precondition of the driving operation fails,
        nothing at all changes."

        Design: Corner/entities/type_constraints_reject_unknown_mail_class_enum_value
        """
        owner = _northline_with_permit(api)
        payload = {
            "client_id": owner.client_id,
            "permit_account_id": owner.permit_id,
            "mail_class": "MARKETING_MAIL",
            "processing_category": "LETTERS",
            "declared_piece_count": 1000,
            "declared_weight_oz_per_piece": 1.0,
        }
        payload[field] = rejected_value

        validate_error(
            api.create_mail_job(payload, PRESORT_OPERATOR),
            e.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        _rows, meta = validate_paginated(
            api.list_client_mail_jobs(owner.client_id, PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 0, (
            f"a job carrying {field} {rejected_value!r} must never be stored"
        )


FIRST_PASS = {
    "submitted_piece_count": 1250,
    "cass_matched_count": 1100,
    "ncoa_move_updated_count": 40,
    "undeliverable_removed_count": 100,
    "move_update_age_days": 200,
}
SECOND_PASS = {
    "submitted_piece_count": 1250,
    "cass_matched_count": 1235,
    "ncoa_move_updated_count": 40,
    "undeliverable_removed_count": 50,
    "move_update_age_days": 30,
}


def _job_with_two_hygiene_passes(api):
    """One tendered 1250-piece job cleaned twice: a bad pass then a good one."""
    owner = _northline_with_permit(api)
    job = fx.create_mail_job(
        api,
        f.mail_job_payload(
            owner.client_id,
            owner.permit_id,
            declared_piece_count=1250,
            declared_weight_oz_per_piece=1.2,
        ),
    )
    run_0 = validate_success(
        api.create_hygiene_run(job["id"], dict(FIRST_PASS), PRESORT_OPERATOR),
        expected_status=201,
    )
    run_1 = validate_success(
        api.create_hygiene_run(job["id"], dict(SECOND_PASS), PRESORT_OPERATOR),
        expected_status=201,
    )
    return job, run_0, run_1


class TestHygieneRunAppendOnlySurface:
    """A corrective pass appends history rather than editing the earlier row."""

    def test_a_second_pass_appends_a_new_row_and_leaves_the_first_verdict_intact(
        self, api
    ):
        """Both passes survive as separate rows in recording order.

        "Earlier runs are retained as history and are never averaged in; a
        corrective pass therefore fully replaces its predecessor's verdict." Each
        row keeps its own ordinal: "Its `run_index` is a zero-based ordinal equal
        to the job's `hygiene_run_count` as it stood immediately *before* this run
        was counted, so a job's very first pass carries `run_index` 0; the job's
        `hygiene_run_count` is then incremented by one."

        The first pass keeps its own arithmetic — "Its `net_piece_count` is the
        `submitted_piece_count` less the `undeliverable_removed_count`." and "Its
        `address_quality_pct` is the `cass_matched_count` multiplied by one hundred
        and divided by the `submitted_piece_count`, rounded half up to two decimal
        places." and "Its `move_update_compliant` is true when
        `move_update_age_days` is less than or equal to the maximum permitted age
        of 95 days, so a data set exactly 95 days old is compliant while one 96
        days old is not."

        Design: Corner/entities/immutability_hygiene_run_carries_no_version_and_has_no_update_endpoint
        """
        job, run_0, run_1 = _job_with_two_hygiene_passes(api)

        rows, meta = validate_paginated(
            api.list_hygiene_runs(job["id"], PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 2, "both passes must be retained as history"
        assert find_by_id(rows, run_0["id"])["run_index"] == 0
        assert find_by_id(rows, run_1["id"])["run_index"] == 1

        stored_first = find_by_id(rows, run_0["id"])
        assert_field_values(
            stored_first,
            {"net_piece_count": 1150, "move_update_compliant": False},
        )
        assert_pct_2dp(stored_first, "address_quality_pct", 88.00)

    def test_neither_hygiene_run_carries_a_version_or_an_updated_at(self, api):
        """The two history records are deliberately leaner than every other row.

        "Two resources are append-only records of history rather than mutable
        state, and they are deliberately leaner: `AddressHygieneRun` and
        `VerificationFinding` carry only `id` and `created_at`. Neither has an
        `updated_at` and neither has a `version`; those two fields are absent from
        their representations entirely."

        Design: Corner/entities/immutability_hygiene_run_carries_no_version_and_has_no_update_endpoint
        """
        job, run_0, run_1 = _job_with_two_hygiene_passes(api)

        assert_append_only_identity(run_0)
        assert_append_only_identity(run_1)

        rows, _meta = validate_paginated(
            api.list_hygiene_runs(job["id"], PRESORT_OPERATOR)
        )
        for row in rows:
            assert_append_only_identity(row)

    def test_the_job_mirrors_the_newest_pass_and_not_the_earlier_one(self, api):
        """The highest ordinal wins outright; the two passes are never blended.

        "Those three derived measures are then **mirrored onto the job** from the
        run with the highest `run_index` — always the newest run. The job's
        `accepted_piece_count` is set to that run's `net_piece_count`, its
        `address_quality_pct` to that run's `address_quality_pct`, and its
        `move_update_compliant` to that run's `move_update_compliant`." And
        explicitly: "Earlier runs are retained as history and are never averaged
        in; a corrective pass therefore fully replaces its predecessor's verdict."

        A repeat pass is a legitimate self-loop rather than a new state:
        "recording a further pass on a job already in `HYGIENE_CLEARED` is a
        deliberate self-loop `HYGIENE_CLEARED → HYGIENE_CLEARED`, which is how a
        stale move-update file gets replaced before pooling."

        Design: Corner/entities/immutability_hygiene_run_carries_no_version_and_has_no_update_endpoint
        """
        job, _run_0, _run_1 = _job_with_two_hygiene_passes(api)

        stored = validate_success(api.get_mail_job(job["id"], PRESORT_OPERATOR))
        assert_field_values(
            stored,
            {
                "accepted_piece_count": 1200,
                "move_update_compliant": True,
                "hygiene_run_count": 2,
                "status": "HYGIENE_CLEARED",
            },
        )
        assert_pct_2dp(stored, "address_quality_pct", 98.80)


class TestMailJobPermitParentLinkage:
    """A permit account is a child of one client, and the link is enforced."""

    def test_tendering_under_another_mailer_s_permit_is_refused(self, api):
        """Both rows exist and both are active; only the parentage is wrong.

        "A mailer may never file under another mailer's permit: if the named permit
        account's own `client_id` differs from the job's `client_id`, the tender is
        rejected with `ERR_PERMIT_CLIENT_MISMATCH`." The ladder gives that its own
        rung: "**Permit belongs to the client** — the `PermitAccount` named by
        `permit_account_id` has a `client_id` equal to the request's `client_id`.
        Violation: `ERR_PERMIT_CLIENT_MISMATCH` (422)."

        It is not a resolution failure, because both identifiers resolve — "every
        foreign key supplied in the body resolves to an existing row, checked in
        the order `client_id`, `permit_account_id`, `entry_facility_id`,
        `commingle_batch_id`, `mail_job_id`" — and it is not a shape failure
        either, since every field holds a declared member.

        Design: Corner/entities/parent_relationships_permit_account_of_another_client_is_rejected
        """
        north = _northline_with_permit(api)
        south = fx.setup_client_with_permit(
            api,
            name="Southgate Mailers",
            client_code="SOUTH",
            service_fee_rate_per_thousand_cents=1600,
            permit_number="PI-800800",
            payment_method="METER",
        )

        error = validate_error(
            api.create_mail_job(
                f.mail_job_payload(
                    north.client_id,
                    south.permit_id,
                    declared_piece_count=1000,
                    declared_weight_oz_per_piece=1.0,
                ),
                PRESORT_OPERATOR,
            ),
            e.ERR_PERMIT_CLIENT_MISMATCH,
            expected_status=422,
        )
        assert error["error_id"] not in (
            e.ERR_CLIENT_NOT_FOUND,
            e.ERR_PERMIT_ACCOUNT_NOT_FOUND,
            e.ERR_INVALID_REQUEST,
        )

        _rows, north_meta = validate_paginated(
            api.list_client_mail_jobs(north.client_id, PRESORT_OPERATOR)
        )
        _rows_s, south_meta = validate_paginated(
            api.list_client_mail_jobs(south.client_id, PRESORT_OPERATOR)
        )
        assert north_meta["total_count"] == 0
        assert south_meta["total_count"] == 0

    def test_the_same_tender_under_the_mailer_s_own_permit_is_accepted(self, api):
        """The identical body succeeds once the parentage lines up.

        A job is tendered "naming the owning `client_id` and the funding
        `permit_account_id`", and the only rule that failed before is this one: "A
        mailer may never file under another mailer's permit: if the named permit
        account's own `client_id` differs from the job's `client_id`, the tender is
        rejected with `ERR_PERMIT_CLIENT_MISMATCH`." A clean tender opens where the
        contract says: "A tendered job opens in `RECEIVED`."

        Design: Corner/entities/parent_relationships_permit_account_of_another_client_is_rejected
        """
        north = _northline_with_permit(api)
        south = fx.setup_client_with_permit(
            api,
            name="Southgate Mailers",
            client_code="SOUTH",
            service_fee_rate_per_thousand_cents=1600,
            permit_number="PI-800800",
            payment_method="METER",
        )

        validate_error(
            api.create_mail_job(
                f.mail_job_payload(
                    north.client_id,
                    south.permit_id,
                    declared_piece_count=1000,
                    declared_weight_oz_per_piece=1.0,
                ),
                PRESORT_OPERATOR,
            ),
            e.ERR_PERMIT_CLIENT_MISMATCH,
            expected_status=422,
        )

        job = validate_success(
            api.create_mail_job(
                f.mail_job_payload(
                    north.client_id,
                    north.permit_id,
                    declared_piece_count=1000,
                    declared_weight_oz_per_piece=1.0,
                ),
                PRESORT_OPERATOR,
            ),
            expected_status=201,
        )
        assert_field_values(
            job, {"permit_account_id": north.permit_id, "status": "RECEIVED"}
        )

        _rows, north_meta = validate_paginated(
            api.list_client_mail_jobs(north.client_id, PRESORT_OPERATOR)
        )
        _rows_s, south_meta = validate_paginated(
            api.list_client_mail_jobs(south.client_id, PRESORT_OPERATOR)
        )
        assert north_meta["total_count"] == 1
        assert south_meta["total_count"] == 0
