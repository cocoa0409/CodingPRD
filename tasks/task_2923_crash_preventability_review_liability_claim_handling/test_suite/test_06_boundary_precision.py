"""Boundaries probed from both sides: one second apart, and one cent apart."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_instants_equal
from test_helpers.constants import (
    CLAIM_HANDLING_NEGOTIATION,
    CLAIMANT_TYPE_PROPERTY,
    DEMAND_STATE_OFFER_OUTSTANDING,
    DEMAND_STATE_SETTLED,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    REPORTING_STATUS_FILED,
    REPORTING_STATUS_LATE_FILED,
    REPORTING_STATUS_PENDING_FILING,
    RESERVE_BASIS_DEMAND_BASED,
    ROUND_OUTCOME_OPEN,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MODERATE,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_demand,
    build_driver,
    build_policy_layer,
    build_terminal,
    make_offer,
    revise_reserve,
    set_clock,
    settle,
)

DUE_INSTANT = "2026-08-02T14:00:00Z"
ONE_SECOND_LATE = "2026-08-02T14:00:01Z"
DISABLING_TOW_CODE = "DISABLING_TOW"

SIR_LIMIT_CENTS = 10_000_000
PRIMARY_LIMIT_CENTS = 5_000_000
TOWER_CAPACITY_CENTS = 15_000_000
DEMAND_AMOUNT_CENTS = 20_000_000
FITTING_OFFER_CENTS = 13_392_857
OVERFLOWING_OFFER_CENTS = 13_392_858
SHARED_ALAE_CENTS = 1_607_143


def _two_identical_recordable_crashes(api: ApiClient) -> dict:
    """Sibling crashes sharing one due instant, so it can be probed twice."""
    terminal = build_terminal(
        api,
        name="Kenton Terminal",
        terminal_code="KEN01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1201",
        full_name="Abe Fontaine",
        cdl_number="OH-CDL-1201",
        hire_date="2009-07-13",
    )
    shared = {
        "occurred_at": "2026-07-30T14:00:00Z",
        "severity": SEVERITY_MODERATE,
        "route_class": ROUTE_CLASS_REGIONAL,
        "tow_away": True,
        "tow_reason": TOW_REASON_DISABLING_DAMAGE,
    }
    crash_a = build_crash(
        api,
        driver["id"],
        terminal["id"],
        notified_at="2026-07-30T14:30:00Z",
        location_text="US-68 at Scioto Marsh Rd",
        **shared,
    )
    crash_b = build_crash(
        api,
        driver["id"],
        terminal["id"],
        notified_at="2026-07-30T14:45:00Z",
        location_text="US-68 at Scioto Marsh Rd, second unit",
        **shared,
    )
    return {"terminal": terminal, "crash_a": crash_a, "crash_b": crash_b}


class TestFilingAtTheExactDueInstant:
    """The due instant is inside the window; one second past it is not."""

    def test_the_frozen_due_instant_is_seventy_two_hours_after_the_crash(
        self, api: ApiClient
    ):
        """A disabling tow is one code, and the non-hazmat window is 72 hours.

        PRD: "A tow contributes `DISABLING_TOW` only when `tow_away` is true *and*
        `tow_reason` is `DISABLING_DAMAGE` ... `report_due_at` is 24 hours after
        `occurred_at` when a hazardous-material release occurred, and 72 hours —
        three days — after `occurred_at` otherwise, and `reporting_status` starts
        at `PENDING_FILING`."

        Design: Difficulty/boundary_precision_check/regulatory_report_at_exact_due_instant_is_filed
        """
        context = _two_identical_recordable_crashes(api)
        for label in ("crash_a", "crash_b"):
            crash = context[label]
            assert crash["dot_recordable"] is True
            assert crash["recordability_codes"] == [DISABLING_TOW_CODE]
            assert_instants_equal(crash["report_due_at"], DUE_INSTANT, f"{label} report_due_at")
            assert crash["reporting_status"] == REPORTING_STATUS_PENDING_FILING
            assert crash["filed_at"] is None

    def test_a_filing_on_the_due_instant_is_on_time_and_one_second_later_is_late(
        self, api: ApiClient
    ):
        """The same instant separates FILED from LATE_FILED on two twins.

        PRD: "Filing at or before the exact due instant moves `reporting_status`
        from `PENDING_FILING` to `FILED`; filing after it moves `PENDING_FILING`
        to `LATE_FILED`. The due instant itself is inclusive — a filing landing
        exactly on `report_due_at` is on time."

        Design: Difficulty/boundary_precision_check/regulatory_report_at_exact_due_instant_is_filed
        """
        context = _two_identical_recordable_crashes(api)

        set_clock(api, DUE_INSTANT)
        on_time = validate_success(
            api.file_regulatory_report(
                context["crash_a"]["id"],
                factories.regulatory_report_payload(filing_reference="FMCSA-2026-KEN-A"),
                SAFETY_MANAGER,
            )
        )
        assert on_time["reporting_status"] == REPORTING_STATUS_FILED
        assert on_time["filing_reference"] == "FMCSA-2026-KEN-A"
        assert_instants_equal(on_time["filed_at"], DUE_INSTANT, "filed_at")

        set_clock(api, ONE_SECOND_LATE)
        late = validate_success(
            api.file_regulatory_report(
                context["crash_b"]["id"],
                factories.regulatory_report_payload(filing_reference="FMCSA-2026-KEN-B"),
                SAFETY_MANAGER,
            )
        )
        assert late["reporting_status"] == REPORTING_STATUS_LATE_FILED
        assert late["filing_reference"] == "FMCSA-2026-KEN-B"
        assert_instants_equal(late["filed_at"], ONE_SECOND_LATE, "filed_at")

    def test_only_the_late_twin_lifts_the_terminal_late_filing_counter(
        self, api: ApiClient
    ):
        """One of two identical crashes was late, so the counter reads one.

        PRD: "The late branch carries one extra consequence: the terminal frozen
        on the crash reports a `late_filing_count` one higher on its next read."

        Design: Difficulty/boundary_precision_check/regulatory_report_at_exact_due_instant_is_filed
        """
        context = _two_identical_recordable_crashes(api)
        terminal_id = context["terminal"]["id"]
        assert (
            validate_success(api.get_terminal(terminal_id, SAFETY_ADMIN))["late_filing_count"]
            == 0
        )

        set_clock(api, DUE_INSTANT)
        validate_success(
            api.file_regulatory_report(
                context["crash_a"]["id"],
                factories.regulatory_report_payload(filing_reference="FMCSA-2026-KEN-A"),
                SAFETY_MANAGER,
            )
        )
        assert (
            validate_success(api.get_terminal(terminal_id, SAFETY_ADMIN))["late_filing_count"]
            == 0
        )

        set_clock(api, ONE_SECOND_LATE)
        validate_success(
            api.file_regulatory_report(
                context["crash_b"]["id"],
                factories.regulatory_report_payload(filing_reference="FMCSA-2026-KEN-B"),
                SAFETY_MANAGER,
            )
        )
        assert (
            validate_success(api.get_terminal(terminal_id, SAFETY_ADMIN))["late_filing_count"]
            == 1
        )


def _two_claims_on_one_fifteen_million_tower(api: ApiClient) -> dict:
    """Two claims fully reserved against one 15,000,000-cent tower."""
    terminal = build_terminal(
        api,
        name="Lima Terminal",
        terminal_code="LIM01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1301",
        full_name="Bess Nkemelu",
        cdl_number="OH-CDL-1301",
        hire_date="2008-03-02",
    )
    sir_layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=SIR_LIMIT_CENTS,
        insurer_name="Self-Insured Retention",
    )
    primary_layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=2,
        layer_type=LAYER_KIND_PRIMARY,
        attachment_point_cents=SIR_LIMIT_CENTS,
        limit_cents=PRIMARY_LIMIT_CENTS,
        insurer_name="Continental Freight Casualty",
    )

    def _file(
        occurred_at: str,
        notified_at: str,
        location_text: str,
        note: str,
        claimant_name: str,
        received_at: str,
        offer_cents: int,
    ) -> dict:
        crash = build_crash(
            api,
            driver["id"],
            terminal["id"],
            occurred_at=occurred_at,
            notified_at=notified_at,
            location_text=location_text,
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_LINEHAUL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
        )
        claim = build_claim(
            api, crash["id"], claimant_notice_date="2026-07-31", adjuster_note=note
        )
        demand = build_demand(
            api,
            claim["id"],
            claimant_name=claimant_name,
            claimant_type=CLAIMANT_TYPE_PROPERTY,
            demand_amount_cents=DEMAND_AMOUNT_CENTS,
            represented_by_counsel=False,
            demand_received_at=received_at,
        )
        observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        reserved = revise_reserve(
            api,
            claim["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note=f"reserving {note} to the demand",
        )
        round_row = make_offer(api, demand["id"], offer_cents)
        return {"claim": reserved, "demand": demand, "round": round_row}

    alpha = _file(
        "2026-07-30T10:00:00Z",
        "2026-07-30T10:20:00Z",
        "I-75 MM 125 southbound",
        "claim ALPHA",
        "Allen County Fleet Services",
        "2026-07-31T09:00:00Z",
        FITTING_OFFER_CENTS,
    )
    beta = _file(
        "2026-07-30T18:00:00Z",
        "2026-07-30T18:20:00Z",
        "I-75 MM 127 southbound",
        "claim BETA",
        "Shawnee Logistics Inc",
        "2026-07-31T09:30:00Z",
        OVERFLOWING_OFFER_CENTS,
    )
    return {
        "alpha": alpha,
        "beta": beta,
        "sir_layer": sir_layer,
        "primary_layer": primary_layer,
    }


class TestSettlementAgainstTheExactTowerCapacity:
    """A total equal to capacity fits; one cent more does not."""

    def test_a_total_equal_to_capacity_settles_and_consumes_every_layer(
        self, api: ApiClient
    ):
        """The comparison is fits, not fits with room to spare.

        PRD: "A standing offer of 13,392,857 lands in the middle tier, so
        `alae_cents` is the half-up rounding of 1,607,142.84, namely 1,607,143,
        and `settlement_total_cents` is exactly 15,000,000 — the tower is
        exhausted to the cent and the settlement succeeds, allocating 10,000,000
        to the retention and 5,000,000 to the primary."

        Design: Difficulty/boundary_precision_check/settlement_total_exactly_exhausts_policy_capacity
        """
        context = _two_claims_on_one_fifteen_million_tower(api)
        alpha = context["alpha"]
        assert_cents(
            alpha["claim"]["outstanding_reserve_cents"],
            DEMAND_AMOUNT_CENTS,
            "outstanding_reserve_cents",
        )

        settled = settle(
            api, alpha["demand"]["id"], settlement_reference="SET-2026-LIM-ALPHA"
        )
        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_cents(settled["alae_cents"], SHARED_ALAE_CENTS, "alae_cents")
        assert_cents(
            settled["settlement_total_cents"], TOWER_CAPACITY_CENTS, "settlement_total_cents"
        )

        claim = validate_success(api.get_claim(alpha["claim"]["id"], CLAIMS_MANAGER))
        allocations = claim["layer_allocations"]
        assert len(allocations) == 2
        assert allocations[0]["policy_layer_id"] == context["sir_layer"]["id"]
        assert_cents(allocations[0]["allocated_cents"], SIR_LIMIT_CENTS, "sir allocated_cents")
        assert allocations[1]["policy_layer_id"] == context["primary_layer"]["id"]
        assert_cents(
            allocations[1]["allocated_cents"], PRIMARY_LIMIT_CENTS, "primary allocated_cents"
        )
        assert_cents(claim["sir_eroded_cents"], SIR_LIMIT_CENTS, "sir_eroded_cents")
        assert_cents(claim["insured_paid_cents"], PRIMARY_LIMIT_CENTS, "insured_paid_cents")

    def test_one_cent_more_indemnity_keeps_the_expense_and_overflows_the_tower(
        self, api: ApiClient
    ):
        """The neighbouring cent rounds to the same expense and still overflows.

        PRD: "A standing offer of 13,392,858 produces the same `alae_cents` of
        1,607,143, since 1,607,142.96 also rounds half up to that figure, for a
        total of 15,000,001 — one cent over capacity — and is refused with
        `ERR_COVERAGE_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/settlement_total_exactly_exhausts_policy_capacity
        """
        context = _two_claims_on_one_fifteen_million_tower(api)
        settle(api, context["alpha"]["demand"]["id"], settlement_reference="SET-2026-LIM-ALPHA")
        beta = context["beta"]
        assert_cents(
            beta["claim"]["outstanding_reserve_cents"],
            DEMAND_AMOUNT_CENTS,
            "outstanding_reserve_cents",
        )

        body = validate_error(
            api.settle_demand(
                beta["demand"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-LIM-BETA"),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.COVERAGE_EXHAUSTED.value,
        )
        assert body["error_id"] != ApiErrorId.RESERVE_INSUFFICIENT.value

    def test_the_overflowing_settlement_leaves_its_demand_and_claim_untouched(
        self, api: ApiClient
    ):
        """Settlement is all-or-nothing, so the refused file is unchanged.

        PRD: "If anything is still unallocated after the last layer, the entire
        settlement is refused with `ERR_COVERAGE_EXHAUSTED` and no field on the
        demand, the claim or any layer is modified — settlement is all-or-nothing,
        never partial."

        Design: Difficulty/boundary_precision_check/settlement_total_exactly_exhausts_policy_capacity
        """
        context = _two_claims_on_one_fifteen_million_tower(api)
        settle(api, context["alpha"]["demand"]["id"], settlement_reference="SET-2026-LIM-ALPHA")
        beta = context["beta"]

        validate_error(
            api.settle_demand(
                beta["demand"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-LIM-BETA"),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.COVERAGE_EXHAUSTED.value,
        )

        demand = validate_success(api.get_demand(beta["demand"]["id"], CLAIMS_MANAGER))
        assert demand["status"] == DEMAND_STATE_OFFER_OUTSTANDING
        assert demand["settled_amount_cents"] is None
        assert demand["alae_cents"] is None
        assert demand["settlement_total_cents"] is None
        assert demand["settlement_reference"] is None

        rounds, _ = validate_paginated(
            api.list_negotiation_rounds(beta["demand"]["id"], CLAIMS_MANAGER)
        )
        assert len(rounds) == 1
        assert rounds[0]["outcome"] == ROUND_OUTCOME_OPEN

        claim = validate_success(api.get_claim(beta["claim"]["id"], CLAIMS_MANAGER))
        assert claim["layer_allocations"] == []
        assert_cents(claim["indemnity_paid_cents"], 0, "indemnity_paid_cents")
        assert_cents(claim["alae_paid_cents"], 0, "alae_paid_cents")
        assert_cents(
            claim["outstanding_reserve_cents"],
            DEMAND_AMOUNT_CENTS,
            "outstanding_reserve_cents",
        )
        assert claim["handling_status"] == CLAIM_HANDLING_NEGOTIATION
