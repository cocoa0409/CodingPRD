"""Closing a night: the coverage boundary, the empty scan set, two dimensions."""

from test_helpers import (
    ANALYST_ISSUER,
    VALET_OPS_MANAGER,
    api_client,
    assert_night_coverage,
    assert_night_dimensions,
    assert_statement_waterfall,
    fixtures,
    validate_success,
)

ALL_MONTH = {"move_in_date": "2026-08-01"}


# --------------------------------------------------------------------------
# The verification and billing dimensions advance independently
# --------------------------------------------------------------------------
def _one_served_night_and_one_missed_night(name="Juniper Flats"):
    world = fixtures.build_active_community(
        name=name, resident_units=(101,), resident_kwargs={101: dict(ALL_MONTH)}
    )
    night_one, route_one = fixtures.add_scan_ready_night(world, "2026-09-01")
    fixtures.record_scan(
        route_one["id"],
        world["contractor"]["id"],
        world["residents"][101]["id"],
        "SERVICED",
    )
    night_two = fixtures.schedule_night(world["contract"]["id"], "2026-09-02")
    world["night_one"] = night_one
    world["night_two"] = night_two
    return world


def test_close_settles_verification_and_billing_without_collapsing_them():
    """One night verifies and one is missed, and both accrue on the same close.

    PRD 3.5: "Whichever of the three outcomes is selected, the same three things
    follow: the night's `verification_status` becomes that outcome; the billing
    dimension advances `UNBILLED → ACCRUED`; and every route assignment of the
    night still in `ASSIGNED`, `ACCEPTED` or `IN_PROGRESS` moves to `ABANDONED`
    with `abandon_reason` set to the literal string `NIGHT_CLOSED`, each
    recomputing the night's `assigned_unit_coverage_count` and incrementing its
    own `version`."

    Design: Difficulty/non_linear_state_machine/service_night_verification_and_billing_dimensions_advance_independently
    """
    world = _one_served_night_and_one_missed_night()

    closed_one = fixtures.close_night(world["night_one"]["id"])
    closed_two = fixtures.close_night(world["night_two"]["id"])

    assert_night_dimensions(closed_one, "VERIFIED", "ACCRUED")
    assert_night_coverage(closed_one, expected_doors=1, scanned_doors=1, coverage_bps=10000)
    assert_night_dimensions(closed_two, "MISSED", "ACCRUED")
    assert closed_two["scanned_door_count"] == 0


def test_issue_moves_only_the_billing_dimension_of_the_settled_nights():
    """The verification outcomes stand while billing splits INVOICED from CREDITED.

    PRD 3.8: "Nights whose `billing_status` is still `UNBILLED` — the cancelled
    and skipped ones — are left alone, and no night's `verification_status` is
    touched by the issue."

    Design: Difficulty/non_linear_state_machine/service_night_verification_and_billing_dimensions_advance_independently
    """
    world = _one_served_night_and_one_missed_night()
    fixtures.close_night(world["night_one"]["id"])
    fixtures.close_night(world["night_two"]["id"])
    contract = fixtures.read_contract(world["contract"]["id"])
    draft = fixtures.draft_statement(contract["id"], "2026-09", contract["version"])

    issued = validate_success(api_client.issue_statement(draft["id"], ANALYST_ISSUER))

    assert_statement_waterfall(
        issued,
        gross_cents=3495,
        sla_credit_rate_bps=1200,
        credit_cents=419,
        share_cents=461,
        net_cents=2615,
        missed_service_bps=5000,
        scheduled_night_count=2,
        missed_equivalent_nights=1.0,
    )
    settled = {
        night["id"]: night
        for night in fixtures.list_nights({"contract_id": contract["id"]})
    }
    assert_night_dimensions(settled[world["night_one"]["id"]], "VERIFIED", "INVOICED")
    assert_night_dimensions(settled[world["night_two"]["id"]], "MISSED", "CREDITED")


# --------------------------------------------------------------------------
# The verification threshold is inclusive
# --------------------------------------------------------------------------
def _three_of_four_doors_served(name="Cedar Ridge"):
    world = fixtures.build_active_community(
        name=name,
        resident_units=(101, 102, 103, 104),
        resident_kwargs={unit: dict(ALL_MONTH) for unit in (101, 102, 103, 104)},
    )
    night, route = fixtures.add_scan_ready_night(world, "2026-09-01")
    for unit in (101, 102, 103):
        fixtures.record_scan(
            route["id"],
            world["contractor"]["id"],
            world["residents"][unit]["id"],
            "SERVICED",
        )
    world["night"] = night
    world["route"] = route
    return world


def test_night_verifies_at_exactly_the_coverage_threshold():
    """Three of four doors is exactly 7500 basis points and that verifies.

    PRD 3.5: "The comparison is inclusive: coverage of exactly 7500 basis points
    is `VERIFIED`. Four expected doors with three scanned yields 7500 and
    verifies; four expected with two scanned yields 5000 and does not."

    Design: Difficulty/boundary_precision_check/night_verifies_at_exactly_seventy_five_hundred_coverage_bps
    """
    world = _three_of_four_doors_served()

    closed = fixtures.close_night(world["night"]["id"])

    assert_night_coverage(closed, expected_doors=4, scanned_doors=3, coverage_bps=7500)
    assert closed["verification_status"] == "VERIFIED"


def test_the_threshold_night_accrues_like_any_other_close():
    """Landing on the boundary changes the outcome, not the billing advance.

    PRD 3.5: "`coverage_bps` is 0 when `expected_door_count` is 0, and otherwise
    ten thousand multiplied by `scanned_door_count`, divided by
    `expected_door_count`, rounded half up to a whole basis point."

    Design: Difficulty/boundary_precision_check/night_verifies_at_exactly_seventy_five_hundred_coverage_bps
    """
    world = _three_of_four_doors_served()

    closed = fixtures.close_night(world["night"]["id"])

    assert_night_dimensions(closed, "VERIFIED", "ACCRUED")


# --------------------------------------------------------------------------
# An empty scan set is MISSED before any coverage comparison
# --------------------------------------------------------------------------
def _vacant_community_with_one_night(name="Willow Bend"):
    world = fixtures.build_active_community(
        name=name, resident_units=(), with_contractor=False
    )
    world["night"] = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    return world


def test_a_night_with_no_expected_doors_closes_missed_not_vacuously_verified():
    """Zero over zero is coverage 0, and the empty scan set decides first.

    PRD 3.5: "If `scanned_door_count` is 0, the outcome is `MISSED`. This branch
    is evaluated first and unconditionally, before any coverage comparison. A
    night with `expected_door_count` 0 and `scanned_door_count` 0 therefore
    closes `MISSED`, never `VERIFIED`, even though nobody could argue coverage
    was incomplete."

    Design: Difficulty/boundary_precision_check/night_with_zero_expected_doors_closes_missed_not_vacuously_verified
    """
    world = _vacant_community_with_one_night()

    response = api_client.close_service_night(
        world["night"]["id"], VALET_OPS_MANAGER
    )
    closed = validate_success(response)

    assert_night_coverage(closed, expected_doors=0, scanned_doors=0, coverage_bps=0)
    assert_night_dimensions(closed, "MISSED", "ACCRUED")


def test_the_empty_night_counts_as_a_whole_missed_night_in_the_ratio():
    """A vacant community's missed night still drives the shortfall arithmetic.

    PRD 3.8: "`missed_equivalent_nights` weighs a `MISSED` night as a whole
    failure and a `PARTIAL` night as half of one: it is the count of `MISSED`
    nights plus one half multiplied by the count of `PARTIAL` nights."

    Design: Difficulty/boundary_precision_check/night_with_zero_expected_doors_closes_missed_not_vacuously_verified
    """
    world = _vacant_community_with_one_night()
    fixtures.close_night(world["night"]["id"])
    contract = fixtures.read_contract(world["contract"]["id"])

    draft = fixtures.draft_statement(contract["id"], "2026-09", contract["version"])

    assert draft["scheduled_night_count"] == 1
    assert float(draft["missed_equivalent_nights"]) == 1.0
