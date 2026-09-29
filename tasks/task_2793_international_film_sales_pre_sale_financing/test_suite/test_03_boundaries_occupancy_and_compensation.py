"""Cent-and-minute boundaries, cross-entity gates, venue occupancy and the
compensating edges that restore every quantity a forward operation touched.

Every test pins the logical clock with its first call and builds all of its own
preconditions through the declared endpoints, because each test runs against an
empty database.
"""

from test_helpers import (
    AGREEMENT_TERM_END,
    CLOCK_DEFAULT,
    CONTRACT_MG,
    FACILITY2_COLLATERAL,
    FACILITY_ADVANCE_UNBONDED,
    FACILITY_COLLATERAL,
    LENDER_APPROVER,
    LENDER_APPROVER_ALT,
    accepted_contract,
    approve_facility,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_facility_figures,
    assert_film_counters,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_valuation_prices,
    buyer_amendment_payload,
    buyer_meeting_payload,
    clock_payload,
    comparable_payload,
    contract_payload,
    execute_agreement,
    executed_contract,
    get_success_data,
    make_agreement,
    make_buyer,
    make_comparables,
    make_facility,
    make_film,
    make_fr_territory,
    make_head_of_sales_headers,
    make_lender_headers,
    make_market,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_territory,
    open_market,
    packaged_slate,
    pin_clock,
    publish_payload,
    read_agreement,
    read_buyer,
    read_facility,
    read_film,
    read_valuation,
    screening_slot_payload,
    slate_with_published_valuation,
    state_payload,
    valuation_payload,
    validate_error,
)

EXPOSURE_LIMIT_AT_BOUNDARY = 1500000.00
EXPOSURE_LIMIT_ONE_CENT_HIGHER = 1500000.01
ONE_CENT = 0.01


# ==========================================================================
# Private module-level helpers.  None of them assert anything: they only build
# preconditions through declared endpoints so the tests below stay readable.
# ==========================================================================
def _exposure_boundary_env(api):
    """A picture IN_MARKET with a PUBLISHED DE valuation, a buyer whose gross
    exposure limit is exactly 1500000.00, and a second territory FR so a
    follow-up offer trips neither the duplicate-territory gate nor supersession."""
    env = slate_with_published_valuation(
        api, buyer_overrides={"exposure_limit_usd": EXPOSURE_LIMIT_AT_BOUNDARY}
    )
    env["territory_fr"] = make_fr_territory(api)
    return env


def _offer(api, env, territory_id, minimum_guarantee_usd, buyer_version=None):
    """Open one offer, reading the buyer's live version unless one is supplied."""
    if buyer_version is None:
        buyer_version = read_buyer(api, env["buyer"]["id"])["version"]
    return api.create_contract(
        contract_payload(
            env["film"]["id"],
            env["buyer"]["id"],
            territory_id,
            buyer_version,
            minimum_guarantee_usd=minimum_guarantee_usd,
        ),
        make_sales_agent_headers(),
    )


def _fr_valuation_env(api):
    """A registered ACTION picture with cast score 88 and a territory FR carrying
    a base value index of 1.00 and no comparable titles at all."""
    pin_clock(api, CLOCK_DEFAULT)
    film = make_film(api)
    territory = make_fr_territory(api)
    return {"film": film, "territory": territory}


def _add_comp(api, territory_id, name, fee, release_year, verified=True):
    return get_success_data(
        api.create_comparable_title(
            territory_id,
            comparable_payload(fee, release_year, name=name, verified=verified),
            make_platform_admin_headers(),
        )
    )


def _value_fr(api, env):
    return api.create_valuation(
        valuation_payload(env["film"]["id"], env["territory"]["id"], "CAST_ADJUSTED"),
        make_sales_agent_headers(),
    )


def _count_valuations(api):
    rows, meta = assert_list_response(
        api.list_valuations(make_sales_agent_headers(), {"limit": 100})
    )
    return rows, meta["total_count"]


def _count_contracts(api):
    rows, meta = assert_list_response(
        api.list_contracts(make_sales_agent_headers(), {"limit": 100})
    )
    return rows, meta["total_count"]


# ==========================================================================
# The gross credit gate at cent resolution
# ==========================================================================
def test_offer_landing_exactly_on_the_gross_exposure_limit_is_accepted(api):
    """An offer whose minimum guarantee brings gross exposure to exactly the limit passes.

    PRD: "The credit gate rejects with `ERR_BUYER_EXPOSURE_EXCEEDED` when the buyer's gross pipeline exposure plus the payload's `minimum_guarantee_usd` would exceed the buyer's `exposure_limit_usd`; landing exactly on the limit passes."

    Design: Difficulty/boundary_precision_check/buyer_exposure_limit_passes_at_exact_equality_and_fails_one_cent_over
    """
    env = _exposure_boundary_env(api)

    buyer_before = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer_before, gross=0.00, net=0.00)

    contract = assert_created(
        _offer(api, env, env["territory"]["id"], EXPOSURE_LIMIT_AT_BOUNDARY)
    )
    assert_contract_axes(contract, negotiation="OFFERED")
    assert_money(
        contract["minimum_guarantee_usd"],
        EXPOSURE_LIMIT_AT_BOUNDARY,
        "minimum_guarantee_usd",
    )

    buyer_after = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer_after, gross=EXPOSURE_LIMIT_AT_BOUNDARY, net=0.00)


def test_offer_one_cent_over_the_gross_exposure_limit_persists_no_contract(api):
    """One cent past the limit is refused and leaves the contract table untouched.

    PRD: "The **gross pipeline** figure, stored as `outstanding_exposure_usd`, is the sum of `minimum_guarantee_usd` across every contract of this buyer whose `negotiation_status` is `OFFERED`, `COUNTERED`, `ACCEPTED` or `EXECUTED`, rounded half-up to two decimal places once at the end rather than per contract."

    Design: Difficulty/boundary_precision_check/buyer_exposure_limit_passes_at_exact_equality_and_fails_one_cent_over
    """
    env = _exposure_boundary_env(api)
    at_limit = assert_created(
        _offer(api, env, env["territory"]["id"], EXPOSURE_LIMIT_AT_BOUNDARY)
    )

    rejected = _offer(api, env, env["territory_fr"]["id"], ONE_CENT)
    validate_error(rejected, "ERR_BUYER_EXPOSURE_EXCEEDED", 422)

    rows, total = _count_contracts(api)
    assert total == 1, "the refused offer must not have persisted a contract row"
    assert rows[0]["id"] == at_limit["id"]

    buyer = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer, gross=EXPOSURE_LIMIT_AT_BOUNDARY, net=0.00)


def test_raising_the_exposure_limit_by_one_cent_lets_the_same_offer_through(api):
    """With the limit raised by a cent the identical one-cent offer lands back on equality.

    PRD: "A buyer's `status`, `credit_rating` and `exposure_limit_usd` may each be amended later by a `PlatformAdmin`."

    Design: Difficulty/boundary_precision_check/buyer_exposure_limit_passes_at_exact_equality_and_fails_one_cent_over
    """
    env = _exposure_boundary_env(api)
    assert_created(_offer(api, env, env["territory"]["id"], EXPOSURE_LIMIT_AT_BOUNDARY))
    validate_error(
        _offer(api, env, env["territory_fr"]["id"], ONE_CENT),
        "ERR_BUYER_EXPOSURE_EXCEEDED",
        422,
    )

    amended = assert_object_response(
        api.patch_buyer(
            env["buyer"]["id"],
            buyer_amendment_payload(exposure_limit_usd=EXPOSURE_LIMIT_ONE_CENT_HIGHER),
            make_platform_admin_headers(),
        )
    )
    assert_money(
        amended["exposure_limit_usd"],
        EXPOSURE_LIMIT_ONE_CENT_HIGHER,
        "exposure_limit_usd",
    )

    accepted = assert_created(_offer(api, env, env["territory_fr"]["id"], ONE_CENT))
    assert_contract_axes(accepted, negotiation="OFFERED")

    buyer = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer, gross=EXPOSURE_LIMIT_ONE_CENT_HIGHER, net=0.00)

    rows, total = _count_contracts(api)
    assert total == 2, "both accepted offers must be persisted"


# ==========================================================================
# The comparable sample count and the seven-year lookback edge
# ==========================================================================
def test_valuation_with_no_comparables_at_all_reports_the_empty_set_code(api):
    """An empty eligible set is a different failure from a thin one.

    PRD: "An empty set is rejected with `ERR_NO_COMPARABLE_TITLES`. A non-empty set of fewer than three rows is rejected with `ERR_INSUFFICIENT_COMP_SAMPLE`. Three rows exactly is sufficient."

    Design: Difficulty/boundary_precision_check/comparable_sample_boundary_at_min_sample_and_at_the_lookback_year_edge
    """
    env = _fr_valuation_env(api)

    validate_error(_value_fr(api, env), "ERR_NO_COMPARABLE_TITLES", 422)

    _rows, total = _count_valuations(api)
    assert total == 0, "the refused valuation must not have persisted a row"


def test_two_verified_comparables_and_a_third_outside_the_lookback_stay_short(api):
    """A 2018 comparable sits one year outside the inclusive 2019 edge and cannot count.

    PRD: "The seven-year lookback means that at the default clock reading of 1 August 2026 a comparable released in 2019 is eligible and one released in 2018 is not."

    Design: Difficulty/boundary_precision_check/comparable_sample_boundary_at_min_sample_and_at_the_lookback_year_edge
    """
    env = _fr_valuation_env(api)
    _add_comp(api, env["territory"]["id"], "FR Comp One", 900000.00, 2021)
    _add_comp(api, env["territory"]["id"], "FR Comp Two", 1100000.00, 2022)

    validate_error(_value_fr(api, env), "ERR_INSUFFICIENT_COMP_SAMPLE", 422)

    _add_comp(api, env["territory"]["id"], "FR Comp Stale", 5000000.00, 2018)
    validate_error(_value_fr(api, env), "ERR_INSUFFICIENT_COMP_SAMPLE", 422)

    _rows, total = _count_valuations(api)
    assert total == 0, "neither refused valuation may persist a row"


def test_an_unverified_comparable_inside_the_window_is_still_excluded(api):
    """A datapoint inside the lookback but unverified does not lift the sample to three.

    PRD: "When a `SalesAgent` or `HeadOfSales` values one territory for one film, supplying just three inputs — the `film_id`, the `territory_id` and the `method` — the service assembles the eligible comparable set by taking every comparable title whose `territory_id` equals the territory being valued, whose `genre` equals the film's `genre`, whose `verified` flag is true, and whose `release_year` is at or after the calendar year of the logical present instant minus seven."

    Design: Difficulty/boundary_precision_check/comparable_sample_boundary_at_min_sample_and_at_the_lookback_year_edge
    """
    env = _fr_valuation_env(api)
    _add_comp(api, env["territory"]["id"], "FR Comp One", 900000.00, 2021)
    _add_comp(api, env["territory"]["id"], "FR Comp Two", 1100000.00, 2022)
    unverified = _add_comp(
        api,
        env["territory"]["id"],
        "FR Comp Unverified",
        4000000.00,
        2023,
        verified=False,
    )
    assert unverified["verified"] is False

    validate_error(_value_fr(api, env), "ERR_INSUFFICIENT_COMP_SAMPLE", 422)

    _rows, total = _count_valuations(api)
    assert total == 0, "the refused valuation must not have persisted a row"


def test_a_verified_comparable_dated_exactly_2019_completes_the_sample(api):
    """The inclusive lookback edge yields a three-row sample and the filtered median.

    PRD: "`comp_median_usd` is the median `gross_license_fee_usd` of the eligible set, computed on a sort by `gross_license_fee_usd` ascending with `created_at` ascending as the tie-break."

    Design: Difficulty/boundary_precision_check/comparable_sample_boundary_at_min_sample_and_at_the_lookback_year_edge
    """
    env = _fr_valuation_env(api)
    _add_comp(api, env["territory"]["id"], "FR Comp One", 900000.00, 2021)
    _add_comp(api, env["territory"]["id"], "FR Comp Two", 1100000.00, 2022)
    _add_comp(api, env["territory"]["id"], "FR Comp Stale", 5000000.00, 2018)
    _add_comp(
        api,
        env["territory"]["id"],
        "FR Comp Unverified",
        4000000.00,
        2023,
        verified=False,
    )
    _add_comp(api, env["territory"]["id"], "FR Comp Edge", 1000000.00, 2019)

    valuation = assert_created(_value_fr(api, env))
    assert valuation["comp_sample_size"] == 3, (
        "the 2018 row and the unverified row are outside the eligible set"
    )
    assert_money(valuation["comp_median_usd"], 1000000.00, "comp_median_usd")

    _rows, total = _count_valuations(api)
    assert total == 1, "only the successful probe may have persisted a valuation"


def test_the_cast_adjusted_prices_follow_the_filtered_median(api):
    """The estimate, ask and floor derive from the median of the eligible rows only.

    PRD: "Under `CAST_ADJUSTED` — the packaging view used to argue the ask to buyers — `cast_multiplier` takes the value the cast tier function returns for the film's `principal_cast_score`, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index` and then by that cast multiplier, rounded half-up to two decimal places."

    Design: Difficulty/boundary_precision_check/comparable_sample_boundary_at_min_sample_and_at_the_lookback_year_edge
    """
    env = _fr_valuation_env(api)
    _add_comp(api, env["territory"]["id"], "FR Comp One", 900000.00, 2021)
    _add_comp(api, env["territory"]["id"], "FR Comp Two", 1100000.00, 2022)
    _add_comp(api, env["territory"]["id"], "FR Comp Stale", 5000000.00, 2018)
    _add_comp(
        api,
        env["territory"]["id"],
        "FR Comp Unverified",
        4000000.00,
        2023,
        verified=False,
    )
    _add_comp(api, env["territory"]["id"], "FR Comp Edge", 1000000.00, 2019)

    valuation = assert_created(_value_fr(api, env))
    assert_money(valuation["cast_multiplier"], 1.40, "cast_multiplier")
    assert_valuation_prices(valuation, 1400000.00, 1750000.00, 980000.00)

    reread = read_valuation(api, valuation["id"])
    assert_valuation_prices(reread, 1400000.00, 1750000.00, 980000.00)
    assert reread["status"] == "DRAFT"


# ==========================================================================
# The agency agreement as a gating entity: EXECUTED and inside its term window
# ==========================================================================
def _draft_agreement_env(api):
    """A registered picture whose agreement is still DRAFT, with a DE territory
    carrying three verified in-window comparables and a DRAFT valuation on the
    film-and-territory pair."""
    pin_clock(api, CLOCK_DEFAULT)
    film = make_film(api)
    agreement = make_agreement(api, film["id"])
    territory = make_territory(api)
    make_comparables(api, territory["id"])
    buyer = make_buyer(api, territory["id"])
    valuation = get_success_data(
        api.create_valuation(
            valuation_payload(film["id"], territory["id"], "CAST_ADJUSTED"),
            make_sales_agent_headers(),
        )
    )
    return {
        "film": film,
        "agreement": agreement,
        "territory": territory,
        "buyer": buyer,
        "valuation": valuation,
        "film_version": read_film(api, film["id"])["version"],
    }


def _publish(api, env, film_version, valuer="hos-valuer-1"):
    return api.publish_valuation(
        env["valuation"]["id"],
        publish_payload(film_version),
        make_head_of_sales_headers(valuer),
    )


def _in_market_after_execution(api, env):
    """Execute the agreement, publish the valuation and drive the picture to
    IN_MARKET, which the executed and in-term agreement now permits."""
    execute_agreement(api, env["agreement"]["id"])
    env["valuation"] = assert_object_response(_publish(api, env, env["film_version"]))
    get_success_data(
        api.set_film_state(
            env["film"]["id"], state_payload("PACKAGING"), make_platform_admin_headers()
        )
    )
    env["film"] = get_success_data(
        api.set_film_state(
            env["film"]["id"], state_payload("IN_MARKET"), make_head_of_sales_headers()
        )
    )
    return env


def test_publishing_a_valuation_is_refused_while_the_agreement_is_only_drafted(api):
    """A DRAFT agreement is not in force, so publication is refused and nothing moves.

    PRD: "Four operations require an in-force agreement for the relevant picture and reject with `ERR_AGENCY_AGREEMENT_NOT_IN_FORCE` when there is none: publishing a territory valuation, opening a pre-sale offer, countersigning an accepted contract, and logging a sales expense."

    Design: Difficulty/cross_entity_state_dependency/publish_and_offer_depend_on_the_agency_agreement_being_executed_and_in_term
    """
    env = _draft_agreement_env(api)
    assert env["agreement"]["status"] == "DRAFT"

    validate_error(
        _publish(api, env, env["film_version"]),
        "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE",
        422,
    )

    valuation = read_valuation(api, env["valuation"]["id"])
    assert valuation["status"] == "DRAFT", "the refused publication must not move the row"
    assert valuation["published_by_user_id"] is None
    assert valuation["published_at"] is None

    film = read_film(api, env["film"]["id"])
    assert film["version"] == env["film_version"], (
        "a refused publication must not increment the picture's version"
    )
    assert_film_counters(film, published_count=0)


def test_executing_the_agreement_stamps_the_term_end_and_lets_the_publish_through(api):
    """The identical publication succeeds once the agreement is EXECUTED and in term.

    PRD: "An agreement is **in force** when its `status` is `EXECUTED` and the logical present instant is at or after `term_start_date` and strictly before `term_end_date`."

    Design: Difficulty/cross_entity_state_dependency/publish_and_offer_depend_on_the_agency_agreement_being_executed_and_in_term
    """
    env = _draft_agreement_env(api)
    validate_error(
        _publish(api, env, env["film_version"]),
        "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE",
        422,
    )

    executed = execute_agreement(api, env["agreement"]["id"])
    assert executed["status"] == "EXECUTED"
    assert_instant(executed["term_end_date"], AGREEMENT_TERM_END, "term_end_date")

    published = assert_object_response(_publish(api, env, env["film_version"]))
    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == "hos-valuer-1"
    assert_instant(published["published_at"], CLOCK_DEFAULT, "published_at")

    film = read_film(api, env["film"]["id"])
    assert_film_counters(film, published_count=1)
    assert film["version"] == env["film_version"] + 1, (
        "publication increments the picture's version by exactly 1"
    )


def test_offer_is_refused_one_day_after_the_term_ends_though_the_row_reads_executed(api):
    """Past term_end_date the EXECUTED agreement is no longer in force for an offer.

    PRD: "An agreement is **in force** when its `status` is `EXECUTED` and the logical present instant is at or after `term_start_date` and strictly before `term_end_date`."

    Design: Difficulty/cross_entity_state_dependency/publish_and_offer_depend_on_the_agency_agreement_being_executed_and_in_term
    """
    env = _in_market_after_execution(api, _draft_agreement_env(api))
    buyer_version = read_buyer(api, env["buyer"]["id"])["version"]

    get_success_data(
        api.set_clock(
            clock_payload("2028-08-02T00:00:00Z"), make_platform_admin_headers()
        )
    )
    refused = api.create_contract(
        contract_payload(
            env["film"]["id"],
            env["buyer"]["id"],
            env["territory"]["id"],
            buyer_version,
            minimum_guarantee_usd=CONTRACT_MG,
        ),
        make_sales_agent_headers(),
    )
    validate_error(refused, "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE", 422)

    agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])
    assert agreement["status"] == "EXECUTED", (
        "the agreement row itself is untouched: only the term window has passed"
    )
    _rows, total = _count_contracts(api)
    assert total == 0, "the refused offer must not have persisted a contract row"


def test_offer_back_inside_the_term_window_is_accepted(api):
    """Moving the clock back inside the term lets the identical offer body through.

    PRD: "Four operations require an in-force agreement for the relevant picture and reject with `ERR_AGENCY_AGREEMENT_NOT_IN_FORCE` when there is none: publishing a territory valuation, opening a pre-sale offer, countersigning an accepted contract, and logging a sales expense."

    Design: Difficulty/cross_entity_state_dependency/publish_and_offer_depend_on_the_agency_agreement_being_executed_and_in_term
    """
    env = _in_market_after_execution(api, _draft_agreement_env(api))
    buyer_version = read_buyer(api, env["buyer"]["id"])["version"]
    body = contract_payload(
        env["film"]["id"],
        env["buyer"]["id"],
        env["territory"]["id"],
        buyer_version,
        minimum_guarantee_usd=CONTRACT_MG,
    )

    get_success_data(
        api.set_clock(
            clock_payload("2028-08-02T00:00:00Z"), make_platform_admin_headers()
        )
    )
    validate_error(
        api.create_contract(body, make_sales_agent_headers()),
        "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE",
        422,
    )

    get_success_data(
        api.set_clock(
            clock_payload("2026-09-01T00:00:00Z"), make_platform_admin_headers()
        )
    )
    contract = assert_created(api.create_contract(body, make_sales_agent_headers()))
    assert_contract_axes(contract, negotiation="OFFERED")
    assert_money(contract["minimum_guarantee_usd"], CONTRACT_MG, "minimum_guarantee_usd")


# ==========================================================================
# Facility approval reads live contract and buyer state, never its own cache
# ==========================================================================
def _two_facility_env(api):
    """An ACCEPTED contract for 2000000.00 plus two facilities created while it is
    still merely accepted, so both start with no eligible collateral at all."""
    env = accepted_contract(api)
    env["facility_1"] = make_facility(api, env["film"]["id"])
    env["facility_2"] = make_facility(
        api,
        env["film"]["id"],
        lender_name="Hanse Media Bank",
        discount_rate_pct=0.10,
        advance_rate_pct=0.60,
        facility_cap_usd=2000000.00,
        completion_bond_required=False,
    )
    return env


def _approve(api, facility_id, as_user_id):
    return api.set_facility_state(
        facility_id, state_payload("APPROVED"), make_lender_headers(as_user_id)
    )


def _amend_rating(api, buyer_id, credit_rating):
    return get_success_data(
        api.patch_buyer(
            buyer_id,
            buyer_amendment_payload(credit_rating=credit_rating),
            make_platform_admin_headers(),
        )
    )


def test_facility_approval_is_refused_while_the_only_contract_is_merely_accepted(api):
    """An ACCEPTED contract is not executed paper, so there is no eligible collateral.

    PRD: "`PROPOSED → APPROVED` is a `Lender` move requiring two things: at least one contract of the picture must be `EXECUTED` with a buyer whose `credit_rating` is `AAA`, `AA` or `A` and whose `status` is `ACTIVE`, and the facility's `eligible_collateral_usd` must be strictly greater than zero."

    Design: Difficulty/cross_entity_state_dependency/facility_approval_reads_live_contract_and_buyer_state_not_its_own_stored_collateral
    """
    env = _two_facility_env(api)
    assert_contract_axes(env["contract"], negotiation="ACCEPTED")

    validate_error(
        _approve(api, env["facility_1"]["id"], LENDER_APPROVER),
        "ERR_NO_ELIGIBLE_COLLATERAL",
        422,
    )

    facility = read_facility(api, env["film"]["id"], env["facility_1"]["id"])
    assert_facility_figures(facility, collateral=0.00, status="PROPOSED")
    assert facility["approved_by_user_id"] is None


def test_countersigning_recomputes_both_facilities_and_unblocks_the_approval(api):
    """Execution turns the accepted paper into discountable collateral for both facilities.

    PRD: "A contract of the facility's picture is eligible only when its `negotiation_status` is exactly `EXECUTED`, its `delivery_status` is anything other than `REJECTED`, and its buyer is investment-grade and trading: `credit_rating` of `AAA`, `AA` or `A`, and buyer `status` exactly `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/facility_approval_reads_live_contract_and_buyer_state_not_its_own_stored_collateral
    """
    env = _two_facility_env(api)
    validate_error(
        _approve(api, env["facility_1"]["id"], LENDER_APPROVER),
        "ERR_NO_ELIGIBLE_COLLATERAL",
        422,
    )

    executed_contract(api, env)

    first = read_facility(api, env["film"]["id"], env["facility_1"]["id"])
    assert_facility_figures(
        first,
        collateral=FACILITY_COLLATERAL,
        advance=FACILITY_ADVANCE_UNBONDED,
        status="PROPOSED",
    )
    second = read_facility(api, env["film"]["id"], env["facility_2"]["id"])
    assert_facility_figures(
        second,
        collateral=FACILITY2_COLLATERAL,
        advance=FACILITY2_COLLATERAL,
        status="PROPOSED",
    )

    approved = assert_object_response(
        _approve(api, env["facility_1"]["id"], LENDER_APPROVER)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == LENDER_APPROVER
    assert_facility_figures(
        approved, collateral=FACILITY_COLLATERAL, advance=FACILITY_ADVANCE_UNBONDED
    )


def test_a_downgrade_recomputes_the_approved_facility_and_still_blocks_the_cached_one(api):
    """The amendment recomputes only the APPROVED facility, yet the gate reads the buyer.

    PRD: "Every successful amendment increments the buyer's `version` by 1 — which is exactly what the offer-creation stale-version guard in §2.6 observes — and additionally recomputes `eligible_collateral_usd` and `advance_amount_usd` on every `APPROVED` or `DRAWN` banking facility whose picture has an executed contract with this buyer, since a downgrade or a suspension can remove that buyer's paper from a lender's collateral pool outright."

    Design: Difficulty/cross_entity_state_dependency/facility_approval_reads_live_contract_and_buyer_state_not_its_own_stored_collateral
    """
    env = _two_facility_env(api)
    executed_contract(api, env)
    approve_facility(api, env["facility_1"]["id"], LENDER_APPROVER)

    _amend_rating(api, env["buyer"]["id"], "BBB")

    first = read_facility(api, env["film"]["id"], env["facility_1"]["id"])
    assert_facility_figures(first, collateral=0.00, status="APPROVED")
    second = read_facility(api, env["film"]["id"], env["facility_2"]["id"])
    assert_facility_figures(
        second,
        collateral=FACILITY2_COLLATERAL,
        status="PROPOSED",
    )

    validate_error(
        _approve(api, env["facility_2"]["id"], LENDER_APPROVER_ALT),
        "ERR_NO_ELIGIBLE_COLLATERAL",
        422,
    )
    still_proposed = read_facility(api, env["film"]["id"], env["facility_2"]["id"])
    assert still_proposed["status"] == "PROPOSED"
    assert still_proposed["approved_by_user_id"] is None


def test_restoring_the_rating_repairs_the_first_facility_and_approves_the_second(api):
    """Back at AAA the identical approval succeeds and both facilities read their figures.

    PRD: "Approval records `approved_by_user_id` from `X-User-ID`, recomputes `eligible_collateral_usd` and `advance_amount_usd`, and re-derives the picture's `BANK_DEBT` waterfall tier from `SUSPENDED` to `ACTIVE` — until a bank is actually on the hook, that tier absorbs nothing."

    Design: Difficulty/cross_entity_state_dependency/facility_approval_reads_live_contract_and_buyer_state_not_its_own_stored_collateral
    """
    env = _two_facility_env(api)
    executed_contract(api, env)
    approve_facility(api, env["facility_1"]["id"], LENDER_APPROVER)
    _amend_rating(api, env["buyer"]["id"], "BBB")
    validate_error(
        _approve(api, env["facility_2"]["id"], LENDER_APPROVER_ALT),
        "ERR_NO_ELIGIBLE_COLLATERAL",
        422,
    )

    _amend_rating(api, env["buyer"]["id"], "AAA")

    repaired = read_facility(api, env["film"]["id"], env["facility_1"]["id"])
    assert_facility_figures(
        repaired,
        collateral=FACILITY_COLLATERAL,
        advance=FACILITY_ADVANCE_UNBONDED,
        status="APPROVED",
    )

    approved = assert_object_response(
        _approve(api, env["facility_2"]["id"], LENDER_APPROVER_ALT)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == LENDER_APPROVER_ALT
    assert_facility_figures(
        approved, collateral=FACILITY2_COLLATERAL, advance=FACILITY2_COLLATERAL
    )


# ==========================================================================
# Screening rooms: a mandatory 30-minute turnaround on both sides
# ==========================================================================
INCUMBENT_START = "2026-11-06T10:00:00Z"
INCUMBENT_END = "2026-11-06T12:00:00Z"


def _screening_env(api):
    """A PACKAGING picture and an OPEN market with four rooms, holding one screening
    in room 2 from 10:00 to 12:00 on the second market day."""
    env = packaged_slate(api)
    market = make_market(api)
    env["market"] = open_market(api, market["id"])
    env["incumbent"] = get_success_data(
        api.create_screening_slot(
            screening_slot_payload(
                env["market"]["id"],
                env["film"]["id"],
                2,
                INCUMBENT_START,
                INCUMBENT_END,
            ),
            make_sales_agent_headers(),
        )
    )
    return env


def _slot(api, env, room_number, start_at, end_at, **overrides):
    return api.create_screening_slot(
        screening_slot_payload(
            env["market"]["id"],
            env["film"]["id"],
            room_number,
            start_at,
            end_at,
            **overrides,
        ),
        make_sales_agent_headers(),
    )


def _count_slots(api):
    rows, meta = assert_list_response(
        api.list_screening_slots(make_sales_agent_headers(), {"limit": 100})
    )
    return rows, meta["total_count"]


def test_gaps_shorter_than_the_thirty_minute_turnaround_are_rejected(api):
    """Twenty minutes and twenty-nine minutes after the incumbent both conflict.

    PRD: "Concretely, the requested window conflicts with an existing occupation when the requested `start_at` falls strictly before that occupation's `end_at` extended forward by 30 minutes, **and** the occupation's `start_at` falls strictly before the requested `end_at` extended forward by 30 minutes."

    Design: Difficulty/resource_temporal_overlap/screening_room_requires_exactly_thirty_minutes_turnaround_on_both_sides
    """
    env = _screening_env(api)

    validate_error(
        _slot(api, env, 2, "2026-11-06T12:20:00Z", "2026-11-06T14:00:00Z", capacity=100),
        "ERR_SCREENING_ROOM_CONFLICT",
        409,
    )
    validate_error(
        _slot(api, env, 2, "2026-11-06T12:29:00Z", "2026-11-06T14:00:00Z", capacity=100),
        "ERR_SCREENING_ROOM_CONFLICT",
        409,
    )

    rows, total = _count_slots(api)
    assert total == 1, "neither refused probe may persist a screening slot"
    assert rows[0]["id"] == env["incumbent"]["id"]


def test_a_gap_of_exactly_thirty_minutes_after_the_incumbent_is_accepted(api):
    """One minute more than the rejected 12:29 probe clears the buffer exactly.

    PRD: "Because both comparisons are strict, a gap of exactly 30 minutes between two screenings is accepted, a gap of 29 minutes is rejected, and back-to-back screenings with no gap at all are rejected."

    Design: Difficulty/resource_temporal_overlap/screening_room_requires_exactly_thirty_minutes_turnaround_on_both_sides
    """
    env = _screening_env(api)
    validate_error(
        _slot(api, env, 2, "2026-11-06T12:29:00Z", "2026-11-06T14:00:00Z", capacity=100),
        "ERR_SCREENING_ROOM_CONFLICT",
        409,
    )

    accepted = assert_created(
        _slot(api, env, 2, "2026-11-06T12:30:00Z", "2026-11-06T14:00:00Z", capacity=100)
    )
    assert accepted["status"] == "HELD"
    assert accepted["room_number"] == 2
    assert_instant(accepted["start_at"], "2026-11-06T12:30:00Z", "start_at")

    _rows, total = _count_slots(api)
    assert total == 2


def test_the_turnaround_buffer_applies_on_the_earlier_side_too(api):
    """A screening ending exactly when the incumbent starts is refused; thirty minutes earlier passes.

    PRD: "Because both comparisons are strict, a gap of exactly 30 minutes between two screenings is accepted, a gap of 29 minutes is rejected, and back-to-back screenings with no gap at all are rejected."

    Design: Difficulty/resource_temporal_overlap/screening_room_requires_exactly_thirty_minutes_turnaround_on_both_sides
    """
    env = _screening_env(api)

    validate_error(
        _slot(
            api,
            env,
            2,
            "2026-11-06T09:00:00Z",
            "2026-11-06T10:00:00Z",
            slot_type="PRESS",
            capacity=40,
        ),
        "ERR_SCREENING_ROOM_CONFLICT",
        409,
    )
    _rows, total = _count_slots(api)
    assert total == 1, "the zero-gap probe on the earlier side persisted nothing"

    accepted = assert_created(
        _slot(
            api,
            env,
            2,
            "2026-11-06T08:00:00Z",
            "2026-11-06T09:30:00Z",
            slot_type="PRESS",
            capacity=40,
        )
    )
    assert accepted["status"] == "HELD"
    assert accepted["slot_type"] == "PRESS"
    assert_instant(accepted["end_at"], "2026-11-06T09:30:00Z", "end_at")


def test_the_identical_window_is_free_in_another_room_of_the_same_market(api):
    """Room 3 is a different resource, so the incumbent's window is available there.

    PRD: "The occupied resource is the pair of market and room number."

    Design: Difficulty/resource_temporal_overlap/screening_room_requires_exactly_thirty_minutes_turnaround_on_both_sides
    """
    env = _screening_env(api)

    validate_error(
        _slot(api, env, 2, INCUMBENT_START, INCUMBENT_END, capacity=120),
        "ERR_SCREENING_ROOM_CONFLICT",
        409,
    )

    other_room = assert_created(
        _slot(
            api,
            env,
            3,
            INCUMBENT_START,
            INCUMBENT_END,
            slot_type="MARKET_PREMIERE",
            capacity=300,
        )
    )
    assert other_room["room_number"] == 3
    assert other_room["status"] == "HELD"
    assert_instant(other_room["start_at"], INCUMBENT_START, "start_at")
    assert_instant(other_room["end_at"], INCUMBENT_END, "end_at")


def test_cancelling_the_incumbent_makes_its_own_window_re_bookable_at_once(api):
    """A CANCELLED slot leaves the occupancy input set, so the same window re-books.

    PRD: "Occupancy considers every existing slot of that same market and room number whose `status` is `HELD` or `CONFIRMED`; a `CANCELLED` slot releases its room immediately and its window becomes re-bookable at once."

    Design: Difficulty/resource_temporal_overlap/screening_room_requires_exactly_thirty_minutes_turnaround_on_both_sides
    """
    env = _screening_env(api)
    after = assert_created(
        _slot(api, env, 2, "2026-11-06T12:30:00Z", "2026-11-06T14:00:00Z", capacity=100)
    )
    before = assert_created(
        _slot(
            api,
            env,
            2,
            "2026-11-06T08:00:00Z",
            "2026-11-06T09:30:00Z",
            slot_type="PRESS",
            capacity=40,
        )
    )

    cancelled = assert_object_response(
        api.set_screening_slot_state(
            env["incumbent"]["id"], state_payload("CANCELLED"), make_sales_agent_headers()
        )
    )
    assert cancelled["status"] == "CANCELLED"

    rebooked = assert_created(
        _slot(api, env, 2, INCUMBENT_START, INCUMBENT_END, capacity=120)
    )
    assert rebooked["status"] == "HELD"
    assert rebooked["id"] != env["incumbent"]["id"]

    rows, total = _count_slots(api)
    assert total == 4, "the cancelled slot is retained alongside the three live ones"
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[env["incumbent"]["id"]] == "CANCELLED"
    for slot_id in (after["id"], before["id"], rebooked["id"]):
        assert by_id[slot_id] == "HELD"


# ==========================================================================
# Meeting tables: touching windows are legal, minutes are capped at 240
# ==========================================================================
LIVE_MEETING_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW")


def _meeting_env(api):
    """A PACKAGING picture, an OPEN market with ten tables, two trading buyers in
    territory DE, and a first 90-minute meeting for Rhein Films at table 3."""
    env = packaged_slate(api)
    env["territory"] = make_territory(api)
    env["buyer"] = make_buyer(api, env["territory"]["id"], company_name="Rhein Films")
    env["buyer_alt"] = make_buyer(
        api,
        env["territory"]["id"],
        company_name="Nordic Media",
        credit_rating="AA",
        exposure_limit_usd=2000000.00,
    )
    market = make_market(api)
    env["market"] = open_market(api, market["id"])
    env["meeting_1"] = get_success_data(
        api.create_buyer_meeting(
            buyer_meeting_payload(
                env["market"]["id"],
                env["buyer"]["id"],
                env["film"]["id"],
                3,
                "2026-11-06T10:00:00Z",
                "2026-11-06T11:30:00Z",
            ),
            make_sales_agent_headers(),
        )
    )
    return env


def _meeting(api, env, buyer_id, table_number, start_at, end_at):
    return api.create_buyer_meeting(
        buyer_meeting_payload(
            env["market"]["id"],
            buyer_id,
            env["film"]["id"],
            table_number,
            start_at,
            end_at,
        ),
        make_sales_agent_headers(),
    )


def _all_meetings(api):
    rows, meta = assert_list_response(
        api.list_buyer_meetings(make_sales_agent_headers(), {"limit": 100})
    )
    return rows, meta["total_count"]


def _booked_minutes(api, buyer_id):
    """The buyer's consumed budget, read back from the meetings the service persisted."""
    rows, _total = _all_meetings(api)
    return sum(
        row["duration_minutes"]
        for row in rows
        if row["buyer_id"] == buyer_id and row["status"] in LIVE_MEETING_STATUSES
    )


def test_a_meeting_starting_exactly_when_another_ends_shares_the_same_table(api):
    """No buffer applies to tables, so 11:30 immediately follows an 11:30 finish.

    PRD: "Table occupancy uses half-open intervals with **no buffer whatsoever**, so touching intervals are perfectly legal: a meeting ending at 10:00 and another starting at 10:00 coexist."

    Design: Difficulty/resource_temporal_overlap/meeting_tables_allow_touching_windows_but_cap_buyer_minutes_at_exactly_240
    """
    env = _meeting_env(api)

    touching = assert_created(
        _meeting(
            api,
            env,
            env["buyer_alt"]["id"],
            3,
            "2026-11-06T11:30:00Z",
            "2026-11-06T13:00:00Z",
        )
    )
    assert touching["status"] == "SCHEDULED"
    assert touching["table_number"] == 3
    assert touching["duration_minutes"] == 90, (
        "duration_minutes is the whole minutes between the two instants"
    )
    assert touching["outcome"] is None
    assert _booked_minutes(api, env["buyer_alt"]["id"]) == 90


def test_one_buyer_cannot_hold_two_tables_in_overlapping_windows(api):
    """The second resource is the market-and-buyer pair, whatever table is asked for.

    PRD: "The requested window must not overlap any live meeting at the same `table_number`, and it must not overlap any live meeting of the same `buyer_id` at this market regardless of which table that meeting occupies — a distributor cannot be in two rooms at once."

    Design: Difficulty/resource_temporal_overlap/meeting_tables_allow_touching_windows_but_cap_buyer_minutes_at_exactly_240
    """
    env = _meeting_env(api)

    validate_error(
        _meeting(
            api,
            env,
            env["buyer"]["id"],
            5,
            "2026-11-06T11:00:00Z",
            "2026-11-06T12:00:00Z",
        ),
        "ERR_MEETING_SLOT_CONFLICT",
        409,
    )

    rows, total = _all_meetings(api)
    assert total == 1, "the refused booking must not have persisted a meeting"
    assert rows[0]["id"] == env["meeting_1"]["id"]
    assert _booked_minutes(api, env["buyer"]["id"]) == 90


def test_booked_minutes_may_land_exactly_on_the_two_hundred_and_forty_cap(api):
    """Ninety plus ninety plus sixty reaches the cap precisely and is accepted.

    PRD: "If that total plus the new meeting's duration exceeds 240 minutes the booking is rejected with `ERR_MEETING_MINUTES_CAP_EXCEEDED`; a total landing exactly on 240 minutes is accepted."

    Design: Difficulty/resource_temporal_overlap/meeting_tables_allow_touching_windows_but_cap_buyer_minutes_at_exactly_240
    """
    env = _meeting_env(api)
    buyer_id = env["buyer"]["id"]

    second = assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T13:00:00Z", "2026-11-06T14:30:00Z")
    )
    assert second["duration_minutes"] == 90
    assert _booked_minutes(api, buyer_id) == 180

    third = assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T15:00:00Z", "2026-11-06T16:00:00Z")
    )
    assert third["duration_minutes"] == 60
    assert third["status"] == "SCHEDULED"
    assert _booked_minutes(api, buyer_id) == 240


def test_a_single_minute_past_the_cap_is_refused_and_persists_nothing(api):
    """At 240 booked minutes even a one-minute meeting is over budget.

    PRD: "The booked total is the sum of `duration_minutes` across every meeting of the same market and the same buyer whose `status` is `SCHEDULED`, `COMPLETED` or `NO_SHOW`."

    Design: Difficulty/resource_temporal_overlap/meeting_tables_allow_touching_windows_but_cap_buyer_minutes_at_exactly_240
    """
    env = _meeting_env(api)
    buyer_id = env["buyer"]["id"]
    assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T13:00:00Z", "2026-11-06T14:30:00Z")
    )
    assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T15:00:00Z", "2026-11-06T16:00:00Z")
    )
    assert _booked_minutes(api, buyer_id) == 240

    validate_error(
        _meeting(api, env, buyer_id, 5, "2026-11-06T17:00:00Z", "2026-11-06T17:01:00Z"),
        "ERR_MEETING_MINUTES_CAP_EXCEEDED",
        422,
    )

    _rows, total = _all_meetings(api)
    assert total == 3, "the refused booking must not have persisted a meeting"
    assert _booked_minutes(api, buyer_id) == 240


def test_cancellation_returns_minutes_while_a_no_show_keeps_consuming_them(api):
    """Only cancellation gives the budget back; a no-show holds its ninety minutes.

    PRD: "`SCHEDULED → CANCELLED` has no precondition either, but it is the only one of the three that releases anything: it frees the market-and-table interval **and** returns the meeting's `duration_minutes` to the buyer's budget."

    Design: Difficulty/resource_temporal_overlap/meeting_tables_allow_touching_windows_but_cap_buyer_minutes_at_exactly_240
    """
    env = _meeting_env(api)
    buyer_id = env["buyer"]["id"]
    second = assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T13:00:00Z", "2026-11-06T14:30:00Z")
    )
    assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T15:00:00Z", "2026-11-06T16:00:00Z")
    )
    assert _booked_minutes(api, buyer_id) == 240

    cancelled = assert_object_response(
        api.set_buyer_meeting_state(
            env["meeting_1"]["id"], state_payload("CANCELLED"), make_sales_agent_headers()
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert _booked_minutes(api, buyer_id) == 150

    touching = assert_created(
        _meeting(api, env, buyer_id, 5, "2026-11-06T16:00:00Z", "2026-11-06T17:00:00Z")
    )
    assert touching["duration_minutes"] == 60
    assert _booked_minutes(api, buyer_id) == 210

    no_show = assert_object_response(
        api.set_buyer_meeting_state(
            second["id"], state_payload("NO_SHOW"), make_sales_agent_headers()
        )
    )
    assert no_show["status"] == "NO_SHOW"
    assert _booked_minutes(api, buyer_id) == 210, (
        "a no-show does not return the meeting's minutes"
    )

    validate_error(
        _meeting(api, env, buyer_id, 6, "2026-11-06T18:00:00Z", "2026-11-06T18:40:00Z"),
        "ERR_MEETING_MINUTES_CAP_EXCEEDED",
        422,
    )
    assert _booked_minutes(api, buyer_id) == 210
