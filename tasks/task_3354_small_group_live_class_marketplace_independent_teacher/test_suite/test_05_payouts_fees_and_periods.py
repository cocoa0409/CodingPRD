"""Payout accrual, banded fees, per-section flooring, periods and version guards."""
from test_helpers import (
    ApiErrorId,
    cancel_section,
    confirm_seat,
    create_learner,
    create_section,
    declare_minimum_met,
    get_enrollment,
    get_payout,
    get_teacher,
    get_teacher_version,
    get_success_data,
    list_payouts_for_teacher,
    make_platform_admin_headers,
    make_teacher_headers,
    onboard_active_teacher,
    request_payout,
    reserve_seat,
    run_ops,
    set_clock,
    setup_listing,
    setup_tax_document_gate_scenario,
    subscribe_learner,
    transition_payout,
    validate_error,
    validate_error_is_one_of,
)


def _run_one_time_section(listing, teacher, start_utc, end_utc):
    """Create → open → return the section; the caller fills and completes it."""
    return create_section(listing, teacher, start_utc=start_utc, end_utc=end_utc, min_learners=1, capacity=6)


def test_second_payout_accrues_earned_revenue_not_disbursed_net(api):
    """PRD §3.8: "Gross earnings are computed from accrual, not from disbursement.
    `gross_earnings_cents` is the sum, over every section owned by this teacher through
    its parent listing whose `outcome` is either null or `HELD` and whose `start_utc` is
    at or after `period_start` and strictly before `period_end`, of that section's
    confirmed discounted total — the sum of `discounted_price_cents` over the section's
    `CONFIRMED` enrollments."
    PRD §3.8: "The rejected alternative reading — computing gross as the sum of
    `net_payout_cents` over payouts already in `PAID` status, that is, what has already
    been disbursed rather than what has been earned — is never applied by the server."

    Design: Difficulty/dual_variant_calc/payout_gross_accrual_vs_posted_on_teacherpayout
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Algebra Club", list_price_cents=2000)
    learner = create_learner()

    # --- September: one section that runs and settles -----------------------
    september = _run_one_time_section(listing, teacher, "2026-09-10T14:00:00Z", "2026-09-10T16:00:00Z")
    september_enrollment = reserve_seat(listing, september, learner)
    assert september_enrollment["discounted_price_cents"] == 2000
    subscribe_learner(learner["id"], "PLUS")
    confirm_seat(september_enrollment["id"])
    declare_minimum_met(listing["id"], september["id"], teacher["id"])
    set_clock("2026-09-10T15:00:00Z")
    run_ops()

    september_payout = request_payout(teacher, "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")
    assert september_payout["gross_earnings_cents"] == 2000
    assert september_payout["platform_fee_cents"] == 500
    assert september_payout["net_payout_cents"] == 1500
    transition_payout(september_payout["id"], "SEND")
    paid = transition_payout(september_payout["id"], "PAY")
    assert paid["status"] == "PAID"

    # --- October: a second section in its own period ------------------------
    october = _run_one_time_section(listing, teacher, "2026-10-10T14:00:00Z", "2026-10-10T16:00:00Z")
    # A second learner: the September learner is already on PLUS, and its plan discount
    # would price this seat below the listing price the instance asserts.
    october_learner = create_learner()
    october_enrollment = reserve_seat(listing, october, october_learner)
    assert october_enrollment["discounted_price_cents"] == 2000
    subscribe_learner(october_learner["id"], "PLUS")
    confirm_seat(october_enrollment["id"])
    declare_minimum_met(listing["id"], october["id"], teacher["id"])
    set_clock("2026-10-10T15:00:00Z")
    run_ops()

    october_payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert october_payout["gross_earnings_cents"] == 2000, (
        "the accrual selector reports the earned 2000; the rejected posted selector "
        "would have reported the 1500 already disbursed on the first payout"
    )
    assert october_payout["platform_fee_cents"] == 500
    assert october_payout["net_payout_cents"] == 1500


def test_payouts_of_two_periods_report_the_same_accrued_gross(api):
    """PRD §3.8: "A section that has not started yet still accrues its confirmed revenue,
    and a section cancelled before it starts drops out of the sum entirely because its
    `outcome` is no longer null or `HELD`; this is precisely why a teacher-fault refund
    moves a payout."

    Design: Difficulty/dual_variant_calc/payout_gross_accrual_vs_posted_on_teacherpayout
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Algebra Club", list_price_cents=2000)

    payouts = []
    for start, period in (
        ("2026-09-10T14:00:00Z", ("2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")),
        ("2026-10-10T14:00:00Z", ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")),
    ):
        section = _run_one_time_section(listing, teacher, start, start.replace("T14:00:00Z", "T16:00:00Z"))
        # A fresh learner per section: a learner already on PLUS would discount the next
        # seat, so each period would no longer accrue its section's full list price.
        learner = create_learner()
        enrollment = reserve_seat(listing, section, learner)
        subscribe_learner(learner["id"], "PLUS")
        confirm_seat(enrollment["id"])
        declare_minimum_met(listing["id"], section["id"], teacher["id"])
        set_clock(start.replace("T14:00:00Z", "T15:00:00Z"))
        run_ops()
        payouts.append(request_payout(teacher, *period))

    first, second = payouts
    assert first["gross_earnings_cents"] == second["gross_earnings_cents"] == 2000, (
        "each period accrues its own section's revenue; neither is derived from the other's net"
    )
    assert second["gross_earnings_cents"] != first["net_payout_cents"], (
        "the posted selector would have made the second payout mirror the first payout's net"
    )
    assert (first["platform_fee_cents"], first["net_payout_cents"]) == (500, 1500)
    assert (second["platform_fee_cents"], second["net_payout_cents"]) == (500, 1500)


def test_platform_fee_is_floored_per_section_before_summing(api):
    """PRD §3.8: "The fee itself is floored per section and only then summed.
    `platform_fee_cents` is the sum, over the same accrual set of sections used for gross,
    of each section's confirmed discounted total multiplied by `fee_rate_applied` and
    floored to a whole cent. Summing the section totals first and flooring once at the end
    is the rejected alternative; it produces a larger fee whenever any per-section product
    is fractional, so the order is part of the contract."

    Design: Difficulty/combinatorial_formula/fee_rounding_per_section_vs_sum_on_payout
    """
    teacher = onboard_active_teacher()
    listings = [setup_listing(teacher, title=f"Cheap Class {i}", list_price_cents=1999) for i in (1, 2)]

    sections = []
    for listing, start in zip(listings, ("2026-10-10T14:00:00Z", "2026-10-11T14:00:00Z")):
        section = create_section(
            listing, teacher, start_utc=start, end_utc=start.replace("T14:00:00Z", "T16:00:00Z"),
            min_learners=1, capacity=6,
        )
        # A fresh learner per listing: a learner already on FAMILY would discount the
        # second seat, so the two sections would not both accrue 1999.
        learner = create_learner()
        enrollment = reserve_seat(listing, section, learner)
        assert enrollment["discounted_price_cents"] == 1999
        subscribe_learner(learner["id"], "FAMILY")
        confirm_seat(enrollment["id"])
        declare_minimum_met(listing["id"], section["id"], teacher["id"])
        sections.append(section)

    set_clock("2026-10-20T15:00:00Z")
    run_ops()

    payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert payout["gross_earnings_cents"] == 3998
    assert payout["fee_rate_applied"] == 0.25
    assert payout["platform_fee_cents"] == 998, (
        "floor(1999 * 0.25) twice is 998; flooring the 3998 total once would have given 999"
    )
    assert payout["net_payout_cents"] == 3000


def test_per_section_flooring_keeps_one_cent_the_sum_then_floor_order_would_lose(api):
    """PRD §3.8: "`platform_fee_cents` is the sum, over the same accrual set of sections
    used for gross, of each section's confirmed discounted total multiplied by
    `fee_rate_applied` and floored to a whole cent."
    PRD §2.9: "where a calculation aggregates per-section amounts, each section's amount is
    floored before the amounts are summed."

    Design: Difficulty/combinatorial_formula/fee_rounding_per_section_vs_sum_on_payout
    """
    teacher = onboard_active_teacher()
    listings = [setup_listing(teacher, title=f"Cheap Class {i}", list_price_cents=1999) for i in (1, 2)]

    for listing, start in zip(listings, ("2026-10-10T14:00:00Z", "2026-10-11T14:00:00Z")):
        section = create_section(
            listing, teacher, start_utc=start, end_utc=start.replace("T14:00:00Z", "T16:00:00Z"),
            min_learners=1, capacity=6,
        )
        learner = create_learner()
        enrollment = reserve_seat(listing, section, learner)
        subscribe_learner(learner["id"], "FAMILY")
        confirm_seat(enrollment["id"])
        declare_minimum_met(listing["id"], section["id"], teacher["id"])

    set_clock("2026-10-20T15:00:00Z")
    run_ops()

    payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    per_section = int(1999 * 0.25) + int(1999 * 0.25)
    sum_then_floor = int(3998 * 0.25)
    assert payout["platform_fee_cents"] == per_section == 998
    assert sum_then_floor == 999, "the rejected order is exactly one cent larger here"
    assert payout["platform_fee_cents"] != sum_then_floor


def test_fee_band_edge_is_inclusive_at_exactly_two_thousand_cents(api):
    """PRD §3.8: "The band rate is 0.30 for gross below 2000 cents, 0.25 for gross from
    2000 cents up to but not including 5000 cents, 0.20 for gross from 5000 cents up to
    but not including 10000 cents, and 0.15 for gross at or above 10000 cents."

    Design: Difficulty/boundary_precision_check/fee_band_boundary_at_exactly_two_thousand_cents
    """
    teacher = onboard_active_teacher()
    learner = create_learner(tier="FAMILY")
    on_the_edge = setup_listing(teacher, title="On The Boundary", list_price_cents=2500)
    just_below = setup_listing(teacher, title="Just Below", list_price_cents=2498)

    low_section = create_section(
        on_the_edge, teacher, start_utc="2026-10-10T14:00:00Z", end_utc="2026-10-10T16:00:00Z",
        min_learners=1, capacity=6,
    )
    low_enrollment = reserve_seat(on_the_edge, low_section, learner)
    assert low_enrollment["discounted_price_cents"] == 2000
    confirm_seat(low_enrollment["id"])
    declare_minimum_met(on_the_edge["id"], low_section["id"], teacher["id"])

    high_section = create_section(
        just_below, teacher, start_utc="2026-11-10T14:00:00Z", end_utc="2026-11-10T16:00:00Z",
        min_learners=1, capacity=6,
    )
    high_enrollment = reserve_seat(just_below, high_section, learner)
    assert high_enrollment["discounted_price_cents"] == 1999
    confirm_seat(high_enrollment["id"])
    declare_minimum_met(just_below["id"], high_section["id"], teacher["id"])

    set_clock("2026-11-10T15:00:00Z")
    run_ops()

    low_payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert low_payout["gross_earnings_cents"] == 2000
    assert low_payout["fee_rate_applied"] == 0.25, "the 2000-cent edge belongs to the lower band"
    assert low_payout["platform_fee_cents"] == 500
    assert low_payout["net_payout_cents"] == 1500

    high_payout = request_payout(teacher, "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")
    assert high_payout["gross_earnings_cents"] == 1999
    assert high_payout["fee_rate_applied"] == 0.30, "one cent lower takes the higher band"
    assert high_payout["platform_fee_cents"] == 599
    assert high_payout["net_payout_cents"] == 1400


def test_one_cent_below_the_band_edge_pays_the_higher_rate(api):
    """PRD §3.8: "The band rate is 0.30 for gross below 2000 cents, 0.25 for gross from
    2000 cents up to but not including 5000 cents, 0.20 for gross from 5000 cents up to
    but not including 10000 cents, and 0.15 for gross at or above 10000 cents."

    Design: Difficulty/boundary_precision_check/fee_band_boundary_at_exactly_two_thousand_cents
    """
    teacher = onboard_active_teacher()
    learner = create_learner(tier="FAMILY")
    listing = setup_listing(teacher, title="Just Below", list_price_cents=2498)
    section = create_section(
        listing, teacher, start_utc="2026-11-10T14:00:00Z", end_utc="2026-11-10T16:00:00Z",
        min_learners=1, capacity=6,
    )
    enrollment = reserve_seat(listing, section, learner)
    assert enrollment["discounted_price_cents"] == 1999
    confirm_seat(enrollment["id"])
    declare_minimum_met(listing["id"], section["id"], teacher["id"])

    set_clock("2026-11-10T15:00:00Z")
    run_ops()

    payout = request_payout(teacher, "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")
    assert payout["gross_earnings_cents"] == 1999
    assert payout["fee_rate_applied"] == 0.30
    assert payout["platform_fee_cents"] == 599, "floor(1999 * 0.30) == 599"
    assert payout["net_payout_cents"] == 1400
    assert payout["platform_fee_cents"] == payout["gross_earnings_cents"] - payout["net_payout_cents"]


def test_adjacent_payout_periods_do_not_overlap(api):
    """PRD §2.10: "Settlement periods are half-open intervals. A payout's period covers
    instants that are at or after `period_start` and strictly before `period_end`; a
    section starting exactly at `period_start` falls inside the period, and a section
    starting exactly at `period_end` falls outside it."
    PRD §2.6: "A payout's `period_end` is strictly after its `period_start`, and no other
    non-`VOIDED` payout of the same teacher overlaps the requested period. Any failure here
    is `ERR_PAYOUT_PERIOD_OVERLAP` (HTTP 409), and it applies to payout request."

    Design: Difficulty/resource_temporal_overlap/payout_period_overlap_uses_half_open_intervals
    """
    teacher = onboard_active_teacher()

    first = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert first["period_start"] == "2026-10-01T00:00:00Z"
    assert first["period_end"] == "2026-10-31T00:00:00Z"

    adjacent = request_payout(teacher, "2026-10-31T00:00:00Z", "2026-11-30T00:00:00Z")
    assert adjacent["period_start"] == "2026-10-31T00:00:00Z", (
        "a period beginning exactly at the first period's end is admitted, so the interval "
        "is half-open at its upper edge"
    )

    version = get_teacher_version(teacher["id"])
    colliding = api.create_payout(
        teacher["id"],
        {
            "period_start": "2026-10-15T00:00:00Z",
            "period_end": "2026-11-15T00:00:00Z",
            "expected_teacher_version": version,
        },
        make_teacher_headers(teacher["id"]),
    )
    validate_error(colliding, ApiErrorId.ERR_PAYOUT_PERIOD_OVERLAP)


def test_payout_period_ending_exactly_at_the_next_periods_start_is_admitted(api):
    """PRD §2.10: "Settlement periods are half-open intervals. A payout's period covers
    instants that are at or after `period_start` and strictly before `period_end`; a
    section starting exactly at `period_start` falls inside the period, and a section
    starting exactly at `period_end` falls outside it."

    Design: Difficulty/resource_temporal_overlap/payout_period_overlap_uses_half_open_intervals
    """
    teacher = onboard_active_teacher()

    occupied = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    assert occupied["status"] == "REQUESTED"

    earlier = request_payout(teacher, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
    assert earlier["period_end"] == "2026-10-01T00:00:00Z", (
        "a period ending exactly at the occupied period's start shares no instant with it"
    )

    version = get_teacher_version(teacher["id"])
    inside = api.create_payout(
        teacher["id"],
        {
            "period_start": "2026-10-01T00:00:00Z",
            "period_end": "2026-10-15T00:00:00Z",
            "expected_teacher_version": version,
        },
        make_teacher_headers(teacher["id"]),
    )
    validate_error(inside, ApiErrorId.ERR_PAYOUT_PERIOD_OVERLAP)


def test_paying_an_already_paid_payout_is_refused_without_a_second_drawdown(api):
    """PRD §2.6: "A payout already in `PAID` status may not be transitioned again. Any
    failure here is `ERR_PAYOUT_ALREADY_PAID` (HTTP 409), and it applies to every payout
    transition."
    PRD §3.8: "An `APPROVE` moves a `FAILED` payout to `PAID`, requires `approval_status`
    to be `pending_approval` (otherwise `ERR_PAYOUT_NOT_APPROVED`, 409), writes `approved`,
    and also decrements `unpaid_earnings_cents` by `net_payout_cents`."

    Design: Corner/errors/payout_transition_on_already_paid_payout_returns_invalid_state
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, list_price_cents=2000)
    section = create_section(
        listing, teacher, start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner(tier="FAMILY")
    enrollment = reserve_seat(listing, section, learner)
    confirm_seat(enrollment["id"])
    declare_minimum_met(listing["id"], section["id"], teacher["id"])

    set_clock("2026-11-05T15:00:00Z")
    run_ops()

    payout = request_payout(teacher, "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")
    transition_payout(payout["id"], "SEND")
    paid = transition_payout(payout["id"], "PAY")
    assert paid["status"] == "PAID"
    assert get_teacher(teacher["id"])["unpaid_earnings_cents"] == 0

    second = api.transition_payout(
        payout["id"], {"action": "PAY"}, make_platform_admin_headers()
    )
    validate_error_is_one_of(
        second, [ApiErrorId.ERR_PAYOUT_ALREADY_PAID, ApiErrorId.ERR_INVALID_STATE]
    )

    assert get_payout(payout["id"])["status"] == "PAID"
    assert get_teacher(teacher["id"])["unpaid_earnings_cents"] == 0, (
        "the refused transition did not draw the unpaid balance down a second time"
    )


def test_payout_send_is_blocked_while_the_teacher_tax_document_needs_updating(api):
    """PRD §3.8: "A `SEND` moves a payout from `REQUESTED` to `SENT`, and it requires that
    the payout is not already held with `approval_status` of `pending_approval`, that its
    `tax_document_status` is `ON_FILE` (otherwise `ERR_TAX_DOC_MISSING`, 409), and that the
    cap check above passes; sending does not touch the teacher's unpaid balance, because the
    money is not yet disbursed."
    PRD §3.2: "The teacher's `payout_tax_document_status` is a pure function of
    `lifetime_net_earnings_cents`: a teacher at or below 20000 cents of lifetime net
    earnings is `ON_FILE`, a teacher above 20000 but at or below 200000 cents is
    `REQUIRED_UPDATE`, and a teacher above 200000 cents is `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/payout_send_depends_on_teacher_tax_document_status
    """
    scenario = setup_tax_document_gate_scenario()
    teacher, payout = scenario["teacher"], scenario["payout"]

    assert payout["gross_earnings_cents"] == 24000
    assert payout["platform_fee_cents"] == 3600
    assert payout["net_payout_cents"] == 20400
    assert payout["tax_document_status"] == "REQUIRED_UPDATE"

    current = get_teacher(teacher["id"])
    assert current["lifetime_net_earnings_cents"] == 20400
    assert current["payout_tax_document_status"] == "REQUIRED_UPDATE"

    response = api.transition_payout(
        payout["id"], {"action": "SEND"}, make_platform_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_TAX_DOC_MISSING)

    held = get_payout(payout["id"])
    assert held["status"] == "REQUESTED", "the refused send left the payout where it was"
    assert held["approval_status"] == "not_required"


def test_payout_send_succeeds_after_a_refund_returns_the_teacher_to_on_file(api):
    """PRD §3.2: "An out-of-date tax document never suspends a teacher: teacher status is
    changed only by the manual suspend endpoint and by the report-risk cascade. Instead, the
    tax-document status gates settlement — a payout may not advance to `SENT` while its
    `tax_document_status` is anything other than `ON_FILE`, and the attempt is refused with
    `ERR_TAX_DOC_MISSING` (409)."
    PRD §3.8: "The third hop re-sums `lifetime_net_earnings_cents` from all non-`VOIDED`
    payouts and re-derives `payout_tax_document_status` from that total, which means a refund
    large enough to drop lifetime earnings to or below 20000 cents returns the teacher from
    `REQUIRED_UPDATE` to `ON_FILE`".

    Design: Difficulty/cross_entity_state_dependency/payout_send_depends_on_teacher_tax_document_status
    """
    scenario = setup_tax_document_gate_scenario()
    teacher, listing, payout = scenario["teacher"], scenario["listing"], scenario["payout"]
    cancelled_enrollment = scenario["enrollments"][1]

    blocked = api.transition_payout(
        payout["id"], {"action": "SEND"}, make_platform_admin_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_TAX_DOC_MISSING)

    cancel_section(listing["id"], scenario["sections"][1]["id"], teacher["id"])

    refunded = get_enrollment(cancelled_enrollment["id"])
    assert refunded["status"] == "CANCELLED_BY_TEACHER"
    assert refunded["refund_category"] == "FULL"
    assert refunded["refund_cents"] == 12000

    clawed_back = get_payout(payout["id"])
    assert clawed_back["status"] == "FAILED", "the clawback moved the payout without any request naming it"
    assert clawed_back["gross_earnings_cents"] == 12000, "the refunded section dropped out of the accrual set"
    assert clawed_back["platform_fee_cents"] == 1800
    assert clawed_back["net_payout_cents"] == 10200
    assert clawed_back["platform_fee_reversed_cents"] == 1800
    assert clawed_back["teacher_liability_cents"] == 5100

    current = get_teacher(teacher["id"])
    assert current["lifetime_net_earnings_cents"] == 10200
    assert current["payout_tax_document_status"] == "ON_FILE", (
        "the recomputed lifetime total fell back to or below the reporting threshold"
    )

    fresh_payout = request_payout(teacher, "2026-12-01T00:00:00Z", "2026-12-31T00:00:00Z")
    sent = transition_payout(fresh_payout["id"], "SEND")
    assert sent["status"] == "SENT", (
        "the same transition succeeded once the owning teacher's computed tax status was ON_FILE"
    )
    assert sent["tax_document_status"] == "ON_FILE"


def test_stale_teacher_version_is_rejected_on_payout_create(api):
    """PRD §2.8: "A request to create a payout for a teacher must carry
    `expected_teacher_version` as a non-optional field holding the teacher's `version` as
    the client last observed it. If the teacher's current `version` has advanced past that
    value — because another writer recorded a payout against the same unpaid-earnings
    balance, or because a teacher-fault refund cascade rewrote the teacher's fee-reversed,
    liability and unpaid-earnings totals — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_teacher_version_rejected_on_payout_create
    """
    teacher = onboard_active_teacher()
    observed_version = get_teacher_version(teacher["id"])

    first = request_payout(
        teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z", expected_version=observed_version
    )
    assert first["status"] == "REQUESTED"

    stale = api.create_payout(
        teacher["id"],
        {
            "period_start": "2026-11-01T00:00:00Z",
            "period_end": "2026-11-30T00:00:00Z",
            "expected_teacher_version": observed_version,
        },
        make_teacher_headers(teacher["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    assert get_payout(first["id"])["status"] == "REQUESTED"
    payouts, meta = list_payouts_for_teacher(teacher["id"])
    assert meta["total_count"] == 1, "the stale request created no second payout"
