"""Ownership shares, occupancy intervals and the geometry rules over them.

The ownership registry is the factual evidence behind every residency claim, so
its intervals are half-open, its successors truncate open-ended predecessors, and
a genuine intersection on one parcel or across a taxpayer's parcels is refused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_OCCUPANCY_INTERVAL_OVERLAP,
    ERR_PARCEL_NOT_FOUND,
    ERR_TAXPAYER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_calendar_date,
    assert_common_fields,
    assert_grant,
    assert_parcel_decomposition,
    ids_of,
)
from test_helpers.test_users import ANALYST, CLERK, REVIEWER


def _timeline_world(api):
    """A parcel and a claimant with one closed primary-residence interval on file.

    The interval runs from 2020-01-01 up to but not including 2023-01-01, and it
    carries an explicit end date so that no open-ended truncation can mask the
    geometry check applied to its successors.
    """
    fx.set_clock(api)
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(
        api,
        f.taxpayer_account(
            full_name="OLIVIA OCCUPANT",
            date_of_birth="1975-11-11",
            ssn_last4="8181",
        ),
    )
    first = fx.add_ownership(
        api,
        parcel["id"],
        taxpayer["id"],
        deed_recorded_date="2020-01-01",
        occupancy_start_date="2020-01-01",
        occupancy_end_date="2023-01-01",
    )
    return {"parcel": parcel, "taxpayer": taxpayer, "first": first}


def test_successor_occupancy_interval_may_begin_on_the_day_the_last_one_ended(api):
    """PRD §3.1: "Occupancy intervals are **half-open**: an interval runs from its
    `occupancy_start_date` inclusive to its `occupancy_end_date` exclusive, and a
    null `occupancy_end_date` means the interval is still open-ended." PRD §3.1
    adds: "because the semantics are half-open, touching endpoints are fine — a
    record ending on the day the next one begins does not overlap".

    Design: Difficulty/resource_temporal_overlap/occupancy_intervals_touch_at_endpoints_but_reject_true_overlap
    """
    world = _timeline_world(api)

    second = validate_success(
        api.create_ownership_record(
            f.ownership_record(
                world["parcel"]["id"],
                world["taxpayer"]["id"],
                deed_recorded_date="2023-01-01",
                occupancy_start_date="2023-01-01",
                occupancy_end_date="2026-01-01",
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    assert_common_fields(second)
    assert second["status"] == "VERIFIED", (
        f"a deed-registry record is created VERIFIED, got {second['status']}"
    )
    assert_calendar_date(second, "occupancy_start_date", "2023-01-01")
    assert_calendar_date(second, "occupancy_end_date", "2026-01-01")

    # The predecessor was not open-ended, so nothing truncated or superseded it.
    predecessor = validate_success(
        api.get_ownership_record(world["first"]["id"], ANALYST)
    )
    assert predecessor["status"] == "VERIFIED", (
        "a touching successor does not supersede a closed predecessor, got "
        f"{predecessor['status']}"
    )
    assert_calendar_date(predecessor, "occupancy_end_date", "2023-01-01")


def test_occupancy_interval_that_genuinely_intersects_its_predecessor_is_refused(api):
    """PRD §3.1: "A new `PRIMARY_RESIDENCE` interval must not overlap an existing
    `PRIMARY_RESIDENCE` interval on the same parcel; because the semantics are
    half-open, touching endpoints are fine — a record ending on the day the next
    one begins does not overlap — but any genuine intersection is rejected with
    `ERR_OCCUPANCY_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/occupancy_intervals_touch_at_endpoints_but_reject_true_overlap
    """
    world = _timeline_world(api)
    parcel_id = world["parcel"]["id"]
    taxpayer_id = world["taxpayer"]["id"]
    second = validate_success(
        api.create_ownership_record(
            f.ownership_record(
                parcel_id,
                taxpayer_id,
                deed_recorded_date="2023-01-01",
                occupancy_start_date="2023-01-01",
                occupancy_end_date="2026-01-01",
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    # 2025-06-01 falls strictly inside [2023-01-01, 2026-01-01).
    validate_error(
        api.create_ownership_record(
            f.ownership_record(
                parcel_id,
                taxpayer_id,
                deed_recorded_date="2025-06-01",
                occupancy_start_date="2025-06-01",
            ),
            ANALYST,
        ),
        ERR_OCCUPANCY_INTERVAL_OVERLAP,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_ownership_records(
            ANALYST, parcel_id=parcel_id, occupancy_type="PRIMARY_RESIDENCE"
        )
    )
    assert meta["total_count"] == 2, (
        f"the rejected ingestion must leave two records on the parcel, got {meta['total_count']}"
    )
    assert ids_of(rows) == [world["first"]["id"], second["id"]], (
        f"unexpected primary-residence timeline: {ids_of(rows)}"
    )


def test_both_foreign_keys_on_an_ownership_record_are_resolved_before_insert(api):
    """PRD §2.10 rung 7: "Body foreign keys resolve — the same not-found family plus
    `ERR_PROGRAM_NOT_FOUND` and `ERR_NOTICE_NOT_FOUND`, covering `parcel_id`,
    `taxpayer_id`, `program_id`, `grant_id`, `notice_id`, `docket_id` and
    `destination_parcel_id`. Applies to `POST /ownership-records`". PRD §3.1: "An
    `AssessorAnalyst` ingests an ownership record naming the `parcel_id` and the
    `taxpayer_id` it links".

    Design: Corner/entities/ownership_record_foreign_keys_are_validated_before_insert
    """
    fx.set_clock(api)
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())

    # The parcel resolves and the claimant does not.
    validate_error(
        api.create_ownership_record(
            f.ownership_record(parcel["id"], NON_EXISTENT_UUID), ANALYST
        ),
        ERR_TAXPAYER_NOT_FOUND,
        expected_status=404,
    )

    # The claimant resolves and the parcel does not.
    validate_error(
        api.create_ownership_record(
            f.ownership_record(NON_EXISTENT_UUID, taxpayer["id"]), ANALYST
        ),
        ERR_PARCEL_NOT_FOUND,
        expected_status=404,
    )

    by_parcel, parcel_meta = validate_paginated(
        api.list_ownership_records(ANALYST, parcel_id=parcel["id"])
    )
    assert parcel_meta["total_count"] == 0, (
        f"no record may have reached the parcel, got {parcel_meta['total_count']}"
    )
    assert by_parcel == [], f"unexpected records on the parcel: {by_parcel}"

    by_taxpayer, taxpayer_meta = validate_paginated(
        api.list_ownership_records(ANALYST, taxpayer_id=taxpayer["id"])
    )
    assert taxpayer_meta["total_count"] == 0, (
        f"no record may have reached the claimant, got {taxpayer_meta['total_count']}"
    )
    assert by_taxpayer == [], f"unexpected records for the claimant: {by_taxpayer}"


def _two_grants_on_two_parcels(api):
    """One household holding a homestead on its residence and a farm exemption.

    The residence is supported by an open-ended primary-residence record and the
    smallholding by an open-ended agricultural one, so a later secondary record on
    either parcel supersedes exactly one of the two.
    """
    fx.set_clock(api)
    homestead = fx.create_program(api, f.homestead_basic_program())
    agricultural = fx.create_program(
        api,
        f.agricultural_use_program(
            relief_pct_bps=3000,
            max_exempt_value_cents=5000000,
            statutory_lookback_years=3,
            penalty_pct_bps=1000,
            interest_pct_bps_per_year=500,
        ),
    )
    residence = fx.create_parcel(api, f.parcel())
    smallholding = fx.create_parcel(
        api,
        f.parcel(
            apn="P-0007",
            situs_address_normalized="700 FARM RD NORTHFIELD ST 10007",
            county_zone="WEST",
            base_year=2026,
            base_year_value_cents=1600000,
            market_value_cents=2000000,
        ),
    )
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    residence_record = fx.add_ownership(api, residence["id"], taxpayer["id"])
    farm_record = fx.add_ownership(
        api,
        smallholding["id"],
        taxpayer["id"],
        occupancy_type="AGRICULTURAL",
        deed_recorded_date="2019-01-01",
        occupancy_start_date="2019-01-01",
    )
    fx.inject_matching_residency(api, taxpayer["id"])

    homestead_application = fx.application_ready_for_approval(
        api, residence["id"], taxpayer["id"], homestead["id"]
    )
    homestead_determined = validate_success(
        api.determine_application(
            homestead_application["id"],
            f.approve_determination(residence["version"]),
            REVIEWER,
        )
    )
    farm_application = fx.application_ready_for_approval(
        api,
        smallholding["id"],
        taxpayer["id"],
        agricultural["id"],
        claimed_occupancy_date="2019-01-01",
    )
    farm_determined = validate_success(
        api.determine_application(
            farm_application["id"],
            f.approve_determination(smallholding["version"]),
            REVIEWER,
        )
    )
    return {
        "taxpayer": taxpayer,
        "residence": residence,
        "smallholding": smallholding,
        "residence_record": residence_record,
        "farm_record": farm_record,
        "homestead_grant_id": homestead_determined["resulting_grant_id"],
        "farm_grant_id": farm_determined["resulting_grant_id"],
    }


def test_a_secondary_record_costs_the_homestead_but_spares_the_farm_exemption(api):
    """PRD §3.1: "If the newly ingested record carries an `occupancy_type` of
    `SECONDARY` or `RENTAL`, and the record it supersedes was the very record that
    supported an `ACTIVE` grant on that parcel for that taxpayer, and that grant's
    `exemption_type` is not `AGRICULTURAL_USE`, then the grant loses its factual
    basis. The consequences cascade in order: the predecessor record is truncated
    and marked `SUPERSEDED`; the grant's `benefit_status` moves from `ACTIVE` to
    `SUSPENDED` with `suspension_reason` `OCCUPANCY_LOST`; the grant's departure
    from the active set re-runs the parcel value decomposition ...; and a notice of
    type `SUSPENSION` is mailed to the taxpayer against that grant."

    Design: Corner/state_machines/occupancy_supersession_suspends_the_homestead_grant_but_not_the_agricultural_one
    """
    world = _two_grants_on_two_parcels(api)
    taxpayer_id = world["taxpayer"]["id"]

    # The identical event on the farm: it supersedes the record, and stops there.
    validate_success(
        api.create_ownership_record(
            f.ownership_record(
                world["smallholding"]["id"],
                taxpayer_id,
                deed_recorded_date="2026-07-20",
                occupancy_type="SECONDARY",
                occupancy_start_date="2026-08-01",
                source_system="FIELD_INSPECTION",
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    superseded_farm = validate_success(
        api.get_ownership_record(world["farm_record"]["id"], ANALYST)
    )
    assert superseded_farm["status"] == "SUPERSEDED", (
        f"the open-ended predecessor is closed out, got {superseded_farm['status']}"
    )
    assert_calendar_date(superseded_farm, "occupancy_end_date", "2026-08-01")

    farm_grant = validate_success(api.get_grant(world["farm_grant_id"], REVIEWER))
    assert_grant(
        farm_grant,
        benefit_status="ACTIVE",
        benefit_amount_cents=480000,
        applied_exempt_value_cents=480000,
        suspension_reason=None,
    )
    farm_parcel = validate_success(api.get_parcel(world["smallholding"]["id"], ANALYST))
    assert_parcel_decomposition(
        farm_parcel,
        assessed_value_cents=1600000,
        exempt_value_cents=480000,
        taxable_value_cents=1120000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert farm_parcel["version"] == 2, (
        "no cascade fired, so the only mutation is still the approval, got version "
        f"{farm_parcel['version']}"
    )

    # The same event on the residence costs the household its homestead.
    validate_success(
        api.create_ownership_record(
            f.ownership_record(
                world["residence"]["id"],
                taxpayer_id,
                deed_recorded_date="2026-07-20",
                occupancy_type="SECONDARY",
                occupancy_start_date="2026-08-01",
                source_system="FIELD_INSPECTION",
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    superseded_residence = validate_success(
        api.get_ownership_record(world["residence_record"]["id"], ANALYST)
    )
    assert superseded_residence["status"] == "SUPERSEDED", (
        f"the supporting record is closed out, got {superseded_residence['status']}"
    )
    assert_calendar_date(superseded_residence, "occupancy_end_date", "2026-08-01")

    homestead_grant = validate_success(
        api.get_grant(world["homestead_grant_id"], REVIEWER)
    )
    assert_grant(
        homestead_grant,
        benefit_status="SUSPENDED",
        suspension_reason="OCCUPANCY_LOST",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=0,
    )

    residence_parcel = validate_success(
        api.get_parcel(world["residence"]["id"], ANALYST)
    )
    assert_parcel_decomposition(
        residence_parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )
    assert residence_parcel["version"] == 3, (
        "creation, approval and the suspension are three mutations, got version "
        f"{residence_parcel['version']}"
    )

    rows, meta = validate_paginated(
        api.list_notices(taxpayer_id, CLERK, notice_type="SUSPENSION")
    )
    assert meta["total_count"] == 1, (
        f"only the homestead suspension mails a notice, got {meta['total_count']}"
    )
    assert rows[0]["subject_id"] == world["homestead_grant_id"], (
        f"the notice is mailed against the suspended grant, got {rows[0]['subject_id']}"
    )
