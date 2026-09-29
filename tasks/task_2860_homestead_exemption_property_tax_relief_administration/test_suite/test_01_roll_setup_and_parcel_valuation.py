"""The statutory catalogue, the parcel roll and the derived value decomposition.

Everything a claim can be made against is published here: relief programmes with
their rates and ceilings, parcels with their valuation inputs, and the four-step
derivation that turns those inputs plus the active grant set into a parcel's
assessed, exempt and taxable values.
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
    ERR_INVALID_REQUEST,
    ERR_PARCEL_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_bps,
    assert_common_fields,
    assert_grant,
    assert_instant,
    assert_money,
    assert_parcel_decomposition,
)
from test_helpers.test_users import ADMIN, ANALYST, REVIEWER


def _coowner_ceiling_world(api):
    """A one-third owner on a parcel whose statutory share overshoots the ceiling.

    The parcel's base-year value of 60000000 is two years behind its tax year at
    a two percent annual cap, so the capped and assessed basis is 62400000; a
    relief rate of 2500 basis points asks for 15600000, well past the programme's
    10000000 ceiling, and the claimant holds only 3333 basis points of the title.
    """
    return fx.approval_world(
        api,
        parcel=f.parcel(
            apn="P-0002",
            situs_address_normalized="202 CEDAR LN EASTWICK ST 10002",
            county_zone="EAST",
            base_year=2024,
            base_year_value_cents=60000000,
            market_value_cents=70000000,
        ),
        taxpayer=f.taxpayer_account(
            full_name="FRANK COOWNER",
            date_of_birth="1960-07-04",
            ssn_last4="1111",
            mailing_address_normalized="202 CEDAR LN EASTWICK ST 10002",
        ),
        ownership={
            "ownership_pct_bps": 3333,
            "deed_recorded_date": "2019-01-01",
            "occupancy_start_date": "2019-01-01",
        },
    )


def test_programme_ceiling_binds_before_the_ownership_share_is_applied(api):
    """PRD §3.4: "Fourth, the programme ceiling: the running figure is replaced by
    the smaller of itself and `max_exempt_value_cents`. Fifth, the ownership
    share: the result is multiplied by the grant's `ownership_pct_bps_snapshot`
    and divided by ten thousand." PRD §3.4 pins that order: "the order of steps
    four and five is pinned: the ceiling applies *before* the ownership
    pro-ration, never after, because applying it afterwards would hand a
    fractional owner a larger benefit than the statute allows."

    Design: Difficulty/combinatorial_formula/benefit_ceiling_applied_before_ownership_proration_nested_min
    """
    world = _coowner_ceiling_world(api)
    grant = world["grant"]

    assert_bps(grant, "ownership_pct_bps_snapshot", 3333)
    assert_bps(grant, "relief_multiplier_bps", 10000)
    assert_money(grant, "benefit_amount_cents", 3333000)
    assert grant["benefit_amount_cents"] != 5199480, (
        "pro-rating before the ceiling would yield 5199480; the pinned order "
        f"yields 3333000, got {grant['benefit_amount_cents']}"
    )
    assert_money(grant, "applied_exempt_value_cents", 3333000)


def test_capped_basis_and_exempt_total_after_a_pro_rated_approval(api):
    """PRD §2.7: "The `capped_value_cents` is then the `base_year_value_cents`
    multiplied by the quantity ten thousand plus `assessment_cap_pct_bps` times
    the elapsed-year count, divided by ten thousand, and rounded half up to a
    whole cent." PRD §2.7 continues: "The sum of all absorbed amounts becomes the
    parcel's `exempt_value_cents`, and `taxable_value_cents` is
    `assessed_value_cents` less `exempt_value_cents`."

    Design: Difficulty/combinatorial_formula/benefit_ceiling_applied_before_ownership_proration_nested_min
    """
    world = _coowner_ceiling_world(api)
    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))

    assert_money(parcel, "capped_value_cents", 62400000)
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=62400000,
        exempt_value_cents=3333000,
        taxable_value_cents=59067000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_a_new_parcel_is_published_with_its_decomposition_already_run(api):
    """PRD §3.1: "Creation immediately runs the value decomposition of §2.7 against
    an empty active-grant set, so a new parcel is published with its
    `capped_value_cents` and `assessed_value_cents` computed, `exempt_value_cents`
    at 0, `taxable_value_cents` equal to the assessed basis, and `exemption_status`
    reading `UNEXEMPTED`."

    Design: Corner/entities/parcel_creation_computes_the_full_value_decomposition
    """
    fx.set_clock(api)

    created = validate_success(
        api.create_parcel(f.parcel(), ANALYST), expected_status=201
    )

    assert_common_fields(created)
    assert created["version"] == 1, (
        f"a freshly created row starts at version 1, got {created['version']}"
    )
    # Six elapsed years at 200 basis points grow 30000000 to 33600000, which is
    # below the market value of 40000000 and so controls the assessed basis.
    assert_money(created, "capped_value_cents", 33600000)
    assert_parcel_decomposition(
        created,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )
    assert created["apn"] == "P-0001", f"the assessor number is echoed, got {created['apn']}"
    assert created["county_zone"] == "NORTH", (
        f"the zone is echoed, got {created['county_zone']}"
    )
    assert created["tax_year"] == 2026, (
        f"the published values belong to 2026, got {created['tax_year']}"
    )
    assert created["base_year"] == 2020, (
        f"the base year is echoed, got {created['base_year']}"
    )


def test_reading_a_parcel_returns_the_stored_valuation_and_its_first_version(api):
    """PRD §2.7: the decomposition "is the only writer of `capped_value_cents`,
    `assessed_value_cents`, `exempt_value_cents`, `taxable_value_cents` and
    `exemption_status` on a `Parcel`", and each run "refreshes the parcel's
    `updated_at` and increments the parcel's `version` by exactly 1."

    Design: Corner/entities/parcel_read_returns_the_stored_valuation_and_current_version
    """
    fx.set_clock(api)
    created = fx.create_parcel(api, f.parcel())

    fetched = validate_success(api.get_parcel(created["id"], ANALYST))

    assert fetched["id"] == created["id"], (
        f"the read must return the row that was created, got {fetched['id']}"
    )
    assert_money(fetched, "capped_value_cents", 33600000)
    assert_parcel_decomposition(
        fetched,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )
    assert fetched["version"] == 1, (
        "a read is not a mutation, so the version must still be 1, got "
        f"{fetched['version']}"
    )
    assert fetched["assessed_value_cents"] == created["assessed_value_cents"], (
        "the stored basis must not drift between the create and the read: "
        f"{created['assessed_value_cents']} became {fetched['assessed_value_cents']}"
    )


def test_reading_a_parcel_that_was_never_minted_is_refused_as_not_found(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`", and the error payload carries
    "`error_id`", "a unique, machine-readable string that identifies the specific
    error", together with "`message`", "a human-readable explanation".

    Design: Corner/entities/unknown_parcel_id_on_read_returns_parcel_not_found
    """
    fx.set_clock(api)
    real = fx.create_parcel(api, f.parcel())

    error = validate_error(
        api.get_parcel(NON_EXISTENT_UUID, ANALYST),
        ERR_PARCEL_NOT_FOUND,
        expected_status=404,
    )
    assert set(error) == {"error_id", "message"}, (
        f"an error payload carries nothing but the identifier and message: {error}"
    )

    # The failed lookup neither invented a row nor disturbed the real one.
    still_there = validate_success(api.get_parcel(real["id"], ANALYST))
    assert still_there["version"] == 1, (
        f"the existing parcel is untouched, got version {still_there['version']}"
    )


def test_a_programme_that_omits_its_optional_flags_takes_the_permissive_defaults(api):
    """PRD §3.1: "Four booleans and two ceilings decide how much scrutiny a
    programme carries, and each defaults to the permissive value when omitted.
    `income_limit_cents` ... defaults to null, meaning the programme is not
    income-tested; `asset_limit_cents` ... likewise defaults to null ...
    `requires_income_certification` defaults to false ... `recertification_required`
    defaults to false ... `freeze_enabled` defaults to false". PRD §3.1 adds: "A
    programme is created with `status` set to `OPEN`".

    Design: Corner/entities/relief_program_omitting_optional_flags_applies_declared_defaults
    """
    fx.set_clock(api)
    payload = f.homestead_basic_program()
    for optional in (
        "requires_income_certification",
        "recertification_required",
        "freeze_enabled",
        "income_limit_cents",
        "asset_limit_cents",
    ):
        assert optional not in payload, (
            f"the payload under test must omit {optional} entirely"
        )

    program = validate_success(
        api.create_relief_program(payload, ADMIN), expected_status=201
    )

    assert program["requires_income_certification"] is False, (
        "an omitted certification requirement is false, got "
        f"{program['requires_income_certification']!r}"
    )
    assert program["recertification_required"] is False, (
        "an omitted recertification requirement is false, got "
        f"{program['recertification_required']!r}"
    )
    assert program["freeze_enabled"] is False, (
        f"an omitted freeze flag is false, got {program['freeze_enabled']!r}"
    )
    assert program["income_limit_cents"] is None, (
        "an omitted income ceiling means no income test, got "
        f"{program['income_limit_cents']!r}"
    )
    assert program["asset_limit_cents"] is None, (
        f"an omitted asset ceiling means no asset test, got {program['asset_limit_cents']!r}"
    )
    assert program["status"] == "OPEN", (
        f"a new programme opens for submissions, got {program['status']}"
    )
    assert_common_fields(program)
    assert program["version"] == 1, (
        f"a freshly created programme starts at version 1, got {program['version']}"
    )

    # The read agrees with the create: the defaults were stored, not improvised.
    fetched = validate_success(api.get_relief_program(program["id"], ADMIN))
    assert fetched["freeze_enabled"] is False, (
        f"the stored freeze flag is false, got {fetched['freeze_enabled']!r}"
    )
    assert fetched["income_limit_cents"] is None, (
        f"the stored income ceiling is null, got {fetched['income_limit_cents']!r}"
    )
    assert_bps(fetched, "relief_pct_bps", 2500)


def test_a_programme_code_outside_the_statutory_catalogue_is_refused(api):
    """PRD §3.1: "A `ProgramAdministrator` registers each **relief programme** with
    its `program_code` — one of `HOMESTEAD_BASIC`, `SENIOR_FREEZE`,
    `VETERAN_DISABILITY`, `DISABILITY_INCOME` or `AGRICULTURAL_USE`, unique across
    programmes". PRD §2.6 and §2.5 both route a malformed payload to
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/relief_program_with_an_undeclared_program_code_is_rejected
    """
    fx.set_clock(api)

    validate_error(
        api.create_relief_program(
            f.homestead_basic_program(program_code="SOLAR_CREDIT"), ADMIN
        ),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )

    # Nothing was stored, so the unique priority rank of 10 is still available.
    accepted = validate_success(
        api.create_relief_program(f.homestead_basic_program(), ADMIN),
        expected_status=201,
    )
    assert accepted["program_code"] == "HOMESTEAD_BASIC", (
        f"a declared code is accepted, got {accepted['program_code']}"
    )
    assert accepted["priority_rank"] == 10, (
        "the refused create must not have consumed the rank, got "
        f"{accepted['priority_rank']}"
    )
    assert accepted["status"] == "OPEN", (
        f"the surviving programme is open, got {accepted['status']}"
    )


def test_a_parcel_that_names_no_cap_rate_takes_the_statutory_two_percent(api):
    """PRD §2.7: "The `capped_value_cents` is then the `base_year_value_cents`
    multiplied by the quantity ten thousand plus `assessment_cap_pct_bps` times the
    elapsed-year count, divided by ten thousand, and rounded half up to a whole
    cent ... When `assessment_cap_pct_bps` is omitted at parcel creation it defaults
    to 200, and it may be set anywhere from 0 through 2000 inclusive."

    Design: Corner/calculations/omitted_assessment_cap_falls_back_to_the_declared_default_constant
    """
    fx.set_clock(api)
    payload = {
        key: value
        for key, value in f.parcel().items()
        if key != "assessment_cap_pct_bps"
    }
    assert "assessment_cap_pct_bps" not in payload, (
        "the payload under test must leave the cap rate unstated"
    )

    parcel = validate_success(api.create_parcel(payload, ANALYST), expected_status=201)

    assert_bps(parcel, "assessment_cap_pct_bps", 200)
    # Six elapsed years at 200 bps: 30000000 * 11200 / 10000 = 33600000, which
    # sits below the market value of 40000000 and so sets the assessed basis.
    assert_money(parcel, "capped_value_cents", 33600000)
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )


def test_a_capped_value_landing_on_a_half_cent_rounds_upward(api):
    """PRD §2.7: "The `capped_value_cents` is then the `base_year_value_cents`
    multiplied by the quantity ten thousand plus `assessment_cap_pct_bps` times the
    elapsed-year count, divided by ten thousand, and rounded half up to a whole cent.
    This is the only rounding anywhere in the procedure." PRD §2.7 step two adds:
    "The assessed basis starts as the smaller of the parcel's `market_value_cents`
    and its `capped_value_cents`."

    Design: Corner/calculations/capped_value_rounds_half_up_on_a_trailing_half_cent
    """
    fx.set_clock(api)

    # 20000010 * 10500 / 10000 = 21000010.5 exactly, so half-up gives 21000011.
    parcel = validate_success(
        api.create_parcel(
            f.parcel(
                apn="P-0011",
                situs_address_normalized="1100 HALFCENT WAY NORTHFIELD ST 10011",
                county_zone="EAST",
                base_year=2024,
                base_year_value_cents=20000010,
                market_value_cents=25000000,
                assessment_cap_pct_bps=250,
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    assert_money(parcel, "capped_value_cents", 21000011)
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=21000011,
        exempt_value_cents=0,
        taxable_value_cents=21000011,
        exemption_status="UNEXEMPTED",
    )


def test_the_junior_grant_absorbs_only_what_the_senior_one_left_behind(api):
    """PRD §2.7: "Beginning with the whole `assessed_value_cents` as the remaining
    basis, each grant in turn absorbs the smaller of its own `benefit_amount_cents`
    and the remaining basis. That absorbed figure is written to the grant's
    `applied_exempt_value_cents` and subtracted from the remaining basis. A grant
    whose benefit exceeds what is left absorbs only the remainder". PRD §2.7 step
    four adds: "When the absorbed total equals `assessed_value_cents` exactly, it
    becomes `FULLY_EXEMPT`."

    Design: Corner/calculations/waterfall_absorbs_the_second_grant_only_up_to_the_remaining_basis
    """
    world = fx.waterfall_parcel_world(api)
    parcel_id = world["parcel"]["id"]

    repriced = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert repriced["version"] == 2, (
        f"the first approval is the parcel's second mutation, got {repriced['version']}"
    )

    second_determined = validate_success(
        api.determine_application(
            world["second_application_id"],
            f.approve_determination(repriced["version"]),
            REVIEWER,
        )
    )

    senior = validate_success(api.get_grant(world["first_grant_id"], REVIEWER))
    assert_grant(
        senior,
        benefit_status="ACTIVE",
        benefit_amount_cents=900000,
        applied_exempt_value_cents=900000,
    )

    # 1000000 - 900000 leaves 100000, which is all the rank-40 grant can absorb.
    junior = validate_success(
        api.get_grant(second_determined["resulting_grant_id"], REVIEWER)
    )
    assert_grant(
        junior,
        benefit_status="ACTIVE",
        benefit_amount_cents=500000,
        applied_exempt_value_cents=100000,
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=1000000,
        exempt_value_cents=1000000,
        taxable_value_cents=0,
        exemption_status="FULLY_EXEMPT",
    )
    assert (
        parcel["exempt_value_cents"] + parcel["taxable_value_cents"]
        == parcel["assessed_value_cents"]
    ), (
        "exempt plus taxable must equal assessed after every run: "
        f"{parcel['exempt_value_cents']} + {parcel['taxable_value_cents']} "
        f"!= {parcel['assessed_value_cents']}"
    )
    assert parcel["version"] == 3, (
        f"creation and two approvals are three mutations, got {parcel['version']}"
    )

    rows, meta = validate_paginated(api.list_grants(REVIEWER, parcel_id=parcel_id))
    assert meta["total_count"] == 2, (
        f"the parcel carries both grants, got {meta['total_count']}"
    )
    assert [row["applied_exempt_value_cents"] for row in rows] == [900000, 100000], (
        "the senior grant was minted first and absorbed first, got "
        f"{[row['applied_exempt_value_cents'] for row in rows]}"
    )


def test_a_registered_programme_reads_back_every_declared_parameter_unchanged(api):
    """PRD §3.1: "`relief_pct_bps` is the share of the assessed basis the programme
    exempts before any ceiling ... `max_exempt_value_cents` is the hard ceiling on
    the value one parcel may absorb from this programme ... `priority_rank` places
    the programme in the parcel waterfall ... `statutory_lookback_years` bounds
    retroactive reach ... `penalty_pct_bps` and `interest_pct_bps_per_year` — both
    non-negative — drive the recovery assessment ... A programme is created with
    `status` set to `OPEN`." PRD §2.4: "Every resource also carries `created_at`, an
    ISO 8601 UTC timestamp with three fractional digits (for example
    `2026-08-01T00:00:00.000Z`) recording when the row was first written", and
    "`updated_at` is an ISO 8601 UTC timestamp with three fractional digits,
    refreshed on every mutation of the row."

    Design: Corner/endpoints/relief_program_create_then_read_round_trips_every_declared_field
    """
    fx.set_clock(api)
    payload = f.senior_freeze_program(
        relief_pct_bps=1000,
        max_exempt_value_cents=10000000,
        income_limit_cents=9000000,
        statutory_lookback_years=2,
        penalty_pct_bps=1500,
        interest_pct_bps_per_year=600,
        priority_rank=15,
    )
    assert "asset_limit_cents" not in payload, (
        "the asset ceiling is deliberately omitted so the read must report null"
    )
    assert "recertification_required" not in payload, (
        "the recertification flag is deliberately omitted so the read reports false"
    )

    created = validate_success(
        api.create_relief_program(payload, ADMIN), expected_status=201
    )
    assert created["version"] == 1, (
        f"a freshly registered programme starts at version 1, got {created['version']}"
    )

    programme = validate_success(api.get_relief_program(created["id"], ADMIN))
    assert programme["id"] == created["id"], (
        f"the read must return the programme just registered, got {programme['id']}"
    )
    assert programme["version"] == 1, (
        f"a read is not a mutation, got version {programme['version']}"
    )
    assert programme["program_code"] == "SENIOR_FREEZE", (
        f"the statutory code round-trips, got {programme['program_code']}"
    )
    assert programme["name"] == payload["name"], (
        f"the human-readable name round-trips, got {programme['name']!r}"
    )
    assert programme["freeze_enabled"] is True, (
        f"the supplied freeze flag round-trips, got {programme['freeze_enabled']!r}"
    )
    assert programme["recertification_required"] is False, (
        "an omitted recertification requirement stays false, got "
        f"{programme['recertification_required']!r}"
    )
    assert_bps(programme, "relief_pct_bps", 1000)
    assert_money(programme, "max_exempt_value_cents", 10000000)
    assert_money(programme, "income_limit_cents", 9000000)
    assert programme["asset_limit_cents"] is None, (
        f"the omitted asset ceiling reads back as null, got {programme['asset_limit_cents']!r}"
    )
    assert programme["statutory_lookback_years"] == 2, (
        f"the lookback bound round-trips, got {programme['statutory_lookback_years']}"
    )
    assert_bps(programme, "penalty_pct_bps", 1500)
    assert_bps(programme, "interest_pct_bps_per_year", 600)
    assert programme["priority_rank"] == 15, (
        f"the waterfall rank round-trips, got {programme['priority_rank']}"
    )
    assert programme["status"] == "OPEN", (
        f"a registered programme accepts submissions, got {programme['status']}"
    )
    assert_common_fields(programme)

    # The clock is pinned, so both stamps carry the one instant the row was written.
    assert_instant(programme, "created_at", "2026-08-01T00:00:00.000Z")
    assert_instant(programme, "updated_at", "2026-08-01T00:00:00.000Z")


def test_the_annual_roll_reports_its_counts_and_earns_the_cap_another_year(api):
    """PRD §3.5: "The **annual assessment roll** is the county's yearly sweep, run by
    an `AssessorAnalyst` against a `target_tax_year`. It does three things in order
    and reports how much of each it did, returning the `target_tax_year` alongside a
    `parcels_rolled_count`, a `certifications_lapsed_count`, a
    `grants_suspended_count` and a `grants_lapsed_count`. First, every parcel whose
    `tax_year` is earlier than the target has its `tax_year` set to the target and
    its value decomposition re-run — which is where the assessment cap earns another
    year of growth — with each rolled parcel's `version` incrementing by 1."

    Design: Corner/endpoints/assessment_roll_run_returns_per_category_counts_and_rerolls_the_parcel
    """
    world = fx.approved_homestead_world(api)
    parcel_id = world["parcel"]["id"]
    fx.set_clock(api, "2027-01-02T00:00:00Z")

    run = validate_success(
        api.create_assessment_roll_run(f.assessment_roll_run(2027), ANALYST)
    )

    assert run["target_tax_year"] == 2027, (
        f"the run echoes the year it was aimed at, got {run['target_tax_year']}"
    )
    assert run["parcels_rolled_count"] == 1, (
        f"the single parcel behind the roll is rolled once, got {run['parcels_rolled_count']}"
    )
    assert run["certifications_lapsed_count"] == 0, (
        "no certification exists anywhere, so nothing can go stale, got "
        f"{run['certifications_lapsed_count']}"
    )
    assert run["grants_suspended_count"] == 0, (
        "the programme does not require recertification, so no lapse propagates, got "
        f"{run['grants_suspended_count']}"
    )
    assert run["grants_lapsed_count"] == 0, (
        f"no grant reaches the end of its life here, got {run['grants_lapsed_count']}"
    )

    # 2027 less the 2020 base year is seven years of two percent growth:
    # 30000000 * (10000 + 200 * 7) / 10000 = 34200000, still under the market value.
    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["tax_year"] == 2027, (
        f"the rolled parcel now sits in the target year, got {parcel['tax_year']}"
    )
    assert_money(parcel, "capped_value_cents", 34200000)
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=34200000,
        exempt_value_cents=8400000,
        taxable_value_cents=25800000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert parcel["version"] == 3, (
        "creation, approval and the roll are three mutations, got version "
        f"{parcel['version']}"
    )

    # The roll re-runs the decomposition; it does not recompute the benefit.
    assert_grant(
        validate_success(api.get_grant(world["grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=8400000,
    )
