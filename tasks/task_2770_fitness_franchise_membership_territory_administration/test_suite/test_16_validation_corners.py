"""The precedence ladder read from both ends: one request that breaks nothing, and several
that break two bands at once.

A signing that satisfies all fifteen bands returns a fully populated contract. Beside it,
an ownership failure hides an out-of-range radius, a missing member hides a stale version,
a stale version hides a draft plan, and two statutes refuse work that is lawful elsewhere.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_club,
    create_franchisee,
    create_member,
    create_relocation_request_payload,
    create_royalty_report_payload,
    create_territory,
    create_transfer_request_payload,
    inspect_club,
    make_club_manager_headers,
    make_franchise_owner_headers,
    open_club,
    read_agreement,
    read_agreement_version,
    read_club,
    read_club_version,
    read_plan_template,
    read_royalty_report,
    set_clock_date,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
    submit_royalty_report,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _one_open_california_club_and_one_member(publish_plan: bool = True) -> dict:
    """A 650-bps operator with one OPEN CA club, a CORE12 plan and one registered member."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        publish_plan=publish_plan,
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    return scenario


def _sign(scenario: dict, member_id: str, expected_club_version: int):
    """One signing attempt by the home club's manager, returning the raw response."""
    payload = create_agreement_payload(
        member_id,
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        expected_club_version,
        signed_on="2026-08-01",
        multi_club_access=False,
    )
    return api_client.create_agreement(
        payload, make_club_manager_headers(scenario["club"]["id"])
    )


def _clean_signing(scenario: dict):
    """The request that violates none of the fifteen bands: real member, published plan,
    open compliant club, freshly read version, undiscounted price above the floor."""
    return _sign(scenario, scenario["member"]["id"], read_club_version(scenario["club"]["id"]))


def _two_operators_each_with_an_open_club() -> dict:
    """Two franchisees whose protected circles are 55 kilometres apart, each holding one
    OPEN club."""
    first = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    second = setup_single_club_franchise(
        legal_name="Ridgeway Athletics LLC",
        contact_email="ops@ridgewayath.example",
        club_name="Ridgeway Valley",
        opened_on="2024-06-01",
        center_lat=34.5,
        center_lng=-118.0,
        with_plan=False,
    )
    return {"first": first, "second": second}


def _file_relocation(club_id: str, acting_franchisee_id: str, requested_radius_km: float):
    payload = create_relocation_request_payload(
        club_id,
        requested_lat=34.52,
        requested_lng=-118.01,
        requested_radius_km=requested_radius_km,
        justification="Filed against a club we do not own.",
    )
    return api_client.create_relocation_request(
        payload, make_franchise_owner_headers(acting_franchisee_id)
    )


def test_a_signing_that_breaks_no_band_opens_on_both_initial_statuses():
    """Nothing in the request is unsatisfied, so the contract is created and each of its two
    independent dimensions sits at its own starting value.

    PRD 3.3: "A freshly signed agreement carries two independent status dimensions, and both
    start at their initial values. The contract dimension, `agreement_status`, starts at
    `PENDING` and takes the values `PENDING`, `ACTIVE`, `FROZEN`, `CANCELLATION_PENDING` and
    `CANCELLED`. The collections dimension, `dues_status`, starts at `CURRENT` and takes the
    values `CURRENT`, `PAST_DUE`, `DELINQUENT`, `IN_COLLECTIONS` and `WRITTEN_OFF`."

    Design: Corner/validations/corner_clean_agreement_create_satisfies_every_validation_priority
    """
    scenario = _one_open_california_club_and_one_member()

    agreement = validate_success(_clean_signing(scenario), expected_status=201)
    assert agreement["agreement_status"] == "PENDING"
    assert agreement["dues_status"] == "CURRENT"


def test_the_clean_signing_leaves_every_money_counter_and_settlement_field_empty():
    """No ledger entry and no cancellation have happened yet, so the four counters are 0 and
    the five settlement fields are null.

    PRD 3.3: "Alongside them the agreement is created with `outstanding_balance_cents` 0,
    `dues_paid_cents` 0, `delinquency_days` 0 and `transfer_count` 0, and with
    `cancellation_requested_on`, `cancellation_effective_on`, `refund_cents`,
    `early_termination_fee_cents` and `net_settlement_cents` all null."

    Design: Corner/validations/corner_clean_agreement_create_satisfies_every_validation_priority
    """
    scenario = _one_open_california_club_and_one_member()

    agreement = validate_success(_clean_signing(scenario), expected_status=201)
    assert agreement["outstanding_balance_cents"] == 0
    assert agreement["dues_paid_cents"] == 0
    assert agreement["delinquency_days"] == 0
    assert agreement["transfer_count"] == 0
    assert agreement["cancellation_requested_on"] is None
    assert agreement["cancellation_effective_on"] is None
    assert agreement["refund_cents"] is None
    assert agreement["early_termination_fee_cents"] is None
    assert agreement["net_settlement_cents"] is None


def test_the_clean_signing_pins_the_statute_the_two_prices_and_the_term_end():
    """The California club's statute, the template's two figures and a twelve-month term of
    thirty-day months are all copied onto the contract at creation.

    PRD 3.3: "Four terms are copied off their sources at signing and then frozen for the life
    of the contract. The agreement's `state_code` is taken from the home club's `state_code`
    and is never re-derived. `monthly_dues_base_cents` is a pinned copy of the template's
    `monthly_dues_cents`, and `initiation_fee_cents` a pinned copy of the template's
    `initiation_fee_cents`, so a later edit to the library cannot move a signed contract.
    `term_end_on` is the `signed_on` date plus 30 days multiplied by the template's
    `term_months`, using the 30-day month convention."

    Design: Corner/validations/corner_clean_agreement_create_satisfies_every_validation_priority
    """
    scenario = _one_open_california_club_and_one_member()

    agreement = validate_success(_clean_signing(scenario), expected_status=201)
    assert agreement["state_code"] == "CA"
    assert agreement["monthly_dues_base_cents"] == 4500
    assert agreement["initiation_fee_cents"] == 4900
    assert agreement["signed_on"] == "2026-08-01"
    assert agreement["term_end_on"] == "2027-07-27"


def test_the_thirty_day_notice_is_exactly_at_californias_statutory_ceiling():
    """The template asks for 30 days and California allows 30, so the lesser of the two is the
    template's own figure and the sale is lawful.

    PRD 3.3: "The stored `cancellation_notice_days` is the lesser of the template's
    `cancellation_notice_days` and the maximum notice days the agreement's governing statute
    allows; and independently of that, a template whose notice period exceeds the statutory
    maximum for the home club's state may not be sold there at all, which is refused with
    `ERR_STATUTE_NOTICE_LIMIT`."

    Design: Corner/validations/corner_clean_agreement_create_satisfies_every_validation_priority
    """
    scenario = _one_open_california_club_and_one_member()

    agreement = validate_success(_clean_signing(scenario), expected_status=201)
    assert agreement["cancellation_notice_days"] == 30
    assert read_plan_template(scenario["plan_template"]["id"])["cancellation_notice_days"] == 30


def test_the_undiscounted_price_clears_the_floor_and_is_stored_verbatim():
    """With no promotion, no corporate account and no multi-club right, the gross figure is
    the list price itself, which sits comfortably above the 3600-cent floor.

    PRD 3.3: "When the gross figure is at or above the floor, it is stored verbatim as
    `effective_monthly_dues_cents`, and that figure — like every other pinned term — never
    moves again, not when the quoted promotion is later withdrawn by the brand, and not when
    the membership is transferred to another club."

    Design: Corner/validations/corner_clean_agreement_create_satisfies_every_validation_priority
    """
    scenario = _one_open_california_club_and_one_member()

    agreement = validate_success(_clean_signing(scenario), expected_status=201)
    assert agreement["effective_monthly_dues_cents"] == 4500
    assert agreement["promo_discount_cents"] == 0
    assert agreement["corporate_credit_cents"] == 0
    assert agreement["multi_club_credit_cents"] == 0
    assert read_plan_template(scenario["plan_template"]["id"])["floor_price_cents"] == 3600


def test_ownership_answers_before_the_out_of_range_radius():
    """The filing names a club the acting franchisee does not own and carries a 0.1 km radius
    below the 0.5 km minimum; the ownership band is the earlier of the two.

    PRD 2.1: "A `FranchiseOwner` may therefore write only against `Territory`, `Club`,
    `RelocationRequest`, `Promotion`, and `RoyaltyReport` records whose owning `franchisee_id`
    equals `X-User-ID` — and for a `RelocationRequest`, the owning franchisee is that of the
    club named by `club_id`."

    Design: Corner/validations/corner_ownership_check_outranks_the_out_of_range_radius
    """
    setup = _two_operators_each_with_an_open_club()

    response = _file_relocation(
        setup["second"]["club"]["id"], setup["first"]["franchisee"]["id"], 0.1
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


def test_the_rightful_owner_may_still_draft_against_that_same_club():
    """The refusal was about who was asking, not about the club, so its own franchisee files
    the move and gets a fresh draft at the head of the review cycle.

    PRD 3.1: "The `FranchiseOwner` drafts the request against its own club, naming the
    `club_id`, the proposed `requested_lat` and `requested_lng`, a `requested_radius_km`
    between 0.5 and 50.0 inclusive, and a free-text `justification` making the business case.
    The draft is created in `DRAFT` with `revision_count` at 0"

    Design: Corner/validations/corner_ownership_check_outranks_the_out_of_range_radius
    """
    setup = _two_operators_each_with_an_open_club()
    _file_relocation(setup["second"]["club"]["id"], setup["first"]["franchisee"]["id"], 0.1)

    drafted = validate_success(
        _file_relocation(
            setup["second"]["club"]["id"], setup["second"]["franchisee"]["id"], 5.0
        ),
        expected_status=201,
    )
    assert drafted["status"] == "DRAFT"
    assert drafted["revision_count"] == 0
    assert drafted["club_id"] == setup["second"]["club"]["id"]
    assert drafted["requested_radius_km"] == 5.0


def _club_whose_version_moved_after_it_was_read(publish_plan: bool = True) -> dict:
    """The club's version is captured, then a scored inspection bumps it, so the captured
    value is stale by the time it is quoted."""
    scenario = _one_open_california_club_and_one_member(publish_plan=publish_plan)
    scenario["stale_version"] = read_club_version(scenario["club"]["id"])
    scenario["inspection"] = inspect_club(scenario["club"]["id"], "2026-07-15", 95, 92, 90, 12)
    return scenario


def _one_operator_with_a_california_and_a_new_york_club() -> dict:
    """One franchisee holding an OPEN CA club and an OPEN NY club, one member at each, and a
    signed California agreement on the 30-day-notice template."""
    scenario = _one_open_california_club_and_one_member()
    franchisee_id = scenario["franchisee"]["id"]
    ny_territory = create_territory(
        franchisee_id,
        center_lat=40.75,
        center_lng=-73.99,
        protected_radius_km=3.0,
        state_code="NY",
    )
    ny_club = create_club(
        ny_territory["id"],
        franchisee_id,
        name="Harborline Midtown",
        opened_on="2024-06-01",
        guest_fee_cents=1250,
    )
    scenario["ny_club"] = open_club(ny_club["id"], franchisee_id)
    scenario["ny_member"] = create_member(
        ny_club["id"],
        full_name="Dara Kim",
        email="dara.kim@example.com",
        home_state_code="NY",
    )
    scenario["california_agreement"] = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        signed_on="2026-08-01",
    )
    return scenario


def _sign_at_new_york(scenario: dict):
    payload = create_agreement_payload(
        scenario["ny_member"]["id"],
        scenario["ny_club"]["id"],
        scenario["plan_template"]["id"],
        read_club_version(scenario["ny_club"]["id"]),
        signed_on="2026-08-01",
        multi_club_access=False,
    )
    return api_client.create_agreement(
        payload, make_club_manager_headers(scenario["ny_club"]["id"])
    )


def test_the_unknown_member_is_reported_before_the_stale_version():
    """Existence sits above optimistic concurrency, so the caller hears about the member it
    invented rather than about the version it failed to refresh.

    PRD 2.6: "Every request is evaluated through the following fifteen precedence bands, in
    this exact order. The first band that rejects wins, and no later band is consulted; this
    matters because several bands can be simultaneously unsatisfied and the caller must
    receive the earlier code."

    Design: Corner/validations/corner_existence_check_runs_before_the_stale_version_check
    """
    scenario = _club_whose_version_moved_after_it_was_read()

    response = _sign(scenario, NON_EXISTENT_UUID, scenario["stale_version"])
    assert response.status_code == 404
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_STALE_CLUB_VERSION.value


def test_the_missing_member_answers_with_the_member_family_404():
    """The unresolvable reference is a `Member`, and the existence band has one code reserved
    for exactly that family.

    PRD 2.6: "`ERR_MEMBER_NOT_FOUND` for a missing `Member`; `ERR_PLAN_ASSET_NOT_FOUND` for a
    missing `MembershipPlanTemplate`, `Promotion` or `CorporateAccount`;"

    Design: Corner/validations/corner_existence_check_runs_before_the_stale_version_check
    """
    scenario = _club_whose_version_moved_after_it_was_read()

    response = _sign(scenario, NON_EXISTENT_UUID, scenario["stale_version"])
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_the_captured_club_version_really_had_gone_stale():
    """Naming the real member exposes the version problem that was there all along, which is
    what makes the earlier 404 a genuine precedence result.

    PRD 2.7: "Signing a membership agreement requires the non-optional input field
    `expected_club_version`, carrying the client's last observed `version` of the home `Club`.
    If that value does not equal the home club's current `version`, the create is rejected
    with `ERR_STALE_CLUB_VERSION` (HTTP 412)."

    Design: Corner/validations/corner_existence_check_runs_before_the_stale_version_check
    """
    scenario = _club_whose_version_moved_after_it_was_read()

    response = _sign(scenario, scenario["member"]["id"], scenario["stale_version"])
    validate_error(response, ApiErrorId.ERR_STALE_CLUB_VERSION.value, 412)
    assert read_club_version(scenario["club"]["id"]) > scenario["stale_version"]


def test_the_stale_version_answers_before_the_draft_plan():
    """Optimistic concurrency sits above the declared-transition band, so the caller is told
    to refresh before the plan problem is ever mentioned.

    PRD 2.7: "Signing a membership agreement requires the non-optional input field
    `expected_club_version`, carrying the client's last observed `version` of the home `Club`.
    If that value does not equal the home club's current `version`, the create is rejected
    with `ERR_STALE_CLUB_VERSION` (HTTP 412)."

    Design: Corner/validations/corner_stale_club_version_outranks_the_unpublished_plan_state
    """
    scenario = _club_whose_version_moved_after_it_was_read(publish_plan=False)

    response = _sign(scenario, scenario["member"]["id"], scenario["stale_version"])
    validate_error(response, ApiErrorId.ERR_STALE_CLUB_VERSION.value, 412)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PLAN_NOT_PUBLISHED.value


def test_the_draft_plan_surfaces_once_the_version_is_refreshed():
    """A freshly read version satisfies the concurrency band and the next band down refuses
    the sale, with the template still sitting unpublished in the library.

    PRD 3.2: "Only a `PUBLISHED` template may back a promotion or a membership agreement, and
    citing a `DRAFT` one is refused with `ERR_PLAN_NOT_PUBLISHED`."

    Design: Corner/validations/corner_stale_club_version_outranks_the_unpublished_plan_state
    """
    scenario = _club_whose_version_moved_after_it_was_read(publish_plan=False)
    _sign(scenario, scenario["member"]["id"], scenario["stale_version"])

    response = _clean_signing(scenario)
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_PUBLISHED.value)
    assert read_plan_template(scenario["plan_template"]["id"])["status"] == "DRAFT"


def test_a_thirty_day_notice_template_may_not_be_sold_at_a_new_york_club():
    """New York caps notice at 15 days, so the very template that is lawful in California is
    unsellable at the Midtown club.

    PRD 3.3: "a template whose notice period exceeds the statutory maximum for the home club's
    state may not be sold there at all, which is refused with `ERR_STATUTE_NOTICE_LIMIT`. A
    30-day-notice template is therefore unsellable at an `NY` club, whose statute caps notice
    at 15 days."

    Design: Corner/validations/corner_new_york_notice_ceiling_rejects_a_thirty_day_template
    """
    scenario = _one_operator_with_a_california_and_a_new_york_club()

    response = _sign_at_new_york(scenario)
    validate_error(response, ApiErrorId.ERR_STATUTE_NOTICE_LIMIT.value)


def test_the_governing_statute_is_read_off_the_club_not_the_member():
    """The refused sale was to a New York resident at a New York club; the accepted one is
    governed by California because that is where it was signed, whatever either member's
    residence says.

    PRD 2.9: "The governing statute for a membership is the one attached to the club where it
    was signed, not the one where the member happens to live: `home_state_code` on the
    `Member` record is captured for audit only."

    Design: Corner/validations/corner_new_york_notice_ceiling_rejects_a_thirty_day_template
    """
    scenario = _one_operator_with_a_california_and_a_new_york_club()
    _sign_at_new_york(scenario)

    assert scenario["ny_member"]["home_state_code"] == "NY"
    assert scenario["member"]["home_state_code"] == "CA"
    california = read_agreement(scenario["california_agreement"]["id"])
    assert california["state_code"] == "CA"
    assert california["cancellation_notice_days"] == 30


def test_the_refused_new_york_signing_leaves_that_club_without_memberships():
    """Nothing was created at the New York club, so its live membership counter has never
    moved off zero and it lists no agreements at all.

    PRD 3.3: "What signing does *not* do is move the club's `active_agreement_count`: a
    `PENDING` agreement is not yet an active membership, and the counter only moves when the
    first payment lands, as §3.4 describes."

    Design: Corner/validations/corner_new_york_notice_ceiling_rejects_a_thirty_day_template
    """
    scenario = _one_operator_with_a_california_and_a_new_york_club()
    _sign_at_new_york(scenario)

    assert read_club(scenario["ny_club"]["id"])["active_agreement_count"] == 0
    agreements, meta = validate_paginated(
        api_client.list_agreements(BRAND, params={"home_club_id": scenario["ny_club"]["id"]})
    )
    assert meta["total_count"] == 0
    assert agreements == []


def _california_membership_and_a_texas_club() -> dict:
    """One franchisee holding an OPEN CA club and an OPEN TX club, with one ACTIVE California
    membership whose dues are fully paid."""
    scenario = _one_open_california_club_and_one_member()
    franchisee_id = scenario["franchisee"]["id"]
    tx_territory = create_territory(
        franchisee_id,
        center_lat=32.78,
        center_lng=-96.8,
        protected_radius_km=4.0,
        state_code="TX",
    )
    tx_club = create_club(
        tx_territory["id"],
        franchisee_id,
        name="Harborline Deep Ellum",
        opened_on="2024-06-01",
        guest_fee_cents=1250,
    )
    scenario["tx_club"] = open_club(tx_club["id"], franchisee_id)
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
    )
    return scenario


def _file_transfer_to_texas(scenario: dict):
    payload = create_transfer_request_payload(
        scenario["agreement"]["id"],
        scenario["club"]["id"],
        scenario["tx_club"]["id"],
        read_agreement_version(scenario["agreement"]["id"]),
        reason="Member moving to Dallas.",
    )
    return api_client.create_transfer_request(
        payload, make_club_manager_headers(scenario["club"]["id"])
    )


def _accepted_august_report() -> dict:
    """One truthful August report from a 650-bps operator with a single ACTIVE membership,
    filed once the clock has moved past the end of the period."""
    scenario = _one_open_california_club_and_one_member()
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
    )
    set_clock_date("2026-09-05")
    scenario["report"] = submit_royalty_report(scenario["franchisee"]["id"], "2026-08", 1)
    return scenario


def _resubmit_august(scenario: dict, reported_member_count: int = 1):
    return api_client.create_royalty_report(
        create_royalty_report_payload(
            scenario["franchisee"]["id"], "2026-08", reported_member_count
        ),
        make_franchise_owner_headers(scenario["franchisee"]["id"]),
    )


def test_a_california_membership_cannot_be_handed_to_a_texas_club():
    """Both clubs are open, compliant and owned by the same operator, and the membership is
    not in arrears — the only obstacle is California's refusal of cross-state portability.

    PRD 3.6: "A destination club whose `state_code` differs from the agreement's own pinned
    `state_code` is prohibited whenever the agreement's governing statute forbids cross-state
    portability, which is the case for `CA`, and the attempt is refused with
    `ERR_CROSS_STATE_TRANSFER_PROHIBITED`; `TX` and `NY` agreements travel freely. Finally, a
    membership in arrears cannot be handed off: a `dues_status` of `DELINQUENT`,
    `IN_COLLECTIONS` or `WRITTEN_OFF` is refused with `ERR_TRANSFER_BLOCKED_BY_ARREARS`."

    Design: Corner/validations/corner_california_agreement_may_not_transfer_across_a_state_line
    """
    scenario = _california_membership_and_a_texas_club()

    assert scenario["agreement"]["dues_status"] == "CURRENT"
    response = _file_transfer_to_texas(scenario)
    validate_error(response, ApiErrorId.ERR_CROSS_STATE_TRANSFER_PROHIBITED.value)


def test_the_statute_is_read_off_the_pinned_state_code_and_the_membership_stays_put():
    """The refusal is decided by the statute the contract carries, not by the destination, and
    the membership is left exactly where it was signed.

    PRD 2.9: "Once an agreement's `state_code` is pinned at signing it is never re-derived —
    neither a relocation that moves the club's geometry nor a transfer that moves the
    membership to a club in another state changes which statute governs the contract."

    Design: Corner/validations/corner_california_agreement_may_not_transfer_across_a_state_line
    """
    scenario = _california_membership_and_a_texas_club()
    _file_transfer_to_texas(scenario)

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["state_code"] == "CA"
    assert agreement["home_club_id"] == scenario["club"]["id"]
    assert agreement["transfer_count"] == 0
    assert read_club(scenario["tx_club"]["id"])["state_code"] == "TX"


def test_a_report_for_the_month_the_clock_sits_in_is_refused():
    """The franchisee, the period format and the head count are each individually lawful; the
    2026-08 period simply has not ended at the 2026-08-01 clock.

    PRD 3.9: "The period must be closed: a `period_month` equal to or later than the logical
    clock's own month is refused with `ERR_REPORT_PERIOD_NOT_CLOSED`."

    Design: Corner/validations/corner_royalty_report_for_a_period_still_running_is_rejected
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        royalty_rate_bps=650,
    )

    response = api_client.create_royalty_report(
        create_royalty_report_payload(franchisee["id"], "2026-08", 0),
        make_franchise_owner_headers(franchisee["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_NOT_CLOSED.value)


def test_the_month_before_is_closed_and_a_zero_report_is_accepted():
    """At the same clock the previous month is finished, and a nil return against a nil
    verified set is truthful by definition.

    PRD 3.9: "When `verified_member_count` is 0 the division is undefined, so `variance_pct`
    is exactly 0.00 if `reported_member_count` is also 0 and exactly 100.00 otherwise. The
    report is created `SUBMITTED` and immediately auto-resolves on the absolute value of
    `variance_pct` against a tolerance of 5.00 percent: a variance whose magnitude exceeds
    5.00 resolves to `DISPUTED`, and anything at or within 5.00 resolves to `ACCEPTED`."

    Design: Corner/validations/corner_royalty_report_for_a_period_still_running_is_rejected
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        royalty_rate_bps=650,
    )

    report = validate_success(
        api_client.create_royalty_report(
            create_royalty_report_payload(franchisee["id"], "2026-07", 0),
            make_franchise_owner_headers(franchisee["id"]),
        ),
        expected_status=201,
    )
    assert report["verified_member_count"] == 0
    assert report["variance_pct"] == 0.00
    assert report["status"] == "ACCEPTED"


def test_a_second_report_for_the_same_period_is_refused():
    """The pair of franchisee and period admits exactly one report, so the byte-identical
    resubmission is turned away.

    PRD 3.9: "Only one report may exist per `franchisee_id` and `period_month` pair, and a
    second is refused with `ERR_DUPLICATE_ROYALTY_PERIOD`."

    Design: Corner/validations/corner_second_royalty_report_for_the_same_period_is_rejected
    """
    scenario = _accepted_august_report()

    validate_error(
        _resubmit_august(scenario), ApiErrorId.ERR_DUPLICATE_ROYALTY_PERIOD.value
    )


def test_the_surviving_report_keeps_both_royalty_figures_it_was_accepted_with():
    """One membership at list price gives the same 4500-cent basis on both sides, and 650
    basis points of it rounds half up from 292.5 to 293 cents twice over.

    PRD 3.9: "The reported basis, `reported_dues_basis_cents`, is `reported_member_count`
    multiplied by the brand list price of 4500 cents per member per month, which ignores every
    promotion, corporate credit and multi-club credit; `reported_royalty_cents` is that basis
    multiplied by the franchisee's `royalty_rate_bps` divided by 10000, rounded half up to
    whole cents. The verified basis produces `royalty_due_cents` the same way, from
    `verified_dues_basis_cents` and the same rate."

    Design: Corner/validations/corner_second_royalty_report_for_the_same_period_is_rejected
    """
    scenario = _accepted_august_report()
    _resubmit_august(scenario)

    report = read_royalty_report(scenario["report"]["id"])
    assert report["reported_dues_basis_cents"] == 4500
    assert report["verified_dues_basis_cents"] == 4500
    assert report["reported_royalty_cents"] == 293
    assert report["royalty_due_cents"] == 293
    assert report["status"] == "ACCEPTED"


def test_the_refused_duplicate_leaves_the_operator_holding_one_report():
    """A restated head count does not buy a second filing either: the uniqueness key is the
    pair, not the reported count, so the ledger of reports never grows.

    PRD 3.9: "Only one report may exist per `franchisee_id` and `period_month` pair, and a
    second is refused with `ERR_DUPLICATE_ROYALTY_PERIOD`."

    Design: Corner/validations/corner_second_royalty_report_for_the_same_period_is_rejected
    """
    scenario = _accepted_august_report()
    validate_error(
        _resubmit_august(scenario, reported_member_count=4),
        ApiErrorId.ERR_DUPLICATE_ROYALTY_PERIOD.value,
    )

    reports, meta = validate_paginated(
        api_client.list_royalty_reports(
            BRAND, params={"franchisee_id": scenario["franchisee"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert reports[0]["id"] == scenario["report"]["id"]
    assert reports[0]["period_month"] == "2026-08"
