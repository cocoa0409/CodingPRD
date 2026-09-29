"""Monthly settlement: the two variants and the four-step waterfall."""

from test_helpers import (
    ANALYST_DRAFTER,
    ANALYST_ISSUER,
    ApiErrorId,
    TEST_DEFAULTS,
    api_client,
    assert_night_dimensions,
    assert_statement_waterfall,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _prorated_community(name, clock=None):
    """Build the pinned settlement fixture: 4 doors, three billable residents.

    Unit 101 occupies the whole of September (30 billable days), unit 102 moves
    in on the 14th (17 days), unit 103 moves out on the 18th exclusive
    (17 days) and unit 104 stays vacant.
    """
    fixtures.set_clock(clock or TEST_DEFAULTS["SETUP_CLOCK"])
    prop = fixtures.create_property(name=name, unit_count=4)
    contract = fixtures.draft_contract(
        prop["id"],
        per_unit_monthly_fee_cents=3495,
        property_revenue_share_bps=1500,
        sla_missed_threshold_bps=1000,
    )
    residents = {
        101: fixtures.create_resident(
            prop["id"], 101, full_name="Rosa One", move_in_date="2026-08-01"
        ),
        102: fixtures.create_resident(
            prop["id"], 102, full_name="Ravi Two", move_in_date="2026-09-14"
        ),
        103: fixtures.create_resident(
            prop["id"], 103, full_name="Rita Three", move_in_date="2026-08-01"
        ),
    }
    fixtures.move_out_resident(prop["id"], residents[103]["id"], "2026-09-18")
    contract = fixtures.activate_contract(contract["id"])
    return {
        "property": fixtures.read_property(prop["id"]),
        "contract": contract,
        "residents": residents,
    }


def _scan_two_doors_and_close(world, night, contractor):
    """Serve units 101 and 103 on `night`, leaving the route in progress."""
    route = fixtures.assign_and_accept_route(night["id"], contractor["id"], 101, 103)
    fixtures.record_scan(
        route["id"], contractor["id"], world["residents"][101]["id"], "SERVICED"
    )
    fixtures.record_scan(
        route["id"], contractor["id"], world["residents"][103]["id"], "SERVICED"
    )
    return route


# --------------------------------------------------------------------------
# The PROVISIONAL / FINAL divergence
# --------------------------------------------------------------------------
def test_provisional_draft_bills_the_contracted_door_count():
    """A draft bills every door, vacant ones included.

    PRD 3.8: "Under the `PROVISIONAL` variant it is simply
    `per_unit_monthly_fee_cents` multiplied by the community's `unit_count`:
    the contracted door count, with vacant doors billed and no proration
    whatsoever."

    Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_diverge_on_gross_basis
    """
    world = _prorated_community("Maple Court")
    contract = world["contract"]
    contractor = fixtures.create_eligible_contractor()

    night_one = fixtures.schedule_night(contract["id"], "2026-09-01")
    night_two = fixtures.schedule_night(contract["id"], "2026-09-02")
    _scan_two_doors_and_close(world, night_two, contractor)
    fixtures.close_night(night_two["id"])
    fixtures.close_night(night_one["id"])

    response = api_client.create_statement(
        contract["id"],
        factories.statement_payload("2026-09", contract["version"]),
        ANALYST_DRAFTER,
    )
    statement = validate_success(response, expected_status=201)

    assert statement["variant"] == "PROVISIONAL"
    assert_statement_waterfall(
        statement,
        gross_cents=13980,
        sla_credit_rate_bps=1200,
        credit_cents=1678,
        share_cents=1845,
        net_cents=10457,
        missed_service_bps=5000,
        scheduled_night_count=2,
        missed_equivalent_nights=1.0,
    )


def test_issue_recomputes_the_same_statement_onto_the_prorated_gross():
    """Issuing the identical statement moves gross 13980 to 7457 and net to 5578.

    PRD 3.8: "The `variant` switches `PROVISIONAL → FINAL` and all six money
    and ratio fields — `gross_passthrough_cents`, `missed_service_bps`,
    `sla_credit_rate_bps`, `missed_service_credit_cents`,
    `property_revenue_share_cents` and `net_due_from_property_cents` — are
    recomputed from scratch under the final variant, alongside
    `scheduled_night_count` and `missed_equivalent_nights`."

    Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_diverge_on_gross_basis
    """
    world = _prorated_community("Maple Court")
    contract = world["contract"]
    contractor = fixtures.create_eligible_contractor()

    night_one = fixtures.schedule_night(contract["id"], "2026-09-01")
    night_two = fixtures.schedule_night(contract["id"], "2026-09-02")
    _scan_two_doors_and_close(world, night_two, contractor)
    fixtures.close_night(night_two["id"])
    fixtures.close_night(night_one["id"])

    draft = fixtures.draft_statement(
        contract["id"], "2026-09", contract["version"]
    )

    issued = validate_success(
        api_client.issue_statement(draft["id"], ANALYST_ISSUER)
    )

    assert issued["variant"] == "FINAL"
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == "analyst-issuer"
    assert_statement_waterfall(
        issued,
        gross_cents=7457,
        sla_credit_rate_bps=1200,
        credit_cents=895,
        share_cents=984,
        net_cents=5578,
    )
    assert draft["gross_passthrough_cents"] - issued["gross_passthrough_cents"] == 6523
    assert (
        draft["net_due_from_property_cents"] - issued["net_due_from_property_cents"]
        == 4879
    )

    settled = {
        night["id"]: night
        for night in fixtures.list_nights({"contract_id": contract["id"]})
    }
    assert_night_dimensions(settled[night_one["id"]], "MISSED", "CREDITED")
    assert_night_dimensions(settled[night_two["id"]], "VERIFIED", "INVOICED")


# --------------------------------------------------------------------------
# Per-line rounding of the prorated gross
# --------------------------------------------------------------------------
def test_final_gross_rounds_each_resident_line_before_summing():
    """Two 17-day lines round to 1981 apiece, so the gross is 7457 and not 7456.

    PRD 3.8: "Multiply the exact daily rate by that day count and **round the
    resulting line half up to whole cents**. Finally add the rounded lines
    together."

    Design: Difficulty/combinatorial_formula/statement_gross_rounds_each_resident_line_before_summing
    """
    world = _prorated_community("Willow Gate", clock="2026-09-30T00:00:00Z")
    contract = world["contract"]
    draft = fixtures.draft_statement(contract["id"], "2026-09", contract["version"])

    issued = validate_success(api_client.issue_statement(draft["id"], ANALYST_ISSUER))

    assert issued["variant"] == "FINAL"
    assert issued["gross_passthrough_cents"] == 7457, (
        "the three lines are 3495 + 1981 + 1981; summing the exact values first "
        "would have produced 7456"
    )


def test_final_gross_excludes_the_vacant_door_and_carries_the_share_onward():
    """With no night in the period the SLA arm is inert and only the share bites.

    PRD 3.8: "`missed_service_bps` is then 0 when `scheduled_night_count` is 0,
    and otherwise ten thousand multiplied by `missed_equivalent_nights`,
    divided by `scheduled_night_count`, rounded half up to a whole basis
    point."

    Design: Difficulty/combinatorial_formula/statement_gross_rounds_each_resident_line_before_summing
    """
    world = _prorated_community("Willow Gate", clock="2026-09-30T00:00:00Z")
    contract = world["contract"]
    draft = fixtures.draft_statement(contract["id"], "2026-09", contract["version"])

    issued = validate_success(api_client.issue_statement(draft["id"], ANALYST_ISSUER))

    assert_statement_waterfall(
        issued,
        gross_cents=7457,
        sla_credit_rate_bps=0,
        credit_cents=0,
        share_cents=1119,
        net_cents=6338,
        missed_service_bps=0,
        scheduled_night_count=0,
    )


# --------------------------------------------------------------------------
# The four-step waterfall keying
# --------------------------------------------------------------------------
def _two_missed_nights_with_draft(name="Maple Court"):
    world = _prorated_community(name)
    contract = world["contract"]
    night_one = fixtures.schedule_night(contract["id"], "2026-09-01")
    night_two = fixtures.schedule_night(contract["id"], "2026-09-02")
    fixtures.close_night(night_one["id"])
    fixtures.close_night(night_two["id"])
    draft = fixtures.draft_statement(contract["id"], "2026-09", contract["version"])
    world["nights"] = [night_one, night_two]
    world["draft"] = draft
    return world


def test_sla_credit_is_keyed_on_the_gross_figure():
    """A 1200 bps rate on a gross of 7457 credits 895 cents.

    PRD 3.8: "Then `missed_service_credit_cents` is `gross_passthrough_cents`
    multiplied by `sla_credit_rate_bps`, divided by ten thousand, rounded half
    up. Note carefully that the credit is keyed on the **gross** figure and
    never on any net figure."

    Design: Difficulty/combinatorial_formula/statement_waterfall_keys_credit_on_gross_and_share_on_net_of_credit
    """
    world = _two_missed_nights_with_draft()

    issued = validate_success(
        api_client.issue_statement(world["draft"]["id"], ANALYST_ISSUER)
    )

    assert issued["gross_passthrough_cents"] == 7457
    assert issued["missed_service_bps"] == 10000
    assert issued["sla_credit_rate_bps"] == 1200
    assert issued["missed_service_credit_cents"] == 895, (
        "894 would mean the credit was keyed on the gross net of the owner's share"
    )


def test_owner_share_is_keyed_on_the_gross_net_of_the_credit():
    """The share reads 6562, not 7457, so it lands on 984 rather than 1119.

    PRD 3.8: "`property_revenue_share_cents` is the gross **minus the credit
    just computed**, multiplied by the contract's `property_revenue_share_bps`,
    divided by ten thousand, rounded half up."

    Design: Difficulty/combinatorial_formula/statement_waterfall_keys_credit_on_gross_and_share_on_net_of_credit
    """
    world = _two_missed_nights_with_draft()

    issued = validate_success(
        api_client.issue_statement(world["draft"]["id"], ANALYST_ISSUER)
    )

    assert_statement_waterfall(
        issued,
        gross_cents=7457,
        sla_credit_rate_bps=1200,
        credit_cents=895,
        share_cents=984,
        net_cents=5578,
        missed_service_bps=10000,
        scheduled_night_count=2,
        missed_equivalent_nights=2.0,
    )
    settled = {
        night["id"]: night
        for night in fixtures.list_nights({"contract_id": world["contract"]["id"]})
    }
    for night in world["nights"]:
        assert_night_dimensions(settled[night["id"]], "MISSED", "CREDITED")


# --------------------------------------------------------------------------
# Issue is gated on the terminality of the period's nights
# --------------------------------------------------------------------------
def _period_with_one_live_night():
    world = _prorated_community("Maple Court")
    contract = world["contract"]
    contractor = fixtures.create_eligible_contractor()
    night_one = fixtures.schedule_night(contract["id"], "2026-09-01")
    fixtures.close_night(night_one["id"])
    night_two = fixtures.schedule_night(contract["id"], "2026-09-02")
    _scan_two_doors_and_close(world, night_two, contractor)
    world["nights"] = [night_one, night_two]
    world["draft"] = fixtures.draft_statement(
        contract["id"], "2026-09", contract["version"]
    )
    return world


def test_issue_is_refused_while_a_night_of_the_period_is_still_in_progress():
    """A legal DRAFT cannot be issued over a night that has not been closed.

    PRD 3.8: "every service night of the contract whose `service_date` falls
    inside `billing_period` must already be terminal, that is `VERIFIED`,
    `PARTIAL`, `MISSED` or `CANCELLED`, or the issue is refused with
    `ERR_PERIOD_NOT_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/statement_issue_requires_every_night_in_period_terminal
    """
    world = _period_with_one_live_night()

    response = api_client.issue_statement(world["draft"]["id"], ANALYST_ISSUER)

    validate_error(response, ApiErrorId.ERR_PERIOD_NOT_CLOSED.value, 409)
    unchanged = fixtures.read_statement(world["draft"]["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["variant"] == "PROVISIONAL"


def test_closing_the_last_night_of_the_period_unblocks_the_issue():
    """Closing a different entity is what makes ISSUED reachable.

    PRD 3.5: "Otherwise, if `coverage_bps` is at or above the verification
    threshold of 7500 basis points — that is, three quarters of the expected
    doors or better — the outcome is `VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/statement_issue_requires_every_night_in_period_terminal
    """
    world = _period_with_one_live_night()
    night_one, night_two = world["nights"]
    api_client.issue_statement(world["draft"]["id"], ANALYST_ISSUER)

    closed = fixtures.close_night(night_two["id"])
    assert_night_dimensions(closed, "VERIFIED", "ACCRUED")
    assert closed["coverage_bps"] == 10000

    issued = validate_success(
        api_client.issue_statement(world["draft"]["id"], ANALYST_ISSUER)
    )

    assert issued["status"] == "ISSUED"
    assert issued["variant"] == "FINAL"
    assert_statement_waterfall(
        issued,
        gross_cents=7457,
        sla_credit_rate_bps=1200,
        credit_cents=895,
        share_cents=984,
        net_cents=5578,
        missed_service_bps=5000,
    )
    settled = {
        night["id"]: night
        for night in fixtures.list_nights({"contract_id": world["contract"]["id"]})
    }
    assert settled[night_one["id"]]["billing_status"] == "CREDITED"
    assert settled[night_two["id"]]["billing_status"] == "INVOICED"
