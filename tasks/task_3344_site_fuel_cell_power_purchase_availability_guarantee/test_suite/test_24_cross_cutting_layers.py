"""The layers that cut across every workflow: the optimistic-concurrency
guards, the draw posture that moves with a single request, and the way a
filtered collection pages."""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_fuel_delivery_payload,
    create_settlement_line_payload,
    issue_allowance_payload,
)
from test_helpers.fixtures import (
    ANALYST,
    FUEL_COORDINATOR,
    OPERATOR,
    create_settlement_line,
    create_site,
    get_delivery,
    get_ppa,
    get_site,
    issue_allowance,
    list_deliveries,
    post_accrual,
    schedule_delivery,
    set_clock,
    setup_active_ppa,
    take_resource_hold,
)

LATER_PERIOD = {"period_start": "2026-04-11T00:00:00Z", "period_end": "2026-05-11T00:00:00Z"}


def test_a_delivery_create_on_a_superseded_site_view_is_refused():
    """PRD §2.7: "Scheduling a fuel delivery against a site is guarded: the request must carry
    `expected_site_version` equal to the target `Site`'s current `version`. A site may legitimately
    hold many scheduled deliveries, so the only thing that can make a second, otherwise valid
    create illegitimate is that the client is acting on a site view that an earlier write has
    already superseded — that earlier write will have advanced `Site.version` through its own
    cascades into `draw_position_therms`. The rejection code is `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_layers/create_delivery_with_a_stale_site_version_returns_stale_version
    """
    set_clock()
    site = create_site()
    stale_version = site["version"]

    schedule_delivery(
        site["id"],
        volume_therms=2000,
        delivered_at="2026-03-12T00:00:00Z",
        confirm_after_iso8601="2026-03-13T00:00:00Z",
    )
    fresh = get_site(site["id"])
    assert fresh["version"] != stale_version, (
        "the first create must have advanced the site version, otherwise the stale form "
        "below would not be stale at all"
    )

    stale = api_client.create_fuel_delivery(
        site["id"],
        FUEL_COORDINATOR,
        create_fuel_delivery_payload(
            expected_site_version=stale_version,
            volume_therms=3000,
            delivered_at="2026-03-14T00:00:00Z",
            confirm_after_iso8601="2026-03-15T00:00:00Z",
        ),
    )

    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412, (
        f"a superseded site view is a precondition failure; got {stale.status_code}"
    )
    assert len(list_deliveries(site["id"])) == 1, (
        "nothing is persisted by a stale-version refusal"
    )

    retry = api_client.create_fuel_delivery(
        site["id"],
        FUEL_COORDINATOR,
        create_fuel_delivery_payload(
            expected_site_version=get_site(site["id"])["version"],
            volume_therms=3000,
            delivered_at="2026-03-14T00:00:00Z",
            confirm_after_iso8601="2026-03-15T00:00:00Z",
        ),
    )
    accepted = validate_success(retry, expected_status=201)
    assert accepted["lifecycle_state"] == "DELIVERY_SCHEDULED"
    assert len(list_deliveries(site["id"])) == 2


def test_a_settlement_line_create_on_a_superseded_contract_view_is_refused():
    """PRD §2.7: "Creating a settlement line against a contract is guarded the same way, with
    `expected_ppa_version` compared against the target `Ppa`'s current `version`. Opening a second
    settlement period is otherwise a legitimate act, so again the sole guard is the caller's
    observed contract version, which an earlier create has already advanced by rewriting the
    contract's pool-derived fields. The rejection code is `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_layers/create_settlement_line_with_a_stale_ppa_version_returns_stale_version
    """
    ctx = setup_active_ppa()
    stale_version = get_ppa(ctx["ppa_id"])["version"]

    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100000)
    create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-04-11T00:00:00Z",
    )
    fresh = get_ppa(ctx["ppa_id"])
    assert fresh["version"] > stale_version, (
        "an intervening write must leave the contract on a newer version than the caller saw"
    )

    stale = api_client.create_settlement_line(
        ctx["ppa_id"],
        ANALYST,
        create_settlement_line_payload(
            expected_ppa_version=stale_version, **LATER_PERIOD
        ),
    )

    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412
    rows, meta = validate_paginated(
        api_client.list_settlement_lines(ctx["ppa_id"], ANALYST)
    )
    assert meta["total_count"] == 1, (
        f"the refused period must not be persisted; found {meta['total_count']} rows"
    )

    retry = api_client.create_settlement_line(
        ctx["ppa_id"],
        ANALYST,
        create_settlement_line_payload(
            expected_ppa_version=get_ppa(ctx["ppa_id"])["version"], **LATER_PERIOD
        ),
    )
    accepted = validate_success(retry, expected_status=201)
    assert accepted["status"] == "SETTLEMENT_DRAFT"


def test_an_allowance_issued_against_a_superseded_contract_view_is_refused():
    """PRD §2.7: "Issuing a settlement allowance against a contract is the third guarded write,
    and it too carries `expected_ppa_version` compared against the target `Ppa`'s current `version`.
    Issuing a further allowance is otherwise legitimate; a stale observed contract version is the
    only thing that blocks it. The rejection code is `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_layers/issue_allowance_with_a_stale_ppa_version_returns_stale_version
    """
    ctx = setup_active_ppa()
    observed_version = get_ppa(ctx["ppa_id"])["version"]
    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100000)

    stale = api_client.issue_allowance(
        ctx["ppa_id"],
        ANALYST,
        issue_allowance_payload(expected_ppa_version=observed_version - 1),
    )

    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412
    rows, meta = validate_paginated(
        api_client.list_allowances(ctx["ppa_id"], ANALYST)
    )
    assert meta["total_count"] == 0, (
        f"a stale-version refusal issues nothing; found {meta['total_count']} allowances"
    )

    issued = issue_allowance(ctx["ppa_id"], amount_cents=185000)
    assert issued["lifecycle_state"] == "ALLOWANCE_ISSUED", (
        f"the same call on the current version succeeds; got {issued['lifecycle_state']}"
    )


def test_a_resource_hold_moves_an_available_site_into_drawing_with_no_batch_run():
    """PRD §3.3: "Taking
    a resource hold moves a site from `RESOURCE_AVAILABLE` to `RESOURCE_DRAWING`, and it requires
    the site to be `SITE_ACTIVE`, to hold at least the requested volume in
    `draw_position_therms`, and to be below its simultaneous-commitment ceiling counting all
    deliveries in `DELIVERY_SCHEDULED` or `DELIVERY_IN_TRANSIT` other than the one being created."

    Design: Corner/cross_cutting_layers/site_registration_advances_draw_posture_without_an_ops_run
    """
    set_clock()
    site = create_site()
    assert site["lifecycle_state"] == "RESOURCE_AVAILABLE"
    opening = site["draw_position_therms"]
    assert opening == site["initial_fuel_inventory_therms"]

    response = api_client.take_resource_hold(
        site["id"],
        OPERATOR,
        {
            "requested_therms": 25000,
            "window_start_iso8601": "2026-04-01T00:00:00Z",
            "window_end_iso8601": "2026-04-04T00:00:00Z",
        },
    )
    hold = validate_success(response, expected_status=201)

    assert hold["volume_therms"] == 25000
    assert hold["lifecycle_state"] == "DELIVERY_SCHEDULED"
    moved = get_site(site["id"])
    assert moved["draw_position_therms"] == opening - 25000, (
        "the hold draws the pool down by its own volume in the same request"
    )
    assert moved["lifecycle_state"] == "RESOURCE_DRAWING", (
        "the resource dimension advances on the hold alone, with no batch run behind it"
    )
    assert moved["status"] == "SITE_ACTIVE", (
        "the posture dimension is independent of the resource dimension"
    )


def test_a_released_hold_returns_its_window_to_the_site():
    """PRD §2.6: "because a delivery is a reservation before it is a physical event, the
    system treats scheduling a delivery as an immediate draw against the pool and treats
    cancelling one as an immediate restoration."
    PRD §3.3: "Releasing a hold is a `SiteOperator` action that names the hold through `delivery_id`: the
    named delivery moves to `DELIVERY_CANCELLED`, the site's `draw_position_therms` is increased
    by exactly the released `volume_therms` so that the pool returns to its prior value without
    drift, and the site's `lifecycle_state` returns to `RESOURCE_AVAILABLE` — but only when the
    site's `active_ppa_count` is zero, because a site still hosting live contracts has no business
    declaring itself resource-free."

    Design: Corner/cross_cutting_layers/canceled_hold_returns_its_window_for_reuse
    """
    set_clock()
    site = create_site()
    window = {
        "window_start_iso8601": "2026-04-01T00:00:00Z",
        "window_end_iso8601": "2026-04-04T00:00:00Z",
    }
    opening = site["draw_position_therms"]
    first = take_resource_hold(site["id"], requested_therms=25000, **window)

    released = validate_success(
        api_client.release_resource_hold(
            site["id"], OPERATOR, {"delivery_id": first["id"]}
        )
    )

    assert (
        get_delivery(site["id"], first["id"])["lifecycle_state"] == "DELIVERY_CANCELLED"
    ), "the released hold is cancelled rather than deleted"
    assert released["draw_position_therms"] == opening, (
        "the released volume returns the pool to its prior value without drift"
    )
    assert released["lifecycle_state"] == "RESOURCE_AVAILABLE"

    second = take_resource_hold(site["id"], requested_therms=25000, **window)
    assert second["id"] != first["id"], "a fresh hold is created, not the cancelled one revived"
    assert second["lifecycle_state"] == "DELIVERY_SCHEDULED"
    assert get_site(site["id"])["draw_position_therms"] == opening - 25000

    rows = list_deliveries(site["id"])
    assert {row["id"] for row in rows} == {first["id"], second["id"]}, (
        "the cancelled hold stays queryable through the site's delivery collection"
    )


def test_filtered_pages_of_accruals_are_disjoint_and_cover_every_match_once():
    """PRD §2.4: "The accrual collection filters on `ppa_id`, `site_id`, `accrual_type`,
    `lifecycle_state`, `source_settlement_line_id` and `applied_allowance_id`."
    PRD §2.4: "Every one of these
    list operations also accepts `limit` and `offset` per §2.3."
    PRD §2.3: "`total_count` reports the size
    of the full filtered collection, not the size of the page, and `has_more` reports whether
    further items remain beyond the page that was returned."

    Design: Corner/cross_cutting_layers/list_filter_and_pagination_compose_without_duplicates
    """
    ctx = setup_active_ppa()
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        amount_cents=100000,
        period_anchor_iso8601="2026-01-01T00:00:00Z",
    )
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        amount_cents=100000,
        period_anchor_iso8601="2026-02-01T00:00:00Z",
    )
    trueup = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="TRUEUP_ACCRUAL",
        amount_cents=25000,
        period_anchor_iso8601="2026-03-01T00:00:00Z",
    )

    first_page = api_client.list_accruals(
        ANALYST,
        {
            "ppa_id": ctx["ppa_id"],
            "accrual_type": "CHARGE_ACCRUAL",
            "limit": 2,
            "offset": 0,
        },
    )
    first_rows, first_meta = validate_paginated(first_page)
    assert first_meta["total_count"] == 2, (
        "the filter is applied before the page is cut, so the true-up row is not counted; got "
        f"{first_meta['total_count']}"
    )
    assert len(first_rows) == 2
    assert first_meta["has_more"] is False, (
        "two matching rows fit inside a limit of two, so nothing remains beyond the page"
    )

    second_page = api_client.list_accruals(
        ANALYST,
        {
            "ppa_id": ctx["ppa_id"],
            "accrual_type": "CHARGE_ACCRUAL",
            "limit": 2,
            "offset": 2,
        },
    )
    second_rows, second_meta = validate_paginated(second_page)
    assert second_rows == [], "the second page is past the end of the filtered collection"
    assert second_meta["has_more"] is False

    union = [row["id"] for row in first_rows + second_rows]
    assert len(union) == len(set(union)) == 2, (
        "paging must not repeat a row: the union of the pages covers each match exactly once"
    )

    everything, all_meta = validate_paginated(
        api_client.list_accruals(ANALYST, {"ppa_id": ctx["ppa_id"]})
    )
    assert all_meta["total_count"] == 3
    assert {row["id"] for row in everything} - set(union) == {trueup["id"]}, (
        "the unfiltered collection carries exactly the one row the filter excluded"
    )
