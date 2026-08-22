"""Quoting a lease: rent derivation, mobilization pricing and the occupancy calendar."""
from test_helpers import (
    RURAL,
    ApiErrorId,
    assert_lease,
    create_branch,
    create_building_spec,
    create_customer,
    create_lease,
    create_published_configuration,
    create_unit,
    get_unit,
    make_fleet_admin_headers,
    make_leasing_agent_headers,
    setup_dallas_catalog,
    setup_rural_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    CONFIG_2_OFFICE_ADA,
    SPEC_MOB_2460,
    create_lease_payload,
)

RURAL_SITE = "9 County Road 12, Rural TX"


# ─── Rent: two separately rounded lines ──────────────────────────────────────

def test_monthly_base_rate_adds_two_separately_rounded_lines(api):
    """PRD §3.4: "The product of the list rate and those three factors is
    rounded half up to a whole cent, and that is the shell line."
    PRD §3.4: "The **build-out line** amortizes the configuration's
    `config_surcharge_cents` over a thirty-six-month horizon: divide the
    surcharge by 36 and round half up to a whole cent."
    PRD §3.4: "The monthly base rate is the shell line plus the build-out line,
    added **after** each has been rounded on its own; summing the two unrounded
    figures and rounding once at the end is wrong and can differ by a cent."

    PRD §3.4: "When the customer passes, the system snapshots the lessee's
    current `credit_tier` into the lease's own `pinned_credit_tier`."

    Design: Difficulty/combinatorial_formula/monthly_rate_rounds_each_line_before_summing
    """
    ctx = setup_rural_catalog()

    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address=RURAL_SITE, start_date="2026-10-01",
                             term_months=12),
        make_leasing_agent_headers())
    lease = validate_success(response, 201)
    assert_lease(lease)

    assert lease["monthly_base_rate_cents"] == 127_065, (
        f"round-each-line-then-add gives 127065; got "
        f"{lease['monthly_base_rate_cents']}")
    assert lease["monthly_base_rate_cents"] != 127_064, (
        "127064 is the sum-then-round answer, which the PRD rules out")
    assert lease["pinned_credit_tier"] == "GOLD", (
        f"the lessee's tier must be snapshotted onto the lease, got "
        f"{lease['pinned_credit_tier']}")


def test_build_out_line_amortizes_the_configuration_surcharge_over_thirty_six_months(api):
    """PRD §3.2: "The office component charges $420.00 for each private office.
    The restroom component charges $1,750.00 for each restroom."
    PRD §3.4: "The **build-out line** amortizes the configuration's
    `config_surcharge_cents` over a thirty-six-month horizon: divide the
    surcharge by 36 and round half up to a whole cent."
    PRD §3.4: "Months in this business are uniform thirty-day months, so the
    system derives `end_date` by advancing thirty days per contracted month from
    the start date and then stepping back one day — the lease occupies a closed
    interval whose last day is the derived end date."

    Design: Difficulty/combinatorial_formula/monthly_rate_rounds_each_line_before_summing
    """
    ctx = setup_rural_catalog()

    assert ctx["config"]["config_surcharge_cents"] == 452_000, (
        f"Expected the Open Plan build-out to cost 452000 cents, got "
        f"{ctx['config']['config_surcharge_cents']}")

    lease = create_lease(ctx["customer"]["id"], ctx["unit"]["id"],
                         ctx["jurisdiction"]["id"], ctx["config"]["id"],
                         site_address=RURAL_SITE, start_date="2026-10-01",
                         term_months=12)

    # 452000 / 36 = 12555.55… which rounds half up to 12556; the shell line is
    # 118050 * 1.00 * 1.00 * 0.97 = 114508.5 which rounds half up to 114509.
    assert lease["monthly_base_rate_cents"] == 114_509 + 12_556, (
        f"Expected the two rounded lines to add to 127065, got "
        f"{lease['monthly_base_rate_cents']}")
    assert lease["end_date"] == "2027-09-25", (
        f"Expected a 12-month term from 2026-10-01 to end on 2027-09-25, got "
        f"{lease['end_date']}")


# ─── Mobilization: the tier reads the transport subtotal ─────────────────────

def test_mobilization_discount_tier_reads_the_transport_subtotal_alone(api):
    """PRD §3.4: "First the system forms a transport subtotal: the model's
    `delivery_base_cents` plus its `install_base_cents` plus the anchoring
    allowance dictated by the jurisdiction's `anchoring_standard`, which
    contributes nothing for `NONE`, $850.00 for `GROUND_ANCHOR`, $2,400.00 for
    `PIER_FOUNDATION`, and $6,100.00 for `ENGINEERED_SLAB`."
    PRD §3.4: "Second — and this is the pinned part — the volume discount tier
    is selected by looking at **that subtotal alone**, never at the lease's
    grand total, which already contains the fee: no discount when the subtotal
    is below $3,000.00, five percent when it is at or above $3,000.00 but below
    $8,000.00, and nine percent when it is at or above $8,000.00."

    Design: Difficulty/combinatorial_formula/mobilization_discount_tier_keyed_on_presale_subtotal
    """
    ctx = setup_rural_catalog()

    lease = create_lease(ctx["customer"]["id"], ctx["unit"]["id"],
                         ctx["jurisdiction"]["id"], ctx["config"]["id"],
                         site_address=RURAL_SITE, start_date="2026-10-01",
                         term_months=12)

    # 165000 + 120000 + 85000 = 370000, which sits in the five-percent band.
    assert lease["mobilization_fee_cents"] == 351_500, (
        f"Expected a 5% discount off the 370000 subtotal, got "
        f"{lease['mobilization_fee_cents']}")
    assert lease["mobilization_fee_cents"] != 336_700, (
        "336700 is what keying the tier off the grand total would give, which "
        "the PRD rules out")


def test_quoted_total_projects_the_full_term_on_the_subtotal_keyed_fee(api):
    """PRD §3.4: "Finally the system projects `quoted_total_cents`, the
    forward-looking value of the deal as signed: the mobilization fee plus the
    sum of the monthly base rate and the monthly accessory rate, multiplied by
    the contracted `term_months`."
    PRD §3.4: "Second — and this is the pinned part — the volume discount tier
    is selected by looking at **that subtotal alone**, never at the lease's
    grand total, which already contains the fee: no discount when the subtotal
    is below $3,000.00, five percent when it is at or above $3,000.00 but below
    $8,000.00, and nine percent when it is at or above $8,000.00."

    Design: Difficulty/combinatorial_formula/mobilization_discount_tier_keyed_on_presale_subtotal
    """
    ctx = setup_rural_catalog()

    lease = create_lease(ctx["customer"]["id"], ctx["unit"]["id"],
                         ctx["jurisdiction"]["id"], ctx["config"]["id"],
                         site_address=RURAL_SITE, start_date="2026-10-01",
                         term_months=12)

    assert lease["quoted_total_cents"] == RURAL["QUOTED_TOTAL_CENTS"], (
        f"Expected 351500 + 127065 * 12 = 1876280, got "
        f"{lease['quoted_total_cents']}")
    assert lease["quoted_total_cents"] != 1_861_480, (
        "1861480 is the grand-total-keyed variant the PRD rules out")
    assert lease["monthly_accessory_rate_cents"] == 0, (
        "no accessory package is attached yet, so the projection covers shell "
        "and build-out only")


# ─── The occupancy calendar and its fourteen-day refurbishment buffer ────────

def test_booking_exactly_fourteen_days_after_an_existing_end_is_rejected(api):
    """PRD §3.4: "Between two consecutive tenancies the yard needs a
    refurbishment window, so each existing interval is treated as if it were
    widened by fourteen days at each end."
    PRD §3.4: "A candidate interval is therefore rejected with
    `ERR_UNIT_OCCUPANCY_CONFLICT` whenever its first day falls on or before
    fourteen days after an existing interval's last day **and** its last day
    falls on or after fourteen days before that existing interval's first day."

    Design: Difficulty/resource_temporal_overlap/unit_occupancy_buffer_rejects_start_exactly_fourteen_days_after_end
    """
    ctx = setup_dallas_catalog(customer_overrides={"credit_limit_cents": 9_000_000})
    incumbent = create_lease(
        ctx["customer"]["id"], ctx["unit"]["id"], ctx["jurisdiction"]["id"],
        ctx["config"]["id"], site_address="400 Commerce St, Dallas TX",
        start_date="2026-09-01", term_months=12)
    assert incumbent["end_date"] == "2027-08-26", (
        f"Expected the incumbent to end on 2027-08-26, got {incumbent['end_date']}")

    # 2027-09-09 is exactly fourteen days after the incumbent's last day.
    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address="600 Elm St, Dallas TX",
                             start_date="2027-09-09", term_months=12),
        make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_UNIT_OCCUPANCY_CONFLICT.value)

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the rejected booking must not persist a lease, got {meta['total_count']}")


def test_booking_fifteen_days_after_an_existing_end_is_accepted(api):
    """PRD §3.4: "A candidate interval is therefore rejected with
    `ERR_UNIT_OCCUPANCY_CONFLICT` whenever its first day falls on or before
    fourteen days after an existing interval's last day **and** its last day
    falls on or after fourteen days before that existing interval's first day."
    PRD §3.4: "In the same operation, a unit that is currently `IN_FLEET` and
    whose custody branch is `OPERATIONAL` is taken `IN_FLEET → RESERVED`; a unit
    already `RESERVED`, `IN_TRANSIT`, `ON_LEASE` or `RETURNED` is being booked
    forward and keeps the status it has."

    Design: Difficulty/resource_temporal_overlap/unit_occupancy_buffer_rejects_start_exactly_fourteen_days_after_end
    """
    ctx = setup_dallas_catalog(customer_overrides={"credit_limit_cents": 9_000_000})
    incumbent = create_lease(
        ctx["customer"]["id"], ctx["unit"]["id"], ctx["jurisdiction"]["id"],
        ctx["config"]["id"], site_address="400 Commerce St, Dallas TX",
        start_date="2026-09-01", term_months=12)
    assert incumbent["end_date"] == "2027-08-26"

    # 2027-09-10 is fifteen days after the incumbent's last day — clear of the
    # widened interval.
    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address="600 Elm St, Dallas TX",
                             start_date="2027-09-10", term_months=12),
        make_leasing_agent_headers())
    successor = validate_success(response, 201)
    assert successor["start_date"] == "2027-09-10"
    assert successor["end_date"] == "2028-09-03", (
        f"Expected a 12-month term from 2027-09-10 to end on 2028-09-03, got "
        f"{successor['end_date']}")
    assert successor["occupancy_status"] == "PENDING"

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "RESERVED", (
        f"a forward booking on an already RESERVED unit keeps its status, got "
        f"{unit['status']}")

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 2, (
        f"Expected both leases on the unit, got {meta['total_count']}")


# ─── Corner coverage ─────────────────────────────────────────────────────────

def test_new_lease_starts_pending_unbilled_with_a_zero_ledger(api):
    """PRD §3.4: "A newly quoted lease is `PENDING` on its `occupancy_status`
    axis and `UNBILLED` on its `billing_status` axis, with `extends_lease_id`,
    `actual_vacated_date` and `final_settlement_cents` all null, and with
    `monthly_accessory_rate_cents`, `relocation_surcharge_cents`,
    `billed_to_date_cents`, `credited_cents` and `assessment_round` all at
    zero."
    PRD §3.4: "In the same operation, a unit that is currently `IN_FLEET` and
    whose custody branch is `OPERATIONAL` is taken `IN_FLEET → RESERVED`; a unit
    already `RESERVED`, `IN_TRANSIT`, `ON_LEASE` or `RETURNED` is being booked
    forward and keeps the status it has."

    PRD §3.4: "A new customer starts with `outstanding_balance_cents` at 0 and
    `credit_hold` at false; from then on both are derived rather than set,
    exactly as §2.11 describes."

    Design: Corner/state_machines/new_lease_starts_pending_and_unbilled_with_zero_ledger
    """
    ctx = setup_rural_catalog()

    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address=RURAL_SITE, start_date="2026-10-01",
                             term_months=12),
        make_leasing_agent_headers())
    lease = validate_success(response, 201)
    assert_lease(lease)

    assert lease["occupancy_status"] == "PENDING", (
        f"Expected PENDING occupancy, got {lease['occupancy_status']}")
    assert lease["billing_status"] == "UNBILLED", (
        f"Expected UNBILLED billing, got {lease['billing_status']}")
    assert lease["billed_to_date_cents"] == 0
    assert lease["credited_cents"] == 0
    assert lease["relocation_surcharge_cents"] == 0
    assert lease["assessment_round"] == 0
    assert lease["final_settlement_cents"] is None, (
        f"Expected final_settlement_cents null, got {lease['final_settlement_cents']}")
    assert lease["extends_lease_id"] is None, (
        f"Expected extends_lease_id null, got {lease['extends_lease_id']}")
    assert lease["actual_vacated_date"] is None

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "RESERVED", (
        f"quoting must reserve the IN_FLEET unit, got {unit['status']}")
    customer = validate_success(
        api.get_customer(ctx["customer"]["id"], make_leasing_agent_headers()))
    assert customer["outstanding_balance_cents"] == 0, (
        "quoting charges nothing, so exposure stays at zero")


def test_lease_without_a_start_date_is_rejected_and_reserves_nothing(api):
    """PRD §3.4: "A `LeasingAgent` supplies the `customer_id` of the lessee, the
    `unit_id` of the physical building, the `jurisdiction_id` of the permitting
    authority governing the site, the `floorplan_configuration_id` of the
    interior build-out, the delivery `site_address`, the `start_date` as the
    first occupied calendar day in `yyyy-mm-dd` form, and the `term_months` of
    the contracted term, which must be at least 1."
    PRD §2.9: "**Body shape.** Required fields present, enum members legal,
    numeric fields inside their declared ranges, dates parsing as `yyyy-mm-dd`,
    and the two conditional logistics fields supplied exactly when they are due
    — `destination_branch_id` present for a teardown-and-return job and absent
    otherwise, `new_site_address` present for a relocation job and absent
    otherwise. Failure is `ERR_INVALID_REQUEST` with HTTP 422."

    Design: Corner/entities/create_lease_missing_required_start_date_returns_invalid_request
    """
    ctx = setup_rural_catalog()

    payload = create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                                   ctx["jurisdiction"]["id"], ctx["config"]["id"],
                                   site_address=RURAL_SITE, term_months=12)
    payload.pop("start_date")
    response = api.create_lease(payload, make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_FLEET", (
        f"the rejected quote must not reserve the unit, got {unit['status']}")
    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the rejected quote must not persist a lease, got {meta['total_count']}")


def test_term_factor_switches_between_eleven_and_twelve_months(api):
    """PRD §3.4: "The first is a term factor rewarding commitment: 1.25 when
    `term_months` is 5 or fewer, 1.10 when it is between 6 and 11 inclusive,
    1.00 when it is between 12 and 23 inclusive, and 0.92 when it is 24 or
    more."
    PRD §3.4: "Finally the system projects `quoted_total_cents`, the
    forward-looking value of the deal as signed: the mobilization fee plus the
    sum of the monthly base rate and the monthly accessory rate, multiplied by
    the contracted `term_months`."

    PRD §3.4: "Rent is then derived into `monthly_base_rate_cents` as the sum of
    two separately rounded lines. The **shell line** starts from the model's
    `base_monthly_rate_cents` and applies three multipliers in one product."
    PRD §3.4: "The second is a wind-exposure factor read from the jurisdiction's
    `wind_zone`: 1.00 in zone 1, 1.15 in zone 2, 1.35 in zone 3, and 1.60 in
    zone 4."
    PRD §3.4: "The third is a credit factor equal to one minus the discount
    earned by the lease's `pinned_credit_tier`, where `PLATINUM` earns a
    discount of 0.06, `GOLD` earns 0.03, and both `STANDARD` and `WATCH` earn
    nothing at all."
    PRD §3.4: "The **build-out line** amortizes the configuration's
    `config_surcharge_cents` over a thirty-six-month horizon: divide the
    surcharge by 36 and round half up to a whole cent."

    Design: Corner/calculations/term_factor_switches_between_eleven_and_twelve_months
    """
    ctx = setup_rural_catalog(unit_count=2)

    eleven = create_lease(ctx["customer"]["id"], ctx["units"][0]["id"],
                          ctx["jurisdiction"]["id"], ctx["config"]["id"],
                          site_address="1 Rig Road, Rural TX",
                          start_date="2026-10-01", term_months=11)
    twelve = create_lease(ctx["customer"]["id"], ctx["units"][1]["id"],
                          ctx["jurisdiction"]["id"], ctx["config"]["id"],
                          site_address="2 Rig Road, Rural TX",
                          start_date="2026-10-01", term_months=12)

    assert eleven["monthly_base_rate_cents"] == 138_515, (
        f"an 11-month term earns the 1.10 factor, expected 138515, got "
        f"{eleven['monthly_base_rate_cents']}")
    assert twelve["monthly_base_rate_cents"] == 127_065, (
        f"a 12-month term earns the 1.00 factor, expected 127065, got "
        f"{twelve['monthly_base_rate_cents']}")
    assert eleven["quoted_total_cents"] == 1_875_165, (
        f"Expected 351500 + 138515 * 11 = 1875165, got "
        f"{eleven['quoted_total_cents']}")
    assert twelve["quoted_total_cents"] == 1_876_280, (
        f"Expected 351500 + 127065 * 12 = 1876280, got "
        f"{twelve['quoted_total_cents']}")


def test_mobilization_tier_is_zero_below_the_three_thousand_dollar_floor(api):
    """PRD §3.4: "Second — and this is the pinned part — the volume discount
    tier is selected by looking at **that subtotal alone**, never at the lease's
    grand total, which already contains the fee: no discount when the subtotal
    is below $3,000.00, five percent when it is at or above $3,000.00 but below
    $8,000.00, and nine percent when it is at or above $8,000.00."
    PRD §3.4: "Third, the discount amount is the subtotal multiplied by the
    selected percentage, rounded half up to a whole cent. Fourth, the
    mobilization fee is the subtotal minus that discount."

    Design: Corner/calculations/mobilization_tier_is_zero_below_the_three_hundred_thousand_floor
    """
    branch = create_branch()
    no_anchor = validate_success(api.create_jurisdiction(
        {"code": "TX-NONE", "name": "No Anchor County", "permit_required": False,
         "permit_lead_days": 0, "anchoring_standard": "NONE", "wind_zone": 1,
         "permit_fee_cents": 0, "ada_ramp_required": False,
         "min_ramp_run_ratio": 12.0},
        make_fleet_admin_headers()), 201)
    ground_anchor = validate_success(api.create_jurisdiction(
        {"code": "TX-GA", "name": "Ground Anchor County", "permit_required": False,
         "permit_lead_days": 0, "anchoring_standard": "GROUND_ANCHOR",
         "wind_zone": 1, "permit_fee_cents": 0, "ada_ramp_required": False,
         "min_ramp_run_ratio": 12.0},
        make_fleet_admin_headers()), 201)

    spec = create_building_spec(
        model_code="MOB-1240", width_ft=12, length_ft=40, sections=1,
        floor_height_in=24, base_monthly_rate_cents=90_000,
        delivery_base_cents=120_000, install_base_cents=95_000,
        replacement_value_cents=4_000_000, max_occupancy=8)
    config = create_published_configuration(
        spec["id"], name="Bare Shell", private_offices=0, restrooms=0,
        partition_linear_ft=0, hvac_tons=0)
    assert config["config_surcharge_cents"] == 0, (
        f"a bare shell has no build-out cost, got {config['config_surcharge_cents']}")

    unit_a = create_unit(spec["id"], branch["id"], serial_number="MSU-3001")
    unit_b = create_unit(spec["id"], branch["id"], serial_number="MSU-3002")
    customer = create_customer(name="Trench Co", billing_email="ap@trench.test",
                               credit_tier="STANDARD", credit_limit_cents=9_000_000)

    lease_none = create_lease(customer["id"], unit_a["id"], no_anchor["id"],
                              config["id"], site_address="1 Flat Road",
                              start_date="2026-10-01", term_months=12)
    lease_ga = create_lease(customer["id"], unit_b["id"], ground_anchor["id"],
                            config["id"], site_address="2 Flat Road",
                            start_date="2026-10-01", term_months=12)

    assert lease_none["mobilization_fee_cents"] == 215_000, (
        f"a 215000 subtotal sits below the floor and earns no discount, got "
        f"{lease_none['mobilization_fee_cents']}")
    assert lease_ga["mobilization_fee_cents"] == 285_000, (
        f"a 300000 subtotal is at the floor inclusive and earns 5%, got "
        f"{lease_ga['mobilization_fee_cents']}")
    assert lease_none["monthly_base_rate_cents"] == 90_000
    assert lease_ga["monthly_base_rate_cents"] == 90_000
    assert lease_none["quoted_total_cents"] == 1_295_000
    assert lease_ga["quoted_total_cents"] == 1_365_000


def test_lease_naming_a_draft_configuration_is_rejected(api):
    """PRD §3.4: "The configuration named on the lease must be `PUBLISHED`, or
    the request is rejected with `ERR_CONFIG_NOT_PUBLISHED`."
    PRD §3.2: "A configuration is born in `DRAFT`, recorded in its `status`, and
    only a `PUBLISHED` configuration may be named by a new lease."

    Design: Corner/validations/lease_on_a_draft_configuration_is_rejected
    """
    ctx = setup_rural_catalog(publish=False)

    payload = create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                                   ctx["jurisdiction"]["id"], ctx["config"]["id"],
                                   site_address=RURAL_SITE,
                                   start_date="2026-10-01", term_months=12)
    validate_error(api.create_lease(payload, make_leasing_agent_headers()),
                   ApiErrorId.ERR_CONFIG_NOT_PUBLISHED.value)

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_FLEET", (
        f"the rejected quote must leave the unit IN_FLEET, got {unit['status']}")

    validate_success(api.publish_floorplan_configuration(
        ctx["config"]["id"], make_fleet_admin_headers()))
    lease = validate_success(
        api.create_lease(payload, make_leasing_agent_headers()), 201)
    assert lease["monthly_base_rate_cents"] == RURAL["MONTHLY_BASE_RATE_CENTS"]
    assert get_unit(ctx["unit"]["id"])["status"] == "RESERVED"


def test_lease_pairing_a_unit_with_another_models_configuration_is_rejected(api):
    """PRD §3.4: "The configuration must have been cut against the same model
    the unit actually is — the configuration's `building_spec_id` and the unit's
    `building_spec_id` must agree — or the request is rejected with
    `ERR_ENTITY_LINK_MISMATCH`."

    Design: Corner/validations/lease_configuration_from_another_building_spec_is_rejected
    """
    ctx = setup_rural_catalog()
    other_spec = create_building_spec(**SPEC_MOB_2460)
    other_config = create_published_configuration(
        other_spec["id"], **CONFIG_2_OFFICE_ADA)

    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], other_config["id"],
                             site_address=RURAL_SITE, start_date="2026-10-01",
                             term_months=12),
        make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_ENTITY_LINK_MISMATCH.value)

    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "IN_FLEET", (
        f"the mismatched quote must leave the unit IN_FLEET, got {unit['status']}")
    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the mismatched quote must not persist a lease, got {meta['total_count']}")
