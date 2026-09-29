"""Data feeds, show-system preparation and the rights-compliance gates.

Every test builds its own preconditions from scratch: the database is empty and
the logical clock sits at its startup value when the test begins.
"""

from test_helpers import (
    assert_data_feed,
    assert_instant_equals,
    assert_readiness,
    assert_status,
    assert_system_prep,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH_STAMP
from test_helpers.factories import create_system_prep_payload
from test_helpers.fixtures import (
    create_prep,
    create_validated_prep,
    new_data_feed,
    new_production,
    read_feed,
    read_prep,
    read_production,
    set_clock,
)


# ---------------------------------------------------------------------------
# The concurrent-consumer ceiling
# ---------------------------------------------------------------------------
def test_first_prep_validates_while_the_feed_consumer_count_is_below_its_ceiling(
    api, td_headers
):
    """A feed at consumer count 0 admits a validation and counts the new consumer.

    PRD: "When the latency is no greater than the ceiling of **250 ms**, the preparation moves to `VALIDATED`, its `feed_validated_at` is stamped with the logical clock, and the feed's `active_consumer_count` rises by 1 — and because the count of validated preparations is one of the three provisioning conditions, reaching `required_validated_preps` here can carry the production `SURVEYED → PROVISIONED`."
    PRD: "The clock's value at server startup is exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time before the clock is first set."
    Design: Difficulty/boundary_precision_check/feed_consumer_count_at_exactly_max_concurrent_consumers
    """
    production = new_production(api)
    feed = new_data_feed(
        api,
        latency_ms=120,
        contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=1,
    )
    assert feed["active_consumer_count"] == 0, (
        "a new feed opens with active_consumer_count at 0"
    )
    prep = create_prep(api, production["id"], feed["id"], system_kind="GRAPHICS")

    validated = validate_success(api.validate_prep_feed(prep["id"], td_headers), 200)

    assert_system_prep(validated)
    assert_status(validated, "VALIDATED", "prep status")
    assert_instant_equals(
        validated["feed_validated_at"], CLOCK_EPOCH_STAMP, "feed_validated_at"
    )
    assert read_feed(api, feed["id"])["active_consumer_count"] == 1, (
        "the validated preparation is the feed's one consumer"
    )


def test_second_prep_refused_when_the_feed_consumer_count_equals_its_ceiling(
    api, td_headers
):
    """Equality with max_concurrent_consumers is enough to block a second consumer.

    PRD: "Then the consumer ceiling: validation is refused with `ERR_FEED_CONSUMER_LIMIT` when the feed's `active_consumer_count` has reached `max_concurrent_consumers`, equality being enough to block, where that count includes only preparations currently sitting in `VALIDATED`."
    PRD: "A new preparation opens at `PENDING` with `feed_validated_at` null."
    Design: Difficulty/boundary_precision_check/feed_consumer_count_at_exactly_max_concurrent_consumers
    """
    production = new_production(api)
    feed = new_data_feed(
        api,
        latency_ms=120,
        contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=1,
    )
    create_validated_prep(api, production["id"], feed["id"], system_kind="GRAPHICS")
    assert read_feed(api, feed["id"])["active_consumer_count"] == 1, (
        "the feed stands at its ceiling of one validated consumer"
    )
    second = create_prep(
        api, production["id"], feed["id"], system_kind="REPLAY",
        replay_channel_count=4,
    )

    response = api.validate_prep_feed(second["id"], td_headers)

    validate_error(response, "ERR_FEED_CONSUMER_LIMIT")
    blocked = read_prep(api, second["id"])
    assert_status(blocked, "PENDING", "prep status")
    assert blocked["feed_validated_at"] is None, (
        "a refused validation stamps no feed_validated_at"
    )
    feed_after = read_feed(api, feed["id"])
    assert_data_feed(feed_after)
    assert feed_after["active_consumer_count"] == 1, (
        "the refused validation consumed no slot"
    )
    assert_status(feed_after, "ACTIVE", "feed status")


# ---------------------------------------------------------------------------
# The bound feed's own status decides the preparation's verdict
# ---------------------------------------------------------------------------
def test_validate_feed_refused_once_the_bound_feed_has_been_suspended(
    api, td_headers, lo_headers
):
    """A perfectly legal PENDING prep is refused because a different row was pulled.

    PRD: "The feed must still be `ACTIVE`, or `ERR_FEED_STATE_INVALID`."
    PRD: "On success the feed moves `ACTIVE → SUSPENDED`, and **every** preparation bound to that feed which sits at `VALIDATED` is reverted `VALIDATED → PENDING` with its `feed_validated_at` cleared to null."
    Design: Difficulty/cross_entity_state_dependency/prep_validation_depends_on_data_feed_status
    """
    production = new_production(api)
    feed = new_data_feed(
        api,
        latency_ms=120,
        contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=2,
    )
    first = create_validated_prep(
        api, production["id"], feed["id"], system_kind="GRAPHICS"
    )
    assert_status(first, "VALIDATED", "prep status")
    second = create_prep(
        api, production["id"], feed["id"], system_kind="REPLAY",
        replay_channel_count=4,
    )

    suspended = validate_success(api.suspend_data_feed(feed["id"], lo_headers), 200)
    response = api.validate_prep_feed(second["id"], td_headers)

    validate_error(response, "ERR_FEED_STATE_INVALID")
    assert_status(suspended, "SUSPENDED", "feed status")
    assert suspended["active_consumer_count"] == 0, (
        "the reverted consumer is decremented off the feed"
    )
    reverted = read_prep(api, first["id"])
    assert_status(reverted, "PENDING", "prep status")
    assert reverted["feed_validated_at"] is None, (
        "the suspend cascade clears feed_validated_at"
    )
    still_pending = read_prep(api, second["id"])
    assert_status(still_pending, "PENDING", "prep status")
    assert still_pending["feed_validated_at"] is None
    assert_status(read_production(api, production["id"]), "PLANNED", "production stage")


def test_opening_a_preparation_against_a_suspended_feed_is_refused(
    api, td_headers, lo_headers
):
    """Prep creation reads the feed's status too, not just validation.

    PRD: "The production must not be `ON_AIR`, `WRAPPED` or `SETTLED`, and the feed being bound must be `ACTIVE` — binding a preparation to a `SUSPENDED` feed is refused with `ERR_FEED_STATE_INVALID`."
    PRD: "A new feed opens at `ACTIVE` with `active_consumer_count` at 0; its only other status is `SUSPENDED`."
    Design: Difficulty/cross_entity_state_dependency/prep_validation_depends_on_data_feed_status
    """
    production = new_production(api)
    feed = new_data_feed(
        api,
        latency_ms=120,
        contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=2,
    )
    assert_status(feed, "ACTIVE", "feed status")
    graphics = create_prep(api, production["id"], feed["id"], system_kind="GRAPHICS")
    validate_success(api.suspend_data_feed(feed["id"], lo_headers), 200)

    response = api.create_system_prep(
        create_system_prep_payload(production["id"], feed["id"], system_kind="STATS"),
        td_headers,
    )

    validate_error(response, "ERR_FEED_STATE_INVALID")
    rows, meta = validate_paginated(
        api.list_system_preps(td_headers, params={"production_id": production["id"]})
    )
    assert meta["total_count"] == 1, (
        "the refused creation wrote no second preparation row"
    )
    assert [row["id"] for row in rows] == [graphics["id"]]
    assert_status(read_production(api, production["id"]), "PLANNED", "production stage")


# ---------------------------------------------------------------------------
# Latency is a branch, not an error
# ---------------------------------------------------------------------------
def test_feed_slower_than_the_latency_ceiling_fails_the_prep_with_http_200(
    api, td_headers
):
    """A 300 ms feed drives the preparation to FAILED without raising an error.

    PRD: "When the latency is strictly greater than 250 ms, the preparation moves to `FAILED` instead: `feed_validated_at` stays null and the feed's `active_consumer_count` is left unchanged."
    PRD: "Once the four gates above are clear, the feed's `latency_ms` decides which of two branches the request takes, and both branches succeed with HTTP 200."
    Design: Corner/calculations/feed_latency_above_the_ceiling_fails_the_prep_with_http_200
    """
    production = new_production(api)
    slow_feed = new_data_feed(
        api, provider_code="GFXNET", feed_kind="OFFICIAL_SCORING", latency_ms=300,
        contract_expiry_utc="2026-09-01T00:00:00Z",
    )
    prep = create_prep(api, production["id"], slow_feed["id"], system_kind="GRAPHICS")

    failed = validate_success(api.validate_prep_feed(prep["id"], td_headers), 200)

    assert_system_prep(failed)
    assert_status(failed, "FAILED", "prep status")
    assert failed["feed_validated_at"] is None, (
        "a latency failure stamps no feed_validated_at"
    )
    assert read_feed(api, slow_feed["id"])["active_consumer_count"] == 0, (
        "a FAILED preparation is not a consumer of the feed"
    )
    assert_status(read_production(api, production["id"]), "PLANNED", "production stage")
    rows, meta = validate_paginated(
        api.list_system_preps(
            td_headers,
            params={"production_id": production["id"], "status": "FAILED"},
        )
    )
    assert meta["total_count"] == 1, "the latency-failed preparation is listable"
    assert rows[0]["id"] == prep["id"]


def test_feed_at_exactly_the_latency_ceiling_validates_the_prep(api, td_headers):
    """250 ms is "no greater than" the ceiling, so the preparation validates.

    PRD: "When the latency is no greater than the ceiling of **250 ms**, the preparation moves to `VALIDATED`, its `feed_validated_at` is stamped with the logical clock, and the feed's `active_consumer_count` rises by 1 — and because the count of validated preparations is one of the three provisioning conditions, reaching `required_validated_preps` here can carry the production `SURVEYED → PROVISIONED`."
    PRD: "The **systems component** is worth 20 points and is awarded in full when the variant's validated-preparation count is at least `required_validated_preps`, and zero otherwise."
    Design: Corner/calculations/feed_latency_above_the_ceiling_fails_the_prep_with_http_200
    """
    production = new_production(api)
    fast_feed = new_data_feed(
        api, provider_code="STATSCO", feed_kind="LIVE_STATS", latency_ms=250,
        contract_expiry_utc="2026-09-01T00:00:00Z",
    )
    prep = create_prep(api, production["id"], fast_feed["id"], system_kind="STATS")

    validated = validate_success(api.validate_prep_feed(prep["id"], td_headers), 200)

    assert_status(validated, "VALIDATED", "prep status")
    assert_instant_equals(
        validated["feed_validated_at"], CLOCK_EPOCH_STAMP, "feed_validated_at"
    )
    assert read_feed(api, fast_feed["id"])["active_consumer_count"] == 1
    production_after = read_production(api, production["id"])
    assert_status(production_after, "PLANNED", "production stage")
    assert production_after["required_validated_preps"] == 1, (
        "a TIER_3 event demands one validated preparation"
    )
    assert_readiness(production_after, certified=20.00)


# ---------------------------------------------------------------------------
# One preparation per system kind, whatever its status
# ---------------------------------------------------------------------------
def test_duplicate_prep_kind_refused_even_when_the_first_one_failed(api, td_headers):
    """A FAILED preparation still occupies its kind, but another kind is free.

    PRD: "A production may hold at most one preparation per system kind, counted unconditionally across `PENDING`, `VALIDATED` and `FAILED` alike, so a second preparation of the same kind for the same production is refused with `ERR_DUPLICATE_PREP_KIND`; a failed preparation is retried in place rather than re-created."
    PRD: "When the latency is strictly greater than 250 ms, the preparation moves to `FAILED` instead: `feed_validated_at` stays null and the feed's `active_consumer_count` is left unchanged."
    Design: Corner/validations/duplicate_prep_kind_rejected_regardless_of_prep_status
    """
    production = new_production(api)
    feed = new_data_feed(
        api, latency_ms=300, contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=2,
    )
    graphics = create_prep(api, production["id"], feed["id"], system_kind="GRAPHICS")
    failed = validate_success(api.validate_prep_feed(graphics["id"], td_headers), 200)
    assert_status(failed, "FAILED", "prep status")

    response = api.create_system_prep(
        create_system_prep_payload(
            production["id"], feed["id"], system_kind="GRAPHICS"
        ),
        td_headers,
    )

    validate_error(response, "ERR_DUPLICATE_PREP_KIND")
    other_kind = validate_success(
        api.create_system_prep(
            create_system_prep_payload(
                production["id"], feed["id"], system_kind="STATS"
            ),
            td_headers,
        ),
        201,
    )
    assert_status(other_kind, "PENDING", "prep status")
    assert other_kind["system_kind"] == "STATS"
    rows, meta = validate_paginated(
        api.list_system_preps(td_headers, params={"production_id": production["id"]})
    )
    assert meta["total_count"] == 2, (
        "only the duplicate GRAPHICS row was refused, not the STATS row"
    )
    assert sorted(row["system_kind"] for row in rows) == ["GRAPHICS", "STATS"]


# ---------------------------------------------------------------------------
# Contract expiry is inclusive of the expiry instant
# ---------------------------------------------------------------------------
def test_feed_contract_lapses_exactly_at_its_expiry_instant(api, td_headers):
    """One minute early validates; at the expiry instant itself validation is refused.

    PRD: "Data-rights compliance comes next: validation is refused with `ERR_FEED_CONTRACT_EXPIRED` when the logical clock stands **at or after** the feed's `contract_expiry_utc`, so a contract that lapses exactly at the instant of validation is already lapsed."
    PRD: "Integrating and validating the feed is where the compliance gates bite, and they are evaluated in a fixed order."
    Design: Corner/validations/feed_contract_expiry_blocks_validation_at_the_instant_it_expires
    """
    production = new_production(api)
    feed = new_data_feed(
        api, latency_ms=120, contract_expiry_utc="2026-08-10T00:00:00Z",
        max_concurrent_consumers=4,
    )
    prep_a = create_prep(api, production["id"], feed["id"], system_kind="GRAPHICS")
    prep_b = create_prep(api, production["id"], feed["id"], system_kind="STATS")

    set_clock(api, "2026-08-09T23:59:00Z", headers=td_headers)
    before = validate_success(api.validate_prep_feed(prep_a["id"], td_headers), 200)

    assert_status(before, "VALIDATED", "prep status")
    assert_instant_equals(
        before["feed_validated_at"], "2026-08-09T23:59:00.000Z", "feed_validated_at"
    )
    assert read_feed(api, feed["id"])["active_consumer_count"] == 1

    set_clock(api, "2026-08-10T00:00:00Z", headers=td_headers)
    response = api.validate_prep_feed(prep_b["id"], td_headers)

    validate_error(response, "ERR_FEED_CONTRACT_EXPIRED")
    blocked = read_prep(api, prep_b["id"])
    assert_status(blocked, "PENDING", "prep status")
    assert blocked["feed_validated_at"] is None
    assert read_feed(api, feed["id"])["active_consumer_count"] == 1, (
        "the expired validation attempt consumed no slot"
    )
    assert_instant_equals(
        read_prep(api, prep_a["id"])["feed_validated_at"],
        "2026-08-09T23:59:00.000Z",
        "feed_validated_at",
    )


# ---------------------------------------------------------------------------
# replay_channel_count is required for REPLAY and forbidden elsewhere
# ---------------------------------------------------------------------------
def test_replay_channel_count_is_required_for_replay_and_forbidden_for_graphics(
    api, td_headers
):
    """The same field is mandatory on one kind and rejected on every other kind.

    PRD: "`replay_channel_count`, the number of replay channels to be armed, is required when the kind is `REPLAY` and forbidden otherwise, and must be at least 1 when present."
    Design: Corner/validations/replay_prep_requires_a_channel_count_that_other_kinds_forbid
    """
    production = new_production(api)
    feed = new_data_feed(
        api, latency_ms=120, contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=4,
    )

    missing = create_system_prep_payload(
        production["id"], feed["id"], system_kind="REPLAY"
    )
    missing.pop("replay_channel_count", None)
    validate_error(api.create_system_prep(missing, td_headers), "ERR_INVALID_REQUEST")

    forbidden = create_system_prep_payload(
        production["id"], feed["id"], system_kind="GRAPHICS", replay_channel_count=4
    )
    validate_error(api.create_system_prep(forbidden, td_headers), "ERR_INVALID_REQUEST")

    accepted = validate_success(
        api.create_system_prep(
            create_system_prep_payload(
                production["id"], feed["id"], system_kind="REPLAY",
                replay_channel_count=4,
            ),
            td_headers,
        ),
        201,
    )
    assert_system_prep(accepted)
    assert_status(accepted, "PENDING", "prep status")
    assert accepted["replay_channel_count"] == 4
    rows, meta = validate_paginated(
        api.list_system_preps(td_headers, params={"production_id": production["id"]})
    )
    assert meta["total_count"] == 1, "neither refused payload was persisted"
    assert rows[0]["id"] == accepted["id"]


# ---------------------------------------------------------------------------
# A validated preparation cannot be validated twice
# ---------------------------------------------------------------------------
def test_revalidating_an_already_validated_prep_is_refused(api, td_headers):
    """The second validation is a state error and leaves the first stamp intact.

    PRD: "The preparation itself must be in `PENDING` or `FAILED`; an already-`VALIDATED` preparation cannot be re-validated and is refused with `ERR_PREP_STATE_INVALID`."
    PRD: "Then the consumer ceiling: validation is refused with `ERR_FEED_CONSUMER_LIMIT` when the feed's `active_consumer_count` has reached `max_concurrent_consumers`, equality being enough to block, where that count includes only preparations currently sitting in `VALIDATED`."
    Design: Corner/errors/revalidating_an_already_validated_prep_rejected
    """
    production = new_production(api)
    feed = new_data_feed(
        api, latency_ms=120, contract_expiry_utc="2026-12-31T00:00:00Z",
        max_concurrent_consumers=4,
    )
    prep = create_prep(api, production["id"], feed["id"], system_kind="GRAPHICS")

    first = validate_success(api.validate_prep_feed(prep["id"], td_headers), 200)
    assert_status(first, "VALIDATED", "prep status")
    assert_instant_equals(
        first["feed_validated_at"], CLOCK_EPOCH_STAMP, "feed_validated_at"
    )
    assert read_feed(api, feed["id"])["active_consumer_count"] == 1

    response = api.validate_prep_feed(prep["id"], td_headers)

    validate_error(response, "ERR_PREP_STATE_INVALID")
    unchanged = read_prep(api, prep["id"])
    assert_status(unchanged, "VALIDATED", "prep status")
    assert_instant_equals(
        unchanged["feed_validated_at"], CLOCK_EPOCH_STAMP, "feed_validated_at"
    )
    assert read_feed(api, feed["id"])["active_consumer_count"] == 1, (
        "the refused re-validation did not double-count the consumer"
    )
