"""Derived figures: fee bands, input sets, ruleset constants, remainders and thresholds.

Every expected integer below is transcribed from the arithmetic PRD s2.10, s3.5, s3.7,
s3.8 and s3.9 pin, never recomputed by the test.
"""

from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_donor_ledger,
    assert_release_money,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    communication_log_payload,
    contribution_payload,
    eligibility_change_payload,
    payment_release_payload,
    roster_allocation_payload,
    termination_payload,
)
from test_helpers.fixtures import (
    activate_contract,
    build_athlete,
    build_collective,
    build_donor,
    build_draft_contract,
    build_open_tier,
    build_settled_contribution,
    clear_disclosure,
    read_athlete,
    read_collective,
    read_contract,
    read_donor,
    read_release,
    record_taxpayer_doc,
)
from test_helpers.test_users import (
    make_compliance_headers,
    make_director_headers,
    make_treasury_headers,
)


def test_both_fee_band_edges_are_inclusive_and_the_fee_can_fall(api):
    """One extra cent of gross at a band edge lowers the fee, because the rate is average.

    PRD s3.5: "Band selection is by **average** rate on the whole gross amount, not
    marginal: exactly one band applies to the entire `gross_amount_cents`, and both band
    boundaries are inclusive", with 290 basis points plus 30 cents at or below 99,999,
    250 basis points plus 30 cents at or below 999,999, and 210 basis points with no fixed
    component above that. "Because the boundaries are inclusive, a gross of exactly 99,999
    cents is a first-band charge while 100,000 cents is a second-band charge, and a gross of
    exactly 999,999 cents is a second-band charge while 1,000,000 cents is a third-band
    charge." PRD s3.6 adds that a collective whose `charitable_deduction_enabled` is false
    reports `deductible_amount_cents` 0 "for every contribution of every donor".

    Design: Corner/calculations/processing_fee_band_boundaries_are_inclusive_on_both_edges
    """
    collective = build_collective(
        api,
        "022400",
        name="Fee Band Collective",
        institution_name="Fee Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        entity_structure="FOR_PROFIT_LLC",
    )
    tier = build_open_tier(api, collective["id"], "T1", 10000, 1)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Fee Donor", email="fee@example.com"
    )

    first_band_edge = build_settled_contribution(
        api, donor["id"], 99999, designation="UNRESTRICTED"
    )
    second_band_start = build_settled_contribution(
        api, donor["id"], 100000, designation="UNRESTRICTED"
    )
    second_band_edge = build_settled_contribution(
        api, donor["id"], 999999, designation="UNRESTRICTED"
    )
    third_band_start = build_settled_contribution(
        api, donor["id"], 1000000, designation="UNRESTRICTED"
    )

    assert_contribution_money(
        first_band_edge,
        processing_fee_cents=2930,
        net_amount_cents=97069,
        deductible_amount_cents=0,
    )
    assert_contribution_money(
        second_band_start, processing_fee_cents=2530, net_amount_cents=97470
    )
    assert_contribution_money(
        second_band_edge, processing_fee_cents=25030, net_amount_cents=974969
    )
    assert_contribution_money(
        third_band_start, processing_fee_cents=21000, net_amount_cents=979000
    )
    assert (
        first_band_edge["processing_fee_cents"] > second_band_start["processing_fee_cents"]
    ), "One extra cent of gross at the band-1 edge must lower the fee by 400 cents"

    assert_collective_ledger(
        read_collective(api, collective["id"]), settled_net_funds_cents=2148508
    )


def test_only_settled_rows_reach_the_collective_and_donor_ledgers(api):
    """A deferred row and a declined row of larger gross contribute nothing.

    PRD s2.10: "`settled_net_funds_cents` is the sum of `net_amount_cents` over the
    collective's contributions with status `SETTLED`, less the `net_amount_cents` of rows
    with status `REFUNDED`." PRD s3.5 adds that "Settlement is where the fee band is
    applied", that "`DEFER` leaves it in `PENDING`", and that a failing contribution "zeroes
    its fee, net and deductible figures".

    Design: Corner/calculations/pending_and_failed_contributions_excluded_from_settled_net_funds
    """
    collective = build_collective(
        api,
        "022500",
        name="Filter Collective",
        institution_name="Filter Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T2", 40000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Filter Donor",
        email="filter@example.com",
    )

    settled = build_settled_contribution(api, donor["id"], 100000, designation="UNRESTRICTED")
    pending = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"], 200000, designation="UNRESTRICTED", processor_outcome="DEFER"
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    failed = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"], 300000, designation="UNRESTRICTED", processor_outcome="DECLINE"
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )

    assert_contribution_money(settled, status="SETTLED", net_amount_cents=97470)
    assert_contribution_money(
        pending, status="PENDING", processing_fee_cents=0, net_amount_cents=0
    )
    assert_contribution_money(
        failed, status="FAILED", processing_fee_cents=0, net_amount_cents=0
    )

    assert_collective_ledger(
        read_collective(api, collective["id"]),
        settled_net_funds_cents=97470,
        funding_posture="OPEN",
    )
    assert_donor_ledger(read_donor(api, donor["id"]), lifetime_settled_cents=97470)


def _advanced_contract(
    api,
    ipeds_code,
    association_ruleset,
    home_state_code,
    state_law_citation,
    association_rule_citation,
    label,
):
    """A fully advanced 200000-cent contract with no deliverables at all.

    Earned is therefore 0 and the whole 200000 is unearned, so only the ruleset's cap
    percentage can decide the clawback.
    """
    collective = build_collective(
        api,
        ipeds_code,
        name=f"Cap Collective {label}",
        institution_name=f"Cap Institution {label}",
        home_state_code=home_state_code,
        association_ruleset=association_ruleset,
    )
    tier = build_open_tier(api, collective["id"], "T3", 100000, 3)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name=f"Cap Donor {label}",
        email=f"cap{label.lower()}@example.com",
    )
    assert_contribution_money(
        build_settled_contribution(api, donor["id"], 500000, designation="UNRESTRICTED"),
        processing_fee_cents=12530,
        net_amount_cents=487470,
    )
    athlete = build_athlete(
        api,
        collective["id"],
        f"ath-cap-{label.lower()}",
        full_name=f"Cap Athlete {label}",
        sport="FOOTBALL",
        class_year=2028,
    )
    contract = build_draft_contract(
        api, collective["id"], athlete["id"], 200000, funding_designation="UNRESTRICTED"
    )
    clear_disclosure(
        api,
        contract["id"],
        state_law_citation=state_law_citation,
        association_rule_citation=association_rule_citation,
    )
    activated = activate_contract(api, contract["id"])
    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                200000,
                expected_deal_contract_version=activated["version"],
            ),
            make_treasury_headers("treasury-cap"),
        ),
        expected_status=201,
    )
    assert_release_money(release, status="RELEASED")
    return {"collective_id": collective["id"], "contract_id": contract["id"]}


def test_the_clawback_cap_percentage_comes_from_the_collectives_ruleset(api):
    """Identical money under two rulesets yields two different capped clawbacks.

    PRD s3.8: "A cap is then applied, and which cap depends on the collective's
    `association_ruleset`: 100 percent of `released_total_cents` under `NCAA_2024`, 50
    percent under `NCAA_2026`, and 75 percent under `NAIA`. The cap itself is the
    `released_total_cents` multiplied by that percentage, divided by 100, with the quotient
    floored to a whole cent. The `clawback_amount_cents` is then the smaller of the unearned
    figure and the cap", and "When the computed `clawback_amount_cents` is strictly greater
    than zero, the payment dimension moves to `CLAWBACK_DUE`". With no deliverables the
    earned figure is 0, so the unearned figure is the whole 200000 in both collectives.
    The NAIA collective uses `home_state_code` FL because the PRD permits only AL, CA, FL,
    OH and TX.

    Design: Corner/calculations/clawback_cap_percentage_differs_by_association_ruleset
    """
    alpha = _advanced_contract(
        api, "022600", "NCAA_2026", "CA", "CA-AB131", "NCAA-2026-12.5", "A"
    )
    beta = _advanced_contract(
        api, "022700", "NAIA", "FL", "FL-1006.74", "NAIA-2026-A", "B"
    )

    terminated_alpha = read_data(
        api.terminate_deal_contract(
            alpha["contract_id"], termination_payload("BREACH"), make_compliance_headers()
        )
    )
    terminated_beta = read_data(
        api.terminate_deal_contract(
            beta["contract_id"], termination_payload("BREACH"), make_compliance_headers()
        )
    )

    assert_contract_money(
        terminated_alpha,
        released_total_cents=200000,
        clawback_amount_cents=100000,
        termination_reason="BREACH",
    )
    assert_contract_dimensions(terminated_alpha, payment_status="CLAWBACK_DUE")
    assert_contract_money(
        terminated_beta,
        released_total_cents=200000,
        clawback_amount_cents=150000,
        termination_reason="BREACH",
    )
    assert_contract_dimensions(terminated_beta, payment_status="CLAWBACK_DUE")
    assert (
        terminated_alpha["clawback_amount_cents"] < 200000
        and terminated_beta["clawback_amount_cents"] < 200000
    ), "Both caps sit strictly below the unearned figure, so neither is the raw unearned sum"

    assert_collective_ledger(
        read_collective(api, alpha["collective_id"]), committed_unreleased_cents=0
    )


def test_the_single_remainder_cent_goes_to_the_heaviest_earliest_athlete(api):
    """The floor pass loses one cent and the pinned tie-break decides who recovers it.

    PRD s3.8: "**Step three, distribution:** the athletes are ordered by descending weight,
    then by ascending athlete `sequence_no`, and exactly one additional cent is added to each
    of the first athletes in that order until the remainder is exhausted. An athlete
    identifier is never an ordering input here." With weights 3, 3 and 1 the floor pass gives
    428571 + 428571 + 142857 = 999999, so the remainder is 1 and the first athlete by that
    order takes it.

    Design: Corner/calculations/roster_remainder_cents_ordered_by_weight_desc_then_sequence_no_asc
    """
    collective = build_collective(
        api,
        "022800",
        name="Remainder Collective",
        institution_name="Remainder Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T4", 500000, 4)
    donor = build_donor(
        api, collective["id"], tier["id"], display_name="Rem Donor", email="rem@example.com"
    )
    assert_contribution_money(
        build_settled_contribution(api, donor["id"], 2000000, designation="UNRESTRICTED"),
        processing_fee_cents=42000,
        net_amount_cents=1958000,
    )
    first = build_athlete(
        api,
        collective["id"],
        "ath-rem-1",
        full_name="Rem Athlete One",
        sport="FOOTBALL",
        class_year=2027,
        roster_weight=3,
    )
    second = build_athlete(
        api,
        collective["id"],
        "ath-rem-2",
        full_name="Rem Athlete Two",
        sport="FOOTBALL",
        class_year=2028,
        roster_weight=3,
    )
    third = build_athlete(
        api,
        collective["id"],
        "ath-rem-3",
        full_name="Rem Athlete Three",
        sport="FOOTBALL",
        class_year=2029,
        roster_weight=1,
    )
    assert (first["sequence_no"], second["sequence_no"], third["sequence_no"]) == (1, 2, 3)

    collective_now = read_collective(api, collective["id"])
    batch = read_data(
        api.create_roster_allocation(
            roster_allocation_payload(
                collective["id"],
                "REM-1",
                "FOOTBALL",
                1000000,
                "WEIGHTED_BY_ROSTER_WEIGHT",
                "2026-09-01T00:00:00Z",
                "2026-12-01T00:00:00Z",
                expected_collective_version=collective_now["version"],
                funding_designation="UNRESTRICTED",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert batch["created_contract_count"] == 3
    assert batch["allocated_total_cents"] == 1000000
    assert batch["remainder_cents"] == 1
    assert batch["min_share_cents"] == 142857
    assert batch["max_share_cents"] == 428572

    shares = {}
    for athlete in (first, second, third):
        rows = rows_of(
            api.list_deal_contracts(
                {"allocation_batch_code": "REM-1", "athlete_id": athlete["id"]},
                make_director_headers(),
            )
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["deal_kind"] == "ROSTER_SHARE"
        assert row["allocation_batch_code"] == "REM-1"
        assert_contract_dimensions(row, lifecycle_status="DRAFT", payment_status="UNPAID")
        shares[athlete["id"]] = row["total_value_cents"]

    assert shares[first["id"]] == 428572
    assert shares[second["id"]] == 428571
    assert shares[third["id"]] == 142857
    assert sum(shares.values()) == 1000000


def test_the_first_matching_communication_clause_decides_both_fields(api):
    """Clause 1 outranks the coach clause even under a monitored policy.

    PRD s3.1: "Four clauses are evaluated **in this order, and the first one that matches
    decides both fields**", clause 1 being "If an `athlete_id` was supplied and that
    athlete's `eligibility_status` is anything other than `ENROLLED`, the `verdict` is
    `PROHIBITED` and the `rationale_code` is `ATHLETE_NOT_ENROLLED`", and clause 2 under
    `MONITORED_CONTACT` giving `PERMITTED_WITH_DISCLOSURE` with
    `MONITORED_CHANNEL_REQUIRED` over the institution portal and `PROHIBITED` with the same
    rationale over any other channel. PRD s3.1 also states that "a `PROHIBITED` verdict is
    still recorded, with HTTP 201".

    Design: Corner/calculations/communication_verdict_first_matching_clause_wins_over_later_clauses
    """
    collective = build_collective(
        api,
        "022900",
        name="Clause Collective",
        institution_name="Clause Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
        communication_policy="MONITORED_CONTACT",
    )
    enrolled = build_athlete(
        api,
        collective["id"],
        "ath-clause-1",
        full_name="Clause Enrolled",
        sport="FOOTBALL",
        class_year=2028,
        as_compliance=True,
    )
    in_portal = build_athlete(
        api,
        collective["id"],
        "ath-clause-2",
        full_name="Clause Portal",
        sport="FOOTBALL",
        class_year=2028,
        as_compliance=True,
    )
    read_data(
        api.change_athlete_eligibility(
            in_portal["id"],
            eligibility_change_payload("ENTER_PORTAL"),
            make_compliance_headers(),
        )
    )

    def log(actor_role, channel, topic, athlete_id):
        return read_data(
            api.create_communication_log(
                communication_log_payload(
                    collective["id"], actor_role, channel, topic, athlete_id=athlete_id
                ),
                make_compliance_headers(),
            ),
            expected_status=201,
        )

    monitored_portal = log(
        "HEAD_COACH", "INSTITUTION_PORTAL", "DEAL_TERMS", enrolled["id"]
    )
    assert monitored_portal["verdict"] == "PERMITTED_WITH_DISCLOSURE"
    assert monitored_portal["rationale_code"] == "MONITORED_CHANNEL_REQUIRED"

    not_enrolled = log(
        "HEAD_COACH", "INSTITUTION_PORTAL", "DEAL_TERMS", in_portal["id"]
    )
    assert not_enrolled["verdict"] == "PROHIBITED"
    assert not_enrolled["rationale_code"] == "ATHLETE_NOT_ENROLLED"

    wrong_channel = log("HEAD_COACH", "DIRECT_MESSAGE", "DEAL_TERMS", enrolled["id"])
    assert wrong_channel["verdict"] == "PROHIBITED"
    assert wrong_channel["rationale_code"] == "MONITORED_CHANNEL_REQUIRED"

    fall_through = log(
        "COMPLIANCE_OFFICER", "INSTITUTION_PORTAL", "COMPLIANCE_NOTICE", enrolled["id"]
    )
    assert fall_through["verdict"] == "PERMITTED"
    assert fall_through["rationale_code"] == "POLICY_ALLOWS"

    prohibited = rows_of(
        api.list_communication_logs(
            {"collective_id": collective["id"], "verdict": "PROHIBITED"},
            make_compliance_headers(),
        )
    )
    assert len(prohibited) == 2


def test_the_reporting_threshold_flips_on_the_sixty_thousandth_cent(api):
    """59999 paid needs no form; one more cent requires the 1099.

    PRD s3.7: "if `tax_year_gross_paid_cents` is at least 60,000 cents — six hundred dollars
    — `tax_form_required` is `FORM_1099_NEC` ... The threshold comparison is inclusive, so a
    US person paid exactly six hundred dollars in the year requires the form while one paid a
    cent less does not." PRD s3.7 also fixes the starting point: "If `tax_year_gross_paid_cents`
    is zero, `tax_form_required` is `NONE`."

    Design: Corner/calculations/athlete_1099_threshold_is_inclusive_at_exactly_sixty_thousand
    """
    collective = build_collective(
        api,
        "023000",
        name="Threshold Collective",
        institution_name="Threshold Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T2", 30000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Thresh Donor",
        email="thresh@example.com",
    )
    assert_contribution_money(
        build_settled_contribution(api, donor["id"], 120000, designation="UNRESTRICTED"),
        processing_fee_cents=3030,
        net_amount_cents=116970,
    )
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-thresh",
        full_name="Thresh Athlete",
        sport="WOMENS_BASKETBALL",
        class_year=2028,
        tax_person_kind="US_PERSON",
    )
    assert_athlete_tax_ledger(athlete, tax_form_required="NONE")
    documented = record_taxpayer_doc(api, athlete["id"], "W9")
    assert documented["taxpayer_doc_on_file"] == "W9"

    contract = build_draft_contract(
        api, collective["id"], athlete["id"], 60000, funding_designation="UNRESTRICTED"
    )
    clear_disclosure(
        api,
        contract["id"],
        state_law_citation="TX-51.9246",
        association_rule_citation="NCAA-2024-12.5",
    )
    activated = activate_contract(api, contract["id"])

    below = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                59999,
                expected_deal_contract_version=activated["version"],
            ),
            make_treasury_headers("treasury-thresh"),
        ),
        expected_status=201,
    )
    assert_release_money(below, status="RELEASED", withholding_basis="NONE")
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=59999,
        tax_form_required="NONE",
    )

    version_now = read_contract(api, contract["id"])["version"]
    last_cent = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                1,
                expected_deal_contract_version=version_now,
            ),
            make_treasury_headers("treasury-thresh"),
        ),
        expected_status=201,
    )
    assert_release_money(last_cent, status="RELEASED", net_payable_cents=1)
    assert_athlete_tax_ledger(
        read_athlete(api, athlete["id"]),
        tax_year_gross_paid_cents=60000,
        tax_form_required="FORM_1099_NEC",
    )

    final = read_contract(api, contract["id"])
    assert_contract_money(final, released_total_cents=60000)
    assert_contract_dimensions(final, payment_status="FULLY_PAID")
    assert_collective_ledger(
        read_collective(api, collective["id"]), committed_unreleased_cents=0
    )
    assert read_release(api, below["id"])["status"] == "RELEASED"
