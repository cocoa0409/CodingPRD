"""Access control, duty separation, stale-view guards and the imbalance tier boundary.

These tests exercise the cross-cutting layers the carrier's obligations rest on:
authentication and role authorization on the nomination and tariff surfaces,
shipper ownership on a single-nomination read, the segregation of duties between
the operator who publishes a cycle's schedule and the operator who certifies the
settlement it raised, the optimistic-concurrency tokens on nomination submission
and terminal inventory adjustment, and the tier boundary that decides whether a
shipper's volumetric imbalance is billed as STANDARD or as PENALTY.

Every test builds its own network, cycles, nominations and batch tickets from
scratch: the database is empty when the test starts and the logical clock reads
the instant it reads before any call.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANONYMOUS_HEADERS,
    CERTIFIER,
    CERTIFIER_USER_ID,
    OPERATOR,
    PUBLISHER,
    PUBLISHER_USER_ID,
    SCHEDULER,
    ApiErrorId,
    build_schedule,
    close_cycle,
    create_inventory_adjustment_payload,
    create_nomination_payload,
    create_tariff_payload,
    deliver_ticket,
    fund_linefill,
    inject_ticket,
    make_shipper_headers,
    nomination_key,
    nominate,
    open_cycle,
    prorate_cycle,
    publish_schedule,
    refresh_cycle,
    refresh_nomination,
    setup_closed_cycle,
    setup_cycle_with_nomination,
    setup_delivered_cycle,
    setup_draft_settlement,
    setup_network,
    setup_open_cycle,
    settle_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def _money(value) -> float:
    """Monetary and measured amounts as a float, whatever the wire rendering."""
    return float(value)


def test_nomination_submitted_without_a_role_header_is_unauthenticated(api):
    """PRD 2.1: "Every request to the service must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that
    principal is acting in. If either header is missing or empty, or if
    `X-User-Role` is not one of the four role names declared below, the request is
    refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 3.3: "A new cycle's `status` is `OPEN`, its `schedule_version` is 0, its
    `nominated_total_bbl`, `allocated_total_bbl`, `unallocated_capacity_bbl` and
    `total_transmix_bbl` are all 0, its `effective_capacity_bbl` and
    `derate_pct_applied` are 0, its `proration_factor`, `schedule_published_at`,
    `schedule_published_by_user_id` and `settled_at` are null, and its `version` is
    1."

    Design: Corner/rbac/nomination_create_without_a_role_header_rejected
    """
    ctx = setup_open_cycle(shippers=("ALPHA",))
    cycle = ctx["cycle"]

    # A payload that is entirely valid on every business gate; only the identity
    # headers are missing.
    payload = create_nomination_payload(
        cycle["id"],
        ctx["shippers"]["ALPHA"]["id"],
        ctx["grades"]["ULSD"]["id"],
        ctx["origin"]["id"],
        ctx["destination"]["id"],
        cycle["version"],
        nominated_bbl=30000,
    )
    response = api.create_nomination(payload, ANONYMOUS_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    unchanged = refresh_cycle(ctx)
    assert int(unchanged["version"]) == 1, (
        f"a refused submission must not advance the cycle's version, got {unchanged['version']}"
    )
    assert _money(unchanged["nominated_total_bbl"]) == 0, (
        f"nominated_total_bbl must stay 0, got {unchanged['nominated_total_bbl']}"
    )
    rows, meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no nomination may be written for the cycle, got {meta['total_count']}"
    )
    assert rows == [], f"expected no nomination rows, got {rows}"


def test_shipper_cannot_prorate_a_closed_cycle(api):
    """PRD 2.1: "Once the headers are accepted, the acting role must appear in the
    authorized-role list of the endpoint being called; a role that is not listed
    there is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "**`PipelineScheduler`** — the carrier's scheduling desk. It opens and
    closes cycles, prorates capacity, builds and publishes the batch sequence,
    reschedules injection windows, plans and progresses maintenance, sends
    nominations back for revision, settles cycles and certifies the resulting
    settlements."
    PRD 2.1: "**`Shipper`** — a common carrier customer that nominates volume into a
    cycle, revises that nomination when the carrier asks, withdraws it, and reads
    its own nominations, batch tickets and settlements alongside the public
    reference data (cycles, segments, product grades, tariffs and maintenance
    notices)."

    Design: Corner/rbac/shipper_cannot_prorate_a_cycle
    """
    # The cycle is CLOSED with ALPHA's nomination pinned and accepted, so proration
    # would succeed for the scheduling desk: only the acting role differs.
    ctx = setup_closed_cycle(nominated_bbl=30000)
    alpha = ctx["shippers"]["ALPHA"]

    response = api.prorate_cycle(ctx["cycle"]["id"], make_shipper_headers(alpha["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    after = refresh_cycle(ctx)
    assert after["status"] == "CLOSED", (
        f"the cycle must stay CLOSED after the refusal, got {after['status']}"
    )
    assert _money(after["allocated_total_bbl"]) == 0, (
        "no allocation may be computed for a shipper-driven proration attempt"
    )
    nomination = refresh_nomination(ctx, nomination_key("ALPHA"))
    assert nomination["status"] == "ACCEPTED", (
        f"the nomination must stay as the close left it, got {nomination['status']}"
    )
    assert _money(nomination["allocated_bbl"]) == 0, (
        f"allocated_bbl must stay 0, got {nomination['allocated_bbl']}"
    )


def test_shipper_cannot_read_another_shippers_nomination(api):
    """PRD 2.1: "Concretely, a `Shipper` may act on or read a nomination only when
    the nomination's `shipper_id` equals `X-User-ID`; may read a batch ticket only
    when the ticket's nomination belongs to that shipper; may read a settlement only
    when the settlement's `shipper_id` equals `X-User-ID`; and, when submitting a
    nomination, must supply a body `shipper_id` equal to `X-User-ID`."
    PRD 2.1: "Any of those mismatches is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP
    403)."

    Design: Corner/rbac/shipper_cannot_read_another_shippers_nomination
    """
    ctx = setup_cycle_with_nomination(nominated_bbl=30000, shippers=("ALPHA", "BRAVO"))
    alpha = ctx["shippers"]["ALPHA"]
    bravo = ctx["shippers"]["BRAVO"]
    nomination = ctx["nominations"][nomination_key("ALPHA")]

    # BRAVO holds the Shipper role and its id is a real Shipper row, yet the
    # nomination's shipper_id is ALPHA's.
    refused = api.get_nomination(nomination["id"], make_shipper_headers(bravo["id"]))
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    # The owning shipper reads the very same nomination.
    own_read = validate_success(
        api.get_nomination(nomination["id"], make_shipper_headers(alpha["id"]))
    )
    assert own_read["id"] == nomination["id"]
    assert own_read["shipper_id"] == alpha["id"], (
        f"the nomination must belong to ALPHA, got shipper_id {own_read['shipper_id']}"
    )
    assert _money(own_read["nominated_bbl"]) == 30000
    assert own_read["status"] == "SUBMITTED"


def test_terminal_operator_cannot_file_a_tariff(api):
    """PRD 2.1: "Once the headers are accepted, the acting role must appear in the
    authorized-role list of the endpoint being called; a role that is not listed
    there is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "**`TariffAdministrator`** — the commercial administrator. It maintains
    master data (terminals, product grades, segments, shippers, historical movement
    records), sets shipper credit, drafts and activates tariffs, changes a segment's
    proration methodology, and invoices certified settlements."
    PRD 2.1: "**`TerminalOperator`** — the terminal-side operator. It books physical
    inventory adjustments, funds linefill, and executes injections and deliveries
    with the measured quality and measured volumes taken at the manifold."

    Design: Corner/rbac/terminal_operator_cannot_file_a_tariff
    """
    ctx = setup_network(grades=("ULSD",))

    # A fully valid rate filing, offered by the terminal-side operator.
    payload = create_tariff_payload(ctx["segment"]["id"], ctx["grades"]["ULSD"]["id"])
    response = api.create_tariff(payload, OPERATOR)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    rows, meta = validate_paginated(api.list_tariffs(ADMIN, params={"limit": 100}))
    assert meta["total_count"] == 0, (
        f"no tariff row may be created by the refused filing, got {meta['total_count']}"
    )
    assert rows == [], f"expected an empty tariff catalogue, got {rows}"


def test_the_publishing_scheduler_cannot_certify_its_own_cycle_settlement(api):
    """PRD 2.10: "A settlement may be certified only by a `PipelineScheduler` whose
    `X-User-ID` differs from the `schedule_published_by_user_id` recorded on the
    settled cycle; a certification attempt by the very operator who published that
    cycle's schedule is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.9: "A `PipelineScheduler` certifies a settlement, driving it `DRAFT →
    CERTIFIED`; certification from any other status is refused with
    `ERR_SETTLEMENT_INVALID_STATE`, and certification by the very operator whose
    `X-User-ID` was recorded in the cycle's `schedule_published_by_user_id` is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.9: "A successful certification records the certifier's `X-User-ID` in
    `certified_by_user_id`."

    Design: Corner/rbac/the_publishing_scheduler_cannot_certify_its_own_cycle_settlement
    """
    # The cycle's schedule was published by one named scheduling operator, its batch
    # was injected on-spec and delivered, and the settle raised one DRAFT settlement.
    ctx = setup_draft_settlement(publisher_user_id=PUBLISHER_USER_ID)
    settlement = ctx["settlements"][0]
    assert ctx["cycle"]["schedule_published_by_user_id"] == PUBLISHER_USER_ID, (
        "the publishing operator must be recorded on the settled cycle, got "
        f"{ctx['cycle']['schedule_published_by_user_id']}"
    )

    # Both callers hold PipelineScheduler, so this is not a role check.
    refused = api.certify_settlement(settlement["id"], PUBLISHER)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_draft = validate_success(api.get_settlement(settlement["id"], SCHEDULER))
    assert still_draft["status"] == "DRAFT", (
        f"the refusal must leave the settlement DRAFT, got {still_draft['status']}"
    )
    assert still_draft["certified_by_user_id"] is None, (
        "certified_by_user_id must stay null after a refused certification, got "
        f"{still_draft['certified_by_user_id']}"
    )

    # A different scheduling operator certifies the very same settlement.
    certified = validate_success(api.certify_settlement(settlement["id"], CERTIFIER))
    assert certified["status"] == "CERTIFIED", (
        f"a second operator's certification must succeed, got {certified['status']}"
    )
    assert certified["certified_by_user_id"] == CERTIFIER_USER_ID, (
        f"the certifier must be recorded, got {certified['certified_by_user_id']}"
    )


def test_stale_expected_cycle_version_on_a_second_nomination_is_refused(api):
    """PRD 2.6: "`POST /pipeline/nominations` requires a non-optional body field
    `expected_cycle_version` carrying the `version` of the target `NominationCycle`
    as the client last observed it. If that value does not equal the cycle's current
    `version`, the submission is refused with `ERR_STALE_CYCLE_VERSION` and HTTP
    412."
    PRD 2.6: "A successful submission increments the cycle's `version` by one, so a
    client that submits twice must re-read the cycle between attempts."

    Design: Corner/cross_cutting_layers/stale_expected_cycle_version_on_second_nomination_rejected
    """
    ctx = setup_open_cycle(shippers=("ALPHA", "BRAVO"))
    cycle = ctx["cycle"]
    bravo = ctx["shippers"]["BRAVO"]

    # Both shippers read the cycle at the same instant and hold the same token.
    stale_token = cycle["version"]
    alpha_nomination = nominate(
        ctx, "ALPHA", nominated_bbl=30000, expected_cycle_version=stale_token
    )

    # ALPHA's accepted submission has already moved the cycle on by one version.
    response = api.create_nomination(
        create_nomination_payload(
            cycle["id"],
            bravo["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            stale_token,
            nominated_bbl=20000,
        ),
        make_shipper_headers(bravo["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_CYCLE_VERSION.value)

    after = refresh_cycle(ctx)
    assert int(after["version"]) == stale_token + 1, (
        f"only ALPHA's submission may advance the version, got {after['version']}"
    )
    assert _money(after["nominated_total_bbl"]) == 30000, (
        f"the refused submission must not be counted, got {after['nominated_total_bbl']}"
    )
    rows, meta = validate_paginated(
        api.list_nominations(SCHEDULER, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"only ALPHA's nomination may be on file, got {meta['total_count']}"
    )
    assert rows[0]["id"] == alpha_nomination["id"]
    assert rows[0]["status"] == "SUBMITTED"


def test_refreshed_expected_cycle_version_lets_the_second_nomination_through(api):
    """PRD 2.6: "A successful submission increments the cycle's `version` by one, so a
    client that submits twice must re-read the cycle between attempts."
    PRD 3.3: "Every accepted submission has two consequences on the parent cycle. The
    cycle's `version` increments by one — which is exactly why the next submission
    must re-read it — and the cycle's `nominated_total_bbl`, `allocated_total_bbl`
    and `unallocated_capacity_bbl` are recomputed."
    PRD 3.3: "The new nomination itself starts with `status` of `SUBMITTED`,
    `revision_count` of 0, `allocated_bbl` of 0, `history_base_bbl` of 0,
    `allocation_class` of `NEW_SHIPPER`, `pinned_tariff_id` of null and
    `rejection_reason` of null."
    PRD 3.4: "`nominated_total_bbl` is the sum of `nominated_bbl` over the cycle's
    nominations whose `status` is one of `SUBMITTED`, `ACCEPTED`, `PRORATED`,
    `REVISION_REQUESTED`, `SCHEDULED` or `COMPLETED`"

    Design: Corner/cross_cutting_layers/refreshed_expected_cycle_version_lets_the_second_nomination_through
    """
    ctx = setup_open_cycle(shippers=("ALPHA", "BRAVO"))
    cycle = ctx["cycle"]
    bravo = ctx["shippers"]["BRAVO"]

    opening_version = cycle["version"]
    nominate(ctx, "ALPHA", nominated_bbl=30000, expected_cycle_version=opening_version)

    # BRAVO re-reads the cycle before quoting a token.
    refreshed = refresh_cycle(ctx)
    assert int(refreshed["version"]) == opening_version + 1, (
        f"the refreshed read must show one accepted write, got {refreshed['version']}"
    )

    bravo_nomination = validate_success(
        api.create_nomination(
            create_nomination_payload(
                cycle["id"],
                bravo["id"],
                ctx["grades"]["ULSD"]["id"],
                ctx["origin"]["id"],
                ctx["destination"]["id"],
                refreshed["version"],
                nominated_bbl=20000,
            ),
            make_shipper_headers(bravo["id"]),
        ),
        201,
    )
    assert bravo_nomination["status"] == "SUBMITTED", (
        f"a new nomination starts SUBMITTED, got {bravo_nomination['status']}"
    )
    assert _money(bravo_nomination["allocated_bbl"]) == 0, (
        f"a new nomination starts with allocated_bbl of 0, got {bravo_nomination['allocated_bbl']}"
    )

    after = refresh_cycle(ctx)
    assert int(after["version"]) == opening_version + 2, (
        f"the counter tracks accepted writes only, got {after['version']}"
    )
    assert _money(after["nominated_total_bbl"]) == 50000, (
        f"both SUBMITTED nominations must be counted, got {after['nominated_total_bbl']}"
    )
    assert after["status"] == "OPEN", f"the cycle stays OPEN, got {after['status']}"
    assert _money(after["allocated_total_bbl"]) == 0, (
        f"nothing is allocated before proration, got {after['allocated_total_bbl']}"
    )


def test_stale_expected_terminal_version_on_a_second_adjustment_is_refused(api):
    """PRD 2.6: "`POST /pipeline/terminals/{id}/inventory-adjustments` requires a
    non-optional body field `expected_terminal_version` carrying the `version` of the
    target `Terminal` as the client last observed it. If that value does not equal
    the terminal's current `version`, the adjustment is refused with
    `ERR_STALE_TERMINAL_VERSION` and HTTP 412."
    PRD 2.6: "A successful adjustment increments the terminal's `version` by one."
    PRD 3.1: "An `adjustment_kind` of `LINEFILL` behaves differently: it requires an
    accompanying `segment_id`, it adds `adjustment_bbl` to that segment's
    `linefill_bbl`, and it leaves the terminal's `inventory_bbl` untouched."
    PRD 3.1: "A newly registered terminal starts with `inventory_bbl` of 0 and
    `version` of 1."

    Design: Corner/cross_cutting_layers/stale_expected_terminal_version_on_second_adjustment_rejected
    """
    ctx = setup_network(grades=("ULSD",), linefill_bbl=0)
    origin_token = ctx["origin"]["version"]

    # Funding the segment's linefill moves the origin terminal on by one version.
    fund_linefill(ctx, 20000, reason="initial linefill of the mainline")
    assert int(ctx["origin"]["version"]) == origin_token + 1, (
        f"the linefill adjustment must bump the terminal, got {ctx['origin']['version']}"
    )

    # The operator replays the token it read before that adjustment.
    response = api.create_inventory_adjustment(
        ctx["origin"]["id"],
        create_inventory_adjustment_payload(
            origin_token,
            adjustment_kind="INVENTORY",
            adjustment_bbl=100000,
            reason="refinery receipt replayed on a stale token",
            segment_id=ctx["segment"]["id"],
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_TERMINAL_VERSION.value)

    terminal = validate_success(api.get_terminal(ctx["origin"]["id"], SCHEDULER))
    assert _money(terminal["inventory_bbl"]) == 0, (
        f"the refused receipt must not reach the tank, got {terminal['inventory_bbl']}"
    )
    assert int(terminal["version"]) == origin_token + 1, (
        f"the refusal must not bump the terminal, got {terminal['version']}"
    )
    segment = validate_success(api.get_segment(ctx["segment"]["id"], SCHEDULER))
    assert _money(segment["linefill_bbl"]) == 20000, (
        f"the segment keeps the linefill it was funded, got {segment['linefill_bbl']}"
    )


def test_imbalance_tier_boundary_between_standard_and_penalty(api):
    """PRD 3.9: "The cycle's system loss is the total injected less the total
    delivered, rounded half up to two decimal places"
    PRD 3.9: "Otherwise each billed shipper, taken in ascending order of the
    shipper's `created_at`, receives a share equal to the system loss multiplied by
    that shipper's own delivered volume divided by the cycle's total delivered
    volume, rounded half up to two decimal places."
    PRD 3.9: "For a given ticket, the billable volume under the `DELIVERED` basis is
    the larger of the ticket's `delivered_bbl` — treated as zero when it is null —
    and the pinned tariff's `tender_minimum_bbl`; under the `SCHEDULED` basis it is
    the larger of the ticket's `volume_bbl` and that same `tender_minimum_bbl`."
    PRD 3.9: "The rate that applies to that billable volume is the pinned tariff's
    `tier2_rate_usd_per_bbl` when the billable volume is at or above `tier2_min_bbl`,
    otherwise its `tier1_rate_usd_per_bbl` when the billable volume is at or above
    `tier1_min_bbl`, and otherwise its `base_rate_usd_per_bbl`."
    PRD 3.9: "The charge on the `basis_mode` the scheduler chose is written to
    `tariff_charge_usd`; the charge on the other basis is written to
    `alt_basis_charge_usd` as an explicit counterfactual; and `basis_delta_usd` is
    `alt_basis_charge_usd` less `tariff_charge_usd`, rounded half up to two decimal
    places."
    PRD 3.9: "Step one: the settlement's `scheduled_bbl` is the sum of `volume_bbl`
    over the shipper's tickets in the cycle whose `movement_status` is `PLANNED`,
    `INJECTED` or `DELIVERED`."
    PRD 3.9: "Step two: its `delivered_bbl` is the sum of `delivered_bbl` over the
    shipper's tickets whose `movement_status` is `DELIVERED`."
    PRD 3.9: "Step four: `imbalance_bbl` is the `delivered_bbl` less the
    `scheduled_bbl` plus the `loss_allocation_bbl`, rounded half up to two decimal
    places — note that it may legitimately be negative."
    PRD 3.9: "Step five: `imbalance_pct` is 0 when `scheduled_bbl` is zero, and
    otherwise the absolute value of `imbalance_bbl` divided by `scheduled_bbl`,
    rounded half up to six decimal places."
    PRD 3.9: "Step six sets `imbalance_tier` and its multiplier from that percentage:
    an `imbalance_pct` at or below 0.005 — half of one percent — is `TOLERANCE` and
    carries a multiplier of 0; an `imbalance_pct` above that but at or below 0.02 —
    two percent — is `STANDARD` and carries a multiplier of 1.0; anything larger is
    `PENALTY` and carries a multiplier of 2.5."
    PRD 3.9: "Step seven computes `imbalance_charge_usd` as the absolute value of
    `imbalance_bbl` multiplied by the applicable `imbalance_penalty_rate_usd_per_bbl`
    and then by the tier multiplier, rounded half up to two decimal places"
    PRD 3.9: "Step eight computes `total_billed_usd` as `tariff_charge_usd` plus
    `imbalance_charge_usd`, rounded half up to two decimal places."

    Design: Corner/cross_cutting_layers/imbalance_tier_boundary_standard_versus_penalty
    """
    # Cycle one: a 30000 bbl schedule delivered 600 bbl short, which is an imbalance
    # of exactly two percent and therefore sits on the STANDARD side of the boundary.
    ctx = setup_delivered_cycle(nominated_bbl=30000, injected_bbl=29400, delivered_bbl=29400)
    settle_cycle(ctx, "DELIVERED")
    boundary = validate_success(api.get_settlement(ctx["settlements"][0]["id"], SCHEDULER))

    assert _money(boundary["scheduled_bbl"]) == pytest.approx(30000, abs=0.005), (
        f"the single ticket was planned at 30000 bbl, got {boundary['scheduled_bbl']}"
    )
    assert _money(boundary["delivered_bbl"]) == pytest.approx(29400, abs=0.005), (
        f"the ticket delivered 29400 bbl, got {boundary['delivered_bbl']}"
    )
    assert _money(boundary["loss_allocation_bbl"]) == pytest.approx(0, abs=0.005), (
        "injected equals delivered so the cycle books no system loss, got "
        f"{boundary['loss_allocation_bbl']}"
    )
    assert _money(boundary["imbalance_bbl"]) == pytest.approx(-600, abs=0.005), (
        f"29400 delivered less 30000 scheduled is -600.00, got {boundary['imbalance_bbl']}"
    )
    assert _money(boundary["imbalance_pct"]) == pytest.approx(0.020000, abs=1e-6), (
        f"600 over 30000 is exactly 0.020000, got {boundary['imbalance_pct']}"
    )
    assert boundary["imbalance_tier"] == "STANDARD", (
        f"an imbalance at 0.02 is still STANDARD, got {boundary['imbalance_tier']}"
    )
    assert _money(boundary["imbalance_charge_usd"]) == pytest.approx(270.00, abs=0.005), (
        "600 bbl at 0.45 with the STANDARD multiplier of 1.0 is 270.00, got "
        f"{boundary['imbalance_charge_usd']}"
    )
    assert _money(boundary["tariff_charge_usd"]) == pytest.approx(50127.00, abs=0.005), (
        f"29400 bbl at the tier-one rate of 1.705 is 50127.00, got "
        f"{boundary['tariff_charge_usd']}"
    )
    assert _money(boundary["alt_basis_charge_usd"]) == pytest.approx(51150.00, abs=0.005), (
        "the SCHEDULED counterfactual bills 30000 bbl at 1.705, or 51150.00, got "
        f"{boundary['alt_basis_charge_usd']}"
    )
    assert _money(boundary["basis_delta_usd"]) == pytest.approx(1023.00, abs=0.005), (
        f"51150.00 less 50127.00 is 1023.00, got {boundary['basis_delta_usd']}"
    )
    assert _money(boundary["total_billed_usd"]) == pytest.approx(50397.00, abs=0.005), (
        f"50127.00 plus 270.00 is 50397.00, got {boundary['total_billed_usd']}"
    )

    # Cycle two on the same segment: the very same schedule, delivered ten barrels
    # further short. That single barrel-step crosses the two-percent line.
    open_cycle(
        ctx,
        cycle_code="2026-10",
        ship_start_at="2026-10-01T00:00:00Z",
        ship_end_at="2026-10-31T00:00:00Z",
    )
    nominate(ctx, "ALPHA", nominated_bbl=30000, key="ALPHA:ULSD:2026-10")
    close_cycle(ctx)
    prorate_cycle(ctx)
    build_schedule(ctx)
    publish_schedule(ctx)
    second_ticket = ctx["tickets"][0]
    inject_ticket(ctx, second_ticket["id"], 29390)
    deliver_ticket(ctx, second_ticket["id"], 29390)
    settle_cycle(ctx, "DELIVERED")
    over_the_line = validate_success(api.get_settlement(ctx["settlements"][0]["id"], SCHEDULER))

    assert _money(over_the_line["scheduled_bbl"]) == pytest.approx(30000, abs=0.005), (
        f"the second cycle plans the same 30000 bbl, got {over_the_line['scheduled_bbl']}"
    )
    assert _money(over_the_line["delivered_bbl"]) == pytest.approx(29390, abs=0.005), (
        f"the second ticket delivered 29390 bbl, got {over_the_line['delivered_bbl']}"
    )
    assert _money(over_the_line["loss_allocation_bbl"]) == pytest.approx(0, abs=0.005), (
        f"again no system loss to share, got {over_the_line['loss_allocation_bbl']}"
    )
    assert _money(over_the_line["imbalance_bbl"]) == pytest.approx(-610, abs=0.005), (
        f"29390 delivered less 30000 scheduled is -610.00, got {over_the_line['imbalance_bbl']}"
    )
    assert _money(over_the_line["imbalance_pct"]) == pytest.approx(0.020333, abs=1e-6), (
        f"610 over 30000 rounds to 0.020333, got {over_the_line['imbalance_pct']}"
    )
    assert over_the_line["imbalance_tier"] == "PENALTY", (
        "anything above 0.02 is PENALTY, got "
        f"{over_the_line['imbalance_tier']} at {over_the_line['imbalance_pct']}"
    )
    assert _money(over_the_line["imbalance_charge_usd"]) == pytest.approx(686.25, abs=0.005), (
        "610 bbl at 0.45 with the PENALTY multiplier of 2.5 is 686.25, got "
        f"{over_the_line['imbalance_charge_usd']}"
    )
    assert _money(over_the_line["tariff_charge_usd"]) == pytest.approx(50109.95, abs=0.005), (
        f"29390 bbl at 1.705 is 50109.95, got {over_the_line['tariff_charge_usd']}"
    )
    assert _money(over_the_line["alt_basis_charge_usd"]) == pytest.approx(51150.00, abs=0.005), (
        "the SCHEDULED counterfactual is unchanged at 51150.00, got "
        f"{over_the_line['alt_basis_charge_usd']}"
    )
    assert _money(over_the_line["basis_delta_usd"]) == pytest.approx(1040.05, abs=0.005), (
        f"51150.00 less 50109.95 is 1040.05, got {over_the_line['basis_delta_usd']}"
    )
    assert _money(over_the_line["total_billed_usd"]) == pytest.approx(50796.20, abs=0.005), (
        f"50109.95 plus 686.25 is 50796.20, got {over_the_line['total_billed_usd']}"
    )

    # Ten barrels of extra shrinkage cost 416.25 dollars: that is the boundary.
    assert _money(over_the_line["imbalance_charge_usd"]) > _money(
        boundary["imbalance_charge_usd"]
    ), "crossing the tier boundary must raise the penalty, not lower it"
