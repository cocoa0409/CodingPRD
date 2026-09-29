"""Endpoints whose whole job is to aggregate, to link, or to refuse a shortcut.

The agency report is a pure read over the award's tree; the benefits agreement
is a junction row over two foreign keys; and the cure endpoint is not a
general-purpose deployment route.
"""
from test_helpers import (
    ApiErrorId,
    SETUP_CLOCK,
    add_project_company,
    add_sub_allocation,
    agency_report_payload,
    assert_cents,
    assert_instant,
    assert_pct,
    create_cba_payload,
    cure_payload,
    get_success_data,
    make_agency_headers,
    read_award,
    read_qei,
    setup_active_award,
    setup_certified_project_company,
    setup_deployed_investment,
    validate_error,
    validate_paginated,
    validate_success,
)

MODERATE_TRACT = {
    "tract_code": "28049000800",
    "state_code": "MS",
    "poverty_rate_pct": 22.00,
    "mfi_ratio_pct": 78.00,
    "unemployment_ratio": 1.10,
}
MODERATE_QALICB = {
    "legal_name": "Delta Machine Works LLC",
    "state_code": "MS",
    "naics_code": "332710",
}
MODERATE_CBA = {"target_fte_count": 15, "measurement_basis": "PAYROLL_HOURS"}
SEVERE_PLACEMENT_CENTS = 60_000_000
MODERATE_PLACEMENT_CENTS = 35_000_000


def test_the_agency_report_weights_distress_by_principal_not_by_business(api):
    """Two businesses, one severe, and a share that counts money rather than heads.

    PRD: "The `CDESponsor` supplies a single `report_year`, and the server answers
    with a snapshot: the `allocation_award_id` reported on, the `report_year`,
    `issued_qei_count` as the count of the award's investments whose
    `deployment_status` is anything other than `VOIDED`, `deployed_principal_cents`
    as the sum of `outstanding_principal_cents` over the sub-allocations of those
    investments whose `status` is `DEPLOYED` or `PARTIALLY_REPAID`,
    `qualifying_qalicb_count` as the number of *distinct* project companies funded
    by those same sub-allocations, the freshly recomputed
    `severe_distress_share_pct`, a `severe_distress_shortfall` flag that is true
    exactly when that share sits strictly below the award's
    `min_severe_distress_share_pct`, and the award's derived `at_risk_qei_count`,
    `recaptured_qei_count` and `cba_breach_count` copied across."

    PRD: "Filing sets `last_agency_report_year` to the reported year and increments
    the award's `version`."

    PRD: "The share is 100 multiplied by the severe sum, divided by the total sum,
    rounded half-up to 2 decimal places; when the total sum is 0 the share is
    0.00."

    PRD: "Note carefully that a shortfall against `min_severe_distress_share_pct`
    is *reported* but never restricting: it flags the annual agency report and
    refuses no request."

    Design: Corner/endpoints/agency_report_aggregates_deployment_and_impact_across_two_qalicbs
    """
    scenario = setup_deployed_investment(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=123,
        award_overrides={"min_severe_distress_share_pct": 70.00},
        qlici_overrides={"loan_class": "A", "principal_cents": SEVERE_PLACEMENT_CENTS},
    )
    assert scenario.tract["distress_tier"] == "SEVERE"

    moderate = add_project_company(
        api,
        scenario,
        tract_overrides=MODERATE_TRACT,
        qalicb_overrides=MODERATE_QALICB,
        cba_overrides=MODERATE_CBA,
    )
    moderate_tract = scenario.tracts[-1]
    assert moderate_tract["distress_tier"] == "MODERATE"
    assert moderate_tract["severe_criteria_met_count"] == 0
    assert_pct(moderate_tract["distress_score"], 37.83, "distress_score")
    add_sub_allocation(
        api,
        scenario,
        moderate,
        loan_class="B",
        principal_cents=MODERATE_PLACEMENT_CENTS,
    )

    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["uninvested_cash_cents"], 0, "uninvested_cash_cents")
    assert qei["deployment_status"] == "FULLY_DEPLOYED"
    assert_pct(
        qei["substantially_all_pct_direct"], 100.00, "substantially_all_pct_direct"
    )

    before = read_award(api, scenario.award["id"])
    report = get_success_data(
        api.file_agency_report(
            scenario.award["id"], agency_report_payload(2026), scenario.cde_headers
        )
    )
    assert report["report_year"] == 2026
    assert report["allocation_award_id"] == scenario.award["id"]
    assert report["issued_qei_count"] == 1
    assert_cents(
        report["deployed_principal_cents"], 95_000_000, "deployed_principal_cents"
    )
    assert report["qualifying_qalicb_count"] == 2
    assert_pct(
        report["severe_distress_share_pct"], 63.16, "severe_distress_share_pct"
    )
    assert report["severe_distress_shortfall"] is True
    assert report["at_risk_qei_count"] == 0
    assert report["recaptured_qei_count"] == 0
    assert report["cba_breach_count"] == 0

    award = read_award(api, scenario.award["id"])
    assert award["last_agency_report_year"] == 2026
    assert_pct(
        award["severe_distress_share_pct"], 63.16, "severe_distress_share_pct"
    )
    assert award["compliance_posture"] == "UNRESTRICTED"
    assert award["version"] == before["version"] + 1


UNKNOWN_QALICB_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_AWARD_ID = "00000000-0000-4000-8000-0000000000bb"


def test_the_first_declared_foreign_key_answers_when_both_are_unknown(api):
    """Two unresolvable references, and only the first one gets a say.

    PRD: "A `CDESponsor` binds a project company to a community benefits agreement
    by naming the business through `qalicb_id` and the award whose
    community-outcome commitments it sits under through `allocation_award_id`, then
    setting the terms: `target_fte_count`, the committed number of qualifying
    full-time-equivalent jobs per certification year (at least 1);
    `wage_floor_cents_per_hour`, the minimum average hourly wage in cents for a
    reporting period to count toward that commitment (zero or more);
    `local_hire_pct_target`, the committed minimum share of headcount hired from
    the service area (0.00 through 100.00 with 2 decimal places); and
    `measurement_basis`, which is either `HEADCOUNT` or `PAYROLL_HOURS` and governs
    how achievement is measured for the agreement's whole life."

    PRD: "Foreign keys supplied in a request body are resolved after path
    identifiers and in the order in which the operation declares its input fields,
    again reporting the first failure with the not-found code of the missing
    resource's own type."

    PRD: "A new agreement stamps `agreement_start_at` from the logical clock — the
    anchor for every certification-year window — opens in `status` `ACTIVE`, with
    `consecutive_cure_required_count` at 0, `latest_compliance_pct` and
    `latest_local_hire_pct` at 0.00, `last_certified_year` null and `breached_at`
    null."

    Design: Corner/endpoints/binding_a_benefits_agreement_validates_both_foreign_keys_in_declared_order
    """
    scenario = setup_active_award(
        api, clock=SETUP_CLOCK, certification_suffix=124
    )
    setup_certified_project_company(api, scenario)

    both_unknown = api.create_community_benefits_agreement(
        create_cba_payload(UNKNOWN_QALICB_ID, UNKNOWN_AWARD_ID),
        scenario.cde_headers,
    )
    validate_error(both_unknown, ApiErrorId.ERR_QALICB_NOT_FOUND.value, 404)

    award_unknown = api.create_community_benefits_agreement(
        create_cba_payload(scenario.qalicb["id"], UNKNOWN_AWARD_ID),
        scenario.cde_headers,
    )
    validate_error(
        award_unknown, ApiErrorId.ERR_ALLOCATION_AWARD_NOT_FOUND.value, 404
    )

    agreement = validate_success(
        api.create_community_benefits_agreement(
            create_cba_payload(scenario.qalicb["id"], scenario.award["id"]),
            scenario.cde_headers,
        ),
        201,
    )
    assert agreement["qalicb_id"] == scenario.qalicb["id"]
    assert agreement["allocation_award_id"] == scenario.award["id"]
    assert agreement["status"] == "ACTIVE"
    assert_instant(
        agreement["agreement_start_at"], SETUP_CLOCK, "agreement_start_at"
    )
    assert agreement["consecutive_cure_required_count"] == 0
    assert_pct(agreement["latest_compliance_pct"], 0.00, "latest_compliance_pct")
    assert_pct(agreement["latest_local_hire_pct"], 0.00, "latest_local_hire_pct")
    assert agreement["last_certified_year"] is None
    assert agreement["breached_at"] is None

    _, meta = validate_paginated(
        api.list_community_benefits_agreements(make_agency_headers())
    )
    assert meta["total_count"] == 1, "the two refused calls persisted nothing"


CURE_TARGET_CENTS = 50_750_000
PARTIAL_PLACEMENT_CENTS = 30_000_000


def test_a_healthy_investment_cannot_use_the_cure_route_to_deploy(api):
    """Plenty of cash, a certified target, and still the wrong door.

    PRD: "While an investment is `AT_RISK` and the logical clock is at or before
    its `cure_deadline_at`, the `CDESponsor` may deploy additional qualifying
    principal by naming the receiving business through `qalicb_id` and the money
    through `principal_cents`."

    PRD: "A cure on an investment that is not `AT_RISK`, or one attempted after
    `cure_deadline_at`, is `ERR_INVALID_STATE_TRANSITION`; a cure aimed at a
    `DISQUALIFIED` business is `ERR_QALICB_DISQUALIFIED`; a cure that exceeds the
    investment's `uninvested_cash_cents` is `ERR_INSUFFICIENT_UNINVESTED_CASH`; and
    a cure on a recaptured investment is `ERR_QEI_RECAPTURED`."

    PRD: "Rules are evaluated in ascending priority, the first violated rule alone
    decides the response, and a rejected request persists nothing at all — no
    partial cascade, no counter movement, no version increment."

    Design: Corner/endpoints/curing_a_compliant_qei_returns_invalid_state_transition
    """
    scenario = setup_deployed_investment(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=126,
        qlici_overrides={"principal_cents": PARTIAL_PLACEMENT_CENTS},
    )
    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["uninvested_cash_cents"], 65_000_000, "uninvested_cash_cents")
    assert_pct(
        qei["substantially_all_pct_direct"], 31.58, "substantially_all_pct_direct"
    )
    assert qei["compliance_status"] == "COMPLIANT"
    assert qei["cure_deadline_at"] is None

    refused = api.cure_qei(
        qei["id"],
        cure_payload(scenario.qalicb["id"], CURE_TARGET_CENTS),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    after = read_qei(api, qei["id"])
    assert_cents(after["uninvested_cash_cents"], 65_000_000, "uninvested_cash_cents")
    assert_pct(
        after["substantially_all_pct_direct"], 31.58, "substantially_all_pct_direct"
    )
    assert after["compliance_status"] == "COMPLIANT"

    _, meta = validate_paginated(api.list_qlicis(make_agency_headers()))
    assert meta["total_count"] == 1, "the cure created no sub-allocation"

    award = read_award(api, scenario.award["id"])
    assert award["at_risk_qei_count"] == 0
    assert award["compliance_posture"] == "UNRESTRICTED"
