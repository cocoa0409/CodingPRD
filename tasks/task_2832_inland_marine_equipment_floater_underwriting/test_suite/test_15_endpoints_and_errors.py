"""Computed reads, sub-resource walks, and the four HTTP families a refusal lands in."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import assert_instant_equals, find_entry
from test_helpers.test_users import (
    ACTUARY,
    ADJUSTER,
    MANAGER,
    UNDERWRITER,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
)
from test_helpers.types import Ledger, LedgerEntryType

NOWHERE = "00000000-0000-0000-0000-0000000000ff"


def file_with_a_blanket_limit_it_is_not_charged_on(api):
    """The canonical scheduled file whose part also declares a blanket alternative."""
    return fixtures.build_scheduled_file(
        api,
        part_kwargs=dict(blanket_limit_cents=10000000, coinsurance_pct_bp=9000),
        quote_it=True)


def test_the_premium_summary_derives_both_bases_and_charges_only_one(api):
    """One read hands back 173318 scheduled beside 188510 blanket, charging neither.

    PRD: The policy's premium summary is a computed read that derives everything on the fly and returns `sum_of_part_premiums_cents`, the `expense_load_bp` actually in force for the policy's territory, `written_premium_cents`, `scheduled_basis_premium_cents`, `blanket_basis_premium_cents`, a `minimum_premium_applied` boolean stating whether the floor rather than the loaded figure produced the written premium, `total_insured_value_cents`, `premium_balance_cents`, `incurred_loss_cents` and `referral_required`.
    PRD: Next compute the coinsurance credit: 500 basis points when the part's `coinsurance_pct_bp` is at least 9,000 — that is, when the insured co-insures at 90 percent or better — and zero otherwise.
    PRD: The two comparison roll-ups run the identical load-then-floor pipeline over the corresponding variant premiums, producing `scheduled_basis_premium_cents` and `blanket_basis_premium_cents`.
    Design: Corner/endpoints/corner_premium_summary_computed_read
    """
    ctx = file_with_a_blanket_limit_it_is_not_charged_on(api)
    before = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))

    summary = validate_success(api.get_premium_summary(ctx.policy_id, MANAGER))

    assert summary["sum_of_part_premiums_cents"] == 173318
    assert summary["expense_load_bp"] == 10400
    assert summary["written_premium_cents"] == 180251
    assert summary["scheduled_basis_premium_cents"] == 180251
    assert summary["blanket_basis_premium_cents"] == 188510
    assert summary["minimum_premium_applied"] is False
    assert summary["total_insured_value_cents"] == 8160000
    assert summary["premium_balance_cents"] == 0
    assert summary["incurred_loss_cents"] == 0
    assert summary["referral_required"] is False

    after = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert after["version"] == before["version"]
    assert after["written_premium_cents"] == 180251
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["rated_premium_cents"] == 173318
    assert part["rating_basis"] == "SCHEDULED"
    assert part["blanket_limit_cents"] == 10000000
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["rated_premium_cents"] == 173318


def test_the_worksheet_reports_both_settlement_bases_before_either_is_chosen(api):
    """2900000 and 8060000 coexist on one inspected claim, and the read moves nothing.

    PRD: The settlement worksheet is a computed read that derives everything on the fly and returns `valuation_at_loss_cents`, `constructive_total_loss_threshold_cents`, a `constructive_total_loss_reached` boolean stating whether `repair_estimate_cents` has reached the threshold, `underreporting_factor_bp`, `claim_limit_cents`, the part's `deductible_cents`, `loss_of_use_paid_cents`, both `repair_basis_settlement_cents` and `total_loss_basis_settlement_cents` side by side, a `repair_basis_selectable` boolean that is true exactly when an adjustment on the repair basis would be permitted, and the part's remaining `aggregate_available_cents`.
    PRD: For every `part_type` other than `REPORTING_FORM`, `underreporting_factor_bp` is 10000 and the penalty does not exist.
    PRD: `claim_limit_cents` is the governing part's `per_item_limit_cents` when `part_type` is `SCHEDULED_EQUIPMENT` or `RENTED_LEASED`, its `blanket_limit_cents` when `BLANKET_EQUIPMENT`, its `reporting_limit_cents` when `REPORTING_FORM`, the subject shipment's `applicable_limit_cents` when `TRANSIT`, and the subject floater's `installed_value_limit_cents` when `INSTALLATION_FLOATER`.
    Design: Corner/endpoints/corner_settlement_worksheet_computed_read
    """
    ctx = fixtures.build_in_force_file(api)
    claim = fixtures.build_inspected_claim(api, ctx, 3000000, 8160000,
                                          loss_type="COLLISION")

    worksheet = validate_success(api.get_settlement_worksheet(claim["id"], ADJUSTER))

    assert worksheet["valuation_at_loss_cents"] == 8160000
    assert worksheet["constructive_total_loss_threshold_cents"] == 6120000
    assert worksheet["constructive_total_loss_reached"] is False
    assert worksheet["underreporting_factor_bp"] == 10000
    assert worksheet["claim_limit_cents"] == 20000000
    assert worksheet["deductible_cents"] == 100000
    assert worksheet["loss_of_use_paid_cents"] == 0
    assert worksheet["repair_basis_settlement_cents"] == 2900000
    assert worksheet["total_loss_basis_settlement_cents"] == 8060000
    assert worksheet["repair_basis_selectable"] is True
    assert worksheet["aggregate_available_cents"] == 200000000

    unmoved = get_success_data(api.get_claim(claim["id"], ADJUSTER))
    assert unmoved["adjustment_status"] == "INSPECTED"
    assert unmoved["adjustment_basis"] is None
    assert unmoved["settlement_amount_cents"] is None
    assert unmoved["settlement_paid_cents"] is None
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["aggregate_paid_net_cents"] == 0


def indexed_file(api):
    """The canonical file on a cell that also publishes a replacement-cost index."""
    return fixtures.build_scheduled_file(
        api, rate_rule_kwargs=dict(replacement_cost_index_bp=11000), quote_it=True)


def test_endorsing_the_valuation_basis_stores_the_term_without_restating_the_money(api):
    """The PATCH bumps the part's version and leaves 173318 exactly where it was.

    PRD: Switching `rating_basis` or `valuation_basis` does not itself restate the charged premium; it changes which variant of the equipment roll-up will produce `rated_premium_cents` at the next quote.
    PRD: The endorsement advances the part's `version` by 1, and it is refused with `ERR_PART_VOID` on a voided part and with `ERR_POLICY_NOT_MUTABLE` when the owning policy is past mutability.
    Design: Corner/endpoints/corner_patch_coverage_part_defers_repricing_to_the_next_quote
    """
    ctx = indexed_file(api)
    token = fixtures.part_version(api, ctx.part_id)

    patched = validate_success(api.patch_coverage_part(
        ctx.part_id, factories.part_endorsement(valuation_basis="REPLACEMENT_COST"),
        UNDERWRITER))

    assert patched["valuation_basis"] == "REPLACEMENT_COST"
    assert patched["version"] == token + 1
    assert patched["rated_premium_cents"] == 173318

    item = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert item["insured_value_cents"] == 8160000
    assert item["rated_premium_cents"] == 173318
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["written_premium_cents"] == 180251
    assert policy["total_insured_value_cents"] == 8160000
    assert policy["status"] == "QUOTED"


def test_the_endorsed_basis_governs_the_next_unit_not_the_one_already_rated(api):
    """A re-quote leaves the copied ACV basis alone; the newcomer is indexed to 13200000.

    PRD: Where `geo_tracker_installed` is omitted it is false; where `ownership` is omitted it is `OWNED`; where the item-level `valuation_basis` is omitted the parent part's `valuation_basis` is copied onto the item at creation, so the item always carries an explicit basis afterwards.
    PRD: Under `REPLACEMENT_COST`, `insured_value_cents` is the original cost multiplied by the selected rate cell's `replacement_cost_index_bp`, divided by ten thousand, and rounded half-up once.
    PRD: A `DRAFT` policy becomes `QUOTED`; a `QUOTED` policy re-quotes to `QUOTED` again, which is how a policy is re-priced after a schedule or limit endorsement without leaving the quoted state.
    Design: Corner/endpoints/corner_patch_coverage_part_defers_repricing_to_the_next_quote
    """
    ctx = indexed_file(api)
    get_success_data(api.patch_coverage_part(
        ctx.part_id, factories.part_endorsement(valuation_basis="REPLACEMENT_COST"),
        UNDERWRITER))

    requoted = validate_success(api.quote_policy(ctx.policy_id, UNDERWRITER))

    assert requoted["status"] == "QUOTED"
    survivor = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert survivor["valuation_basis"] == "ACV"
    assert survivor["insured_value_cents"] == 8160000
    assert survivor["rated_premium_cents"] == 173318

    newcomer = fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                      description="Excavator E2")

    assert newcomer["valuation_basis"] == "REPLACEMENT_COST"
    assert newcomer["insured_value_cents"] == 13200000
    assert newcomer["rated_premium_cents"] == 322423
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 495741
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["sum_of_part_premiums_cents"] == 495741
    assert policy["written_premium_cents"] == 515571
    assert policy["total_insured_value_cents"] == 21360000


def test_the_sweep_is_a_no_op_on_the_grace_date_and_bites_the_day_after(api):
    """Nothing is minted while due_date equals the clock; one period falls a day later.

    PRD: For every reporting period of the part, derived as described above, whose `due_date` is strictly before the logical clock's current date and for which no report on the part in status `SUBMITTED`, `ACCEPTED` or `PENALIZED` exists for that exact period, the sweep mints a report with `reported_value_cents` of zero, `period_earned_premium_cents` and `late_penalty_cents` of zero, `submitted_at` stamped from the logical clock, and status `DELINQUENT`.
    PRD: A period whose `due_date` equals the clock date is not yet swept.
    PRD: The response reports `swept_period_count`, the `delinquent_report_ids` it created, the resulting `policy_status`, and the `part_id` it ran against.
    PRD: The field `latest_report_period_end_date` is the greatest `period_end_date` among the reports on the part whose status is `SUBMITTED`, `ACCEPTED`, `PENALIZED` or `DELINQUENT`, with ties broken by the greatest `created_at`, and is null when the part has no such report.
    Design: Corner/endpoints/corner_reporting_sweep_no_op_at_the_grace_boundary
    """
    ctx = fixtures.build_reporting_file(api)
    token = fixtures.part_version(api, ctx.part_id)
    fixtures.set_clock(api, "2026-09-15T00:00:00Z")

    quiet = validate_success(api.run_reporting_sweep(ctx.part_id, UNDERWRITER))

    assert quiet["swept_period_count"] == 0
    assert quiet["delinquent_report_ids"] == []
    assert quiet["policy_status"] == "IN_FORCE"
    assert quiet["part_id"] == ctx.part_id
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["latest_report_period_end_date"] is None
    assert part["version"] == token + 1
    empty, meta = validate_paginated(api.list_value_reports(
        ctx.part_id, UNDERWRITER, limit=100, offset=0))
    assert (empty, meta["total_count"]) == ([], 0)
    standing = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert standing["status"] == "IN_FORCE"
    assert standing["premium_balance_cents"] == 100000

    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    biting = validate_success(api.run_reporting_sweep(ctx.part_id, UNDERWRITER))

    assert biting["swept_period_count"] == 1
    assert len(biting["delinquent_report_ids"]) == 1
    assert biting["policy_status"] == "SUSPENDED"
    swept = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert swept["latest_report_period_end_date"] == "2026-08-31"
    assert swept["version"] == token + 2

    rows, meta = validate_paginated(api.list_value_reports(
        ctx.part_id, UNDERWRITER, limit=100, offset=0))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == biting["delinquent_report_ids"][0]
    assert rows[0]["status"] == "DELINQUENT"
    assert rows[0]["reported_value_cents"] == 0
    assert rows[0]["period_start_date"] == "2026-08-01"
    assert rows[0]["period_end_date"] == "2026-08-31"
    assert rows[0]["due_date"] == "2026-09-15"
    assert rows[0]["period_earned_premium_cents"] == 0
    assert rows[0]["late_penalty_cents"] == 0
    assert_instant_equals(rows[0]["submitted_at"], "2026-09-16T00:00:00Z")
    suspended = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["premium_balance_cents"] == 100000


def restated_august(api):
    """An August period accepted at 9000000, then restated at 12000000."""
    ctx = fixtures.build_reporting_file(api)
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    first = fixtures.file_value_report(api, ctx.part_id, "2026-08-01", "2026-08-31",
                                       9000000, headers=ctx["policyholder"])
    ctx["first"] = get_success_data(api.adjudicate_value_report(first["id"], UNDERWRITER))
    return ctx


def test_the_superseded_reports_link_is_walked_in_one_direction_only(api):
    """The restatement lists its predecessor; the predecessor lists nobody.

    PRD: A report exposes the reports it superseded: the superseded-reports list of a given report returns every report whose `superseded_by_report_id` equals that report's `id`, which is how the self-referential restatement chain is walked.
    PRD: Every prior report on the same part for the identical period whose status is not already `SUPERSEDED` moves to `SUPERSEDED`, with its `superseded_by_report_id` set to the new report's `id`.
    Design: Corner/endpoints/corner_superseded_reports_sub_resource_walks_the_self_reference
    """
    ctx = restated_august(api)
    assert ctx["first"]["status"] == "ACCEPTED"
    assert ctx["first"]["period_earned_premium_cents"] == 19110

    second = fixtures.file_value_report(api, ctx.part_id, "2026-08-01", "2026-08-31",
                                        12000000, headers=ctx["policyholder"])

    assert second["status"] == "SUBMITTED"
    assert second["superseded_by_report_id"] is None
    predecessor = get_success_data(api.get_value_report(ctx["first"]["id"], UNDERWRITER))
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by_report_id"] == second["id"]

    behind, meta = validate_paginated(api.list_superseded_reports(
        second["id"], UNDERWRITER, limit=100, offset=0))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in behind] == [ctx["first"]["id"]]
    assert behind[0]["reported_value_cents"] == 9000000
    assert behind[0]["status"] == "SUPERSEDED"

    ahead, ahead_meta = validate_paginated(api.list_superseded_reports(
        ctx["first"]["id"], UNDERWRITER, limit=100, offset=0))
    assert ahead == []
    assert ahead_meta["total_count"] == 0
    assert ahead_meta["has_more"] is False


def test_the_restatement_backs_the_predecessor_s_earned_premium_out_of_the_book(api):
    """Three rows: the deposit, the 19110 that was earned, and the 19110 undone.

    PRD: When a superseded predecessor was `ACCEPTED` or `PENALIZED` its money must be undone: its `period_earned_premium_cents` is subtracted from the part's `earned_reported_premium_cents` and a compensating `REPORTING_ADJUSTMENT` entry is appended to the premium ledger for the negative of that amount, after which `premium_balance_cents` is recomputed.
    PRD: A superseded report contributes nothing to `earned_reported_premium_cents` thereafter.
    Design: Corner/endpoints/corner_superseded_reports_sub_resource_walks_the_self_reference
    """
    ctx = restated_august(api)
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["earned_reported_premium_cents"] == 19110

    fixtures.file_value_report(api, ctx.part_id, "2026-08-01", "2026-08-31",
                               12000000, headers=ctx["policyholder"])

    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.PREMIUM))
    assert meta["total_count"] == 3
    assert sorted(row["amount_cents"] for row in rows) == [-19110, 19110, 100000]
    assert find_entry(rows, LedgerEntryType.INITIAL_PREMIUM)["amount_cents"] == 100000
    assert [row["entry_type"] for row in rows].count("REPORTING_ADJUSTMENT") == 2

    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["earned_reported_premium_cents"] == 0
    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["premium_balance_cents"] == 100000
    assert policy["premium_balance_cents"] == sum(r["amount_cents"] for r in rows)


def test_deleting_the_only_unit_before_inception_writes_no_ledger_row_at_all(api):
    """The part falls to 0, the policy falls to its floor, and the book stays empty.

    PRD: An item may be endorsed off the schedule from either `RATED` or `ACTIVE`, moving to `REMOVED` with `removed_at` stamped from the logical clock.
    PRD: While the policy is still `DRAFT`, `QUOTED`, `REFERRED` or `BOUND`, no endorsement entry is written at all — the unit is simply folded into the quote.
    PRD: Items that are `REMOVED` or `TOTALED` are excluded from the moment they leave risk.
    PRD: Finally the minimum premium floor is applied, strictly **after** the load: `written_premium_cents` is the greater of the loaded figure and the policy's `minimum_premium_cents`.
    Design: Corner/endpoints/corner_delete_equipment_item_before_inception_writes_no_ledger_entry
    """
    ctx = fixtures.build_scheduled_file(api, quote_it=True)
    assert ctx.quoted["written_premium_cents"] == 180251

    removed = validate_success(api.delete_equipment_item(ctx.item_id, UNDERWRITER))

    assert removed["status"] == "REMOVED"
    assert_instant_equals(removed["removed_at"], "2026-08-01T00:00:00Z")
    assert removed["rated_premium_cents"] == 173318
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 0

    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["sum_of_part_premiums_cents"] == 0
    assert policy["written_premium_cents"] == 100000
    assert policy["total_insured_value_cents"] == 0
    assert policy["status"] == "QUOTED"
    assert policy["premium_balance_cents"] == 0

    book, book_meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0))
    assert (book, book_meta["total_count"]) == ([], 0)

    off_risk, off_meta = validate_paginated(api.list_part_equipment_items(
        ctx.part_id, UNDERWRITER, limit=100, offset=0, status="REMOVED"))
    assert off_meta["total_count"] == 1
    assert [row["id"] for row in off_risk] == [ctx.item_id]


def test_the_two_books_are_listed_separately_and_never_netted_together(api):
    """One premium row and one loss row, reachable by ledger, by type and by claim.

    PRD: There are eight entry types, and each belongs to exactly one book.
    PRD: The two conserved quantities on a policy follow directly: `premium_balance_cents` is the sum of `amount_cents` over that policy's entries in the `PREMIUM` ledger, and `incurred_loss_cents` is the sum over its entries in the `LOSS` ledger.
    PRD: Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.
    PRD: Every filter is optional, and omitting one means the corresponding dimension is unconstrained.
    Design: Corner/endpoints/corner_ledger_entries_listings_split_premium_from_loss
    """
    ctx = fixtures.build_in_force_file(api)
    claim = fixtures.build_repair_claim(api, ctx, loss_type="COLLISION")
    settled = fixtures.settle(api, claim["id"])
    assert settled["settlement_paid_cents"] == 2900000

    both, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, MANAGER, limit=100, offset=0))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["entry_type"] for row in both] == ["INITIAL_PREMIUM",
                                                   "CLAIM_SETTLEMENT"]

    premium, premium_meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, MANAGER, limit=100, offset=0, ledger=Ledger.PREMIUM))
    assert premium_meta["total_count"] == 1
    assert premium[0]["entry_type"] == "INITIAL_PREMIUM"
    assert premium[0]["ledger"] == "PREMIUM"
    assert premium[0]["amount_cents"] == 180251
    assert premium[0]["claim_id"] is None

    loss, loss_meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, MANAGER, limit=100, offset=0, ledger=Ledger.LOSS))
    assert loss_meta["total_count"] == 1
    assert loss[0]["entry_type"] == "CLAIM_SETTLEMENT"
    assert loss[0]["ledger"] == "LOSS"
    assert loss[0]["amount_cents"] == 2900000
    assert loss[0]["claim_id"] == claim["id"]

    none, none_meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, MANAGER, limit=100, offset=0,
        entry_type=LedgerEntryType.ENDORSEMENT_RETURN))
    assert (none, none_meta["total_count"]) == ([], 0)

    by_claim, claim_meta = validate_paginated(api.list_claim_ledger_entries(
        claim["id"], ADJUSTER, limit=100, offset=0))
    assert claim_meta["total_count"] == 1
    assert by_claim[0]["id"] == loss[0]["id"]

    policy = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert policy["premium_balance_cents"] == 180251
    assert policy["incurred_loss_cents"] == 2900000
    part = get_success_data(api.get_coverage_part(ctx.part_id, UNDERWRITER))
    assert part["aggregate_paid_net_cents"] == 2900000
    assert part["aggregate_available_cents"] == 197100000
    assert get_success_data(api.get_claim(claim["id"], ADJUSTER))["adjustment_status"] == "CLOSED"
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "ACTIVE"


def test_an_unknown_path_identifier_is_refused_in_the_name_of_its_own_entity(api):
    """Ten reads of the same absent id produce ten pairwise distinct error ids.

    PRD: A policy identifier that does not resolve yields `ERR_POLICY_NOT_FOUND`; a coverage part identifier `ERR_COVERAGE_PART_NOT_FOUND`; a rate rule identifier `ERR_RATE_RULE_NOT_FOUND`; an equipment item identifier `ERR_EQUIPMENT_ITEM_NOT_FOUND`; a jobsite identifier `ERR_JOBSITE_NOT_FOUND`; an installation floater identifier `ERR_INSTALLATION_FLOATER_NOT_FOUND`; a vehicle identifier `ERR_VEHICLE_NOT_FOUND`; a transit shipment identifier `ERR_TRANSIT_SHIPMENT_NOT_FOUND`; a value report identifier `ERR_VALUE_REPORT_NOT_FOUND`; and a claim identifier `ERR_CLAIM_NOT_FOUND`.
    PRD: All ten are HTTP 404.
    Design: Corner/errors/corner_not_found_is_namespaced_per_entity_path
    """
    refusals = [
        (api.get_policy(NOWHERE, UNDERWRITER),
         api_errors.ERR_POLICY_NOT_FOUND),
        (api.get_coverage_part(NOWHERE, UNDERWRITER),
         api_errors.ERR_COVERAGE_PART_NOT_FOUND),
        (api.get_rate_rule(NOWHERE, ACTUARY),
         api_errors.ERR_RATE_RULE_NOT_FOUND),
        (api.get_equipment_item(NOWHERE, UNDERWRITER),
         api_errors.ERR_EQUIPMENT_ITEM_NOT_FOUND),
        (api.get_jobsite(NOWHERE, UNDERWRITER),
         api_errors.ERR_JOBSITE_NOT_FOUND),
        (api.get_installation_floater(NOWHERE, UNDERWRITER),
         api_errors.ERR_INSTALLATION_FLOATER_NOT_FOUND),
        (api.get_vehicle(NOWHERE, UNDERWRITER),
         api_errors.ERR_VEHICLE_NOT_FOUND),
        (api.get_transit_shipment(NOWHERE, UNDERWRITER),
         api_errors.ERR_TRANSIT_SHIPMENT_NOT_FOUND),
        (api.get_value_report(NOWHERE, UNDERWRITER),
         api_errors.ERR_VALUE_REPORT_NOT_FOUND),
        (api.get_claim(NOWHERE, UNDERWRITER),
         api_errors.ERR_CLAIM_NOT_FOUND),
    ]

    for response, error_id in refusals:
        body = validate_error(response, error_id, 404)
        assert body["error_id"] == error_id
        assert body["message"].strip() != ""

    assert len({error_id for _, error_id in refusals}) == 10


def dangling_reference_file(api):
    """A drafted file with a scheduled part, one unit, and a transit part beside it."""
    ctx = fixtures.build_scheduled_file(api)
    ctx["transit_part"] = fixtures.create_part(
        api, ctx.policy_id,
        factories.transit_part(transit_owned_limit_cents=10000000,
                              transit_hired_limit_cents=4000000,
                              catastrophe_limit_cents=5000000))
    return ctx


def test_an_unknown_identifier_in_the_body_is_named_by_the_field_that_carried_it(api):
    """Every path id resolves, so only the body can be at fault, and it says which.

    PRD: A `jobsite_id` supplied in the body of an equipment-item create, an installation-floater create, or a jobsite assignment must resolve, else `ERR_JOBSITE_NOT_FOUND` (404).
    PRD: A `vehicle_id` supplied on a transit-shipment create must resolve, else `ERR_VEHICLE_NOT_FOUND` (404).
    PRD: On claim creation, the supplied `coverage_part_id` and the single named loss subject must both resolve, else `ERR_LOSS_SUBJECT_NOT_FOUND` (404).
    Design: Corner/errors/corner_not_found_also_fires_for_ids_referenced_in_request_bodies
    """
    ctx = dangling_reference_file(api)
    token = fixtures.policy_version(api, ctx.policy_id)

    validate_error(api.assign_jobsite(ctx.item_id,
                                      factories.jobsite_assignment(NOWHERE),
                                      UNDERWRITER),
                   api_errors.ERR_JOBSITE_NOT_FOUND, 404)
    validate_error(api.create_transit_shipment(ctx["transit_part"]["id"],
                                               factories.transit_shipment(NOWHERE),
                                               UNDERWRITER),
                   api_errors.ERR_VEHICLE_NOT_FOUND, 404)
    validate_error(api.create_claim(ctx.policy_id,
                                    factories.claim(ctx.part_id, loss_type="THEFT",
                                                    equipment_item_id=NOWHERE),
                                    UNDERWRITER),
                   api_errors.ERR_LOSS_SUBJECT_NOT_FOUND, 404)
    validate_error(api.create_claim(ctx.policy_id,
                                    factories.claim(NOWHERE, loss_type="THEFT",
                                                    equipment_item_id=ctx.item_id),
                                    UNDERWRITER),
                   api_errors.ERR_LOSS_SUBJECT_NOT_FOUND, 404)

    item = get_success_data(api.get_equipment_item(ctx.item_id, UNDERWRITER))
    assert item["assigned_jobsite_id"] is None
    assert item["rated_premium_cents"] == 173318
    assert fixtures.policy_version(api, ctx.policy_id) == token

    shipments, shipment_meta = validate_paginated(api.list_transit_shipments(
        UNDERWRITER, limit=100, offset=0,
        coverage_part_id=ctx["transit_part"]["id"]))
    assert (shipments, shipment_meta["total_count"]) == ([], 0)
    claims, claim_meta = validate_paginated(api.list_claims(
        UNDERWRITER, limit=100, offset=0, policy_id=ctx.policy_id))
    assert (claims, claim_meta["total_count"]) == ([], 0)


def shape_test_file(api):
    """A drafted file with a scheduled unit and a live floater, both real subjects."""
    ctx = fixtures.build_scheduled_file(api)
    floater_part = fixtures.create_part(api, ctx.policy_id,
                                        factories.installation_floater_part())
    yard = fixtures.survey_jobsite(api, fixtures.create_jobsite(
        api, name="Shape Yard")["id"], **factories.SURVEY_TIER_2)
    ctx["floater"] = fixtures.open_floater(
        api, floater_part["id"], yard["id"], project_name="Shape Project",
        coverage_start_date="2026-09-01", coverage_end_date="2026-12-01",
        installed_value_limit_cents=20000000)
    return ctx


def test_every_malformed_payload_is_a_four_hundred_and_never_a_four_twenty_two(api):
    """A wrong type, an inverted term, a negative amount, a bad enum, two subjects, a hole.

    PRD: **Request shape.** Every write endpoint validates its payload: all required fields present; integers actually integers; money and limit fields not negative; rate, factor and basis-point fields not negative; every enum field carrying a declared member; dates formatted `YYYY-MM-DD` and instants formatted as ISO 8601 UTC; a policy's `expiration_date` strictly after its `effective_date`; a rate rule's `age_band_min_years` not greater than its `age_band_max_years`; a floater's `coverage_end_date` not earlier than its `coverage_start_date`; a report's `period_end_date` not earlier than its `period_start_date`; a shipment's `arrival_at` strictly after its `departure_at`; and a claim naming exactly one of `equipment_item_id`, `transit_shipment_id` and `installation_floater_id`. Any breach is `ERR_INVALID_REQUEST` (400).
    PRD: Any other combination — two subjects, or none on a part that is not a reporting form — is a shape failure, `ERR_INVALID_REQUEST`.
    Design: Corner/errors/corner_request_shape_rejections_are_400_not_422
    """
    ctx = shape_test_file(api)
    token = fixtures.policy_version(api, ctx.policy_id)

    malformed = [
        api.create_equipment_item(
            ctx.part_id,
            factories.equipment_item(token, description="Spelled Year",
                                     model_year="twenty twenty-two"),
            UNDERWRITER),
        api.create_policy(
            factories.policy(policyholder_name="Inverted Term Co",
                             effective_date="2027-08-01",
                             expiration_date="2026-08-01"),
            UNDERWRITER),
        api.create_equipment_item(
            ctx.part_id,
            factories.equipment_item(token, description="Negative Cost",
                                     original_cost_cents=-12000000),
            UNDERWRITER),
        api.create_equipment_item(
            ctx.part_id,
            factories.equipment_item(token, description="Borrowed Machine",
                                     ownership="BORROWED"),
            UNDERWRITER),
        api.create_claim(
            ctx.policy_id,
            factories.claim(ctx.part_id, loss_type="THEFT",
                            equipment_item_id=ctx.item_id,
                            installation_floater_id=ctx["floater"]["id"]),
            UNDERWRITER),
        api.create_equipment_item(
            ctx.part_id,
            factories.equipment_item(token, description="Typeless Machine",
                                     equipment_type=factories.DROP),
            UNDERWRITER),
    ]

    for response in malformed:
        validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)

    items, item_meta = validate_paginated(api.list_equipment_items(
        UNDERWRITER, limit=100, offset=0, coverage_part_id=ctx.part_id))
    assert item_meta["total_count"] == 1
    assert [row["id"] for row in items] == [ctx.item_id]
    claims, claim_meta = validate_paginated(api.list_claims(
        UNDERWRITER, limit=100, offset=0, policy_id=ctx.policy_id))
    assert (claims, claim_meta["total_count"]) == ([], 0)
    assert fixtures.policy_version(api, ctx.policy_id) == token
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 173318


def test_an_unusable_identity_is_refused_before_the_service_looks_for_the_row(api):
    """Absent, blank and unrecognised identities are all 401, not 403 and not 404.

    PRD: If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
    PRD: A role string outside that set of five is also `ERR_UNAUTHENTICATED` (HTTP 401), not a permission failure.
    Design: Corner/errors/corner_missing_or_unknown_role_header_is_401_before_anything_else
    """
    ctx = fixtures.build_scheduled_file(api)

    validate_error(api.get_policy(ctx.policy_id, headers_without_user_id()),
                   api_errors.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_policy(ctx.policy_id, headers_with_blank_user_id()),
                   api_errors.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_policy(ctx.policy_id, headers_without_role()),
                   api_errors.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_policy(ctx.policy_id, headers_with_blank_role()),
                   api_errors.ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_policy(ctx.policy_id, headers_with_unknown_role()),
                   api_errors.ERR_UNAUTHENTICATED, 401)

    validate_error(api.get_policy(NOWHERE, UNDERWRITER),
                   api_errors.ERR_POLICY_NOT_FOUND, 404)
    assert validate_success(api.get_policy(
        ctx.policy_id, UNDERWRITER))["id"] == ctx.policy_id


def out_of_sequence_file(api):
    """One IN_FORCE file carrying three parts, a live floater, an accepted report, a claim."""
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api,
                                    policyholder_name="Out Of Sequence Contractors")
    scheduled = fixtures.create_part(api, policy["id"],
                                     factories.scheduled_equipment_part())
    floater_part = fixtures.create_part(api, policy["id"],
                                        factories.installation_floater_part())
    reporting = fixtures.create_part(api, policy["id"],
                                     factories.reporting_form_part())
    yard = fixtures.survey_jobsite(api, fixtures.create_jobsite(
        api, name="Sequence Yard")["id"], **factories.SURVEY_TIER_2)
    item = fixtures.schedule_item(api, scheduled["id"], policy["id"])
    floater = fixtures.open_floater(
        api, floater_part["id"], yard["id"], project_name="Sequence Project",
        coverage_start_date="2026-09-01", coverage_end_date="2026-12-01",
        installed_value_limit_cents=20000000)
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, item["id"])
    fixtures.activate_floater(api, floater["id"])
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    report = fixtures.file_value_report(api, reporting["id"], "2026-08-01",
                                        "2026-08-31", 9000000)
    get_success_data(api.adjudicate_value_report(report["id"], UNDERWRITER))
    claim = get_success_data(api.create_claim(
        policy["id"],
        factories.claim(scheduled["id"], loss_date="2026-09-01",
                        loss_type="THEFT", equipment_item_id=item["id"]),
        UNDERWRITER))
    return fixtures.Ctx(policy_id=policy["id"], part_id=scheduled["id"],
               floater_part_id=floater_part["id"], reporting_part_id=reporting["id"],
               jobsite_id=yard["id"], item_id=item["id"], floater_id=floater["id"],
               report_id=report["id"], claim_id=claim["id"])


def test_each_out_of_sequence_action_is_refused_in_the_name_of_its_own_entity(api):
    """Six repeats on one live file, six distinct 409 ids, and nothing moves.

    PRD: **Target-entity state.** The entity the request targets is in a state that admits the operation.
    PRD: The policy must be `REFERRED` with `referral_status` `PENDING`, else `ERR_REFERRAL_NOT_PENDING`, and the deciding manager must not be the referring underwriter, else `ERR_SEGREGATION_OF_DUTIES`.
    PRD: Activation requires the floater to be `PENDING`, else `ERR_FLOATER_NOT_IN_REQUIRED_STATE`; requires the owning policy to be `IN_FORCE`, else `ERR_POLICY_NOT_IN_FORCE`; requires the jobsite to be `SURVEYED` with a `security_tier` other than `TIER_0`, else `ERR_JOBSITE_SECURITY_INSUFFICIENT`; and requires `installed_value_limit_cents` to be no greater than the part's `aggregate_available_cents` at that moment, else `ERR_FLOATER_LIMIT_EXCEEDS_PART_AGGREGATE`.
    PRD: Adjudication requires the report to be `SUBMITTED`, else `ERR_REPORT_ALREADY_ADJUDICATED` — which is also the error for adjudicating a report that is already `ACCEPTED`, `PENALIZED`, `DELINQUENT` or `SUPERSEDED`.
    PRD: Only a `ClaimsAdjuster` records the salvage outcome, and only on a claim whose `adjustment_status` is `SETTLED` and whose `salvage_status` is `PENDING`, else `ERR_CLAIM_NOT_SETTLED` — the wording is exact, because only a declared total loss ever arms the salvage axis, so a settled repair claim can never take this call.
    PRD: Attempting to activate, re-site or remove an item that is already `REMOVED` or `TOTALED` — or to activate one that is already `ACTIVE` — is refused with `ERR_ITEM_ALREADY_OFF_RISK`.
    Design: Corner/errors/corner_every_state_precondition_refusal_is_409_and_names_its_own_entity
    """
    ctx = out_of_sequence_file(api)
    opened = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert opened["status"] == "IN_FORCE"
    assert opened["referral_status"] == "NOT_REQUIRED"
    assert opened["sum_of_part_premiums_cents"] == 243893
    assert opened["written_premium_cents"] == 253649
    assert opened["premium_balance_cents"] == 272759

    validate_error(api.decide_referral(ctx.policy_id,
                                       factories.referral_decision("APPROVE"),
                                       MANAGER),
                   api_errors.ERR_REFERRAL_NOT_PENDING, 409)
    still = get_success_data(api.get_policy(ctx.policy_id, UNDERWRITER))
    assert still["referral_status"] == "NOT_REQUIRED"
    assert still["referral_decided_by_user_id"] is None

    validate_error(api.activate_installation_floater(ctx.floater_id, UNDERWRITER),
                   api_errors.ERR_FLOATER_NOT_IN_REQUIRED_STATE, 409)
    assert get_success_data(api.get_installation_floater(
        ctx.floater_id, UNDERWRITER))["status"] == "ACTIVE"
    assert get_success_data(api.get_jobsite(
        ctx.jobsite_id, UNDERWRITER))["active_floater_count"] == 1

    validate_error(api.adjudicate_value_report(ctx.report_id, UNDERWRITER),
                   api_errors.ERR_REPORT_ALREADY_ADJUDICATED, 409)
    assert get_success_data(api.get_value_report(
        ctx.report_id, UNDERWRITER))["status"] == "ACCEPTED"
    assert get_success_data(api.get_coverage_part(
        ctx.reporting_part_id, UNDERWRITER))["earned_reported_premium_cents"] == 19110

    validate_error(api.record_salvage_recovery(ctx.claim_id,
                                              factories.salvage(1000000), ADJUSTER),
                   api_errors.ERR_CLAIM_NOT_SETTLED, 409)
    claim = get_success_data(api.get_claim(ctx.claim_id, ADJUSTER))
    assert claim["adjustment_status"] == "OPEN"
    assert claim["salvage_status"] == "NOT_APPLICABLE"
    assert validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0,
        ledger=Ledger.LOSS))[1]["total_count"] == 0

    removed = validate_success(api.delete_equipment_item(ctx.item_id, UNDERWRITER))
    assert removed["status"] == "REMOVED"
    assert_instant_equals(removed["removed_at"], "2026-09-10T00:00:00Z")
    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.PREMIUM))
    returns = [row for row in rows
               if row["entry_type"] == LedgerEntryType.ENDORSEMENT_RETURN]
    assert [row["amount_cents"] for row in returns] == [-154324]

    validate_error(api.delete_equipment_item(ctx.item_id, UNDERWRITER),
                   api_errors.ERR_ITEM_ALREADY_OFF_RISK, 409)
    validate_error(api.activate_equipment_item(ctx.item_id, UNDERWRITER),
                   api_errors.ERR_ITEM_ALREADY_OFF_RISK, 409)

    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=100, offset=0, ledger=Ledger.PREMIUM))
    assert len([row for row in rows
                if row["entry_type"] == LedgerEntryType.ENDORSEMENT_RETURN]) == 1
    assert get_success_data(api.get_equipment_item(
        ctx.item_id, UNDERWRITER))["status"] == "REMOVED"
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == sum(
            row["amount_cents"] for row in rows)


def test_a_voided_part_answers_for_itself_before_its_cancelled_policy_does(api):
    """The cancellation voids all three parts, and each refusal names the part, not the policy.

    PRD: Finally every coverage part still `ACTIVE` becomes `VOID`.
    PRD: So a child create or a part endorsement aimed at a part belonging to a cancelled or declined policy returns `ERR_PART_VOID`, not `ERR_POLICY_NOT_MUTABLE`.
    PRD: The endorsement advances the part's `version` by 1, and it is refused with `ERR_PART_VOID` on a voided part and with `ERR_POLICY_NOT_MUTABLE` when the owning policy is past mutability.
    Design: Corner/errors/corner_every_state_precondition_refusal_is_409_and_names_its_own_entity
    """
    ctx = out_of_sequence_file(api)
    reporting_token = fixtures.part_version(api, ctx.reporting_part_id)

    cancelled = validate_success(api.cancel_policy(
        ctx.policy_id,
        factories.cancellation("INSURED_REQUEST", "2026-10-01"), MANAGER))

    assert cancelled["status"] == "CANCELLED"
    for part_id in (ctx.part_id, ctx.floater_part_id, ctx.reporting_part_id):
        assert get_success_data(api.get_coverage_part(
            part_id, UNDERWRITER))["status"] == "VOID"

    validate_error(api.create_value_report(
        ctx.reporting_part_id,
        factories.value_report("2026-09-01", "2026-09-30", 9000000, reporting_token),
        UNDERWRITER), api_errors.ERR_PART_VOID, 409)
    validate_error(api.patch_coverage_part(
        ctx.part_id, factories.part_endorsement(deductible_cents=200000),
        UNDERWRITER), api_errors.ERR_PART_VOID, 409)

    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["deductible_cents"] == 100000
    reports, report_meta = validate_paginated(api.list_value_reports(
        ctx.reporting_part_id, UNDERWRITER, limit=100, offset=0))
    assert report_meta["total_count"] == 1
    assert [row["status"] for row in reports] == ["ACCEPTED"]
