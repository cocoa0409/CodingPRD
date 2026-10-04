"""Bureau pull side effects, factor explanations and score-alert evaluation."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.constants import SCORE_ALERT_DEFAULT_THRESHOLD
from test_helpers.factories import create_bureau_snapshot_payload
from test_helpers.fixtures import (
    BUREAU_CONNECTOR,
    PLATFORM_ADMIN,
    advance_clock,
    create_consumer,
    create_monitored_consumer,
    grant_consent,
    list_consumer_alerts,
    pull_bureau_snapshot,
    read_consumer,
    read_consumer_version,
)


def test_computed_utilization_is_derived_from_the_balances(api, as_consumer):
    """PRD §2.6: "Each snapshot carries a computed `overall_credit_utilization_pct`
    derived from its own balances".

    Design: Corner/entities/snapshot_computed_utilization_is_derived_not_client_supplied
    """
    consumer = create_consumer(email="comp@example.com", bureau_pin="3333", api=api)
    grant_consent(consumer["id"], api=api)
    version = read_consumer_version(consumer["id"], api=api)
    response = api.create_bureau_snapshot(
        consumer["id"],
        create_bureau_snapshot_payload(
            version, score=660, total_revolving_balance_cents=540_000,
            credit_limit_total_cents=1_200_000, added_account_count=2,
            factor_codes=["high_utilization", "length_of_credit_history"],
        ),
        BUREAU_CONNECTOR,
    )
    snapshot = validate_success(response, 201)

    assert snapshot["overall_credit_utilization_pct"] == 45.00
    assert snapshot["snapshot_ordinal"] == 1
    assert snapshot["status"] == "ACTIVE"

    explanations = validate_success(
        api.list_snapshot_factor_explanations(snapshot["id"], as_consumer(consumer["id"])),
        200,
    )
    assert [e["rank_index"] for e in explanations] == [0, 1]
    assert [e["factor_code"] for e in explanations] == [
        "high_utilization", "length_of_credit_history",
    ]


def test_snapshot_rejects_an_unknown_factor_code(api, as_consumer):
    """PRD §3.1: "Once at least one score tier is `ACTIVE`, every submitted code must
    appear somewhere in the `factor_catalog` of one of those tiers; while none is
    active, the platform does not enforce that membership at all."
    PRD §5: `ERR_INVALID_REQUEST` | 400 Bad Request

    Design: Corner/entities/snapshot_rejects_an_unknown_factor_code_before_persisting
    """
    from test_helpers.fixtures import create_active_score_tier

    create_active_score_tier(api=api)
    consumer = create_consumer(email="badf@example.com", bureau_pin="4444", api=api)
    grant_consent(consumer["id"], api=api)
    version = read_consumer_version(consumer["id"], api=api)

    response = api.create_bureau_snapshot(
        consumer["id"],
        create_bureau_snapshot_payload(version, factor_codes=["unmapped_mystery_factor"]),
        BUREAU_CONNECTOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert validate_success(
        api.list_consumer_bureau_snapshots(consumer["id"], PLATFORM_ADMIN), 200
    ) == []
    assert read_consumer(consumer["id"], api=api)["score_version"] == 0


def test_pull_side_effect_chain_creates_explanations_and_alert(api, as_consumer):
    """PRD §2.5: "Every accepted pull causes the previously `ACTIVE` snapshot for that
    consumer to be marked `SUPERSEDED`".
    PRD §2.6: "Each accepted pull also mints one `ScoreFactorExplanation` row per
    normalized factor code".
    PRD §3.1: "a movement whose negation reaches the effective threshold — that is, a
    drop of at least the effective threshold — sets it to `SCORE_DOWN`"

    Design: Corner/state_machines/snapshot_pull_side_effect_chain_creates_explanations_and_alert
    """
    consumer = create_consumer(email="alicef@example.com", bureau_pin="8888", api=api)
    grant_consent(consumer["id"], api=api)
    first = pull_bureau_snapshot(
        consumer["id"], score=700, balance_cents=420_000, factor_codes=["high_utilization"],
        api=api,
    )
    advance_clock("2026-09-02T00:00:00Z", api=api)
    second = pull_bureau_snapshot(
        consumer["id"], score=650, balance_cents=480_000,
        factor_codes=["high_utilization", "length_of_credit_history"], api=api,
    )

    assert api.get_bureau_snapshot(first["id"], as_consumer(consumer["id"])).json()[
        "data"
    ]["status"] == "SUPERSEDED"

    explanations = validate_success(
        api.list_snapshot_factor_explanations(second["id"], as_consumer(consumer["id"])), 200
    )
    assert len(explanations) == 2
    assert [e["rank_index"] for e in explanations] == [0, 1]

    data = read_consumer(consumer["id"], api=api)
    assert data["current_score"] == 650
    assert data["previous_score"] == 700
    assert data["utilization_pct"] == 40.00
    assert data["score_version"] == 2

    alerts = list_consumer_alerts(consumer["id"], api=api)
    down = [a for a in alerts if a["alert_kind"] == "SCORE_DOWN"]
    assert len(down) == 1
    assert down[0]["threshold_used"] == SCORE_ALERT_DEFAULT_THRESHOLD
    assert down[0]["status"] == "PENDING"


def test_pending_alert_is_suppressed_by_the_next_pull(api, as_consumer):
    """PRD §3.2: "when a daily run observes that the owning consumer's monitoring
    posture is not `COMPLETE`, every one of that consumer's `PENDING` alerts is moved
    to `SUPPRESSED`, and crucially the row is retained rather than deleted"

    Design: Difficulty/transitive_cascade/snapshot_pull_cascade_depth_two
    """
    consumer = create_consumer(email="cascade@example.com", bureau_pin="8889", api=api)
    grant_consent(consumer["id"], api=api)
    first = pull_bureau_snapshot(consumer["id"], score=660, api=api)
    advance_clock("2026-09-02T00:00:00Z", api=api)
    pull_bureau_snapshot(consumer["id"], score=690, api=api)

    up_alerts = list_consumer_alerts(consumer["id"], api=api, params={"status": "PENDING"})
    assert len(up_alerts) == 1
    assert up_alerts[0]["alert_kind"] == "SCORE_UP"

    advance_clock("2026-09-03T00:00:00Z", api=api)
    pull_bureau_snapshot(consumer["id"], score=620, api=api)

    all_alerts = list_consumer_alerts(consumer["id"], api=api)
    kinds = {(a["alert_kind"], a["status"]) for a in all_alerts}
    assert ("SCORE_UP", "PENDING") in kinds
    assert ("SCORE_DOWN", "PENDING") in kinds

    data = read_consumer(consumer["id"], api=api)
    assert data["current_score"] == 620
    assert data["previous_score"] == 690


def test_pending_alert_re_forms_on_the_new_pull(api, as_consumer):
    """PRD §3.1: "a movement that reaches the effective threshold in the positive
    direction sets `alert_kind` to `SCORE_UP`".
    PRD §3.2: "if it carries no entries the pull is a census with nothing in it"
    A PENDING row from the prior pull is retained as SUPPRESSED while the new pull
    writes its own PENDING row.

    Design: Difficulty/transitive_cascade/snapshot_pull_cascade_depth_two
    """
    consumer = create_consumer(email="cascade2@example.com", bureau_pin="8890", api=api)
    grant_consent(consumer["id"], api=api)
    pull_bureau_snapshot(consumer["id"], score=660, api=api)
    advance_clock("2026-09-02T00:00:00Z", api=api)
    pull_bureau_snapshot(consumer["id"], score=700, api=api)

    alerts = list_consumer_alerts(consumer["id"], api=api)
    assert len(alerts) == 2
    assert alerts[0]["alert_kind"] == "SCORE_FLAT"
    assert alerts[0]["status"] == "SUPPRESSED"
    assert alerts[1]["alert_kind"] == "SCORE_UP"
    assert alerts[1]["status"] == "PENDING"


def test_flat_move_writes_a_suppressed_row_echoing_the_channel(api, as_consumer):
    """PRD §3.1: "A `SCORE_FLAT` row is written already in status `SUPPRESSED`, and
    the requested channel is stored on it unchanged rather than being zeroed out."
    PRD §3.1: "The effective threshold is the larger of the consumer's
    `threshold_override_points` and the platform default of 20 points".

    Design: Corner/calculations/score_alert_flat_row_is_written_suppressed_at_the_default_threshold
    """
    consumer = create_consumer(email="flat@example.com", bureau_pin="2468", api=api)
    grant_consent(consumer["id"], api=api)
    pull_bureau_snapshot(consumer["id"], score=660, api=api)
    validate_success(
        api.set_score_alert_threshold(
            consumer["id"], {"threshold_override_points": 5}, as_consumer(consumer["id"])
        ),
        200,
    )
    advance_clock("2026-09-02T00:00:00Z", api=api)
    pull_bureau_snapshot(consumer["id"], score=679, api=api)

    alerts = list_consumer_alerts(consumer["id"], api=api)
    flat = [a for a in alerts if a["alert_kind"] == "SCORE_FLAT" and a["to_score"] == 679]
    assert len(flat) == 1
    assert flat[0]["status"] == "SUPPRESSED"
    assert flat[0]["threshold_used"] == SCORE_ALERT_DEFAULT_THRESHOLD
    assert flat[0]["from_score"] == 660
    assert flat[0]["to_score"] == 679


def test_alert_channel_is_stored_on_the_flat_row(api, as_consumer):
    """PRD §3.1: "`SCORE_UP` and `SCORE_DOWN` rows begin in status `PENDING` and are
    directed at the `channel` the caller requested, which is one of `EMAIL`, `PUSH` or
    `SMS`. A `SCORE_FLAT` row is written already in status `SUPPRESSED`, and the
    requested channel is stored on it unchanged rather than being zeroed out."

    Design: Corner/calculations/score_alert_flat_row_is_written_suppressed_at_the_default_threshold
    """
    consumer = create_consumer(email="chan@example.com", bureau_pin="2469", api=api)
    grant_consent(consumer["id"], api=api)
    pull_bureau_snapshot(consumer["id"], score=660, api=api)
    advance_clock("2026-09-02T00:00:00Z", api=api)
    version = read_consumer_version(consumer["id"], api=api)
    validate_success(
        api.create_bureau_snapshot(
            consumer["id"],
            create_bureau_snapshot_payload(
                version, score=665, total_revolving_balance_cents=480_000
            ),
            BUREAU_CONNECTOR,
        ),
        201,
    )

    alerts = list_consumer_alerts(consumer["id"], api=api)
    flat = [a for a in alerts if a["alert_kind"] == "SCORE_FLAT" and a["to_score"] == 665]
    assert len(flat) == 1
    assert flat[0]["status"] == "SUPPRESSED"


def test_bureau_pull_cooldown_excludes_the_boundary_hour(api, as_consumer):
    """PRD §2.5: "no `BureauSnapshot` for that consumer may have a `pulled_at` strictly
    later than the logical clock minus 24 hours (`PULL_COOLDOWN_HOURS`) — a pull
    attempted inside that cooldown is refused with `ERR_PULL_COOLDOWN_ACTIVE`."
    PRD §2.5: "The comparison is made at day granularity on the stored instant, so a
    pull that is exactly 30 days old is deactivated and one that is 29 days old is not."
    The 24-hour cooldown is a strict-greater-than comparison, so a pull at exactly
    pulled_at + 24h is outside the window.

    Design: Difficulty/resource_temporal_overlap/bureau_pull_cooldown_excludes_the_boundary_hour
    """
    consumer = create_consumer(email="cool@example.com", bureau_pin="7788", api=api)
    grant_consent(consumer["id"], api=api)
    pull_bureau_snapshot(consumer["id"], score=660, api=api)

    advance_clock("2026-09-01T23:00:00Z", api=api)
    version = read_consumer_version(consumer["id"], api=api)
    refused = api.create_bureau_snapshot(
        consumer["id"],
        create_bureau_snapshot_payload(version, score=670, total_revolving_balance_cents=470_000),
        BUREAU_CONNECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_PULL_COOLDOWN_ACTIVE, 409)
    assert read_consumer(consumer["id"], api=api)["score_version"] == 1

    advance_clock("2026-09-02T00:00:00Z", api=api)
    version = read_consumer_version(consumer["id"], api=api)
    accepted = api.create_bureau_snapshot(
        consumer["id"],
        create_bureau_snapshot_payload(version, score=675, total_revolving_balance_cents=460_000),
        BUREAU_CONNECTOR,
    )
    snapshot = validate_success(accepted, 201)
    assert snapshot["snapshot_ordinal"] == 2
    assert read_consumer(consumer["id"], api=api)["score_version"] == 2


def test_bureau_pull_cooldown_boundary_is_enforced_at_the_23rd_hour(api, as_consumer):
    """PRD §2.5: "a pull attempted inside that cooldown is refused with
    `ERR_PULL_COOLDOWN_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/bureau_pull_cooldown_excludes_the_boundary_hour
    """
    consumer = create_consumer(email="cool2@example.com", bureau_pin="7789", api=api)
    grant_consent(consumer["id"], api=api)
    pull_bureau_snapshot(consumer["id"], score=660, api=api)

    advance_clock("2026-09-01T23:00:00Z", api=api)
    version = read_consumer_version(consumer["id"], api=api)
    response = api.create_bureau_snapshot(
        consumer["id"],
        create_bureau_snapshot_payload(version, score=670),
        BUREAU_CONNECTOR,
    )
    data = validate_error(response, ApiErrorId.ERR_PULL_COOLDOWN_ACTIVE, 409)
    assert data["error_id"] == "ERR_PULL_COOLDOWN_ACTIVE"


def test_monitoring_window_day_boundary_on_staleness(api, as_consumer):
    """PRD §2.5: "A snapshot whose `pulled_at` is at or before the logical clock minus
    30 days (`SNAPSHOT_STALENESS_DAYS`) is superseded by the mobility stage of a daily run."
    PRD §2.5: "a pull that is exactly 30 days old is deactivated and one that is 29 days
    old is not."

    Design: Corner/calculations/monitoring_window_day_boundary_on_staleness
    """
    consumer, snapshot = create_monitored_consumer(
        score=660, balance_cents=100_000, email="stale@example.com", bureau_pin="1357", api=api
    )
    advance_clock("2026-10-01T00:00:00Z", api=api)
    validate_success(api.run_ops({"run_key": "stale-sweep-30"}, PLATFORM_ADMIN), 201)

    refreshed = validate_success(
        api.get_bureau_snapshot(snapshot["id"], as_consumer(consumer["id"])), 200
    )
    assert refreshed["status"] == "SUPERSEDED"
    data = read_consumer(consumer["id"], api=api)
    assert data["current_score"] == 660
    assert data["score_version"] == 1