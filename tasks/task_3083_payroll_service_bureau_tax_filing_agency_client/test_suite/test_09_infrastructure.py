"""Response envelope, pagination, and settlement timing tests (PRD §2.2–§2.6, §3.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_client,
    create_jurisdiction,
    create_run,
    get_client,
    impound_run,
    set_clock,
    setup_active_client,
    submit_run,
    validate_paginated,
    validate_success,
)


def test_jurisdiction_create_returns_declared_fields():
    """PRD §3.1: "The `active` flag defaults to true; an inactive jurisdiction
    cannot receive new registrations or deposits."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    exactly 1 on every mutation of the resource."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/e_jurisdiction_create_returns_declared_fields
    """
    resp = api_client.create_jurisdiction(
        {
            "code": "FED-941",
            "name": "IRS Form 941",
            "deposit_frequency": "SEMIWEEKLY",
            "penalty_tier1_rate": 0.02,
            "penalty_tier2_rate": 0.05,
            "penalty_tier3_rate": 0.10,
            "underpayment_threshold_cents": 250000,
        },
        TEST_USERS["compliance_headers"],
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
    assert body["meta"].get("api_request_timestamp"), (
        "meta.api_request_timestamp must be present"
    )
    jur = body["data"]
    assert jur["active"] is True
    assert jur["version"] == 1
    assert jur["deposit_frequency"] == "SEMIWEEKLY"


def test_jurisdiction_create_round_trips_configuration():
    """PRD §3.1: "Each Jurisdiction is created with a bureau-scoped unique `code`
    (values like FED-941, CA-DE9, NY-NYS45), a display `name`, a
    `deposit_frequency` of `SEMIWEEKLY`, `MONTHLY`, or `QUARTERLY`, three
    fractional penalty rates, and an `underpayment_threshold_cents` integer used
    for the quarterly safe-harbor test."

    Design: Corner/entities/e_jurisdiction_create_returns_declared_fields
    """
    jur = create_jurisdiction(
        code="CA-DE9",
        name="CA EDD DE9",
        deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    assert jur["code"] == "CA-DE9"
    assert jur["name"] == "CA EDD DE9"
    assert jur["penalty_tier1_rate"] == 0.02
    assert jur["penalty_tier2_rate"] == 0.05
    assert jur["penalty_tier3_rate"] == 0.10
    assert jur["underpayment_threshold_cents"] == 250000
    fetched = validate_success(
        api_client.get_jurisdiction(jur["id"], TEST_USERS["compliance_headers"])
    )
    assert fetched["id"] == jur["id"]


def test_clients_list_paginates_total_count_and_has_more():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips that many items from the start of the result set and defaults
    to 0. ... List responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope."

    Design: Corner/entities/e_clients_list_paginates_total_count_and_has_more
    """
    create_client(legal_name="Page One")
    create_client(legal_name="Page Two")
    create_client(legal_name="Page Three")

    page1, meta1 = validate_paginated(
        api_client.list_clients(
            TEST_USERS["compliance_headers"], params={"limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_clients(
            TEST_USERS["compliance_headers"], params={"limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_clients_list_pages_do_not_overlap():
    """PRD §2.3: "The `offset` parameter skips that many items from the start of
    the result set and defaults to 0. Unless otherwise specified, all list
    endpoints return resources sorted by creation timestamp in ascending order."

    Design: Corner/entities/e_clients_list_paginates_total_count_and_has_more
    """
    c1 = create_client(legal_name="Order One")
    c2 = create_client(legal_name="Order Two")
    c3 = create_client(legal_name="Order Three")

    page1, _ = validate_paginated(
        api_client.list_clients(
            TEST_USERS["compliance_headers"], params={"limit": 2, "offset": 0}
        )
    )
    page2, _ = validate_paginated(
        api_client.list_clients(
            TEST_USERS["compliance_headers"], params={"limit": 2, "offset": 2}
        )
    )
    ids1 = {c["id"] for c in page1}
    ids2 = {c["id"] for c in page2}
    assert ids1.isdisjoint(ids2)
    assert ids1 | ids2 == {c1["id"], c2["id"], c3["id"]}


def test_settlement_timing_weekend_rollover():
    """PRD §3.4: "for `STANDARD` funding, `due_by` is `initiated_at` plus 2
    business days (rolling forward over Saturdays and Sundays only — a Friday
    initiation lands the deadline on the following Tuesday)."
    PRD §2.6: "The bureau observes no holiday calendar. Business-day arithmetic
    rolls forward over Saturdays and Sundays only: adding two business days to a
    Friday initiation lands on the following Tuesday."

    Design: Corner/calculations/c_settlement_timing_weekend_rollover
    """
    setup = setup_active_client()
    client = setup["client"]

    # Friday 2026-09-04 initiation: +2 business days skips the weekend -> Tue 09-08.
    fri_run = create_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
    )
    submit_run(client, fri_run)
    set_clock("2026-09-04T10:00:00Z")
    fri_imp = impound_run(client, fri_run)
    assert fri_imp["due_by"][:10] == "2026-09-08"

    # Wednesday 2026-09-02 initiation: +2 business days -> Friday 2026-09-04
    # (counted from the day after initiation: Thu=day1, Fri=day2 — consistent
    # with the PRD's Friday-initiation-lands-Tuesday example).
    wed_run = create_run(
        client,
        pay_date="2026-09-09T00:00:00Z",
        period_start="2026-09-05T00:00:00Z",
        period_end="2026-09-09T00:00:00Z",
    )
    submit_run(client, wed_run)
    set_clock("2026-09-02T10:00:00Z")
    wed_imp = impound_run(client, wed_run)
    assert wed_imp["due_by"][:10] == "2026-09-04"


def test_settlement_timing_weekday_initiation_no_rollover():
    """PRD §3.4: "for `STANDARD` funding, `due_by` is `initiated_at` plus 2
    business days (rolling forward over Saturdays and Sundays only — a Friday
    initiation lands the deadline on the following Tuesday)."

    Design: Corner/calculations/c_settlement_timing_weekend_rollover
    """
    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    # Default clock is Tuesday 2026-09-01: +2 business days -> Thursday 2026-09-03.
    imp = impound_run(client, run)
    assert imp["due_by"][:10] == "2026-09-03"
