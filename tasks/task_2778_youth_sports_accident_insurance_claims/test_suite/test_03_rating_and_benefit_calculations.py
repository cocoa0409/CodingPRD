"""Rating and benefit arithmetic: repricing ceilings, volume bands and timeliness.

Three separate calculations in the program turn on where a rounding or a
comparison happens rather than on which rows exist: the two ceilings that squeeze
a provider charge down to an allowed amount, the per-band build-up of a term's
premium, and the calendar-day count that decides whether an injury was reported
in time. Each is pinned here against exact integer cents, exact basis points and
exact day counts.
"""
from test_helpers import (
    assert_claim,
    assert_injury_report,
    assert_league_policy,
    assert_provider_bill,
    canonical_iso,
    create_league,
    create_league_policy_payload,
    create_injury_report_payload,
    create_sport_classification,
    make_claims_examiner_headers,
    make_league_admin_headers,
    make_program_admin_headers,
    read_claim,
    read_injury_report,
    record_provider_bill,
    schedule_activity,
    set_clock,
    setup_enrolled_athlete,
    setup_verified_claim,
    validate_success,
)


def test_out_of_network_charges_are_squeezed_by_the_one_hundred_forty_percent_multiplier_and_the_scheduled_cap(api):
    """PRD §3.7: "`negotiated_amount_cents` branches on the network status."
    PRD §3.7: "For an out-of-network provider the program is willing to go above its own fee schedule but not without limit: take the fee-schedule amount, multiply by 14000 basis points — one hundred and forty percent — divide by ten thousand and round half up to whole cents, then take the smaller of the billed charge and that number."
    PRD §3.7: "`scheduled_cap_cents` is the benefit schedule's cap for this service category, adjusted for how badly the athlete was hurt."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`balance_billed_cents` is the billed charge less the allowed amount, floored at zero."
    PRD §3.7: "For an out-of-network provider it is the balance billed, but capped at 15,000 cents (one hundred and fifty dollars); anything beyond that cap is the provider's problem, not the family's."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "Alongside it, `balance_billed_total_cents` is the sum of `balance_billed_cents` and `family_responsibility_total_cents` the sum of `family_responsibility_cents` across the same set of bills — the latter being the balance-protection figure the family is shown."
    PRD §3.7: "That advance happens on the **first** successful reprice on any bill of the claim and is independent of where the coordination axis has got to."
    PRD §2.5: "Wherever a calculation in §3 produces a non-integral number of cents or basis points, the result is rounded **half up** to the nearest whole unit at exactly the point the calculation names — never earlier and never later."

    Design: Corner/calculations/out_of_network_allowed_amount_uses_one_hundred_forty_percent_of_fee_schedule
    """
    bundle = setup_verified_claim(
        league_overrides={
            "name": "Oakhaven Baseball",
            "league_code": "OHB-120",
            "state_code": "MD",
            "contact_email": "admin@ohb.example",
        },
        report_overrides={
            "body_part": "KNEE",
            "injury_description": "twisted knee rounding second base",
            "severity_tier": "MODERATE",
        },
    )
    claim_id = bundle["claim"]["id"]

    # The imaging cap is 300000 cents on this sport; a MODERATE injury carries a
    # severity factor of 10000 basis points, so the cap stays at 300000.
    assert bundle["sport_classification"]["service_category_caps"]["DIAGNOSTIC_IMAGING"] == 300000
    assert bundle["injury_report"]["severity_tier"] == "MODERATE"

    bill_low = record_provider_bill(
        claim_id,
        provider_npi="1811223349",
        provider_name="Oakhaven Imaging Partners",
        network_status="OUT_OF_NETWORK",
        service_category="DIAGNOSTIC_IMAGING",
        service_date="2026-07-11",
        billed_charge_cents=480000,
        fee_schedule_amount_cents=200000,
    )
    bill_high = record_provider_bill(
        claim_id,
        provider_npi="1811223349",
        provider_name="Oakhaven Imaging Partners",
        network_status="OUT_OF_NETWORK",
        service_category="DIAGNOSTIC_IMAGING",
        service_date="2026-07-11",
        billed_charge_cents=480000,
        fee_schedule_amount_cents=260000,
    )

    # 200000 * 14000 / 10000 = 280000, which sits below the 300000 cap, so the
    # multiplier is what binds this charge.
    low = validate_success(api.reprice_provider_bill(bill_low["id"], make_claims_examiner_headers()))
    assert_provider_bill(low)
    assert low["status"] == "REPRICED", (
        f"a successful reprice moves the bill to REPRICED, got {low['status']}"
    )
    assert low["negotiated_amount_cents"] == 280000, (
        "the out-of-network negotiated amount is the smaller of the 480000 billed "
        "charge and 140 percent of the 200000 fee schedule, got "
        f"{low['negotiated_amount_cents']}"
    )
    assert low["scheduled_cap_cents"] == 300000, (
        "a MODERATE injury leaves the 300000-cent imaging cap untouched, got "
        f"{low['scheduled_cap_cents']}"
    )
    assert low["allowed_amount_cents"] == 280000, (
        "the allowed amount is the smaller of the 280000 negotiated amount and the "
        f"300000 cap, got {low['allowed_amount_cents']}"
    )
    assert low["balance_billed_cents"] == 200000, (
        "the balance billed is 480000 less the 280000 allowed, got "
        f"{low['balance_billed_cents']}"
    )
    assert low["family_responsibility_cents"] == 15000, (
        "an out-of-network balance of 200000 is capped at 15000 cents before it "
        f"reaches the family, got {low['family_responsibility_cents']}"
    )

    # 260000 * 14000 / 10000 = 364000, which overshoots the 300000 cap, so this
    # time the severity-adjusted benefit schedule is what binds.
    high = validate_success(api.reprice_provider_bill(bill_high["id"], make_claims_examiner_headers()))
    assert_provider_bill(high)
    assert high["status"] == "REPRICED"
    assert high["negotiated_amount_cents"] == 364000, (
        "the out-of-network negotiated amount is 140 percent of the 260000 fee "
        f"schedule, still under the 480000 billed charge, got {high['negotiated_amount_cents']}"
    )
    assert high["scheduled_cap_cents"] == 300000
    assert high["allowed_amount_cents"] == 300000, (
        "the allowed amount is clamped to the 300000 scheduled cap because the "
        f"negotiated amount of 364000 exceeds it, got {high['allowed_amount_cents']}"
    )
    assert high["balance_billed_cents"] == 180000, (
        f"the balance billed is 480000 less the 300000 allowed, got {high['balance_billed_cents']}"
    )
    assert high["family_responsibility_cents"] == 15000, (
        "an out-of-network balance of 180000 is capped at 15000 cents before it "
        f"reaches the family, got {high['family_responsibility_cents']}"
    )

    claim = read_claim(claim_id)
    assert_claim(claim)
    assert claim["allowed_amount_total_cents"] == 580000, (
        "the claim's allowed-amount total is 280000 plus 300000 across the two "
        f"REPRICED charges, got {claim['allowed_amount_total_cents']}"
    )
    assert claim["balance_billed_total_cents"] == 380000, (
        f"the balance-billed total is 200000 plus 180000, got {claim['balance_billed_total_cents']}"
    )
    assert claim["family_responsibility_total_cents"] == 30000, (
        "the family's protected share is 15000 on each of the two out-of-network "
        f"charges, got {claim['family_responsibility_total_cents']}"
    )
    assert claim["adjudication_status"] == "UNDER_ADJUDICATION", (
        "the first successful reprice on any bill of the claim drives the "
        f"adjudication axis out of PENDING_COORDINATION, got {claim['adjudication_status']}"
    )
    assert claim["coordination_status"] == "NOT_STARTED", (
        "the reprice advance is independent of the coordination axis, which is "
        f"still NOT_STARTED, got {claim['coordination_status']}"
    )


def test_in_network_charges_track_the_scheduled_cap_below_it_and_clamp_to_it_one_cent_above(api):
    """PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "`scheduled_cap_cents` is the benefit schedule's cap for this service category, adjusted for how badly the athlete was hurt."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`balance_billed_cents` is the billed charge less the allowed amount, floored at zero."
    PRD §3.7: "For an in-network provider it is **always exactly zero** — a participating provider may bill the family nothing above the allowed amount."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "Alongside it, `balance_billed_total_cents` is the sum of `balance_billed_cents` and `family_responsibility_total_cents` the sum of `family_responsibility_cents` across the same set of bills — the latter being the balance-protection figure the family is shown."

    Design: Corner/calculations/allowed_amount_at_and_one_cent_above_the_scheduled_cap
    """
    bundle = setup_verified_claim(
        league_overrides={
            "name": "Pinehurst Baseball",
            "league_code": "PHB-121",
            "state_code": "SC",
            "contact_email": "admin@phb.example",
        },
        report_overrides={
            "body_part": "HIP_GROIN",
            "injury_description": "hip flexor strain sprinting to first",
            "severity_tier": "MODERATE",
        },
    )
    claim_id = bundle["claim"]["id"]
    assert bundle["sport_classification"]["service_category_caps"]["DIAGNOSTIC_IMAGING"] == 300000

    def record_imaging_charge(fee_schedule_amount_cents):
        return record_provider_bill(
            claim_id,
            provider_npi="1922334455",
            provider_name="Pinehurst Radiology",
            network_status="IN_NETWORK",
            service_category="DIAGNOSTIC_IMAGING",
            service_date="2026-07-11",
            billed_charge_cents=480000,
            fee_schedule_amount_cents=fee_schedule_amount_cents,
        )

    bill_below = record_imaging_charge(299999)
    bill_at = record_imaging_charge(300000)
    bill_above = record_imaging_charge(300001)

    examiner = make_claims_examiner_headers()
    below = validate_success(api.reprice_provider_bill(bill_below["id"], examiner))
    at_cap = validate_success(api.reprice_provider_bill(bill_at["id"], examiner))
    above = validate_success(api.reprice_provider_bill(bill_above["id"], examiner))
    for bill in (below, at_cap, above):
        assert_provider_bill(bill)
        assert bill["scheduled_cap_cents"] == 300000, (
            "a MODERATE injury leaves the 300000-cent imaging cap untouched, got "
            f"{bill['scheduled_cap_cents']}"
        )
        assert bill["family_responsibility_cents"] == 0, (
            "an in-network provider may bill the family nothing above the allowed "
            f"amount, got {bill['family_responsibility_cents']}"
        )

    # One cent under the cap: the negotiated amount is the smaller of the two.
    assert below["negotiated_amount_cents"] == 299999, (
        "the in-network negotiated amount is the smaller of the 480000 billed "
        f"charge and the 299999 fee schedule, got {below['negotiated_amount_cents']}"
    )
    assert below["allowed_amount_cents"] == 299999, (
        "one cent under the cap the allowed amount still tracks the negotiated "
        f"amount, got {below['allowed_amount_cents']}"
    )
    assert below["balance_billed_cents"] == 180001, (
        f"the balance billed is 480000 less the 299999 allowed, got {below['balance_billed_cents']}"
    )

    # Exactly at the cap: the two candidates are equal, so the allowed amount is
    # the cap and no cent is lost to a strict comparison.
    assert at_cap["negotiated_amount_cents"] == 300000, (
        f"the in-network negotiated amount is the 300000 fee schedule, got {at_cap['negotiated_amount_cents']}"
    )
    assert at_cap["allowed_amount_cents"] == 300000, (
        "at the cap the allowed amount equals the cap rather than being shaved by a "
        f"cent, got {at_cap['allowed_amount_cents']}"
    )
    assert at_cap["balance_billed_cents"] == 180000, (
        f"the balance billed is 480000 less the 300000 allowed, got {at_cap['balance_billed_cents']}"
    )

    # One cent over the cap: the benefit schedule binds and clamps the allowance.
    assert above["negotiated_amount_cents"] == 300001, (
        f"the in-network negotiated amount is the 300001 fee schedule, got {above['negotiated_amount_cents']}"
    )
    assert above["allowed_amount_cents"] == 300000, (
        "one cent above the cap the allowed amount is clamped to the 300000 "
        f"scheduled cap, got {above['allowed_amount_cents']}"
    )
    assert above["balance_billed_cents"] == 180000, (
        f"the balance billed is 480000 less the 300000 allowed, got {above['balance_billed_cents']}"
    )

    claim = read_claim(claim_id)
    assert_claim(claim)
    assert claim["allowed_amount_total_cents"] == 899999, (
        "the claim's allowed-amount total is 299999 plus 300000 plus 300000, got "
        f"{claim['allowed_amount_total_cents']}"
    )
    assert claim["balance_billed_total_cents"] == 540001, (
        "the balance-billed total is 180001 plus 180000 plus 180000, got "
        f"{claim['balance_billed_total_cents']}"
    )
    assert claim["family_responsibility_total_cents"] == 0, (
        "every charge is in-network, so the family's protected share is zero, got "
        f"{claim['family_responsibility_total_cents']}"
    )


def test_seventy_sixth_declared_athlete_is_priced_in_the_second_volume_band(api):
    """PRD §3.2: "The gross premium slices the declared head count into three cumulative volume bands and prices each band separately."
    PRD §3.2: "The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000."
    PRD §3.2: "The second band covers participants 76 through 400 at a factor of 0.9250, a seven-and-a-half percent volume discount."
    PRD §3.2: "The third band covers every participant beyond 400 at a factor of 0.8500."
    PRD §3.2: "Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "The hazard load is folded into each band line before that line is rounded; it is never applied to a summed total."
    PRD §3.2: "`gross_premium_cents` is then the plain sum of the three already-rounded band lines."
    PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "If the layer was not elected, the charge is exactly 0."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §2.5: "Wherever a calculation in §3 produces a non-integral number of cents or basis points, the result is rounded **half up** to the nearest whole unit at exactly the point the calculation names — never earlier and never later."

    Design: Corner/calculations/premium_band_boundary_at_seventy_five_and_seventy_six_participants
    """
    league_a = create_league(
        name="Quarry Hill Baseball",
        league_code="QHB-122",
        state_code="UT",
        governing_body_code="USYSA",
        contact_email="admin@qhb.example",
    )
    league_b = create_league(
        name="Riverbend Baseball",
        league_code="RBB-123",
        state_code="UT",
        governing_body_code="USYSA",
        contact_email="admin@rbb.example",
    )
    sport = create_sport_classification("baseball")
    assert sport["base_rate_per_participant_cents"] == 1850
    assert sport["hazard_load_bps"] == 1150, (
        "a CLASS_2_MODERATE sport carries a hazard load of 1150 basis points, got "
        f"{sport['hazard_load_bps']}"
    )

    def quote_for(league_id, enrolled_participant_count):
        return validate_success(
            api.create_league_policy(
                create_league_policy_payload(
                    league_id,
                    sport["id"],
                    term_effective_date="2026-03-01",
                    term_expiration_date="2027-03-01",
                    enrolled_participant_count=enrolled_participant_count,
                    coverage_basis_election="EXCESS_ONLY",
                    cat_layer_elected=False,
                ),
                make_program_admin_headers(),
            ),
            201,
        )

    policy_a = quote_for(league_a["id"], 75)
    policy_b = quote_for(league_b["id"], 76)
    assert_league_policy(policy_a)
    assert_league_policy(policy_b)

    # 75 athletes sit wholly inside band 1: 75 * 1850 * 1.0000 = 138750, loaded by
    # 1150 basis points gives 154706.25, rounded half up to 154706. Bands 2 and 3
    # are empty, so the gross premium is that single line.
    assert policy_a["gross_premium_cents"] == 154706, (
        "a 75-athlete term is priced entirely at the band-1 factor and rounded half "
        f"up to 154706, got {policy_a['gross_premium_cents']}"
    )
    assert policy_a["cat_layer_charge_cents"] == 0, (
        "the catastrophic layer was not elected, so the charge is exactly 0, got "
        f"{policy_a['cat_layer_charge_cents']}"
    )
    assert policy_a["premium_subtotal_cents"] == 154706, (
        f"the subtotal is the gross premium plus a zero cat charge, got {policy_a['premium_subtotal_cents']}"
    )
    assert policy_a["volume_credit_bps"] == 0, (
        "a subtotal of 154706 cents is below 500000 and earns no credit at all, got "
        f"{policy_a['volume_credit_bps']}"
    )
    assert policy_a["volume_credit_cents"] == 0, (
        f"a credit rate of 0 basis points yields no credit, got {policy_a['volume_credit_cents']}"
    )
    assert policy_a["annual_premium_cents"] == 154706, (
        "the annual premium is the subtotal less a zero credit and comfortably above "
        f"the 25000-cent floor, got {policy_a['annual_premium_cents']}"
    )

    # The 76th athlete falls into band 2: 1 * 1850 * 0.9250 = 1711.25, loaded by
    # 1150 basis points gives 1908.04375, rounded half up to 1908. Added to the
    # unchanged 154706 band-1 line that is a gross premium of 156614.
    assert policy_b["gross_premium_cents"] == 156614, (
        "a 76-athlete term adds one band-2 line of 1908 to the 154706 band-1 line, "
        f"got {policy_b['gross_premium_cents']}"
    )
    assert policy_b["cat_layer_charge_cents"] == 0
    assert policy_b["premium_subtotal_cents"] == 156614, (
        f"the subtotal is the gross premium plus a zero cat charge, got {policy_b['premium_subtotal_cents']}"
    )
    assert policy_b["volume_credit_bps"] == 0, (
        "a subtotal of 156614 cents is below 500000 and earns no credit at all, got "
        f"{policy_b['volume_credit_bps']}"
    )
    assert policy_b["volume_credit_cents"] == 0
    assert policy_b["annual_premium_cents"] == 156614, (
        f"the annual premium is the subtotal less a zero credit, got {policy_b['annual_premium_cents']}"
    )

    marginal_cents = policy_b["gross_premium_cents"] - policy_a["gross_premium_cents"]
    assert marginal_cents == 1908, (
        "the 76th declared athlete costs one band-2 line item of 1908 cents, got "
        f"{marginal_cents}"
    )
    assert marginal_cents * 75 < policy_a["gross_premium_cents"], (
        "the 76th athlete must cost strictly less than a band-1 athlete, because the "
        "0.9250 volume factor applies to them and not to the first 75"
    )


def test_reports_filed_out_of_chronological_order_each_count_days_from_their_own_injury(api):
    """PRD §3.5: "Two timestamp fields are stamped by the server, never by the client."
    PRD §3.5: "`reported_on_date` is the logical clock's UTC calendar date, truncated to midnight of that date."
    PRD §3.5: "`days_to_report` is the whole number of UTC calendar days from the calendar date of `injury_datetime` to `reported_on_date`."
    PRD §3.5: "The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §2.11: "Day counts — the filing window, the verification window and the explanation-of-benefits waiver window — are whole UTC calendar days, computed by taking the calendar date of each endpoint and counting the days between them."

    Design: Corner/calculations/timeliness_measured_from_injury_datetime_not_filing_order
    """
    bundle = setup_enrolled_athlete(
        league_overrides={
            "name": "Silverton Baseball",
            "league_code": "SVB-124",
            "state_code": "NV",
            "contact_email": "admin@svb.example",
        },
        participant_overrides={
            "first_name": "Kwame",
            "last_name": "Asante",
            "guardian_email": "g28@svb.example",
        },
    )
    league_headers = make_league_admin_headers(bundle["league"]["id"])

    # Two activities two months apart, so the buffered per-athlete collision check
    # never fires and both remain available to report against.
    activity_early = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="PRACTICE",
        venue_name="Silverton Cage 1",
        starts_at="2026-05-10T18:00:00Z",
        ends_at="2026-05-10T20:00:00Z",
    )
    activity_late = schedule_activity(
        bundle["policy"]["id"],
        bundle["league"]["id"],
        activity_type="GAME",
        venue_name="Silverton Field 1",
        starts_at="2026-07-11T18:00:00Z",
        ends_at="2026-07-11T20:00:00Z",
    )

    set_clock("2026-07-20T00:00:00Z")

    # The later injury is filed first, so filing order runs backwards against
    # injury order.
    report_late = validate_success(
        api.create_injury_report(
            create_injury_report_payload(
                bundle["enrollment"]["id"],
                activity_late["id"],
                injury_datetime="2026-07-11T19:00:00Z",
                body_part="ANKLE_FOOT",
                injury_description="rolled ankle sliding into second",
                severity_tier="MINOR",
            ),
            league_headers,
        ),
        201,
    )
    assert_injury_report(report_late)
    # 2026-07-11 to 2026-07-20 is nine whole UTC calendar days.
    assert report_late["days_to_report"] == 9, (
        "the July injury was reported nine calendar days later, got "
        f"{report_late['days_to_report']}"
    )
    assert canonical_iso(report_late["reported_on_date"]) == canonical_iso(
        "2026-07-20T00:00:00Z"
    ), (
        "reported_on_date is midnight of the logical clock's calendar date, got "
        f"{report_late['reported_on_date']}"
    )
    assert report_late["status"] == "PENDING_VERIFICATION", (
        "a report filed nine days after the injury is timely and enters "
        f"PENDING_VERIFICATION, got {report_late['status']}"
    )
    assert report_late["correction_round_count"] == 0

    report_early = validate_success(
        api.create_injury_report(
            create_injury_report_payload(
                bundle["enrollment"]["id"],
                activity_early["id"],
                injury_datetime="2026-05-10T19:00:00Z",
                body_part="HAND_WRIST",
                injury_description="jammed wrist on a batting-cage swing",
                severity_tier="MINOR",
            ),
            league_headers,
        ),
        201,
    )
    assert_injury_report(report_early)
    # 2026-05-10 to 2026-07-20 is 21 + 30 + 20 = 71 whole UTC calendar days, still
    # inside the ninety-day filing window.
    assert report_early["days_to_report"] == 71, (
        "the May injury was reported seventy-one calendar days later, counted from "
        f"its own injury_datetime rather than from filing order, got {report_early['days_to_report']}"
    )
    assert canonical_iso(report_early["reported_on_date"]) == canonical_iso(
        "2026-07-20T00:00:00Z"
    ), (
        "both reports were filed at the same logical clock instant, so both carry "
        f"the same reported_on_date, got {report_early['reported_on_date']}"
    )
    assert report_early["status"] == "PENDING_VERIFICATION", (
        "seventy-one days is ninety or fewer, so the filing is timely, got "
        f"{report_early['status']}"
    )
    assert report_early["correction_round_count"] == 0

    # Filing the second report leaves the first report's own day count alone.
    reread_late = read_injury_report(report_late["id"])
    assert reread_late["days_to_report"] == 9, (
        "the July report's days_to_report is derived from its own injury_datetime "
        f"and does not move when another report is filed, got {reread_late['days_to_report']}"
    )
    assert canonical_iso(reread_late["reported_on_date"]) == canonical_iso(
        "2026-07-20T00:00:00Z"
    )
