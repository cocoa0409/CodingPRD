"""
Endpoints read and written for what they publish rather than for what they change.

Each scenario exercises one endpoint's own contract — the pair of interest figures a
ledger read publishes, the recomputation an amendment performs in place, the join row
addressable from both of its parents, the versioning a patch does and does not do,
and the branch a locate outcome opens or closes.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
)


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _two_unpaid_months_read_in_november(ssn_cp: str, ssn_ncp: str) -> fx.Scenario:
    """
    An entered 75,000-cent order carrying two unpaid 75,000-cent charges due
    2026-08-15 and 2026-09-15, with the clock left at 2026-11-01 — the data on
    which the two interest measures diverge by exactly 750 cents.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Anneke Lindqvist",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Petter Lindqvist",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id, ["2026-08-01", "2026-09-01"], due_day=15
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    return scenario


# ---------------------------------------------------------------------------
# The one endpoint that publishes both interest measures at once
# ---------------------------------------------------------------------------


def test_01_the_ledger_publishes_both_measures_side_by_side():
    """
    One response carries 1,125 of statutory interest and 1,875 of aggregate interest.

    The ledger read reports both measures side by side — `statutory_interest_cents` and `aggregate_interest_cents` — together with `interest_written_off_cents`, `interest_collected_cents`, `interest_receivable_cents`, `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `unapplied_credit_cents`, and it accepts an optional `as_of_date` to value the ledger at a past or future date without mutating anything.

    The two totals therefore diverge on identical data, and the divergence grows with the number of charges.

    Design: Corner/endpoints/ledger_read_reports_both_interest_variants_and_mutates_nothing
    """
    scenario = _two_unpaid_months_read_in_november("6301", "6302")
    assert scenario.order["monthly_obligation_cents"] == 75000

    ledger = fx.read_ledger(scenario.case_id)

    # Two whole months on the older charge and one on the newer.
    assert ledger["statutory_interest_cents"] == 1125
    # Snapshots at 2026-08-31 over 75000 and at 09-30 and 10-31 over 150000.
    assert ledger["aggregate_interest_cents"] == 1875
    assert ledger["aggregate_interest_cents"] - ledger["statutory_interest_cents"] == 750

    # The receivable tracks the aggregate measure, not the certified one.
    assert ledger["interest_receivable_cents"] == 1875
    assert ledger["interest_collected_cents"] == 0
    assert ledger["interest_written_off_cents"] == 0
    assert ledger["arrears_principal_cents"] == 150000
    assert ledger["assigned_arrears_cents"] == 0
    assert ledger["unassigned_arrears_cents"] == 150000
    assert ledger["unapplied_credit_cents"] == 0


def test_02_the_as_of_date_rewinds_the_computation_and_stores_nothing():
    """
    Rewound to 2026-09-20 the two measures agree at 375, and the case never moves.

    A charge that has been outstanding for less than one whole calendar month contributes exactly zero.

    The run is idempotent for a fixed clock: running it twice without advancing the clock produces identical figures, because both measures are pure functions of the charge set and the as-of date rather than accumulators.

    Design: Corner/endpoints/ledger_read_reports_both_interest_variants_and_mutates_nothing
    """
    scenario = _two_unpaid_months_read_in_november("6303", "6304")
    before = fx.read_case(scenario.case_id)
    assert before["interest_receivable_cents"] == 1875

    first = fx.read_ledger(scenario.case_id)
    rewound = fx.read_ledger(scenario.case_id, as_of_date="2026-09-20")
    repeated = fx.read_ledger(scenario.case_id)

    # The newer charge has been outstanding zero whole months and falls after the
    # only month-end in range, so both measures land on the same 375.
    assert rewound["statutory_interest_cents"] == 375
    assert rewound["aggregate_interest_cents"] == 375
    # The rewind values interest; it does not replay the principal.
    assert rewound["arrears_principal_cents"] == 150000

    assert repeated == first

    after = fx.read_case(scenario.case_id)
    assert after["version"] == before["version"]
    assert after["arrears_principal_cents"] == before["arrears_principal_cents"]
    assert after["interest_receivable_cents"] == 1875


# ---------------------------------------------------------------------------
# The action endpoint that rewrites its own row instead of making a successor
# ---------------------------------------------------------------------------


def _served_withholding_order_on_a_hundred_and_fifty_thousand(
    ssn_cp: str, ssn_ncp: str
) -> fx.Scenario:
    """
    A served Minnesota withholding order whose 90,000-cent request is trimmed to
    89,750 by a 250-cent fee, with 75,000 of arrears already outstanding.

    The charge falls due on the day the clock is pinned to, so the arrears
    principal is genuinely outstanding when the order is written and the twenty
    percent recovery component is therefore live.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Delphine Marchetti",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Ugo Marchetti",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
            amount_cents=75000,
        )
    ]
    scenario.employer = fx.create_employer(
        legal_name="Marchetti Stoneworks",
        fein="41-0000111",
        state_code="MN",
        pay_frequency="SEMIMONTHLY",
        remittance_fee_cents=250,
    )
    scenario.withholding_order = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=150000,
    )
    scenario.withholding_order = fx.serve_withholding_order(scenario.iwo_id)
    return scenario


def test_03_an_amendment_rewrites_the_row_it_was_addressed_to():
    """
    Disposable income of 100,000 cuts the withheld figure to 59,750 on the same id.

    It recomputes `ccpa_cap_pct`, `ccpa_cap_amount_cents`, `withholding_amount_cents` and `employer_fee_cents` through the same four movements, re-checks the aggregate ceiling, and increases the order's `version` by 1.

    A transition on one dimension never implies a transition on another unless this document says it does — amending a withholding order, for instance, leaves `remittance_status` completely untouched.

    Design: Corner/endpoints/amendment_recomputes_the_cap_in_place_without_a_new_withholding_order
    """
    scenario = _served_withholding_order_on_a_hundred_and_fifty_thousand("6233", "6234")
    issued = scenario.withholding_order
    assert scenario.order["monthly_obligation_cents"] == 75000
    # round_half_up(75000 * 0.20) against 75000 of outstanding principal.
    assert issued["arrears_recovery_cents"] == 15000
    assert issued["requested_amount_cents"] == 90000
    # floor(150000 * 0.60) leaves 89750 of room once the fee is set aside.
    assert issued["ccpa_cap_amount_cents"] == 90000
    assert issued["withholding_amount_cents"] == 89750
    assert issued["employer_fee_cents"] == 250
    assert issued["service_status"] == "SERVED"
    assert issued["remittance_status"] == "NOT_DUE"
    assert fx.read_employer(scenario.employer_id)["statutory_cap_pct"] is None
    assert fx.read_employer(scenario.employer_id)["active_iwo_count"] == 1

    amended = fx.amend_withholding_order(scenario.iwo_id, 100000)

    # The action mutates the row it was addressed to.
    assert amended["id"] == issued["id"]
    assert amended["service_status"] == "AMENDED"
    assert amended["version"] == issued["version"] + 1
    assert amended["ccpa_cap_pct"] == 0.60
    assert amended["ccpa_cap_amount_cents"] == 60000
    assert amended["withholding_amount_cents"] == 59750
    assert amended["employer_fee_cents"] == 250
    # Neither the order nor the arrears moved, so the request is unchanged.
    assert amended["requested_amount_cents"] == 90000
    assert amended["remittance_status"] == "NOT_DUE"
    assert amended["missed_remittance_count"] == 0


def test_04_a_second_amendment_loops_in_place_and_creates_no_second_order():
    """
    Raising disposable income to 200,000 restores the full 90,000 on the one row.

    When the employer reports a different disposable income than the one on file, a `CaseWorker` amends the order, driving `service_status` `SERVED → AMENDED`, or `AMENDED → AMENDED` on a further amendment; there is no limit on the number of amendments while the order stands.

    `active_iwo_count` thereafter counts the withholding orders naming that employer whose `service_status` is `ISSUED`, `SERVED` or `AMENDED`.

    Design: Corner/endpoints/amendment_recomputes_the_cap_in_place_without_a_new_withholding_order
    """
    scenario = _served_withholding_order_on_a_hundred_and_fifty_thousand("6235", "6236")
    fx.amend_withholding_order(scenario.iwo_id, 100000)

    again = fx.amend_withholding_order(scenario.iwo_id, 200000)

    assert again["id"] == scenario.iwo_id
    assert again["service_status"] == "AMENDED"
    # floor(200000 * 0.60) leaves 119750 of room, so min(90000, 119750) is the request.
    assert again["ccpa_cap_amount_cents"] == 120000
    assert again["withholding_amount_cents"] == 90000
    assert again["employer_fee_cents"] == 250
    assert again["remittance_status"] == "NOT_DUE"

    assert fx.read_employer(scenario.employer_id)["active_iwo_count"] == 1
    rows, meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, params={"order_id": scenario.order_id}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [scenario.iwo_id]


# ---------------------------------------------------------------------------
# The join row, reached from the order, from the employer and from the state
# ---------------------------------------------------------------------------


def _entered_order_without_charges(ssn_cp: str, ssn_ncp: str, cp_name: str, ncp_name: str) -> fx.Scenario:
    """
    One obligor with an entered 75,000-cent order and an untouched ledger, so the
    requested withholding is the bare monthly obligation.
    """
    return fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": cp_name,
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": ncp_name,
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )


def _two_obligors_at_a_minnesota_and_a_texas_payroll() -> Tuple[
    fx.Scenario, fx.Scenario, Dict[str, Any], Dict[str, Any]
]:
    """
    Two independent obligors, so no aggregate ceiling couples them, each with an
    entered 75,000-cent order; one Minnesota employer and one Texas employer, both
    charging no remittance fee.
    """
    case_a = _entered_order_without_charges("6235", "6236", "Rosalind Achebe", "Femi Achebe")
    case_b = _entered_order_without_charges("6237", "6238", "Clemence Duras", "Aurel Duras")
    employer_m = fx.create_employer(
        legal_name="Mesabi Iron Works",
        fein="41-0000112",
        state_code="MN",
        pay_frequency="MONTHLY",
        remittance_fee_cents=0,
    )
    employer_t = fx.create_employer(
        legal_name="Gulf Coast Rigging",
        fein="74-0000113",
        state_code="TX",
        pay_frequency="MONTHLY",
        remittance_fee_cents=0,
    )
    case_a.employer = employer_m
    case_b.employer = employer_t
    case_a.withholding_order = fx.issue_withholding_order(
        case_a.order_id, employer_m["id"], reported_disposable_income_cents=140000
    )
    case_b.withholding_order = fx.issue_withholding_order(
        case_b.order_id, employer_t["id"], reported_disposable_income_cents=140000
    )
    return case_a, case_b, employer_m, employer_t


def test_05_naming_a_different_employer_in_the_body_changes_the_money():
    """
    Identical arithmetic withholds 75,000 through Minnesota and only 70,000 through Texas.

    Its `jurisdiction_state_code` is stamped as a copy of the employer's `state_code` — always the employer's state, never the case's and never the order's `origin_state_code`, because under UIFSA it is the law of the obligor's principal place of employment that governs withholding limits.

    The employer's state ceiling is then brought in: `ccpa_cap_pct` is the smaller of `federal_cap_pct` and the employer's `statutory_cap_pct` when that state ceiling exists, and is simply `federal_cap_pct` when the employer's state has none.

    Design: Corner/endpoints/withholding_order_join_row_is_addressable_from_both_of_its_parents
    """
    case_a, case_b, employer_m, employer_t = _two_obligors_at_a_minnesota_and_a_texas_payroll()
    iwo_a, iwo_b = case_a.withholding_order, case_b.withholding_order

    # The path supplies one parent, the body the other.
    assert iwo_a["order_id"] == case_a.order_id
    assert iwo_a["employer_id"] == employer_m["id"]
    assert iwo_a["jurisdiction_state_code"] == "MN"
    assert iwo_b["order_id"] == case_b.order_id
    assert iwo_b["employer_id"] == employer_t["id"]
    assert iwo_b["jurisdiction_state_code"] == "TX"

    # Both orders ask for the same 75000: no arrears, so no recovery component.
    assert iwo_a["requested_amount_cents"] == 75000
    assert iwo_b["requested_amount_cents"] == 75000

    # Minnesota has no ceiling of its own, so the federal 0.60 governs.
    assert iwo_a["ccpa_cap_pct"] == 0.60
    assert iwo_a["ccpa_cap_amount_cents"] == 84000
    assert iwo_a["withholding_amount_cents"] == 75000
    # Texas caps at 0.50, and floor(140000 * 0.50) truncates the identical request.
    assert iwo_b["ccpa_cap_pct"] == 0.50
    assert iwo_b["ccpa_cap_amount_cents"] == 70000
    assert iwo_b["withholding_amount_cents"] == 70000

    assert iwo_a["withholding_amount_cents"] - iwo_b["withholding_amount_cents"] == 5000


def test_06_both_foreign_keys_and_the_copied_state_code_are_reverse_reachable():
    """
    The order filter finds one row, the employer filter the other, and each counter moves alone.

    Withholding orders accept `order_id`, `employer_id`, `service_status`, `remittance_status` and `jurisdiction_state_code`.

    It stamps `served_at` with the current logical clock, computes `first_withholding_due_at` as `served_at` plus a fourteen-day employer implementation period, sets `next_remittance_due_at` equal to `first_withholding_due_at`, and increases the employer's `active_iwo_count` by 1.

    Design: Corner/endpoints/withholding_order_join_row_is_addressable_from_both_of_its_parents
    """
    case_a, case_b, employer_m, employer_t = _two_obligors_at_a_minnesota_and_a_texas_payroll()
    fx.serve_withholding_order(case_a.iwo_id)
    fx.serve_withholding_order(case_b.iwo_id)

    by_order, order_meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, params={"order_id": case_a.order_id}
        )
    )
    assert order_meta["total_count"] == 1
    assert [row["id"] for row in by_order] == [case_a.iwo_id]

    by_employer, employer_meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, params={"employer_id": employer_t["id"]}
        )
    )
    assert employer_meta["total_count"] == 1
    assert [row["id"] for row in by_employer] == [case_b.iwo_id]

    by_state, state_meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, params={"jurisdiction_state_code": "TX"}
        )
    )
    assert state_meta["total_count"] == 1
    assert [row["id"] for row in by_state] == [case_b.iwo_id]

    # Service increments only the counter of the employer actually named.
    assert fx.read_employer(employer_m["id"])["active_iwo_count"] == 1
    assert fx.read_employer(employer_t["id"])["active_iwo_count"] == 1


# ---------------------------------------------------------------------------
# The one narrow update in the API, and the read side around it
# ---------------------------------------------------------------------------


def _one_case_and_two_unattached_texans() -> Tuple[fx.Scenario, Dict[str, Any], Dict[str, Any]]:
    """
    One entered case in Minnesota plus two participants in Texas who belong to no
    case at all, so every list filter has something to exclude.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Solveig Amundsen",
            "ssn_last4": "6241",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Havard Amundsen",
            "ssn_last4": "6242",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    spare_cp = fx.create_custodial_party(
        full_name="Marisol Vega",
        ssn_last4="6243",
        residence_state_code="TX",
        monthly_gross_income_cents=180000,
    )
    spare_ncp = fx.create_noncustodial_party(
        full_name="Tobias Vega",
        ssn_last4="6244",
        residence_state_code="TX",
        monthly_gross_income_cents=260000,
    )
    return scenario, spare_cp, spare_ncp


def test_07_recording_a_new_income_versions_the_person_and_leaves_the_order_alone():
    """
    The obligor's income rises to 400,000 while the entered order still reports 300,000.

    A `CaseWorker` supplies a fresh `monthly_gross_income_cents` together with the `income_verification_source` that justifies it, and optionally a revised `employer_name`.

    What this operation deliberately does *not* do is disturb history: no order already in `ENTERED` is recalculated, and no charge already posted is adjusted.

    Only guideline calculations run after the update see the new figure.

    Design: Corner/endpoints/income_patch_versions_the_participant_without_reopening_entered_orders
    """
    scenario, _spare_cp, _spare_ncp = _one_case_and_two_unattached_texans()

    before = fx.read_participant(scenario.ncp_id)
    # One version for the registration, one for the locate result.
    assert before["version"] == 2
    assert before["monthly_gross_income_cents"] == 300000
    assert before["locate_status"] == "LOCATED"
    assert before["enforcement_risk_tier"] == "LOW"

    patched = fx.patch_income(
        scenario.ncp_id,
        400000,
        income_verification_source="SELF_REPORTED",
        employer_name="Amundsen Boatyard",
    )

    assert patched["version"] == 3
    assert patched["monthly_gross_income_cents"] == 400000
    assert patched["income_verification_source"] == "SELF_REPORTED"
    assert patched["employer_name"] == "Amundsen Boatyard"
    # The update reaches the income fields and nothing else.
    assert patched["locate_status"] == "LOCATED"

    reread = fx.read_participant(scenario.ncp_id)
    assert reread["version"] == 3
    assert reread["monthly_gross_income_cents"] == 400000
    assert reread["income_verification_source"] == "SELF_REPORTED"

    order = fx.read_order(scenario.order_id)
    assert order["status"] == "ENTERED"
    assert order["guideline_ncp_income_cents"] == 300000
    assert order["monthly_obligation_cents"] == 75000


def test_08_the_participant_list_filters_and_paginates_independently_of_the_update():
    """
    A limit of 1 over two obligors reports a total of 2 on both pages.

    The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts the rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current window.

    Participants may be filtered by `role_type`, `residence_state_code`, `locate_status` and `enforcement_risk_tier`.

    For a participant whose `role_type` is `CUSTODIAL_PARTY`, both risk scores are always zero and both tiers are always `LOW`.

    Design: Corner/endpoints/income_patch_versions_the_participant_without_reopening_entered_orders
    """
    scenario, spare_cp, spare_ncp = _one_case_and_two_unattached_texans()
    fx.patch_income(
        scenario.ncp_id,
        400000,
        income_verification_source="SELF_REPORTED",
        employer_name="Amundsen Boatyard",
    )

    page_one, meta_one = validate_paginated(
        api_client.list_participants(
            CASE_WORKER_HEADERS,
            params={"role_type": "NONCUSTODIAL_PARTY", "limit": 1, "offset": 0},
        )
    )
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [scenario.ncp_id]

    page_two, meta_two = validate_paginated(
        api_client.list_participants(
            CASE_WORKER_HEADERS,
            params={"role_type": "NONCUSTODIAL_PARTY", "limit": 1, "offset": 1},
        )
    )
    # The total is the filtered total, not the page size, and page two exhausts it.
    assert meta_two["total_count"] == 2
    assert meta_two["has_more"] is False
    assert [row["id"] for row in page_two] == [spare_ncp["id"]]

    _texans, texan_meta = validate_paginated(
        api_client.list_participants(CASE_WORKER_HEADERS, params={"residence_state_code": "TX"})
    )
    assert texan_meta["total_count"] == 2

    located, located_meta = validate_paginated(
        api_client.list_participants(CASE_WORKER_HEADERS, params={"locate_status": "LOCATED"})
    )
    # Only the obligor of the one case ever had a locate result recorded.
    assert located_meta["total_count"] == 1
    assert [row["id"] for row in located] == [scenario.ncp_id]

    _low, low_meta = validate_paginated(
        api_client.list_participants(CASE_WORKER_HEADERS, params={"enforcement_risk_tier": "LOW"})
    )
    # Nothing has been charged anywhere, so all four rows score zero.
    assert low_meta["total_count"] == 4
    assert fx.read_participant(spare_cp["id"])["enforcement_risk_tier"] == "LOW"


# ---------------------------------------------------------------------------
# One enum value on one endpoint decides which later endpoints are legal
# ---------------------------------------------------------------------------


def _two_cases_awaiting_a_locate_result() -> Tuple[fx.Scenario, fx.Scenario]:
    """
    Two cases built by byte-identical call sequences, each referred to locate once
    and therefore sitting in `LOCATE` with its obligor at `PENDING`.
    """
    case_l = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Chidinma Nkemelu",
            "ssn_last4": "6251",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Obiora Nkemelu",
            "ssn_last4": "6252",
            "monthly_gross_income_cents": 300000,
        },
        locate_outcome=None,
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    case_u = fx.open_case_with_parties(
        clock=None,
        cp_overrides={
            "full_name": "Ilse Brandt",
            "ssn_last4": "6253",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Gerrit Brandt",
            "ssn_last4": "6254",
            "monthly_gross_income_cents": 300000,
        },
        locate_outcome=None,
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    fx.refer_to_locate(case_l.case_id, "FEDERAL_PLS")
    fx.refer_to_locate(case_u.case_id, "FEDERAL_PLS")
    case_l.reload_case()
    case_u.reload_case()
    return case_l, case_u


def test_09_a_located_obligor_opens_paternity_and_shuts_the_closure_door():
    """
    `LOCATED` and `UNLOCATABLE` send two identical cases in opposite directions.

    The *result* is an act on the participant: a `CaseWorker` records a `locate_outcome` of either `LOCATED` or `UNLOCATABLE`, optionally attaching the `employer_name` the locate turned up, which writes that outcome into `locate_status` and increases the participant's `version` by 1.

    From `LOCATE`, the case may close only when the obligor's `locate_status` is `UNLOCATABLE` and the `closed_reason` is `NO_JURISDICTION` — the agency cannot proceed against a person it cannot find.

    Outside that bypass, an obligor who is not `LOCATED` blocks both the opening of a paternity action and the drafting of a support order with `ERR_NCP_NOT_LOCATED` (HTTP 409), and an obligor whose `locate_status` is `UNLOCATABLE` blocks every establishment step regardless of the good-cause flag.

    Design: Corner/endpoints/locate_outcome_decides_which_case_paths_open_and_which_close
    """
    case_l, case_u = _two_cases_awaiting_a_locate_result()
    assert case_l.case["case_status"] == "LOCATE"
    assert case_u.case["case_status"] == "LOCATE"

    located = fx.record_locate_outcome(case_l.ncp_id, "LOCATED", employer_name="Nkemelu Logistics")
    unlocatable = fx.record_locate_outcome(case_u.ncp_id, "UNLOCATABLE")

    assert located["locate_status"] == "LOCATED"
    assert located["employer_name"] == "Nkemelu Logistics"
    # The same endpoint on the same role, one different enum value.
    assert unlocatable["locate_status"] == "UNLOCATABLE"

    # For a located obligor the LOCATE -> CLOSED transition does not exist at all.
    validate_error(
        api_client.close_case(
            case_l.case_id, f.closure_payload("NO_JURISDICTION"), SUPERVISING_ATTORNEY_HEADERS
        ),
        ApiErrorId.INVALID_CASE_STATUS,
        409,
    )

    # UNLOCATABLE is not LOCATED, and the establishment path is barred.
    validate_error(
        api_client.create_paternity_action(
            case_u.case_id, f.paternity_action_payload("VOLUNTARY_ACKNOWLEDGMENT"), CASE_WORKER_HEADERS
        ),
        ApiErrorId.NCP_NOT_LOCATED,
        409,
    )


def test_10_the_closure_the_located_case_was_refused_is_the_unlocatable_case_s_only_exit():
    """
    `CP_REQUEST` is refused from `LOCATE`, and the two cases end in opposite states.

    Only then are state preconditions evaluated: `ERR_INVALID_CASE_STATUS`, `ERR_INVALID_ORDER_STATUS`, `ERR_INVALID_PATERNITY_STATUS`, `ERR_INVALID_IWO_STATUS`, `ERR_INVALID_REVIEW_STATUS`, `ERR_INVALID_ACTION_STATUS`, `ERR_INVALID_REFERRAL_STATUS` and `ERR_INVALID_OFFER_STATUS`, each at HTTP 409.

    The other two methods create the row in `PENDING` and move the case to `PATERNITY_PENDING`.

    Closure sets `case_status` to `CLOSED`, stamps `closed_at` from the logical clock, and increases the case's `version` by 1.

    Design: Corner/endpoints/locate_outcome_decides_which_case_paths_open_and_which_close
    """
    case_l, case_u = _two_cases_awaiting_a_locate_result()
    fx.record_locate_outcome(case_l.ncp_id, "LOCATED", employer_name="Nkemelu Logistics")
    fx.record_locate_outcome(case_u.ncp_id, "UNLOCATABLE")

    # The transition is reason-conditional as well as status-conditional.
    validate_error(
        api_client.close_case(
            case_u.case_id, f.closure_payload("CP_REQUEST"), SUPERVISING_ATTORNEY_HEADERS
        ),
        ApiErrorId.INVALID_CASE_STATUS,
        409,
    )

    action = fx.open_paternity_action(case_l.case_id, "VOLUNTARY_ACKNOWLEDGMENT")
    assert action["status"] == "PENDING"
    assert action["case_id"] == case_l.case_id

    closed = fx.close_case(case_u.case_id, "NO_JURISDICTION")
    assert closed["case_status"] == "CLOSED"
    assert closed["closed_reason"] == "NO_JURISDICTION"
    a.assert_instant_equals(closed["closed_at"], CLOCK_START, "closed_at")

    assert fx.read_case(case_l.case_id)["case_status"] == "PATERNITY_PENDING"
