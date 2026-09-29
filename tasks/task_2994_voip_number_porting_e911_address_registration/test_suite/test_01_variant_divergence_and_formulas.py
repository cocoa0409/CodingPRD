"""Two-variant calculations and the PRD's pinned orders of operation.

Four rules are exercised here, each from a fresh, empty database:

* the PROVISIONAL / FINAL divergence of a 911 fee assessment over one identical
  population of dispatchable locations;
* the REALTIME / DAILY_REVIEW divergence of the toll-fraud risk score over one
  identical burst of call attempts;
* the per-unit-then-sum rounding order of fee proration;
* the surcharge tier keyed on the surcharge-free day subtotal rather than on the
  projected total it helps produce.

Every test rebuilds its own world through the public API, so no test depends on
another test's state or on execution order.
"""
from test_helpers import (
    ANALYST_USER_ID,
    BILLING_USER_ID,
    BILLING_USER_ID_ALT,
    REMITTANCE_SENTINEL,
    ApiErrorId,
    assert_cents,
    assert_cents_equal,
    assert_instant,
    assert_null,
    billable_minutes,
    estimated_base_cents,
    final_amount_cents,
    get_success_data,
    make_account_admin_headers,
    make_billing_admin_headers,
    make_call_attempt_payload,
    make_calling_restriction_payload,
    make_fee_assessment_payload,
    make_platform_admin_headers,
    make_security_analyst_headers,
    projected_day_total_cents,
    prorated_unit_fee_cents,
    provisional_amount_cents,
    rate_cents_per_minute,
    read_account,
    read_device,
    read_jurisdiction,
    run_remittance,
    seed_account,
    seed_device,
    seed_jurisdiction,
    seed_number_block,
    seed_phone_number,
    seed_registration,
    set_clock,
    surcharge_pct,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
)

# ----------------------------------------------------------------------
# Literals shared by the four scenarios
# ----------------------------------------------------------------------
_CLOCK_MONTH_START = "2026-08-01T00:00:00.000Z"
_CLOCK_MID_MONTH = "2026-08-17T10:00:00.000Z"
_CLOCK_ASSESSMENT = "2026-08-20T00:00:00.000Z"
_CLOCK_REMITTANCE = "2026-09-06T00:00:00.000Z"
_CLOCK_CALLING = "2026-08-05T12:00:00.000Z"

_PERIOD = "2026-08"
_MONTHLY_FEE_CENTS = 175
_DAYS_IN_AUGUST = 31
# Unit 1 is anchored on day 1 (31 active days); units 2 and 3 on day 17 (15 each).
_ACTIVE_DAYS = (31, 15, 15)


# ----------------------------------------------------------------------
# Private world builders (module-private on purpose: test_helpers is shared)
# ----------------------------------------------------------------------
def _build_three_unit_fee_world(
    api,
    account_number,
    county_fips,
    npa_nxx,
    macs,
    billing_name="ACME CORP",
    line_numbers=("0101", "0102", "0103"),
    device_types=("BASE_STATION", "HANDSET", "SOFTPHONE"),
    streets=("100 MAIN ST", "200 OAK AVE", "300 PINE ST"),
    units=("", "3B", ""),
    city="OAKLAND",
    postals=("94601", "94602", "94603"),
):
    """One PER_LINE jurisdiction at 175 cents and three number-holding devices.

    Device 1 is registered and verified while the clock reads the first of the
    month; devices 2 and 3 while it reads the seventeenth. The clock is left at
    2026-08-20T00:00:00Z, mid-period, ready for a provisional assessment.
    """
    set_clock(_CLOCK_MONTH_START)
    account = seed_account(
        account_number,
        billing_name=billing_name,
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=False,
        intl_daily_cap_cents=2000,
    )
    jurisdiction = seed_jurisdiction(
        "CA",
        county_fips,
        fee_type="PER_LINE",
        monthly_fee_cents=_MONTHLY_FEE_CENTS,
        remit_day_of_month=5,
    )
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx=npa_nxx,
        total_capacity=20,
        max_concurrent_reservations=5,
    )
    numbers = [
        seed_phone_number(block["id"], line_number) for line_number in line_numbers
    ]

    devices = []
    registrations = []
    for index in range(3):
        if index == 1:
            # Units 2 and 3 are anchored later in the month than unit 1.
            set_clock(_CLOCK_MID_MONTH)
        device = seed_device(
            account["id"],
            macs[index],
            device_type=device_types[index],
            nomadic=False,
            assigned_number_id=numbers[index]["id"],
        )
        registration = seed_registration(
            device["id"],
            jurisdiction["id"],
            account["id"],
            address_line1=streets[index],
            unit=units[index],
            city=city,
            state_code="CA",
            postal_code=postals[index],
        )
        verify_registration(registration["id"], "VERIFIED")
        devices.append(device)
        registrations.append(registration)

    set_clock(_CLOCK_ASSESSMENT)
    return {
        "account": account,
        "jurisdiction": jurisdiction,
        "block": block,
        "numbers": numbers,
        "devices": devices,
        "registrations": registrations,
    }


def _assess_provisional(api, account_id, jurisdiction_id, user_id=BILLING_USER_ID):
    """Assess a mid-period PROVISIONAL fee and return the created row."""
    return validate_success(
        api.create_fee_assessment(
            make_fee_assessment_payload(account_id, jurisdiction_id, _PERIOD),
            make_billing_admin_headers(user_id),
        ),
        201,
    )


def _build_calling_device_world(
    api,
    account_number,
    county_fips,
    npa_nxx,
    mac,
    cap_cents,
    street,
    city,
    postal,
    billing_name="BOREAL LLC",
    line_number="0201",
):
    """One international-enabled account and one settled, number-holding device.

    The device is created while the clock reads 2026-08-01T00:00:00Z and the
    clock is then left at 2026-08-05T12:00:00Z, so the device is older than the
    new-device age and the 1.5 multiplier never applies. It is non-nomadic, so
    the unsettled-nomadism component is always zero.
    """
    set_clock(_CLOCK_MONTH_START)
    account = seed_account(
        account_number,
        billing_name=billing_name,
        service_state_code="CA",
        status="ACTIVE",
        intl_calling_enabled=True,
        intl_daily_cap_cents=cap_cents,
    )
    jurisdiction = seed_jurisdiction(
        "CA",
        county_fips,
        fee_type="PER_LINE",
        monthly_fee_cents=_MONTHLY_FEE_CENTS,
        remit_day_of_month=5,
    )
    block = seed_number_block(
        jurisdiction["id"],
        npa_nxx=npa_nxx,
        total_capacity=20,
        max_concurrent_reservations=5,
    )
    number = seed_phone_number(block["id"], line_number)
    device = seed_device(
        account["id"],
        mac,
        device_type="BASE_STATION",
        nomadic=False,
        assigned_number_id=number["id"],
    )
    registration = seed_registration(
        device["id"],
        jurisdiction["id"],
        account["id"],
        address_line1=street,
        unit="",
        city=city,
        state_code="CA",
        postal_code=postal,
    )
    registration = verify_registration(registration["id"], "VERIFIED")
    set_clock(_CLOCK_CALLING)
    return {
        "account": account,
        "jurisdiction": jurisdiction,
        "block": block,
        "number": number,
        "device": device,
        "registration": registration,
    }


def _place(api, device_id, account_id, e164, country_code, seconds):
    """Place one attempt that is expected to be admitted, returning the row."""
    return validate_success(
        api.create_call_attempt(
            device_id,
            make_call_attempt_payload(
                destination_e164=e164,
                destination_country_code=country_code,
                requested_duration_seconds=seconds,
            ),
            make_account_admin_headers(account_id),
        ),
        201,
    )


def _attempt(api, device_id, account_id, e164, country_code, seconds):
    """Place one attempt and hand back the raw response for error assertions."""
    return api.create_call_attempt(
        device_id,
        make_call_attempt_payload(
            destination_e164=e164,
            destination_country_code=country_code,
            requested_duration_seconds=seconds,
        ),
        make_account_admin_headers(account_id),
    )


# The four-country burst the fraud instance drives: (e164, country code).
_BURST = (
    ("+2348012345678", "234"),
    ("+252612345678", "252"),
    ("+5352345678", "53"),
    ("+447700900123", "44"),
)


# ======================================================================
# dual_variant_calc / fee_assessment_provisional_vs_final_variant_divergence
# ======================================================================
def test_fee_assessment_provisional_vs_final_variant_divergence__provisional_prorates_each_unit(api):
    """The unit's fee is the jurisdiction's `monthly_fee_cents` multiplied by its active days, divided by the days in the month, **rounded half up to whole cents per unit**, and `amount_cents` is the sum of those rounded per-unit figures.

    Three PER_LINE units anchored on the 1st, the 17th and the 17th of a 31-day
    month at 175 cents therefore break down as [175, 85, 85] and total 345.

    Design: Difficulty/dual_variant_calc/fee_assessment_provisional_vs_final_variant_divergence
    """
    world = _build_three_unit_fee_world(
        api,
        "ACCT0001",
        "06001",
        "415555",
        ("AABBCC000001", "AABBCC000002", "AABBCC000003"),
    )

    provisional = _assess_provisional(
        api, world["account"]["id"], world["jurisdiction"]["id"]
    )

    assert provisional["variant"] == "PROVISIONAL"
    assert provisional["unit_basis"] == "PER_LINE"
    assert provisional["billable_units"] == 3
    for entry in provisional["unit_fee_breakdown"]:
        assert_cents(entry, "unit_fee_breakdown entry")
    assert provisional["unit_fee_breakdown"] == [
        prorated_unit_fee_cents(_MONTHLY_FEE_CENTS, days, _DAYS_IN_AUGUST)
        for days in _ACTIVE_DAYS
    ]
    assert provisional["unit_fee_breakdown"] == [175, 85, 85]
    assert_cents_equal(provisional["amount_cents"], 345, "amount_cents")
    assert provisional["amount_cents"] == sum(provisional["unit_fee_breakdown"])
    assert provisional["status"] == "ASSESSED"
    assert provisional["assessed_by_user_id"] == BILLING_USER_ID


def test_fee_assessment_provisional_vs_final_variant_divergence__run_voids_provisional_and_writes_final(api):
    """This is why the same three registrations that yielded 345 cents provisionally yield 525 cents finally, and it is why the run voids the provisional row before writing the final one: the two are alternative charges for the same month, never cumulative ones.

    The remittance run is the only writer of the FINAL variant, so the same
    population of units diverges from 345 to 525 purely on the variant.

    Design: Difficulty/dual_variant_calc/fee_assessment_provisional_vs_final_variant_divergence
    """
    world = _build_three_unit_fee_world(
        api,
        "ACCT0001",
        "06001",
        "415555",
        ("AABBCC000001", "AABBCC000002", "AABBCC000003"),
    )
    account_id = world["account"]["id"]
    jurisdiction_id = world["jurisdiction"]["id"]

    provisional = _assess_provisional(api, account_id, jurisdiction_id)
    assert provisional["variant"] == "PROVISIONAL"
    assert_cents_equal(provisional["amount_cents"], 345, "provisional amount_cents")

    set_clock(_CLOCK_REMITTANCE)
    run_remittance(
        jurisdiction_id,
        _PERIOD,
        headers=make_billing_admin_headers(BILLING_USER_ID_ALT),
    )

    reread = validate_success(
        api.get_fee_assessment(provisional["id"], make_billing_admin_headers()),
        200,
    )
    assert reread["status"] == "VOIDED"
    assert reread["voided_by_user_id"] == REMITTANCE_SENTINEL

    final_rows, _meta = validate_paginated(
        api.list_fee_assessments(
            make_billing_admin_headers(),
            params={
                "account_id": account_id,
                "jurisdiction_id": jurisdiction_id,
                "period_month": _PERIOD,
                "variant": "FINAL",
            },
        )
    )
    assert len(final_rows) == 1
    final_row = final_rows[0]
    assert final_row["variant"] == "FINAL"
    assert final_row["unit_basis"] == "PER_LINE"
    assert final_row["billable_units"] == 3
    assert final_row["unit_fee_breakdown"] == [
        _MONTHLY_FEE_CENTS,
        _MONTHLY_FEE_CENTS,
        _MONTHLY_FEE_CENTS,
    ]
    assert_cents_equal(
        final_row["amount_cents"], final_amount_cents(_MONTHLY_FEE_CENTS, 3), "amount_cents"
    )
    assert_cents_equal(final_row["amount_cents"], 525, "final amount_cents")
    # The two variants are alternatives, never cumulative.
    assert final_row["amount_cents"] != provisional["amount_cents"]
    assert final_row["id"] != provisional["id"]


def test_fee_assessment_provisional_vs_final_variant_divergence__final_row_is_remitted_and_ledgered(api):
    """Second, the run walks every account in ascending `created_at` order, computes the `FINAL` branch for that account in that jurisdiction and period, and for each account that selects at least one billable unit creates a `FeeAssessment` with `variant` `FINAL`, `unit_basis` copied from the jurisdiction, the computed `billable_units`, `unit_fee_breakdown` and `amount_cents`, `assessed_by_user_id` set to `system:remittance-run`, and `status` `ASSESSED` — then immediately drives that same row `ASSESSED → REMITTED` with `remitted_at` set to the logical clock, moving its money out of `pending_fee_cents` and into `remitted_fee_cents`.

    Only the FINAL 525 lands in the jurisdiction's remitted ledger and on the
    account's liability; the voided provisional 345 leaves nothing behind.

    Design: Difficulty/dual_variant_calc/fee_assessment_provisional_vs_final_variant_divergence
    """
    world = _build_three_unit_fee_world(
        api,
        "ACCT0001",
        "06001",
        "415555",
        ("AABBCC000001", "AABBCC000002", "AABBCC000003"),
    )
    account_id = world["account"]["id"]
    jurisdiction_id = world["jurisdiction"]["id"]

    _assess_provisional(api, account_id, jurisdiction_id)

    set_clock(_CLOCK_REMITTANCE)
    run_remittance(
        jurisdiction_id,
        _PERIOD,
        headers=make_billing_admin_headers(BILLING_USER_ID_ALT),
    )

    final_rows, _meta = validate_paginated(
        api.list_fee_assessments(
            make_billing_admin_headers(),
            params={
                "account_id": account_id,
                "jurisdiction_id": jurisdiction_id,
                "period_month": _PERIOD,
                "variant": "FINAL",
            },
        )
    )
    assert len(final_rows) == 1
    final_row = final_rows[0]
    assert final_row["status"] == "REMITTED"
    assert final_row["assessed_by_user_id"] == REMITTANCE_SENTINEL
    assert_instant(final_row["remitted_at"], _CLOCK_REMITTANCE, "remitted_at")

    jurisdiction = read_jurisdiction(jurisdiction_id)
    assert_cents_equal(jurisdiction["pending_fee_cents"], 0, "pending_fee_cents")
    assert_cents_equal(jurisdiction["remitted_fee_cents"], 525, "remitted_fee_cents")

    account = read_account(account_id)
    assert_cents_equal(account["fee_liability_cents"], 525, "fee_liability_cents")


# ======================================================================
# dual_variant_calc / fraud_score_realtime_vs_daily_review_variant_divergence
# ======================================================================
def _build_fraud_world(api):
    """The fraud instance's world: one settled device on an intl-enabled account."""
    return _build_calling_device_world(
        api,
        "ACCT0002",
        "06013",
        "415556",
        "AABBCC000011",
        100000,
        "10 BRIDGE RD",
        "CONCORD",
        "94520",
    )


def test_fraud_score_realtime_vs_daily_review_variant_divergence__realtime_climbs_per_attempt(api):
    """Velocity contributes 4 points per row in the window, capped at 40 — ten rows saturate it.

    Three one-minute international attempts to Nigeria, Somalia and Cuba climb
    the REALTIME score 34, 49, 59 while every one of them stays admitted.

    Design: Difficulty/dual_variant_calc/fraud_score_realtime_vs_daily_review_variant_divergence
    """
    world = _build_fraud_world(api)
    device_id = world["device"]["id"]
    account_id = world["account"]["id"]

    expected_scores = (34, 49, 59)
    for index in range(3):
        e164, country_code = _BURST[index]
        attempt = _place(api, device_id, account_id, e164, country_code, 60)
        assert attempt["decision"] == "ALLOWED", (
            f"attempt {index + 1} to {country_code} should be admitted"
        )
        assert attempt["realtime_risk_score"] == expected_scores[index], (
            f"attempt {index + 1} realtime_risk_score"
        )
        assert attempt["realtime_risk_score"] < 60
        assert_null(attempt["decision_error_id"], "decision_error_id")

    device = read_device(device_id)
    assert device["toll_fraud_score"] == 59
    assert device["fraud_block_count"] == 0
    assert device["calling_status"] == "UNRESTRICTED"


def test_fraud_score_realtime_vs_daily_review_variant_divergence__fourth_attempt_breaches_realtime(api):
    """Spread contributes 6 points for every distinct `destination_country_code` over the rows beyond the first, so one distinct code scores 0 and four distinct codes score 18.

    The fourth distinct country carries the REALTIME score to 69, at or above the
    threshold, and the refused row is still persisted with its score.

    Design: Difficulty/dual_variant_calc/fraud_score_realtime_vs_daily_review_variant_divergence
    """
    world = _build_fraud_world(api)
    device_id = world["device"]["id"]
    account_id = world["account"]["id"]

    for index in range(3):
        e164, country_code = _BURST[index]
        _place(api, device_id, account_id, e164, country_code, 60)

    fourth_e164, fourth_cc = _BURST[3]
    response = _attempt(api, device_id, account_id, fourth_e164, fourth_cc, 60)
    validate_error(response, ApiErrorId.ERR_TOLL_FRAUD_THRESHOLD_BREACHED.value, 409)

    blocked_rows, _meta = validate_paginated(
        api.list_call_attempts(
            device_id,
            make_platform_admin_headers(),
            params={"decision": "BLOCKED_FRAUD"},
        )
    )
    assert len(blocked_rows) == 1
    blocked = blocked_rows[0]
    assert blocked["realtime_risk_score"] == 69
    assert blocked["realtime_risk_score"] >= 60
    assert blocked["decision"] == "BLOCKED_FRAUD"
    assert (
        blocked["decision_error_id"] == ApiErrorId.ERR_TOLL_FRAUD_THRESHOLD_BREACHED.value
    )

    device = read_device(device_id)
    assert device["fraud_block_count"] == 1
    assert device["toll_fraud_score"] == 69


def test_fraud_score_realtime_vs_daily_review_variant_divergence__daily_review_scores_the_same_burst_lower(api):
    """The DAILY_REVIEW variant scores the same device on a deliberately gentler basis, which is the point of having two variants: the same four attempts that score 69 in REALTIME score 49 here.

    The analyst's review discards the BLOCKED_FRAUD row, halves the velocity
    weight and drops the spread weight, so the release is granted at 49.

    Design: Difficulty/dual_variant_calc/fraud_score_realtime_vs_daily_review_variant_divergence
    """
    world = _build_fraud_world(api)
    device_id = world["device"]["id"]
    account_id = world["account"]["id"]

    for index in range(3):
        e164, country_code = _BURST[index]
        _place(api, device_id, account_id, e164, country_code, 60)
    fourth_e164, fourth_cc = _BURST[3]
    validate_error(
        _attempt(api, device_id, account_id, fourth_e164, fourth_cc, 60),
        ApiErrorId.ERR_TOLL_FRAUD_THRESHOLD_BREACHED.value,
        409,
    )
    assert read_device(device_id)["toll_fraud_score"] == 69

    unblocked = get_success_data(
        api.create_calling_restriction(
            device_id,
            make_calling_restriction_payload("REVIEW_UNBLOCK", note="analyst review"),
            make_security_analyst_headers(ANALYST_USER_ID),
        )
    )
    assert unblocked["id"] == device_id

    device = read_device(device_id)
    # The gentler variant is what the release is judged on, and it is stored.
    assert device["toll_fraud_score"] == 49
    assert device["toll_fraud_score"] != 69
    assert device["calling_status"] == "UNRESTRICTED"
    # Fraud and E911 are separate dimensions: the review never touched E911.
    assert device["registration_status"] == "REGISTERED"


# ======================================================================
# combinatorial_formula / fee_proration_rounds_per_unit_before_summing
# ======================================================================
def _build_proration_world(api):
    """The proration instance's world: three units, 31 / 15 / 15 active days."""
    return _build_three_unit_fee_world(
        api,
        "ACCT0003",
        "06075",
        "415557",
        ("AABBCC000021", "AABBCC000022", "AABBCC000023"),
        billing_name="CEDAR INC",
        line_numbers=("0301", "0302", "0303"),
        streets=("1 FIRST ST", "2 SECOND ST", "3 THIRD ST"),
        units=("", "", ""),
        city="SAN FRANCISCO",
        postals=("94105", "94105", "94105"),
    )


def test_fee_proration_rounds_per_unit_before_summing__each_unit_is_rounded_on_its_own(api):
    """The rounding order is pinned and it is not cosmetic: round every unit to whole cents first, then sum.

    The breakdown is the audit trail of that order: three separately rounded
    per-unit figures, one per billable unit, in the order the units were selected.

    Design: Difficulty/combinatorial_formula/fee_proration_rounds_per_unit_before_summing
    """
    world = _build_proration_world(api)

    provisional = _assess_provisional(
        api, world["account"]["id"], world["jurisdiction"]["id"]
    )

    assert provisional["billable_units"] == 3
    assert len(provisional["unit_fee_breakdown"]) == 3
    for entry in provisional["unit_fee_breakdown"]:
        assert_cents(entry, "unit_fee_breakdown entry")
    # 175 * 31 / 31 = 175 exactly; 175 * 15 / 31 = 84.677... -> 85 per unit.
    assert provisional["unit_fee_breakdown"] == [175, 85, 85]
    assert provisional["unit_fee_breakdown"] == [
        prorated_unit_fee_cents(_MONTHLY_FEE_CENTS, days, _DAYS_IN_AUGUST)
        for days in _ACTIVE_DAYS
    ]


def test_fee_proration_rounds_per_unit_before_summing__pinned_order_yields_345_not_344(api):
    """With a `monthly_fee_cents` of 175 over a 31-day month and three units whose active days are 31, 15 and 15, the pinned order yields 345 cents and the rejected order yields 344.

    Summing first and rounding once would give 344, so the total distinguishes
    the two orders, and it is the total that reaches the jurisdiction's ledger.

    Design: Difficulty/combinatorial_formula/fee_proration_rounds_per_unit_before_summing
    """
    world = _build_proration_world(api)
    jurisdiction_id = world["jurisdiction"]["id"]

    provisional = _assess_provisional(api, world["account"]["id"], jurisdiction_id)

    assert_cents_equal(
        provisional["amount_cents"],
        provisional_amount_cents(_MONTHLY_FEE_CENTS, _ACTIVE_DAYS, _DAYS_IN_AUGUST),
        "amount_cents",
    )
    assert_cents_equal(provisional["amount_cents"], 345, "amount_cents")
    # The rejected order — one rounding of 175 * 61 / 31 — would have given 344.
    assert provisional["amount_cents"] != 344

    jurisdiction = read_jurisdiction(jurisdiction_id)
    assert_cents_equal(jurisdiction["pending_fee_cents"], 345, "pending_fee_cents")


# ======================================================================
# combinatorial_formula / intl_surcharge_tier_keyed_on_subtotal_not_projected_total
# ======================================================================
_UK_NUMBERS = ("+447700900001", "+447700900002", "+447700900003")
_UK_COUNTRY_CODE = "44"
_ONE_HOUR_SECONDS = 3600


def _build_surcharge_world(api):
    """The surcharge instance's world: cap pinned at exactly 2268 cents."""
    return _build_calling_device_world(
        api,
        "ACCT0004",
        "06085",
        "415558",
        "AABBCC000031",
        2268,
        "44 CAP WAY",
        "SAN JOSE",
        "95110",
        billing_name="DELTA WORKS",
        line_number="0401",
    )


def test_intl_surcharge_tier_keyed_on_subtotal_not_projected_total__base_carries_no_surcharge(api):
    """`estimated_base_cents` is `rate_cents_per_minute` multiplied by `billable_minutes`, with no surcharge in it.

    One hour to the United Kingdom at 12 cents a minute is 60 billable minutes
    and a base of 720 cents, the surcharge-free ingredient of every subtotal.

    Design: Difficulty/combinatorial_formula/intl_surcharge_tier_keyed_on_subtotal_not_projected_total
    """
    world = _build_surcharge_world(api)

    first = _place(
        api,
        world["device"]["id"],
        world["account"]["id"],
        _UK_NUMBERS[0],
        _UK_COUNTRY_CODE,
        _ONE_HOUR_SECONDS,
    )

    assert first["billable_minutes"] == billable_minutes(_ONE_HOUR_SECONDS)
    assert first["billable_minutes"] == 60
    assert first["rate_cents_per_minute"] == rate_cents_per_minute(_UK_COUNTRY_CODE)
    assert first["rate_cents_per_minute"] == 12
    assert_cents_equal(
        first["estimated_base_cents"],
        estimated_base_cents(_UK_COUNTRY_CODE, _ONE_HOUR_SECONDS),
        "estimated_base_cents",
    )
    assert_cents_equal(first["estimated_base_cents"], 720, "estimated_base_cents")
    assert first["estimated_base_cents"] == 12 * 60


def test_intl_surcharge_tier_keyed_on_subtotal_not_projected_total__subtotal_accumulates_below_the_first_tier(api):
    """For a non-domestic attempt that reaches gate 8, the day subtotal is this attempt's own `estimated_base_cents` plus the sum of `estimated_base_cents` over every call attempt that belongs to *any* device of the same account, whose `created_at` falls inside the clock's UTC calendar day, whose `destination_country_code` is not `1`, and whose `decision` is `ALLOWED`.

    Two hours of allowed international calling accumulate to 1440 cents, still
    under the 2000-cent floor, so no surcharge is applied to either attempt.

    Design: Difficulty/combinatorial_formula/intl_surcharge_tier_keyed_on_subtotal_not_projected_total
    """
    world = _build_surcharge_world(api)
    device_id = world["device"]["id"]
    account_id = world["account"]["id"]

    first = _place(
        api, device_id, account_id, _UK_NUMBERS[0], _UK_COUNTRY_CODE, _ONE_HOUR_SECONDS
    )
    assert_cents_equal(first["day_subtotal_cents"], 720, "day_subtotal_cents")
    assert first["surcharge_pct_applied"] == surcharge_pct(720)
    assert first["surcharge_pct_applied"] == 0
    assert_cents_equal(
        first["projected_day_total_cents"],
        projected_day_total_cents(720),
        "projected_day_total_cents",
    )
    assert_cents_equal(first["projected_day_total_cents"], 720, "projected_day_total_cents")

    second = _place(
        api, device_id, account_id, _UK_NUMBERS[1], _UK_COUNTRY_CODE, _ONE_HOUR_SECONDS
    )
    assert_cents_equal(second["day_subtotal_cents"], 1440, "day_subtotal_cents")
    assert second["surcharge_pct_applied"] == 0
    assert_cents_equal(
        second["projected_day_total_cents"], 1440, "projected_day_total_cents"
    )
    # Below the first tier the projection is the bare subtotal.
    assert second["projected_day_total_cents"] == second["day_subtotal_cents"]


def test_intl_surcharge_tier_keyed_on_subtotal_not_projected_total__tier_reads_the_subtotal_only(api):
    """The tier is keyed on the surcharge-free subtotal and never on the projected total; keying it on the total would make the definition circular.

    The third hour lifts the subtotal to 2160, which selects the 5 percent tier
    and projects 2268 — exactly the cap, so the attempt is still admitted.

    Design: Difficulty/combinatorial_formula/intl_surcharge_tier_keyed_on_subtotal_not_projected_total
    """
    world = _build_surcharge_world(api)
    device_id = world["device"]["id"]
    account_id = world["account"]["id"]

    for index in range(2):
        _place(
            api,
            device_id,
            account_id,
            _UK_NUMBERS[index],
            _UK_COUNTRY_CODE,
            _ONE_HOUR_SECONDS,
        )

    third = _place(
        api, device_id, account_id, _UK_NUMBERS[2], _UK_COUNTRY_CODE, _ONE_HOUR_SECONDS
    )

    assert_cents_equal(third["day_subtotal_cents"], 2160, "day_subtotal_cents")
    assert third["surcharge_pct_applied"] == surcharge_pct(2160)
    assert third["surcharge_pct_applied"] == 5
    assert_cents_equal(
        third["projected_day_total_cents"],
        projected_day_total_cents(2160),
        "projected_day_total_cents",
    )
    assert_cents_equal(third["projected_day_total_cents"], 2268, "projected_day_total_cents")
    # A projection landing exactly on the cap is admitted, not refused.
    assert third["decision"] == "ALLOWED"
    assert_null(third["decision_error_id"], "decision_error_id")
    assert third["realtime_risk_score"] == 17
