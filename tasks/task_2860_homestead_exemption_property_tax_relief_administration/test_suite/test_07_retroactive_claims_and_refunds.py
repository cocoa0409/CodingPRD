"""Retroactive claims: the provisional figure at filing and the settled one at approval.

Filing publishes a gross refund that ignores what the household owes; approval
recomputes it, absorbs the outstanding recovery oldest year first, adds statutory
interest on what survives the offset and only then moves money.
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
    ERR_APPEAL_DEADLINE_PASSED,
    ERR_CLAIM_NOT_PENDING,
    ERR_CLAIM_YEARS_OVERLAP,
    ERR_GRANT_ALREADY_TERMINAL,
    ERR_GRANT_NOT_FOUND,
    ERR_NO_ELIGIBLE_CLAIM_YEARS,
    ERR_NOTICE_NOT_APPEALABLE,
    ERR_STATUTORY_LOOKBACK_EXCEEDED,
)
from test_helpers.assertions import (
    assert_claim_amounts,
    assert_instant,
    assert_grant,
    assert_parcel_decomposition,
    assert_recovery_assessment,
    assert_taxpayer_ledger,
)
from test_helpers.constants import ADDR_ELM, ADDR_OAK
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    HEARING_CLERK,
    INVESTIGATOR,
    REVIEWER,
    REVIEWER_2,
)


def _refund_settlement_world(api):
    """A homestead grant worth refunding and a substantiated recovery to absorb.

    The household holds a whole-share homestead grant on the residence with a
    benefit of 8400000, and a separate agricultural grant on a small parcel that a
    substantiated investigation has since revoked, leaving 6660 of assessed
    recovery frozen against the account.
    """
    fx.set_clock(api)
    homestead = fx.create_program(api, f.homestead_basic_program())
    agricultural = fx.create_program(
        api,
        f.agricultural_use_program(
            relief_pct_bps=3000,
            max_exempt_value_cents=15000000,
            statutory_lookback_years=5,
            penalty_pct_bps=800,
            interest_pct_bps_per_year=300,
        ),
    )
    residence = fx.create_parcel(api, f.parcel())
    smallholding = fx.create_parcel(
        api,
        f.parcel(
            apn="P-0007",
            situs_address_normalized="7 FARM RD SOUTHTON ST 10007",
            county_zone="SOUTH",
            base_year=2026,
            base_year_value_cents=1600000,
            market_value_cents=2000000,
        ),
    )
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    fx.add_ownership(api, residence["id"], taxpayer["id"])
    fx.add_ownership(
        api, smallholding["id"], taxpayer["id"], occupancy_type="AGRICULTURAL"
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
    grant = validate_success(
        api.get_grant(homestead_determined["resulting_grant_id"], REVIEWER)
    )

    # The agricultural claim's cross-match history is what later carries the
    # investigation past the substantiation threshold.
    farm_application = fx.submitted_application(
        api, smallholding["id"], taxpayer["id"], agricultural["id"]
    )
    fx.inject_registry(
        api,
        taxpayer["id"],
        "VOTER_REGISTRY",
        record_effective_date="2026-02-01",
        address_normalized=ADDR_ELM,
    )
    fx.run_checks(api, farm_application["id"], ["VOTER_REGISTRY"])
    fx.inject_registry(
        api,
        taxpayer["id"],
        "VOTER_REGISTRY",
        record_effective_date="2026-03-01",
        address_normalized=ADDR_OAK,
    )
    fx.run_checks(api, farm_application["id"], ["VOTER_REGISTRY", "DEED_REGISTRY"])
    fx.inject_registry(
        api,
        taxpayer["id"],
        "USPS_NCOA",
        record_effective_date="2026-03-01",
        address_normalized=ADDR_ELM,
    )
    fx.run_checks(api, farm_application["id"], ["USPS_NCOA"])
    fx.create_certification(
        api,
        taxpayer["id"],
        household_income_cents=5000000,
        countable_asset_cents=1000000,
        household_size=2,
        recertification_due_date="2026-12-31",
    )
    fx.inject_registry(
        api,
        taxpayer["id"],
        "INCOME_DOR",
        record_effective_date="2026-03-01",
        reported_income_cents=9000000,
    )
    fx.run_checks(api, farm_application["id"], ["INCOME_DOR"])

    farm_now = validate_success(api.get_parcel(smallholding["id"], ANALYST))
    farm_determined = validate_success(
        api.determine_application(
            farm_application["id"],
            f.approve_determination(farm_now["version"]),
            REVIEWER,
        )
    )
    case = fx.substantiated_fraud_case(
        api,
        farm_determined["resulting_grant_id"],
        taxpayer["id"],
        improper_start_tax_year=2025,
        improper_end_tax_year=2025,
    )

    claim = validate_success(
        api.create_retroactive_claim(
            f.retroactive_claim(grant["id"]),
            fx.make_taxpayer_headers(taxpayer["id"]),
        ),
        expected_status=201,
    )
    return {
        "taxpayer": taxpayer,
        "grant": grant,
        "case": case,
        "claim": claim,
    }


def test_filing_publishes_the_provisional_gross_refund_and_no_settlement_figures(api):
    """PRD §3.7: "the sum of the per-year savings across every year in the window is
    written to `gross_refund_cents`. At filing the claim's `status` is `PENDING`,
    and the provisional variant deliberately ignores the household's outstanding
    recovery balance and adds no interest, leaving `offset_applied_cents`,
    `net_refund_cents`, `refund_interest_cents` and `total_payable_cents` all at
    0."

    Design: Difficulty/dual_variant_calc/refund_gross_provisional_versus_net_final_on_retroactive_claim
    """
    world = _refund_settlement_world(api)
    claim = world["claim"]

    assert claim["first_eligible_tax_year"] == 2023, (
        "the three-year lookback and the requested start agree on 2023, got "
        f"{claim['first_eligible_tax_year']}"
    )
    assert claim["last_eligible_tax_year"] == 2025, (
        f"the filing year is served by the grant itself, got {claim['last_eligible_tax_year']}"
    )
    assert claim["eligible_year_count"] == 3, (
        f"the closed window covers three years, got {claim['eligible_year_count']}"
    )

    # Each year saves 8400000 * 125 / 10000 = 105000, and three years make 315000.
    assert_claim_amounts(
        claim,
        gross_refund_cents=315000,
        offset_applied_cents=0,
        net_refund_cents=0,
        refund_interest_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
    )


def test_approval_offsets_the_recovery_then_pays_interest_on_what_survives(api):
    """PRD §3.7: "the years are walked in **ascending** tax-year order so the oldest
    year absorbs first ... The total absorbed across all years is written to
    `offset_applied_cents`." Interest follows: "for each year, the refundable
    remainder multiplied by the refund interest rate of 400 basis points per year
    ... multiplied by the number of years between that tax year and the
    `filing_tax_year`, divided by ten thousand, and rounded half up to a whole
    cent, with each year rounded before summing."

    Design: Difficulty/dual_variant_calc/refund_gross_provisional_versus_net_final_on_retroactive_claim
    """
    world = _refund_settlement_world(api)

    settled = validate_success(
        api.decide_retroactive_claim(
            world["claim"]["id"],
            f.claim_decision("APPROVE", "Three eligible years confirmed."),
            REVIEWER_2,
        )
    )

    # 2023 absorbs the whole 6660, leaving 98340 + 105000 + 105000 refundable, and
    # interest is 11801 + 8400 + 4200 over three, two and one years respectively.
    assert_claim_amounts(
        settled,
        gross_refund_cents=315000,
        offset_applied_cents=6660,
        net_refund_cents=308340,
        refund_interest_cents=24401,
        total_payable_cents=332741,
        status="APPROVED",
    )

    case = validate_success(api.get_fraud_case(world["case"]["id"], INVESTIGATOR))
    assert_recovery_assessment(
        case, total_assessed_cents=6660, recovery_paid_cents=6660
    )
    assert case["recovery_status"] == "PAID", (
        f"the credit closed the balance exactly, got {case['recovery_status']}"
    )

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=332741,
        lifetime_recovery_collected_cents=6660,
        net_relief_cents=326081,
    )


def _claim_orphaned_by_a_revocation(api):
    """A pending claim whose grant was revoked after the claim was filed.

    No investigation exists anywhere in this world, so nothing but the grant's own
    terminal status can stand in the way of the adjudication.
    """
    world = fx.approved_homestead_world(api)
    world["claim"] = fx.pending_claim(api, world["grant_id"])
    world["revoked"] = fx.revoke_grant(api, world["grant_id"])
    return world


def test_a_claim_cannot_be_approved_once_its_grant_has_been_revoked(api):
    """PRD §3.7: "Approval additionally requires that the grant still support a
    refund: its `benefit_status` must be `ACTIVE` or `SUSPENDED`, since a
    `REVOKED`, `TRANSFERRED` or `LAPSED` grant cannot — such a claim is refused
    with `ERR_GRANT_ALREADY_TERMINAL`".

    Design: Difficulty/cross_entity_state_dependency/claim_approval_requires_non_terminal_grant_state_on_another_entity
    """
    world = _claim_orphaned_by_a_revocation(api)

    validate_error(
        api.decide_retroactive_claim(
            world["claim"]["id"],
            f.claim_decision("APPROVE", "Attempting approval after revocation."),
            REVIEWER_2,
        ),
        ERR_GRANT_ALREADY_TERMINAL,
        expected_status=409,
    )

    claim = validate_success(
        api.get_retroactive_claim(world["claim"]["id"], REVIEWER_2)
    )
    assert_claim_amounts(
        claim,
        gross_refund_cents=315000,
        offset_applied_cents=0,
        net_refund_cents=0,
        refund_interest_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )


def test_the_refused_adjudication_moves_no_money_and_mails_no_refund_notice(api):
    """PRD §2.7: "Grants in any status other than `ACTIVE` — `SUSPENDED`,
    `REVOKED`, `TRANSFERRED` or `LAPSED` — are excluded from both the freeze
    selection and the waterfall, and an excluded grant's
    `applied_exempt_value_cents` is reset to 0." PRD §3.7 mails a
    `REFUND_DETERMINATION` notice only once a claim "becomes `APPROVED`" or
    `DENIED`.

    Design: Difficulty/cross_entity_state_dependency/claim_approval_requires_non_terminal_grant_state_on_another_entity
    """
    world = _claim_orphaned_by_a_revocation(api)

    validate_error(
        api.decide_retroactive_claim(
            world["claim"]["id"],
            f.claim_decision("APPROVE", "Attempting approval after revocation."),
            REVIEWER_2,
        ),
        ERR_GRANT_ALREADY_TERMINAL,
        expected_status=409,
    )

    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
        net_relief_cents=0,
    )

    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(
        grant, benefit_status="REVOKED", applied_exempt_value_cents=0
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )

    rows, meta = validate_paginated(
        api.list_notices(
            world["taxpayer"]["id"], CLERK, notice_type="REFUND_DETERMINATION"
        )
    )
    assert meta["total_count"] == 0, (
        f"no refund notice may have been mailed, got {meta['total_count']}"
    )
    assert rows == [], f"unexpected refund notices: {rows}"


def test_the_requested_start_year_binds_hardest_and_closes_the_window_a_year_early(api):
    """PRD §3.7: "The last eligible year is always the `filing_tax_year` minus one,
    because the current year is served by the grant itself and needs no refund; it is
    written to `last_eligible_tax_year`. The first eligible year is the **greatest**
    of three floors: the filing year minus the programme's
    `statutory_lookback_years`, the grant's own `first_eligible_tax_year`, and the
    `requested_start_tax_year` — whichever binds hardest wins ... The window is a
    closed interval including both ends, and `eligible_year_count` is the last
    eligible year minus the first, plus one."

    Design: Corner/calculations/claim_filing_derives_the_closed_eligible_year_window
    """
    world = fx.approved_homestead_world(api)
    grant = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert grant["first_eligible_tax_year"] == 2019, (
        "the verified occupancy began in 2019, got "
        f"{grant['first_eligible_tax_year']}"
    )

    # The floors are 2023 (2026 less the three-year lookback), 2019 (the grant) and
    # the requested 2024, so the request binds hardest.
    claim = validate_success(
        api.create_retroactive_claim(
            f.retroactive_claim(world["grant_id"], requested_start_tax_year=2024),
            fx.make_taxpayer_headers(world["taxpayer"]["id"]),
        ),
        expected_status=201,
    )

    assert claim["first_eligible_tax_year"] == 2024, (
        f"the requested start is the binding floor, got {claim['first_eligible_tax_year']}"
    )
    assert claim["last_eligible_tax_year"] == 2025, (
        "the filing year itself is served by the grant, so the window closes at "
        f"2025, got {claim['last_eligible_tax_year']}"
    )
    assert claim["eligible_year_count"] == 2, (
        f"2025 less 2024 plus one is two years, got {claim['eligible_year_count']}"
    )

    # Each year saves 8400000 * 125 / 10000 = 105000, and two years make 210000.
    assert_claim_amounts(
        claim,
        gross_refund_cents=210000,
        offset_applied_cents=0,
        net_refund_cents=0,
        refund_interest_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )
    assert_taxpayer_ledger(
        validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK)),
        lifetime_refund_cents=0,
    )


def test_the_grants_claim_link_lists_that_grants_claim_and_404s_on_an_unknown_grant(api):
    """PRD §2.10 rung 6: "Path identifiers resolve, left to right — ...
    `ERR_GRANT_NOT_FOUND` ... Applies to every endpoint with a path parameter."
    PRD §3.7: "At filing the claim's `status` is `PENDING`, and the provisional
    variant deliberately ignores the household's outstanding recovery balance and
    adds no interest, leaving `offset_applied_cents`, `net_refund_cents`,
    `refund_interest_cents` and `total_payable_cents` all at 0."

    Design: Corner/endpoints/grant_retroactive_claims_link_lists_only_that_grants_claims
    """
    world = fx.approved_homestead_world(api)
    claim = validate_success(
        api.create_retroactive_claim(
            f.retroactive_claim(world["grant_id"], requested_start_tax_year=2024),
            fx.make_taxpayer_headers(world["taxpayer"]["id"]),
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_grant_retroactive_claims(world["grant_id"], REVIEWER)
    )
    assert meta["total_count"] == 1, (
        f"the grant carries exactly one claim, got {meta['total_count']}"
    )
    assert rows[0]["id"] == claim["id"], (
        f"the listed row is the claim just filed, got {rows[0]['id']}"
    )
    listed = rows[0]
    assert listed["first_eligible_tax_year"] == 2024, (
        f"the listed window opens in 2024, got {listed['first_eligible_tax_year']}"
    )
    assert listed["last_eligible_tax_year"] == 2025, (
        f"the listed window closes in 2025, got {listed['last_eligible_tax_year']}"
    )
    assert listed["eligible_year_count"] == 2, (
        f"the listed window covers two years, got {listed['eligible_year_count']}"
    )
    assert_claim_amounts(
        listed,
        gross_refund_cents=210000,
        offset_applied_cents=0,
        net_refund_cents=0,
        refund_interest_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )

    # The parent is resolved before the collection is assembled, so an unknown
    # grant is a not-found and never an empty page.
    validate_error(
        api.list_grant_retroactive_claims(NON_EXISTENT_UUID, REVIEWER),
        ERR_GRANT_NOT_FOUND,
        expected_status=404,
    )


def test_the_four_claim_guards_are_distinguished_on_a_single_grant(api):
    """PRD §3.7: "Two related guards apply at filing: a `requested_start_tax_year`
    earlier than the filing year minus the programme's `statutory_lookback_years` is
    refused with `ERR_STATUTORY_LOOKBACK_EXCEEDED`, and a claim whose eligible
    interval intersects the eligible interval of an existing `PENDING` or `APPROVED`
    claim on the same grant — closed-interval intersection, so sharing even a single
    year collides — is refused with `ERR_CLAIM_YEARS_OVERLAP`." PRD §3.7 adds:
    "Should the first eligible year come out later than the last, no year survives
    and the filing is refused with `ERR_NO_ELIGIBLE_CLAIM_YEARS`", and "The claim
    must still be `PENDING`, or the decision is refused with `ERR_CLAIM_NOT_PENDING`."

    Design: Corner/errors/retroactive_claim_window_and_decision_guards_return_4xx
    """
    world = fx.approved_homestead_world(api)
    grant_id = world["grant_id"]
    taxpayer_id = world["taxpayer"]["id"]

    # 2020 is earlier than the 2023 floor set by 2026 minus a three-year lookback.
    validate_error(
        api.create_retroactive_claim(
            f.retroactive_claim(grant_id, requested_start_tax_year=2020), CLERK
        ),
        ERR_STATUTORY_LOOKBACK_EXCEEDED,
        expected_status=422,
    )

    # 2026 clears the lookback, yet the last eligible year is only 2025.
    validate_error(
        api.create_retroactive_claim(
            f.retroactive_claim(grant_id, requested_start_tax_year=2026), CLERK
        ),
        ERR_NO_ELIGIBLE_CLAIM_YEARS,
        expected_status=422,
    )

    claim = validate_success(
        api.create_retroactive_claim(
            f.retroactive_claim(grant_id, requested_start_tax_year=2024), CLERK
        ),
        expected_status=201,
    )
    assert claim["first_eligible_tax_year"] == 2024, (
        f"the requested year binds hardest, got {claim['first_eligible_tax_year']}"
    )
    assert claim["last_eligible_tax_year"] == 2025, (
        f"the filing year is served by the grant itself, got {claim['last_eligible_tax_year']}"
    )
    assert claim["eligible_year_count"] == 2, (
        f"the closed window covers two years, got {claim['eligible_year_count']}"
    )
    assert_claim_amounts(
        claim,
        gross_refund_cents=210000,
        offset_applied_cents=0,
        net_refund_cents=0,
        refund_interest_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )

    # A 2025-2025 window shares a year with the pending 2024-2025 claim.
    validate_error(
        api.create_retroactive_claim(
            f.retroactive_claim(grant_id, requested_start_tax_year=2025), CLERK
        ),
        ERR_CLAIM_YEARS_OVERLAP,
        expected_status=409,
    )

    approved = validate_success(
        api.decide_retroactive_claim(
            claim["id"],
            f.claim_decision("APPROVE", "Occupancy documented for both years."),
            REVIEWER_2,
        )
    )
    # No recovery is outstanding, so nothing is absorbed and interest runs on the
    # whole of each year: 105000 * 400 * 2 / 10000 plus 105000 * 400 * 1 / 10000.
    assert_claim_amounts(
        approved,
        gross_refund_cents=210000,
        offset_applied_cents=0,
        net_refund_cents=210000,
        refund_interest_cents=12600,
        total_payable_cents=222600,
        status="APPROVED",
    )

    validate_error(
        api.decide_retroactive_claim(
            claim["id"],
            f.claim_decision("DENY", "Duplicate decision attempt."),
            REVIEWER_2,
        ),
        ERR_CLAIM_NOT_PENDING,
        expected_status=409,
    )

    settled = validate_success(api.get_retroactive_claim(claim["id"], REVIEWER))
    assert settled["status"] == "APPROVED", (
        f"the refused second decision leaves the claim approved, got {settled['status']}"
    )

    account = validate_success(api.get_taxpayer_account(taxpayer_id, CLERK))
    assert_taxpayer_ledger(
        account,
        lifetime_refund_cents=222600,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=222600,
    )

    rows, meta = validate_paginated(api.list_grant_retroactive_claims(grant_id, REVIEWER))
    assert meta["total_count"] == 1, (
        f"only the accepted filing persisted a row, got {meta['total_count']}"
    )
    assert rows[0]["id"] == claim["id"], (
        f"unexpected claim on the grant: {rows[0]['id']}"
    )


def test_the_refund_notice_on_an_approved_claim_cannot_be_appealed_at_all(api):
    """PRD §3.7: "Finally a notice with `notice_type` `REFUND_DETERMINATION` and
    `subject_type` `RETROACTIVE_CLAIM` is mailed against the claim with `appealable`
    **false** — an approved refund is not an adverse action and there is nothing to
    challenge." PRD §3.9: "The `appealable` flag is true for every notice except one
    case: a `REFUND_DETERMINATION` notice issued on an *approved* retroactive claim is
    not appealable, because a granted refund is not an adverse action ... An attempt to
    appeal a notice whose `appealable` flag is false is refused with
    `ERR_NOTICE_NOT_APPEALABLE`."

    Design: Corner/errors/refund_determination_notice_on_an_approved_claim_is_not_appealable
    """
    world = fx.approved_homestead_world(api)
    taxpayer_id = world["taxpayer"]["id"]
    claim = fx.pending_claim(
        api, world["grant_id"], requested_start_tax_year=2024
    )
    approved = validate_success(
        api.decide_retroactive_claim(
            claim["id"],
            f.claim_decision("APPROVE", "Both years are documented."),
            REVIEWER_2,
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the refund was granted, got {approved['status']}"
    )

    rows, meta = validate_paginated(
        api.list_notices(taxpayer_id, CLERK, notice_type="REFUND_DETERMINATION")
    )
    assert meta["total_count"] == 1, (
        f"the approval mails exactly one refund notice, got {meta['total_count']}"
    )
    notice = rows[0]
    assert notice["appealable"] is False, (
        f"a granted refund is not an adverse action, got {notice['appealable']!r}"
    )
    assert notice["subject_type"] == "RETROACTIVE_CLAIM", (
        f"the notice is mailed against the claim, got {notice['subject_type']}"
    )
    assert notice["subject_id"] == claim["id"], (
        f"the notice names the settled claim, got {notice['subject_id']}"
    )
    assert_instant(notice, "mailed_at", "2026-08-01T00:00:00.000Z")

    # One day after mailing: well inside any thirty-day window, and still refused.
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    response = api.create_appeal(
        f.appeal(notice["id"], grounds="The refund should have covered 2023 as well."),
        fx.make_taxpayer_headers(taxpayer_id),
    )
    validate_error(response, ERR_NOTICE_NOT_APPEALABLE, expected_status=422)
    assert ERR_APPEAL_DEADLINE_PASSED not in response.text, (
        "appealability is a property of the notice, not of the window, so no "
        f"deadline error may be reported: {response.text}"
    )

    appeals, appeal_meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, notice_id=notice["id"])
    )
    assert appeal_meta["total_count"] == 0, (
        f"the refused filing persists nothing, got {appeal_meta['total_count']}"
    )
    assert appeals == [], f"unexpected appeals on the refund notice: {appeals}"

    settled = validate_success(api.get_retroactive_claim(claim["id"], REVIEWER))
    assert settled["status"] == "APPROVED", (
        f"the refused appeal leaves the claim approved, got {settled['status']}"
    )
