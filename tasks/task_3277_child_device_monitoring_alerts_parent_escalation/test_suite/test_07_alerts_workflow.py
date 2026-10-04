"""Alert lifecycle: initial state, transitions, invalid edges, counts, feeds."""
import pytest

from test_helpers import (
    ApiErrorId,
    ingest_content,
    make_parent_headers,
    setup_alert,
    setup_monitoring_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_alert_created_in_delivered_initial_state(api):
    """PRD §3.6: "The alert is created in `DELIVERED` status, copies the
    `severity` from the content item, takes the dominant category as its own
    `category`, links back through `content_item_id`, and carries the excerpt
    described next."
    PRD §2.8: "The `ChildProfile.open_alert_count` equals the number of the
    child's alerts whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or
    `REOPENED`; resolving an alert decreases it by one and reopening increases
    it by one, and a resolve followed by a reopen restores the prior value
    exactly."

    Design: Corner/state_machines/alert_created_in_delivered_initial_state
    """
    fam, parent, child, dev, conn, item = setup_alert()
    assert item["alert_created"] is True

    headers = make_parent_headers(parent["id"])
    alert = validate_success(api.get_alert(item["alert_id"], headers))
    assert alert["alert_status"] == "DELIVERED"

    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 1


def test_alert_acknowledge_from_resolved_returns_409(api):
    """PRD §3.9: "Requesting any transition that does not exist from the
    alert's current state is rejected with `ERR_INVALID_STATE`."
    PRD §3.9: "From `RESOLVED`, reopening moves the alert to `REOPENED` and
    recomputes the count up by one."

    Design: Corner/state_machines/alert_acknowledge_from_resolved_returns_409
    """
    fam, parent, child, dev, conn, item = setup_alert()
    headers = make_parent_headers(parent["id"])
    alert_id = item["alert_id"]

    validate_success(api.set_alert_state(alert_id, {"to_status": "ACKNOWLEDGED"}, headers))
    validate_success(api.set_alert_state(alert_id, {"to_status": "RESOLVED"}, headers))

    # RESOLVED -> ACKNOWLEDGED is not a declared edge.
    resp = api.set_alert_state(alert_id, {"to_status": "ACKNOWLEDGED"}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    alert = validate_success(api.get_alert(alert_id, headers))
    assert alert["alert_status"] == "RESOLVED"


def test_alert_resolve_reopen_cycle(api):
    """PRD §3.9: "From `DELIVERED`, acknowledging moves the alert to
    `ACKNOWLEDGED`; when the alert has a linked escalation case still `OPEN`,
    that case advances to `GUIDANCE_ISSUED` as part of the same action, and the
    child's `open_alert_count` is recomputed. From `ACKNOWLEDGED` or from
    `REOPENED`, resolving moves the alert to `RESOLVED` and recomputes the
    child's `open_alert_count` down by one — with one guard: resolving a
    `SEVERE` alert requires its linked escalation case to be `CLOSED` first, and
    is otherwise rejected with `ERR_ESCALATION_OPEN`. From `REOPENED`,
    acknowledging returns the alert to `ACKNOWLEDGED` with the count recomputed.
    From `RESOLVED`, reopening moves the alert to `REOPENED` and recomputes the
    count up by one."

    Design: Difficulty/non_linear_state_machine/alert_resolve_reopen_cycle
    """
    fam, parent, child, dev, conn, item = setup_alert()
    headers = make_parent_headers(parent["id"])
    alert_id = item["alert_id"]

    sequence = ["ACKNOWLEDGED", "RESOLVED", "REOPENED", "ACKNOWLEDGED", "RESOLVED"]
    for to_status in sequence:
        alert = validate_success(
            api.set_alert_state(alert_id, {"to_status": to_status}, headers)
        )
        assert alert["alert_status"] == to_status

    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 0


def test_alert_resolve_reopen_count_conservation(api):
    """PRD §2.8: "The `ChildProfile.open_alert_count` equals the number of the
    child's alerts whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or
    `REOPENED`; resolving an alert decreases it by one and reopening increases
    it by one, and a resolve followed by a reopen restores the prior value
    exactly."

    Design: Difficulty/compensating_invariant/alert_resolve_reopen_count_conservation
    """
    fam, parent, child, dev, conn, item = setup_alert(direction="OUTBOUND")
    headers = make_parent_headers(parent["id"])
    alert_id = item["alert_id"]

    validate_success(api.set_alert_state(alert_id, {"to_status": "ACKNOWLEDGED"}, headers))
    validate_success(api.set_alert_state(alert_id, {"to_status": "RESOLVED"}, headers))
    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 0

    validate_success(api.set_alert_state(alert_id, {"to_status": "REOPENED"}, headers))
    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 1


def test_alert_feed_immediate_vs_digest_variants(api):
    """PRD §3.9: "The default, `IMMEDIATE`, surfaces each of a child's alerts
    whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or `REOPENED` and whose
    severity is `MODERATE`, `HIGH`, or `SEVERE`. The `DIGEST` variant applies
    the same status filter but admits only `HIGH` and `SEVERE` severities,
    dropping moderate noise from the periodic summary. Both variants exclude
    `RESOLVED` alerts entirely, and both sort the feed by `created_at`
    descending — the one list surface in the system that departs from the
    ascending default."

    Design: Difficulty/dual_variant_calc/alert_feed_immediate_vs_digest_variants
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(
        birth_year=2012, service_type="SOCIAL"
    )
    item_mod = ingest_content(
        conn["id"], dev["id"],
        signals=[
            {"category": "BULLYING", "weight": 30},
            {"category": "EXPLICIT", "weight": 25},
        ],
        raw_text="moderate item",
    )
    item_high = ingest_content(
        conn["id"], dev["id"],
        signals=[
            {"category": "SELF_HARM", "weight": 45},
            {"category": "BULLYING", "weight": 30},
        ],
        raw_text="high item",
        occurred_at="2026-09-01T00:00:00Z",
    )
    assert item_mod["severity"] == "MODERATE"
    assert item_high["severity"] == "HIGH"

    headers = make_parent_headers(parent["id"])
    immediate, meta_i = validate_paginated(
        api.list_alerts(
            headers,
            params={"child_profile_id": child["id"], "variant": "IMMEDIATE"},
        )
    )
    digest, meta_d = validate_paginated(
        api.list_alerts(
            headers,
            params={"child_profile_id": child["id"], "variant": "DIGEST"},
        )
    )

    immediate_ids = {a["id"] for a in immediate}
    digest_ids = {a["id"] for a in digest}
    assert immediate_ids == {item_mod["alert_id"], item_high["alert_id"]}
    assert digest_ids == {item_high["alert_id"]}
    severities = {a["id"]: a["severity"] for a in immediate}
    assert severities[item_mod["alert_id"]] == "MODERATE"
    assert severities[item_high["alert_id"]] == "HIGH"


def test_alert_feed_excludes_resolved(api):
    """PRD §3.9: "Both variants exclude `RESOLVED` alerts entirely, and both
    sort the feed by `created_at` descending — the one list surface in the
    system that departs from the ascending default."

    Design: Difficulty/dual_variant_calc/alert_feed_immediate_vs_digest_variants
    """
    fam, parent, child, dev, conn, item = setup_alert()
    headers = make_parent_headers(parent["id"])
    alert_id = item["alert_id"]

    validate_success(api.set_alert_state(alert_id, {"to_status": "ACKNOWLEDGED"}, headers))
    validate_success(api.set_alert_state(alert_id, {"to_status": "RESOLVED"}, headers))

    immediate, meta_i = validate_paginated(
        api.list_alerts(
            headers,
            params={"child_profile_id": child["id"], "variant": "IMMEDIATE"},
        )
    )
    assert immediate == []
    assert meta_i["total_count"] == 0


def test_alerts_filtered_by_status(api):
    """PRD §3.9: "The feed may be further narrowed with `child_profile_id`,
    `content_item_id`, or `alert_status` query parameters, alongside the usual
    `limit` and `offset`."

    Design: Corner/endpoints/alerts_filtered_by_status
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    item1 = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}], raw_text="filter item 1",
    )
    item2 = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}], raw_text="filter item 2",
        occurred_at="2026-09-01T00:00:00Z",
    )
    headers = make_parent_headers(parent["id"])
    validate_success(
        api.set_alert_state(item1["alert_id"], {"to_status": "ACKNOWLEDGED"}, headers)
    )
    validate_success(
        api.set_alert_state(item1["alert_id"], {"to_status": "RESOLVED"}, headers)
    )

    resolved, meta = validate_paginated(
        api.list_alerts(
            headers,
            params={"child_profile_id": child["id"], "alert_status": "RESOLVED"},
        )
    )
    # PRD §3.9: "Both variants exclude RESOLVED alerts entirely", so narrowing
    # by alert_status=RESOLVED yields an empty feed.
    assert meta["total_count"] == 0
    assert resolved == []

    acked, meta = validate_paginated(
        api.list_alerts(
            headers,
            params={"child_profile_id": child["id"], "alert_status": "DELIVERED"},
        )
    )
    assert meta["total_count"] == 1
    assert [a["id"] for a in acked] == [item2["alert_id"]]
    assert item1["alert_id"] not in {a["id"] for a in acked}


def test_alert_reopened_excluded_from_digest_like_resolved(api):
    """PRD §3.9: "The default, `IMMEDIATE`, surfaces each of a child's alerts
    whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or `REOPENED` and whose
    severity is `MODERATE`, `HIGH`, or `SEVERE`. The `DIGEST` variant applies
    the same status filter but admits only `HIGH` and `SEVERE` severities,
    dropping moderate noise from the periodic summary. Both variants exclude
    `RESOLVED` alerts entirely, and both sort the feed by `created_at`
    descending — the one list surface in the system that departs from the
    ascending default."
    PRD §3.9: "From `RESOLVED`, reopening moves the alert to `REOPENED` and
    recomputes the count up by one."

    Design: Difficulty/non_linear_state_machine/alert_resolve_reopen_cycle
    """
    fam, parent, child, dev, conn, item = setup_alert()
    headers = make_parent_headers(parent["id"])
    alert_id = item["alert_id"]

    validate_success(api.set_alert_state(alert_id, {"to_status": "ACKNOWLEDGED"}, headers))
    validate_success(api.set_alert_state(alert_id, {"to_status": "RESOLVED"}, headers))

    # While RESOLVED the alert is out of the feed entirely.
    feed, meta = validate_paginated(
        api.list_alerts(headers, params={"child_profile_id": child["id"]})
    )
    assert feed == []

    # Reopening returns it to the feed (REOPENED is an open status).
    validate_success(api.set_alert_state(alert_id, {"to_status": "REOPENED"}, headers))
    feed, meta = validate_paginated(
        api.list_alerts(headers, params={"child_profile_id": child["id"]})
    )
    assert [a["id"] for a in feed] == [alert_id]
    assert feed[0]["alert_status"] == "REOPENED"


def test_alert_open_count_with_two_alerts_resolve_reopen(api):
    """PRD §2.8: "The `ChildProfile.open_alert_count` equals the number of the
    child's alerts whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or
    `REOPENED`; resolving an alert decreases it by one and reopening increases
    it by one, and a resolve followed by a reopen restores the prior value
    exactly."

    Design: Difficulty/compensating_invariant/alert_resolve_reopen_count_conservation
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    item1 = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}], raw_text="count item 1",
    )
    item2 = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}], raw_text="count item 2",
        occurred_at="2026-09-01T00:00:00Z",
    )
    headers = make_parent_headers(parent["id"])

    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 2

    validate_success(
        api.set_alert_state(item1["alert_id"], {"to_status": "ACKNOWLEDGED"}, headers)
    )
    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 2, "ACKNOWLEDGED is still an open status"

    validate_success(
        api.set_alert_state(item1["alert_id"], {"to_status": "RESOLVED"}, headers)
    )
    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 1

    validate_success(
        api.set_alert_state(item1["alert_id"], {"to_status": "REOPENED"}, headers)
    )
    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 2, "reopen restores the prior count exactly"
