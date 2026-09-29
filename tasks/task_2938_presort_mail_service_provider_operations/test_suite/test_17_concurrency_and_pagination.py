"""Concurrency tokens and page windows: two ways a second reader gets hurt.

Two of this API's writes are guarded by a version the caller must have observed
first — a deposit against a permit account and a statement prepared against a
sorted batch — and both guards are only worth anything if the refused write
changes nothing at all, version included. The third layer here is the page
window: a filtered list recomputes its own population on every request, so a
count cached across requests or a `has_more` derived from the unfiltered table
both show up the moment a matching row is inserted between two page reads.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_PERMIT_VERSION,
)
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_field_values,
    assert_pagination_meta,
    assert_permit_funds,
    assert_row_count,
    assert_statement_figures,
    ids_of,
)
from test_helpers.constants import FIXTURE_CLOCK_UTC
from test_helpers.test_users import POSTAGE_MANAGER, POSTAGE_MANAGER_2, PRESORT_OPERATOR


DEPOSIT_CENTS = 50000


def _build_fresh_account_world(api):
    """Client OCC1 with one ACTIVE permit account at version 1, holding nothing."""
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    world = fx.setup_client_with_permit(
        api,
        name="Occ One Mailing",
        client_code="OCC1",
        permit_number="PI-460460",
        payment_method="PERMIT_IMPRINT",
    )
    return world


class TestStalePermitVersionOnFunding:
    """A replayed deposit token must not credit the account twice."""

    def test_the_first_deposit_lands_and_advances_the_version(self, api):
        """A deposit moves spendable funds and nothing else.

        "The deposit increases `balance_cents` by `amount_cents`, leaves
        `reserved_cents` untouched — this is what preserves the permit funds
        conservation invariant of §2.10 — and increments the account's `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_permit_version_on_funding
        """
        world = _build_fresh_account_world(api)

        opened = validate_success(
            api.get_permit_account(world.permit_id, POSTAGE_MANAGER)
        )
        assert opened["version"] == 1
        assert_permit_funds(opened, balance_cents=0, reserved_cents=0)

        deposited = validate_success(
            api.fund_permit_account(
                world.permit_id,
                f.funding_payload(DEPOSIT_CENTS, opened["version"], "WIRE-1"),
                POSTAGE_MANAGER,
            )
        )
        assert_permit_funds(deposited, balance_cents=DEPOSIT_CENTS, reserved_cents=0)
        assert deposited["version"] == 2

    def test_replaying_the_first_token_neither_credits_nor_bumps(self, api):
        """The stale token is the only thing telling two deposits apart.

        "A `POST /permit-accounts/{id}/funding` request must carry
        `expected_permit_account_version` holding the client's last observed `version`
        of the target `PermitAccount`. If that value does not equal the account's
        current `version`, the deposit is rejected with `ERR_STALE_PERMIT_VERSION`
        (HTTP 412). Repeated deposits are perfectly legitimate on their own terms, so
        without this guard a caller whose view of `balance_cents` predates another
        writer's change would top the account up to the wrong figure and never learn
        of it; the version check turns that silent error into a deterministic
        stale-version rejection."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_permit_version_on_funding
        """
        world = _build_fresh_account_world(api)
        stale_version = validate_success(
            api.get_permit_account(world.permit_id, POSTAGE_MANAGER)
        )["version"]

        validate_success(
            api.fund_permit_account(
                world.permit_id,
                f.funding_payload(DEPOSIT_CENTS, stale_version, "WIRE-1"),
                POSTAGE_MANAGER,
            )
        )
        validate_error(
            api.fund_permit_account(
                world.permit_id,
                f.funding_payload(DEPOSIT_CENTS, stale_version, "WIRE-2"),
                POSTAGE_MANAGER,
            ),
            ERR_STALE_PERMIT_VERSION,
            expected_status=412,
        )

        after = validate_success(api.get_permit_account(world.permit_id, POSTAGE_MANAGER))
        assert_permit_funds(after, balance_cents=DEPOSIT_CENTS, reserved_cents=0)
        assert after["version"] == 2, (
            "a refused optimistic-concurrency write must not advance the version"
        )

    def test_the_caller_retries_with_the_fresh_token_and_lands_it(self, api):
        """Exactly two of three deposits are meant to survive.

        "**Permit account optimistic concurrency** — `expected_permit_account_version`
        equals the account's current `version`. Violation: `ERR_STALE_PERMIT_VERSION`
        (412). Applies to `POST /permit-accounts/{id}/funding`." A permit account is
        readable for exactly this purpose: it is "the natural way for a
        `PostageManager` to observe the `version` it will then quote as
        `expected_permit_account_version`".

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_permit_version_on_funding
        """
        world = _build_fresh_account_world(api)
        stale_version = validate_success(
            api.get_permit_account(world.permit_id, POSTAGE_MANAGER)
        )["version"]

        first = validate_success(
            api.fund_permit_account(
                world.permit_id,
                f.funding_payload(DEPOSIT_CENTS, stale_version, "WIRE-1"),
                POSTAGE_MANAGER,
            )
        )
        validate_error(
            api.fund_permit_account(
                world.permit_id,
                f.funding_payload(DEPOSIT_CENTS, stale_version, "WIRE-2"),
                POSTAGE_MANAGER,
            ),
            ERR_STALE_PERMIT_VERSION,
            expected_status=412,
        )
        retried = validate_success(
            api.fund_permit_account(
                world.permit_id,
                f.funding_payload(DEPOSIT_CENTS, first["version"], "WIRE-3"),
                POSTAGE_MANAGER,
            )
        )
        assert_permit_funds(
            retried, balance_cents=2 * DEPOSIT_CENTS, reserved_cents=0
        )
        assert retried["version"] == 3


OCC2_PIECES = 1200
OCC2_FUNDING_CENTS = 100000
OCC2_RATE_MILLS = 28556
OCC2_POSTAGE_CENTS = 34267


def _build_presort_ready_world(api):
    """Client OCC2 with a funded permit account, one 1200-piece job pooled into an
    OPEN batch at SCF-021 and a single matching 1200-piece FIVE_DIGIT tray. The
    batch version observed while it is still OPEN is kept as ``stale_v``."""
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    world = fx.setup_client_with_permit(
        api,
        name="Occ Two Mailing",
        client_code="OCC2",
        permit_number="PI-470470",
        payment_method="PERMIT_IMPRINT",
        commingle_opt_in=True,
    )
    fx.fund_permit_account(api, world.permit_id, OCC2_FUNDING_CENTS, "WIRE-OCC2")
    world.facility = fx.setup_facility(api)
    world.facility_id = world.facility["id"]
    cleared = fx.setup_cleared_job(
        api, world.client_id, world.permit_id, declared_piece_count=OCC2_PIECES
    )
    world.job = cleared.job
    world.job_id = cleared.job_id
    world.batch = fx.create_batch(api, f.commingle_batch_payload(world.facility_id))
    world.batch_id = world.batch["id"]
    fx.add_member(api, world.batch_id, world.job_id)
    fx.add_container(
        api,
        world.batch_id,
        f.sort_container_payload(
            container_type="TRAY",
            destination_zip3="021",
            sort_level="FIVE_DIGIT",
            piece_count=OCC2_PIECES,
        ),
    )
    world.stale_v = fx.batch_version(api, world.batch_id)
    return world


class TestStaleBatchVersionOnStatementCreation:
    """The token is the batch's version, and closing sortation advances it."""

    def test_closing_sortation_freezes_the_price_and_moves_the_version_on(self, api):
        """The reader's token goes stale in the very act that prices the pool.

        "When those gates pass, the batch moves `OPEN → SORTED` and the whole
        three-stage derivation of §3.4 runs one final time and is then frozen:
        `achieved_tier` is fixed from the pooled volume, `rate_mills_per_piece` and
        `batch_postage_cents` are fixed from that tier, the mail class base rate and
        the entry facility's `drop_ship_discount_bp`". "The batch's own `version`
        increments by one."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_batch_version_on_statement_creation
        """
        world = _build_presort_ready_world(api)

        sorted_batch = validate_success(api.sort_batch(world.batch_id, PRESORT_OPERATOR))
        assert_batch_pricing(
            sorted_batch,
            status="SORTED",
            achieved_tier="BASIC",
            rate_mills=OCC2_RATE_MILLS,
            postage_cents=OCC2_POSTAGE_CENTS,
        )
        assert sorted_batch["version"] > world.stale_v, (
            "the sort must advance the version the reader captured while OPEN"
        )

    def test_a_token_read_before_the_sort_is_refused_and_writes_no_statement(self, api):
        """The batch is in the state the endpoint wants, and it is still a 412.

        "A `POST /postage-statements` request must carry `expected_batch_version`
        holding the client's last observed `version` of the target `CommingleBatch`. If
        that value does not equal the batch's current `version`, the creation is
        rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412). Preparing a statement
        legitimately supersedes any prior `DRAFT` statement on the same batch, so
        without this guard a caller holding a stale view of the batch would void a
        statement that had been prepared from different piece counts; the version check
        makes that a stale-version rejection instead."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_batch_version_on_statement_creation
        """
        world = _build_presort_ready_world(api)
        fx.sort_batch(api, world.batch_id)

        validate_error(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_id, world.stale_v
                ),
                POSTAGE_MANAGER_2,
            ),
            ERR_STALE_BATCH_VERSION,
            expected_status=412,
        )

        filed, meta = validate_paginated(
            api.list_batch_postage_statements(world.batch_id, POSTAGE_MANAGER)
        )
        assert_row_count(filed, 0, "postage statements")
        assert meta["total_count"] == 0
        still_sorted = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert still_sorted["status"] == "SORTED"

    def test_the_fresh_token_prepares_the_statement_at_the_frozen_price(self, api):
        """One statement, and only one, comes out of the retried filing.

        "**Batch optimistic concurrency** — `expected_batch_version` equals the batch's
        current `version`. Violation: `ERR_STALE_BATCH_VERSION` (412). Applies to
        `POST /postage-statements`." Preparation then copies the frozen figures: "The
        statement's `statement_piece_count` is frozen from the batch's
        `total_piece_count`, its `rate_mills_per_piece` is frozen from the batch's
        `rate_mills_per_piece`, and its `declared_postage_cents` is set from the
        batch's `batch_postage_cents`." "The statement opens in `DRAFT` with
        `adjustment_cents`, `verified_postage_cents`, `verification_error_count` and
        `revision_index` all at 0".

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_batch_version_on_statement_creation
        """
        world = _build_presort_ready_world(api)
        sorted_batch = fx.sort_batch(api, world.batch_id)

        validate_error(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_id, world.stale_v
                ),
                POSTAGE_MANAGER_2,
            ),
            ERR_STALE_BATCH_VERSION,
            expected_status=412,
        )

        statement = validate_success(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_id, sorted_batch["version"]
                ),
                POSTAGE_MANAGER_2,
            ),
            expected_status=201,
        )
        assert_statement_figures(
            statement,
            status="DRAFT",
            declared_postage_cents=OCC2_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=0,
            revision_index=0,
        )
        assert_field_values(
            statement,
            {
                "statement_piece_count": OCC2_PIECES,
                "rate_mills_per_piece": OCC2_RATE_MILLS,
            },
        )

        filed, meta = validate_paginated(
            api.list_batch_postage_statements(world.batch_id, POSTAGE_MANAGER)
        )
        assert_row_count(filed, 1, "postage statements")
        assert meta["total_count"] == 1
        assert filed[0]["id"] == statement["id"]


def _build_paging_world(api):
    """Client PAGE1 with two tendered jobs of 100 and 200 pieces, and client PAGE2
    with one tendered job of 300 that no PAGE1 filter may ever return."""
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    mine = fx.setup_client_with_permit(
        api,
        name="Page One Mailing",
        client_code="PAGE1",
        permit_number="PI-480480",
        payment_method="METER",
    )
    other = fx.setup_client_with_permit(
        api,
        name="Page Two Mailing",
        client_code="PAGE2",
        permit_number="PI-490490",
        payment_method="METER",
    )
    world = fx.World()
    world.client_id = mine.client_id
    world.permit_id = mine.permit_id
    world.other_client_id = other.client_id
    world.other_permit_id = other.permit_id
    world.job_1_id = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.client_id,
            world.permit_id,
            declared_piece_count=100,
            declared_weight_oz_per_piece=1.0,
        ),
    )["id"]
    world.job_2_id = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.client_id,
            world.permit_id,
            declared_piece_count=200,
            declared_weight_oz_per_piece=1.0,
        ),
    )["id"]
    world.other_job_id = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.other_client_id,
            world.other_permit_id,
            mail_class="FIRST_CLASS",
            declared_piece_count=300,
            declared_weight_oz_per_piece=1.0,
        ),
    )["id"]
    return world


def _received_page(api, world, limit, offset):
    return validate_paginated(
        api.list_mail_jobs(
            POSTAGE_MANAGER,
            {
                "client_id": world.client_id,
                "status": "RECEIVED",
                "limit": limit,
                "offset": offset,
            },
        )
    )


class TestFilteredPaginationAcrossAMutation:
    """The page window is recomputed per request, against the filtered population."""

    def test_the_first_page_counts_only_the_rows_the_filter_matches(self, api):
        """Two of the three tendered jobs match, and the count says two.

        "Every list response carries all four pagination fields inside `meta`: `limit`
        and `offset` echo the effective values actually applied, `total_count` is the
        number of records matching the request before the page window is applied, and
        `has_more` is true exactly when records remain beyond the current window." The
        filters are the endpoint's own: "The list accepts optional `client_id`,
        `permit_account_id`, `commingle_batch_id` and `status` filters — the last
        matching against any of `RECEIVED`, `HYGIENE_CLEARED`, `POOLED`, `PRESORTED`,
        `REWORK`, `MAILED`, `BILLED` or `CANCELLED` — together with `limit` and
        `offset`." Every tendered job qualifies, because "A tendered job opens in
        `RECEIVED`."

        Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_stays_consistent_across_a_mutation
        """
        world = _build_paging_world(api)

        page, meta = _received_page(api, world, limit=1, offset=0)
        assert_row_count(page, 1, "mail jobs on the first page")
        assert_pagination_meta(meta, len(page))
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert world.other_job_id not in ids_of(page), (
            "another client's job must never appear inside a client_id filter"
        )

    def test_an_insertion_between_page_reads_lifts_the_total_and_reopens_has_more(
        self, api
    ):
        """A third matching job is inserted, and the next page must see it.

        "`total_count` is the number of records matching the request before the page
        window is applied, and `has_more` is true exactly when records remain beyond
        the current window." Nothing about the window is cached between requests, and
        `limit` is bounded per request: "`limit` controls page size: it defaults to 10
        when omitted, may not be below 1, and may not exceed 100."

        Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_stays_consistent_across_a_mutation
        """
        world = _build_paging_world(api)

        _first_page, first_meta = _received_page(api, world, limit=1, offset=0)
        assert first_meta["total_count"] == 2

        job_3 = validate_success(
            api.create_mail_job(
                f.mail_job_payload(
                    world.client_id,
                    world.permit_id,
                    declared_piece_count=300,
                    declared_weight_oz_per_piece=1.0,
                ),
                PRESORT_OPERATOR,
            ),
            expected_status=201,
        )

        second_page, second_meta = _received_page(api, world, limit=1, offset=1)
        assert_row_count(second_page, 1, "mail jobs on the offset-1 page")
        assert_pagination_meta(second_meta, len(second_page))
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is True

        whole, whole_meta = _received_page(api, world, limit=100, offset=0)
        assert_row_count(whole, 3, "mail jobs in the whole filtered population")
        assert_pagination_meta(whole_meta, len(whole))
        assert whole_meta["total_count"] == 3
        assert whole_meta["has_more"] is False
        assert set(ids_of(whole)) == {
            world.job_1_id,
            world.job_2_id,
            job_3["id"],
        }
        assert world.other_job_id not in ids_of(whole)
        assert world.other_job_id not in ids_of(second_page)
