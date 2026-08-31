"""Acceptance: the counted set, the two percentage-rent variants, the
occupancy-cost watchlist and the reporting ledger the cascade writes.
"""
from test_helpers import (
    AUDITOR, LEASE_ADMIN, TEST_DEFAULTS, ApiErrorId, accept_report,
    activate_lease, amend_lease, assert_charge, assert_ledger_balances,
    assert_ledger_entry, assert_sales_report, charges_for_year, create_center,
    create_lease, create_tenant, file_and_accept, ledger_entries,
    open_lease_year, read_lease, read_lease_year, read_report,
    schedule_monthly_report, set_clock, setup_lease_year,
    setup_year_with_pending_reports, submit_report, validate_error,
    validate_paginated, validate_success,
)

ARTIFICIAL_BREAKPOINT = TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"]


def _two_leases_differing_only_in_billing_mode():
    """Byte-identical economics and sales under each of the two variants.

    Both reporting years pin a 40,000,000 breakpoint and a 600 basis-point
    rate; both take a 30,000,000 September period that is already accepted and
    a 30,000,000 October period waiting in SUBMITTED.
    """
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center(fiscal_year_start_month=9)
    scene = {"center": center}
    for key, mode, suite in (("cumulative", "CUMULATIVE_YTD", "101"),
                             ("standalone", "PERIOD_STANDALONE", "102")):
        tenant = create_tenant(center["id"],
                               legal_name=f"Bright Shoes {key} LLC",
                               trade_name=f"Bright Shoes {key}")
        lease = create_lease(center["id"], tenant["id"], suite_code=suite,
                             breakpoint_type="ARTIFICIAL",
                             artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT,
                             billing_mode=mode)
        lease = activate_lease(lease["id"])
        lease_year = open_lease_year(lease["id"])
        first = schedule_monthly_report(lease_year["id"], 1)
        second = schedule_monthly_report(lease_year["id"], 2)
        file_and_accept(first["id"], tenant["id"], 30_000_000)
        submit_report(second["id"], tenant["id"], 30_000_000)
        scene[key] = {"tenant": tenant, "lease": lease,
                      "lease_year": lease_year, "second_report": second}
    return scene


def test_cumulative_ytd_year_bills_only_the_delta_above_the_annual_breakpoint(api):
    """PRD §3.5: "Under the `CUMULATIVE_YTD` variant the whole year is
    recomputed on every acceptance and only the delta is billed. The service
    sums `net_sales_cents` over every report of that reporting year that is in
    the counted set **excluding the report being processed**, adds the
    processed report's own `net_sales_cents` to obtain the year-to-date
    cumulative net sales, subtracts the year's `breakpoint_cents` and takes the
    result if it is positive or zero if it is not. That excess is multiplied by
    the year's `percentage_rate_bps_snapshot`, divided by 10000, and rounded
    half up to whole cents, giving the gross percentage rent due for the year
    to date. From that the service subtracts the sum of `amount_cents` over
    every charge of the year whose `billing_status` is `ISSUED` — draft and
    voided charges are excluded from this sum — and the difference is the
    amount to bill."

    Design: Difficulty/dual_variant_calc/percentage_rent_billing_mode_divergence_on_lease_year
    """
    scene = _two_leases_differing_only_in_billing_mode()
    cumulative = scene["cumulative"]

    accept_report(cumulative["second_report"]["id"])

    year = read_lease_year(cumulative["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 60_000_000
    assert year["cumulative_billed_cents"] == 1_200_000, (
        "the annual breakpoint is tested once, so only 20,000,000 of excess "
        "is billed at 600 basis points")

    charges = charges_for_year(cumulative["lease_year"]["id"])
    assert len(charges) == 1, "one acceptance crossed the breakpoint, one charge"
    assert_charge(charges[0])
    assert charges[0]["charge_type"] == "PERIODIC"
    assert charges[0]["billing_status"] == "ISSUED"
    assert charges[0]["amount_cents"] == 1_200_000


def test_period_standalone_year_bills_each_period_against_a_pro_rated_breakpoint(api):
    """PRD §3.5: "Under the `PERIOD_STANDALONE` variant each period stands on
    its own against a pro-rated breakpoint, with no credit for prior periods.
    The number of months in a period is one when the lease's
    `reporting_frequency` is `MONTHLY` and three when it is `QUARTERLY`. The
    period breakpoint is the year's `breakpoint_cents` multiplied by that month
    count, divided by twelve, and rounded half up to whole cents. The excess is
    the report's own `net_sales_cents` less that period breakpoint, taken as
    zero if the subtraction is negative. The amount to bill is that excess
    multiplied by the year's `percentage_rate_bps_snapshot`, divided by 10000,
    and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/percentage_rent_billing_mode_divergence_on_lease_year
    """
    scene = _two_leases_differing_only_in_billing_mode()
    standalone = scene["standalone"]

    accept_report(standalone["second_report"]["id"])

    year = read_lease_year(standalone["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 60_000_000, (
        "identical sales to the cumulative-mode lease")
    assert year["cumulative_billed_cents"] == 3_200_000, (
        "each period is measured against its 3,333,333 pro-rata share, so the "
        "same sales bill strictly more rent")

    charges = charges_for_year(standalone["lease_year"]["id"])
    assert len(charges) == 2
    for charge in charges:
        assert_charge(charge)
        assert charge["charge_type"] == "PERIODIC"
        assert charge["billing_status"] == "ISSUED"
        assert charge["amount_cents"] == 1_600_000


def test_acceptance_that_crosses_the_breakpoint_issues_a_periodic_charge(api):
    """PRD §3.5: "The second layer, caused by the first, moves the year's
    running sales: `cumulative_net_sales_cents` increases by the report's
    `net_sales_cents`, and a ledger entry of type `REPORT_ACCEPTED` is appended
    with that figure as its `delta_net_sales_cents` and 0 as its
    `delta_billed_cents`."
    PRD §3.5: "When the amount is non-zero, a percentage-rent charge is created
    against the reporting year with `charge_type` of `PERIODIC`,
    `billing_status` of `ISSUED`, `issued_at` stamped from the logical clock,
    `collection_status` of `UNPAID`, `paid_cents` of 0, `supersedes_charge_id`
    null and `sales_report_id` naming the report that produced it."

    Design: Difficulty/transitive_cascade/accept_report_cascades_to_lease_watchlist_depth_five
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="801", annual_base_rent_cents=48_000_000,
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    first, second = scene["reports"]
    file_and_accept(first["id"], scene["tenant"]["id"], 39_000_000)
    submit_report(second["id"], scene["tenant"]["id"], 21_000_000)

    accept_report(second["id"])

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 60_000_000
    assert year["cumulative_billed_cents"] == 1_200_000

    charges = charges_for_year(scene["lease_year"]["id"])
    assert len(charges) == 1
    assert charges[0]["charge_type"] == "PERIODIC"
    assert charges[0]["billing_status"] == "ISSUED"
    assert charges[0]["collection_status"] == "UNPAID"
    assert charges[0]["paid_cents"] == 0
    assert charges[0]["sales_report_id"] == second["id"]
    assert charges[0]["amount_cents"] == 1_200_000


def test_billing_cascade_reaches_occupancy_cost_and_flips_the_watchlist(api):
    """PRD §3.5: "The lease's `ytd_occupancy_cost_cents` becomes the lease's
    `annual_base_rent_cents` multiplied by the elapsed period count, divided by
    the periods per year and rounded half up to whole cents, plus the year's
    `cumulative_billed_cents`. The lease's `occupancy_cost_ratio_bps` becomes
    `ytd_occupancy_cost_cents` multiplied by 10000 and divided by the year's
    `cumulative_net_sales_cents`, floored to a whole basis point; it is defined
    as 0 when that cumulative net sales figure is zero."
    PRD §3.5: "A lease is put on `WATCHLIST` when its recomputed
    `occupancy_cost_ratio_bps` is at or above 1500 basis points — that is, when
    rent is consuming fifteen percent or more of net sales — or when its
    `delinquency_strikes` has reached three or more."

    Design: Difficulty/transitive_cascade/accept_report_cascades_to_lease_watchlist_depth_five
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="801", annual_base_rent_cents=48_000_000,
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    first, second = scene["reports"]
    file_and_accept(first["id"], scene["tenant"]["id"], 39_000_000)
    submit_report(second["id"], scene["tenant"]["id"], 21_000_000)

    accept_report(second["id"])

    lease = read_lease(scene["lease"]["id"])
    assert lease["ytd_occupancy_cost_cents"] == 9_200_000, (
        "two elapsed periods of base rent plus the 1,200,000 just billed")
    assert lease["occupancy_cost_ratio_bps"] == 1533
    assert lease["watchlist_status"] == "WATCHLIST"

    entries = ledger_entries(scene["lease_year"]["id"])
    assert len(entries) == 3
    for entry in entries:
        assert_ledger_entry(entry)
    assert [entry["entry_type"] for entry in entries] == [
        "REPORT_ACCEPTED", "REPORT_ACCEPTED", "PERIODIC_CHARGE_ISSUED"]
    assert entries[0]["delta_net_sales_cents"] == 39_000_000
    assert entries[1]["delta_net_sales_cents"] == 21_000_000
    assert entries[2]["delta_billed_cents"] == 1_200_000
    assert_ledger_balances(entries, read_lease_year(scene["lease_year"]["id"]))


def test_cumulative_sales_landing_exactly_on_the_breakpoint_bill_nothing(api):
    """PRD §3.5: "In either variant the round-half-up is applied exactly once
    within the branch that runs. When the computed amount is zero, **no charge
    row is created and no billing ledger entry is appended** — a period that
    produced no percentage rent leaves no trace in the billing figures."

    Design: Difficulty/boundary_precision_check/cumulative_sales_exactly_at_breakpoint_bills_nothing
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="1501", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    first, second = scene["reports"]
    submit_report(first["id"], scene["tenant"]["id"], 40_000_000)
    submit_report(second["id"], scene["tenant"]["id"], 20_000)

    accept_report(first["id"])

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 40_000_000
    assert year["cumulative_billed_cents"] == 0, (
        "sales exactly at the breakpoint produce an excess of zero")
    assert charges_for_year(scene["lease_year"]["id"]) == []
    assert [entry["entry_type"] for entry
            in ledger_entries(scene["lease_year"]["id"])] == ["REPORT_ACCEPTED"]


def test_first_cent_above_the_breakpoint_starts_billing(api):
    """PRD §3.5: "That excess is multiplied by the year's
    `percentage_rate_bps_snapshot`, divided by 10000, and rounded half up to
    whole cents, giving the gross percentage rent due for the year to date."
    PRD §3.5: "Because the annual breakpoint is applied to the whole year at
    once, sales below the annual breakpoint produce zero percentage rent no
    matter how unevenly they are spread across periods."

    Design: Difficulty/boundary_precision_check/cumulative_sales_exactly_at_breakpoint_bills_nothing
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="1501", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    first, second = scene["reports"]
    submit_report(first["id"], scene["tenant"]["id"], 40_000_000)
    submit_report(second["id"], scene["tenant"]["id"], 20_000)
    accept_report(first["id"])

    accept_report(second["id"])

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 40_020_000
    assert year["cumulative_billed_cents"] == 1_200

    charges = charges_for_year(scene["lease_year"]["id"])
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 1_200
    assert charges[0]["billing_status"] == "ISSUED"


def test_accepting_a_period_the_tenant_never_filed_is_refused(api):
    """PRD §3.5: "Acceptance is the landlord's vetting act, performed by a
    `LeaseAdministrator` and permitted while the reporting year is `OPEN` or
    `RECONCILING`. It moves the report `SUBMITTED → ACCEPTED` and sets off the
    longest cascade in the system."
    PRD §2.9: "The rejection is the state code matching the entity that
    blocked: `ERR_TENANT_STATE_INVALID`, `ERR_LEASE_STATE_INVALID`,
    `ERR_LEASE_YEAR_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`,
    `ERR_CHARGE_STATE_INVALID`, `ERR_CO_TENANCY_EVENT_STATE_INVALID`,
    `ERR_KICK_OUT_STATE_INVALID` or `ERR_AUDIT_STATE_INVALID`, each HTTP 409."

    Design: Corner/state_machines/accept_report_from_pending_rejected
    """
    scene = setup_year_with_pending_reports(1, suite_code="4101")
    report = scene["reports"][0]

    validate_error(api.accept_sales_report(report["id"], LEASE_ADMIN),
                   ApiErrorId.ERR_REPORT_STATE_INVALID.value, 409)

    assert read_report(report["id"])["status"] == "PENDING"
    assert read_lease_year(
        scene["lease_year"]["id"])["cumulative_net_sales_cents"] == 0


def test_billing_variant_follows_the_pinned_snapshot_not_the_amended_lease(api):
    """PRD §2.7: "Every percentage-rent computation described in Section 3
    reads the snapshot on the reporting year, never the current value on the
    lease — including the choice between the two billing variants, which is
    decided by `billing_mode_snapshot` alone."
    PRD §3.2: "What it does **not** do is rewrite history: the
    `breakpoint_cents`, `percentage_rate_bps_snapshot` and
    `billing_mode_snapshot` pinned onto every existing reporting year are left
    exactly as they were, per Section 2.7."

    Design: Corner/calculations/percentage_rent_variant_follows_lease_year_snapshot_not_current_lease
    """
    scene = setup_lease_year(
        suite_code="5601", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT,
        billing_mode="PERIOD_STANDALONE")
    amend_lease(scene["lease"]["id"], billing_mode="CUMULATIVE_YTD")
    report = schedule_monthly_report(scene["lease_year"]["id"], 1)
    submit_report(report["id"], scene["tenant"]["id"], 30_000_000)

    accept_report(report["id"])

    assert read_lease(scene["lease"]["id"])["billing_mode"] == "CUMULATIVE_YTD"
    year = read_lease_year(scene["lease_year"]["id"])
    assert year["billing_mode_snapshot"] == "PERIOD_STANDALONE"
    assert year["cumulative_billed_cents"] == 1_600_000, (
        "the pinned standalone variant bills against the pro-rated breakpoint, "
        "where the current cumulative mode would have billed nothing")

    charges = charges_for_year(scene["lease_year"]["id"])
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 1_600_000
    assert charges[0]["billing_status"] == "ISSUED"


def test_reporting_ledger_rows_carry_no_updated_at_and_no_version(api):
    """PRD §2.4: "A `ReportingLedgerEntry` is append-only and is never modified
    after it is written, so it carries only `id` and `created_at`; it has no
    `updated_at` field and no `version` field, and those two keys must be
    absent from its representation rather than present and null."
    PRD §2.11: "Whenever a cascade moves a reporting year's
    `cumulative_net_sales_cents` or `cumulative_billed_cents`, it also appends
    a `ReportingLedgerEntry` recording the movement."

    Design: Corner/entities/ledger_entries_are_append_only_without_version_field
    """
    scene = setup_lease_year(
        suite_code="3501", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    report = schedule_monthly_report(scene["lease_year"]["id"], 1)
    file_and_accept(report["id"], scene["tenant"]["id"], 30_000_000)

    entries = validate_success(
        api.list_ledger_entries(scene["lease_year"]["id"], AUDITOR))

    assert len(entries) == 1
    entry = entries[0]
    assert_ledger_entry(entry)
    assert entry["entry_type"] == "REPORT_ACCEPTED"
    assert entry["delta_net_sales_cents"] == 30_000_000
    assert entry["delta_billed_cents"] == 0


def test_reporting_ledger_can_be_narrowed_to_one_entry_type(api):
    """PRD §3.10: "The reporting year's ledger is readable in full by a
    `CenterAdmin`, a `LeaseAdministrator` or an `Auditor`, oldest first, and
    can be narrowed by `entry_type`."
    PRD §2.11: "An entry that moves only sales carries a `delta_billed_cents`
    of 0, and an entry that moves only billing carries a
    `delta_net_sales_cents` of 0."

    Design: Corner/endpoints/get_lease_year_ledger_entries_filters_by_entry_type
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="7201", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    for report in scene["reports"]:
        file_and_accept(report["id"], scene["tenant"]["id"], 30_000_000)

    entries = ledger_entries(scene["lease_year"]["id"], headers=AUDITOR)
    assert [entry["entry_type"] for entry in entries] == [
        "REPORT_ACCEPTED", "REPORT_ACCEPTED", "PERIODIC_CHARGE_ISSUED"]
    assert entries[0]["delta_net_sales_cents"] == 30_000_000
    assert entries[1]["delta_net_sales_cents"] == 30_000_000
    assert entries[2]["delta_billed_cents"] == 1_200_000

    filtered, meta = validate_paginated(
        api.list_ledger_entries(scene["lease_year"]["id"], AUDITOR,
                                params={"entry_type": "PERIODIC_CHARGE_ISSUED"}))
    assert len(filtered) == 1
    assert meta["total_count"] == 1
    assert filtered[0]["delta_billed_cents"] == 1_200_000
    assert filtered[0]["delta_net_sales_cents"] == 0


def test_accept_response_already_carries_every_cascaded_figure(api):
    """PRD §2.11: "The specification treats these as ordered cascades: the
    primary state change happens first, and each dependent effect is applied in
    the order the workflow narrative gives, with every touched resource's
    `updated_at` refreshed and `version` advanced. A cascade never partially
    applies — if the operation is accepted, every effect described for it lands
    in the same request."
    PRD §3.5: "The lease's `occupancy_cost_ratio_bps` becomes
    `ytd_occupancy_cost_cents` multiplied by 10000 and divided by the year's
    `cumulative_net_sales_cents`, floored to a whole basis point; it is defined
    as 0 when that cumulative net sales figure is zero."

    Design: Corner/consistency_model/accept_response_reflects_all_cascaded_state_in_the_same_request
    """
    scene = setup_year_with_pending_reports(
        1, suite_code="9301", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    report = scene["reports"][0]
    submit_report(report["id"], scene["tenant"]["id"], 30_000_000)

    accepted = validate_success(api.accept_sales_report(report["id"], LEASE_ADMIN))

    assert_sales_report(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["net_sales_cents"] == 30_000_000

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 30_000_000
    assert year["cumulative_billed_cents"] == 0

    lease = read_lease(scene["lease"]["id"])
    assert lease["ytd_occupancy_cost_cents"] == 1_000_000
    assert lease["occupancy_cost_ratio_bps"] == 333
    assert lease["watchlist_status"] == "NORMAL"
