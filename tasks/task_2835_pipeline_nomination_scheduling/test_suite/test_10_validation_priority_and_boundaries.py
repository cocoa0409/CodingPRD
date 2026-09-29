"""Which rule wins when a single call breaks two, and what happens one barrel
either side of an inclusive threshold.

A request that violates both a state rule and a volume rule must report the state
rule; a request that violates both a safety rule and a fiscal rule must report the
safety rule. The boundary cases pin the comparison operators themselves.
"""

from test_helpers import (
    OPERATOR,
    SCHEDULER,
    api_client,
    assert_capacity_conservation,
    close_cycle,
    create_nomination_payload,
    inject_payload,
    make_shipper_headers,
    prorate_cycle,
    refresh_cycle,
    refresh_origin,
    refresh_segment,
    refresh_shipper,
    refresh_tickets,
    set_clock,
    setup_multi_shipper_cycle,
    setup_open_cycle,
    ticket_at,
    validate_error,
    validate_success,
)


def _barrels(value) -> int:
    return int(round(float(value)))


def _volume(value) -> float:
    return round(float(value), 2)


def _money(value) -> float:
    return round(float(value), 2)


def _ratio(value) -> float:
    return round(float(value), 6)


def _submit(ctx, shipper_code, nominated_bbl, expected_cycle_version=None, **overrides):
    """Submit a nomination without asserting anything about the outcome."""
    shipper = ctx["shippers"][shipper_code]
    version = (
        ctx["cycle"]["version"]
        if expected_cycle_version is None
        else expected_cycle_version
    )
    return api_client.create_nomination(
        create_nomination_payload(
            ctx["cycle"]["id"],
            shipper["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            version,
            nominated_bbl=nominated_bbl,
            **overrides,
        ),
        make_shipper_headers(shipper["id"]),
    )


def _closed_empty_cycle():
    """A cycle closed over an empty nomination set, with the clock left inside the
    nomination window so the temporal test cannot fire."""
    ctx = setup_open_cycle(shippers=("ALPHA",))
    close_cycle(ctx)
    set_clock("2026-08-05T00:00:00Z", SCHEDULER)
    refresh_cycle(ctx)
    return ctx


def test_a_closed_cycle_outranks_the_tender_minimum_on_a_short_nomination(api):
    """A 5000 bbl nomination into a CLOSED cycle breaks two rules at once — the
    cycle is not open and the volume is under the 6000 bbl minimum — and the cycle
    check is the one reported, so the answer is 409 and never the 422.

    PRD 3.3: "Five business gates then apply in the order of §2.5: the target cycle
    must be `OPEN`, or the request is refused with `ERR_CYCLE_NOT_OPEN`; the logical
    clock must be at or after `window_open_at` and strictly before `window_close_at`,
    or `ERR_NOMINATION_WINDOW_CLOSED`; the nominating shipper's `status` must be
    `ACTIVE`, or `ERR_SHIPPER_NOT_ACTIVE`; the supplied `origin_terminal_id` must
    equal the cycle's segment's `origin_terminal_id` and the supplied
    `destination_terminal_id` must equal that segment's `destination_terminal_id`, or
    `ERR_ROUTE_NOT_SERVED`; and `nominated_bbl` must be at least the segment's
    `min_tender_bbl`, or `ERR_TENDER_MINIMUM_NOT_MET`."

    PRD 2.5: "The ladder below is exhaustive and is evaluated from top to bottom; the
    first rank whose condition fails determines both the `error_id` and the HTTP
    status, and no later rank is consulted."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_tender_minimum_on_nomination
    """
    ctx = _closed_empty_cycle()

    response = _submit(ctx, "ALPHA", 5000)

    validate_error(response, "ERR_CYCLE_NOT_OPEN", expected_status=409)
    body = response.json()
    assert body["data"]["error_id"] != "ERR_TENDER_MINIMUM_NOT_MET"
    assert response.status_code != 422


def test_the_refused_short_nomination_writes_nothing_at_all(api):
    """The refusal is total: no nomination row is created, the cycle stays CLOSED
    with a nominated total of zero, and its version is not bumped — a rejected write
    is not a write.

    PRD 3.3: "Every accepted submission has two consequences on the parent cycle. The
    cycle's `version` increments by one — which is exactly why the next submission
    must re-read it — and the cycle's `nominated_total_bbl`, `allocated_total_bbl` and
    `unallocated_capacity_bbl` are recomputed."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_tender_minimum_on_nomination
    """
    ctx = _closed_empty_cycle()
    version_before = int(ctx["cycle"]["version"])

    validate_error(_submit(ctx, "ALPHA", 5000), "ERR_CYCLE_NOT_OPEN", expected_status=409)

    listing = api_client.list_nominations(SCHEDULER, params={"cycle_id": ctx["cycle"]["id"]})
    assert int(listing.json()["meta"]["total_count"]) == 0

    cycle = refresh_cycle(ctx)
    assert cycle["status"] == "CLOSED"
    assert _barrels(cycle["nominated_total_bbl"]) == 0
    assert int(cycle["version"]) == version_before


def _published_pair_on_a_tight_credit_line():
    """ALPHA's credit line is 100000 USD against two batch lines worth 55650.00 and
    48415.50 USD, so the second batch cannot be afforded once the first is in."""
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000), ("ALPHA", "CBOB", 26100)],
        grades=("ULSD", "CBOB"),
        origin_stock_bbl=100000,
        publish=True,
        shipper_overrides={"credit_limit_usd": 100000},
    )
    set_clock("2026-09-01T00:00:00Z", SCHEDULER)
    diesel_batch = ticket_at(ctx, 1)
    validate_success(
        api_client.inject_batch(diesel_batch["id"], inject_payload(30000, 9, 10), OPERATOR)
    )
    refresh_tickets(ctx)
    return ctx


def test_off_spec_product_is_reported_ahead_of_the_credit_limit(api):
    """The CBOB batch is both off specification at 120 ppm against an 80 ppm ceiling
    and beyond ALPHA's remaining credit, and the carrier answers on quality: 422
    rather than the 402 the fiscal gate would have produced.

    PRD 3.7: "The final gate is credit, and it runs last of all, after quality and
    after inventory."

    PRD 2.5: "Product quality is deliberately enforced ahead of every commercial
    check."

    Design: Difficulty/priority_pair_validation_conflict/quality_safety_beats_credit_limit_on_injection
    """
    ctx = _published_pair_on_a_tight_credit_line()
    gasoline_batch = ticket_at(ctx, 2)

    response = api_client.inject_batch(
        gasoline_batch["id"], inject_payload(26100, 120, 14), OPERATOR
    )

    validate_error(response, "ERR_QUALITY_SPEC_VIOLATION", expected_status=422)
    body = response.json()
    assert body["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"
    assert response.status_code != 402


def test_the_quality_refusal_still_writes_while_the_credit_line_is_never_booked(api):
    """The rejection is a physical event and it persists — quality REJECTED, both
    measurements stored, the retest counter at 1 — yet no volume and no money move:
    exposure stays at the 55650.00 USD of the first batch and the interface cut the
    refused batch would have taken is not debited.

    PRD 3.7: "If either ceiling is exceeded, the carrier exercises its rejection
    right at the injection point: the response is `ERR_QUALITY_SPEC_VIOLATION` with
    HTTP 422, and yet the state writes persist, because the product was physically
    presented and physically refused."

    Design: Difficulty/priority_pair_validation_conflict/quality_safety_beats_credit_limit_on_injection
    """
    ctx = _published_pair_on_a_tight_credit_line()
    gasoline_batch = ticket_at(ctx, 2)

    validate_error(
        api_client.inject_batch(gasoline_batch["id"], inject_payload(26100, 120, 14), OPERATOR),
        "ERR_QUALITY_SPEC_VIOLATION",
        expected_status=422,
    )

    refresh_tickets(ctx)
    refused = ticket_at(ctx, 2)
    assert refused["quality_status"] == "REJECTED"
    assert int(refused["retest_count"]) == 1
    assert refused["movement_status"] == "PLANNED"
    assert _volume(refused["measured_sulfur_ppm"]) == 120
    assert _volume(refused["measured_rvp_psi"]) == 14

    assert _money(refresh_shipper(ctx, "ALPHA")["exposure_usd"]) == 55650.00
    assert _volume(refresh_origin(ctx)["inventory_bbl"]) == 70000.00
    segment = refresh_segment(ctx)
    assert _volume(segment["in_transit_bbl"]) == 30000.00
    assert _volume(segment["transmix_inventory_bbl"]) == 0.00


def _open_cycle_for_two_shippers():
    """An OPEN cycle whose segment batches nothing under 6000 bbl, with the clock
    inside the nomination window and capacity far above either test volume."""
    ctx = setup_open_cycle(shippers=("ALPHA", "BRAVO"))
    set_clock("2026-08-05T00:00:00Z", SCHEDULER)
    refresh_cycle(ctx)
    return ctx


def test_a_nomination_at_exactly_the_tender_minimum_is_accepted(api):
    """6000 bbl is the segment's minimum tender, and a nomination of exactly that
    size is accepted, which is what makes the comparison inclusive rather than strict.

    PRD 3.3: "and `nominated_bbl` must be at least the segment's `min_tender_bbl`, or
    `ERR_TENDER_MINIMUM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/tender_minimum_exact_boundary_accepted_and_one_below_rejected
    """
    ctx = _open_cycle_for_two_shippers()

    nomination = validate_success(_submit(ctx, "ALPHA", 6000), expected_status=201)

    assert _barrels(nomination["nominated_bbl"]) == 6000
    assert nomination["status"] == "SUBMITTED"
    assert _barrels(refresh_cycle(ctx)["nominated_total_bbl"]) == 6000


def test_one_barrel_below_the_tender_minimum_is_refused(api):
    """5999 bbl — a single barrel short of the same threshold — is refused, and the
    refusal contributes nothing to the cycle: the listing still holds one row, the
    nominated total is still the accepted 6000 bbl and the version has not moved.

    PRD 2.5: "**Tender minimum.** The nominated volume clears the applicable tender
    minimum — otherwise `ERR_TENDER_MINIMUM_NOT_MET` (422)."

    Design: Difficulty/boundary_precision_check/tender_minimum_exact_boundary_accepted_and_one_below_rejected
    """
    ctx = _open_cycle_for_two_shippers()
    validate_success(_submit(ctx, "ALPHA", 6000), expected_status=201)
    cycle = refresh_cycle(ctx)
    version_after_accept = int(cycle["version"])

    validate_error(
        _submit(ctx, "BRAVO", 5999, expected_cycle_version=version_after_accept),
        "ERR_TENDER_MINIMUM_NOT_MET",
        expected_status=422,
    )

    listing = api_client.list_nominations(SCHEDULER, params={"cycle_id": ctx["cycle"]["id"]})
    assert int(listing.json()["meta"]["total_count"]) == 1
    cycle = refresh_cycle(ctx)
    assert _barrels(cycle["nominated_total_bbl"]) == 6000
    assert int(cycle["version"]) == version_after_accept


def _empty_cycle_past_its_window():
    """A cycle with no nominations at all and no tariff on file, sized at 100000 bbl,
    read after the nomination window has closed."""
    ctx = setup_open_cycle(shippers=(), tariff_grades=())
    set_clock("2026-08-21T00:00:00Z", SCHEDULER)
    refresh_cycle(ctx)
    return ctx


def test_prorating_an_empty_nomination_set_yields_the_unit_factor(api):
    """With nothing to divide, the proration factor is the pinned literal 1.000000
    rather than a division by zero, and both the nominated and the allocated totals
    stay at zero.

    PRD 3.5: "If the input set is empty, every allocation is 0, the cycle's
    `proration_factor` becomes exactly 1.000000, `unallocated_capacity_bbl` becomes
    the whole of `effective_capacity_bbl`, and the run stops there."

    Design: Difficulty/boundary_precision_check/empty_nomination_set_prorate_yields_unit_factor
    """
    ctx = _empty_cycle_past_its_window()

    validate_success(api_client.close_cycle(ctx["cycle"]["id"], SCHEDULER))
    validate_success(api_client.prorate_cycle(ctx["cycle"]["id"], SCHEDULER))

    cycle = refresh_cycle(ctx)
    assert cycle["status"] == "PRORATED"
    assert _ratio(cycle["proration_factor"]) == 1.000000
    assert _barrels(cycle["nominated_total_bbl"]) == 0
    assert _barrels(cycle["allocated_total_bbl"]) == 0


def test_the_whole_undivided_capacity_lands_in_unallocated_capacity(api):
    """The 100000 bbl the line could have awarded is not lost — it is all reported as
    unallocated, the capacity identity holds on a degenerate cycle just as it does on
    a contested one, and the snapshotted derate is zero because nothing is derated.

    PRD 3.4: "The outcome is written to the cycle's `effective_capacity_bbl`, and the
    value of `derate_pct` used is snapshotted into the cycle's `derate_pct_applied`."

    Design: Difficulty/boundary_precision_check/empty_nomination_set_prorate_yields_unit_factor
    """
    ctx = _empty_cycle_past_its_window()
    close_cycle(ctx)
    prorate_cycle(ctx)

    cycle = refresh_cycle(ctx)
    assert _barrels(cycle["effective_capacity_bbl"]) == 100000
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 100000
    assert round(float(cycle["derate_pct_applied"]), 2) == 0
    assert_capacity_conservation(cycle)
