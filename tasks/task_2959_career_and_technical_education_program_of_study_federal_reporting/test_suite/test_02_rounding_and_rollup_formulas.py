"""Where the grant ledger rounds, and what its indirect tier is keyed on.

Both scenarios here charge a state-approved program against a federal award and
then read the rebuilt ledger. The first pins the rounding boundary — each line
rounds its own federal share before the roll-up adds them together — and the
second pins the intermediate value the indirect-rate tier is looked up on.
"""

from test_helpers import (
    Builder,
    CteApiClient,
    STOP_STATE_APPROVED,
    assert_cents,
    assert_ledger,
    assert_ledger_identity,
    assert_rate,
    f,
    k,
    users,
    validate_unpaginated,
)

# --- Two consumable lines whose share rounds up by half a cent each ----------
ROUNDING_CIP = "15.0805"
LINE_UNIT_COST_CENTS = 125005
LINE_QUANTITY = 2
LINE_GROSS_CENTS = 250010
LINE_APPROVED_CENTS = 212509
TWO_LINE_DIRECT_CENTS = 425018
TWO_LINE_DIRECT_IF_SUMMED_FIRST_CENTS = 425017
TWO_LINE_POOL_CENTS = 34511
TWO_LINE_OBLIGATED_CENTS = 459529
TWO_LINE_REMAINING_CENTS = 4540471
ROUNDING_ALLOCATION_CENTS = 5000000

# --- One professional-development line just under the first tier ceiling -----
TIER_CIP = "15.1301"
TIER_ALLOCATION_CENTS = 10000000
TIER_LINE_CENTS = 4900000
TIER_POOL_CENTS = 397880
TIER_POOL_IF_KEYED_ON_OBLIGATED_CENTS = 318500
TIER_OBLIGATED_CENTS = 5297880
TIER_OBLIGATED_IF_KEYED_ON_OBLIGATED_CENTS = 5218500
TIER_REMAINING_CENTS = 4702120
TIER_ADMIN_CAP_CENTS = 500000


def _approved_program(build: Builder, cip_code: str, title: str):
    """Author, submit, endorse and state-approve a program of study."""
    scenario = build.program(
        cip_code,
        stop_at=STOP_STATE_APPROVED,
        title=title,
        cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
    )
    return scenario.program_id


def _certify(api: CteApiClient, expenditure_id: str):
    """Rule the line allowable as the fiscal officer who did not request it."""
    return validate_unpaginated(
        api.certify_allowability(
            expenditure_id,
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        ),
        200,
    )


def _read_grant(api: CteApiClient, grant_id: str):
    """Read the award, whose ledger figures the certification rebuilt."""
    return validate_unpaginated(
        api.get_grant(grant_id, users.headers(users.FISCAL_OFFICER)), 200
    )


def _two_consumable_lines(build: Builder):
    """Request two identical consumable lines of 250010 gross cents each."""
    program_id = _approved_program(build, ROUNDING_CIP, "Mechatronics")
    grant = build.grant(fiscal_year=2027, allocation_cents=ROUNDING_ALLOCATION_CENTS)
    first = build.expenditure(
        grant.grant_id,
        program_id,
        k.CATEGORY_CONSUMABLE,
        LINE_UNIT_COST_CENTS,
        LINE_QUANTITY,
        service_period_start="2026-09-01",
        service_period_end="2026-09-30",
        description="Shop consumables lot A",
    )
    second = build.expenditure(
        grant.grant_id,
        program_id,
        k.CATEGORY_CONSUMABLE,
        LINE_UNIT_COST_CENTS,
        LINE_QUANTITY,
        service_period_start="2026-10-01",
        service_period_end="2026-10-31",
        description="Shop consumables lot B",
    )
    return grant, first, second


def _single_development_line(build: Builder):
    """Request one professional-development line of 4900000 gross cents."""
    program_id = _approved_program(build, TIER_CIP, "Engineering Design")
    grant = build.grant(fiscal_year=2028, allocation_cents=TIER_ALLOCATION_CENTS)
    line = build.expenditure(
        grant.grant_id,
        program_id,
        k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
        TIER_LINE_CENTS,
        1,
        service_period_start="2026-09-01",
        service_period_end="2027-05-31",
        description="Statewide CTE institute cohort",
    )
    return grant, line


class TestPerLineFederalShareRounding:
    """Each line rounds its own share before the award ledger adds them up."""

    def test_each_consumable_line_rounds_its_own_federal_share(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500."

        PRD §3.7: "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**. The award ledger then sums those already-rounded integers. Aggregating gross amounts across lines and rounding the product once at the end is forbidden: two lines of 250,010 gross cents at a 0.8500 share round to 212,509 cents each for a total of 425,018, whereas rounding a combined 500,020 gross at 0.8500 would yield 425,017 — and 425,018 is the correct figure."

        Design: Difficulty/combinatorial_formula/federal_share_rounds_per_line_before_the_grant_rollup_sums
        """
        _grant, first, second = _two_consumable_lines(build)

        first_certified = _certify(api, first["id"])
        second_certified = _certify(api, second["id"])

        for line in (first_certified, second_certified):
            assert line["status"] == k.EXP_CERTIFIED
            assert_cents(line["gross_cents"], LINE_GROSS_CENTS, "gross_cents")
            assert_rate(line["federal_share_pct"], 0.8500, "federal_share_pct")
            assert_cents(line["approved_cents"], LINE_APPROVED_CENTS, "approved_cents")

    def test_direct_total_sums_the_two_already_rounded_lines(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation. Every addend is an already-rounded integer, so summation order is immaterial."

        PRD §3.7: "Aggregating gross amounts across lines and rounding the product once at the end is forbidden: two lines of 250,010 gross cents at a 0.8500 share round to 212,509 cents each for a total of 425,018, whereas rounding a combined 500,020 gross at 0.8500 would yield 425,017 — and 425,018 is the correct figure."

        Design: Difficulty/combinatorial_formula/federal_share_rounds_per_line_before_the_grant_rollup_sums
        """
        grant, first, second = _two_consumable_lines(build)
        _certify(api, first["id"])
        _certify(api, second["id"])

        award = _read_grant(api, grant.grant_id)

        assert_cents(
            award["direct_obligated_cents"],
            TWO_LINE_DIRECT_CENTS,
            "direct_obligated_cents",
        )
        assert award["direct_obligated_cents"] != TWO_LINE_DIRECT_IF_SUMMED_FIRST_CENTS, (
            "Summing gross cents across the two lines and rounding once at the end "
            f"would have produced {TWO_LINE_DIRECT_IF_SUMMED_FIRST_CENTS}"
        )

    def test_ledger_rebuilds_from_the_per_line_direct_total(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500. The lookup is never keyed on `obligated_cents` or `remaining_cents`, even though `obligated_cents` contains the pool this rate produces — that circularity is precisely the mistake the pinning forbids. Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        PRD §3.7: "Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`, and `admin_cap_cents` is `allocation_cents` multiplied by five percent, rounded half-up to whole cents. After every rebuild, `allocation_cents` must equal `obligated_cents` plus `remaining_cents` exactly — that identity is the conserved quantity of the whole grant model."

        Design: Difficulty/combinatorial_formula/federal_share_rounds_per_line_before_the_grant_rollup_sums
        """
        grant, first, second = _two_consumable_lines(build)
        _certify(api, first["id"])
        _certify(api, second["id"])

        award = _read_grant(api, grant.grant_id)

        assert_ledger(
            award,
            direct_cents=TWO_LINE_DIRECT_CENTS,
            indirect_rate=k.INDIRECT_RATE_LOW,
            pool_cents=TWO_LINE_POOL_CENTS,
            obligated_cents=TWO_LINE_OBLIGATED_CENTS,
            remaining_cents=TWO_LINE_REMAINING_CENTS,
            admin_obligated_cents=0,
        )

    def test_requested_line_carries_gross_cents_but_no_approved_amount(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        PRD §3.7: "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**. The award ledger then sums those already-rounded integers."

        Design: Difficulty/combinatorial_formula/federal_share_rounds_per_line_before_the_grant_rollup_sums
        """
        grant, first, _second = _two_consumable_lines(build)

        assert first["status"] == k.EXP_REQUESTED
        assert_cents(first["gross_cents"], LINE_GROSS_CENTS, "gross_cents")
        assert first["approved_cents"] is None, (
            f"approved_cents must stay null until certification, got {first['approved_cents']}"
        )
        before = _read_grant(api, grant.grant_id)
        assert_cents(before["direct_obligated_cents"], 0, "direct_obligated_cents")

        certified = _certify(api, first["id"])

        assert_cents(certified["approved_cents"], LINE_APPROVED_CENTS, "approved_cents")


class TestIndirectRateTierKey:
    """The tier is looked up on the direct total, never on what it produces."""

    def test_professional_development_line_is_reimbursed_in_full(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "`PROFESSIONAL_DEVELOPMENT` is reimbursed in full at a share of 1.0000."

        PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation."

        Design: Difficulty/combinatorial_formula/indirect_rate_tier_keyed_on_direct_total_not_on_obligated_total
        """
        grant, line = _single_development_line(build)

        certified = _certify(api, line["id"])

        assert_rate(certified["federal_share_pct"], 1.0000, "federal_share_pct")
        assert_cents(certified["approved_cents"], TIER_LINE_CENTS, "approved_cents")
        award = _read_grant(api, grant.grant_id)
        assert_cents(
            award["direct_obligated_cents"], TIER_LINE_CENTS, "direct_obligated_cents"
        )

    def test_tier_is_selected_on_the_direct_total_below_the_first_ceiling(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500. The lookup is never keyed on `obligated_cents` or `remaining_cents`, even though `obligated_cents` contains the pool this rate produces — that circularity is precisely the mistake the pinning forbids. Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value."

        PRD §3.7: "To make the tier key concrete: an award of 10,000,000 allocation cents carrying a single professional-development line of 4,900,000 approved cents takes the 0.0812 tier, yielding an indirect pool of 397,880 cents, obligated cents of 5,297,880 and remaining cents of 4,702,120. Keying the tier on the resulting 5,297,880 would have picked 0.0650 and is wrong."

        Design: Difficulty/combinatorial_formula/indirect_rate_tier_keyed_on_direct_total_not_on_obligated_total
        """
        grant, line = _single_development_line(build)
        _certify(api, line["id"])

        award = _read_grant(api, grant.grant_id)

        assert_rate(award["indirect_rate"], k.INDIRECT_RATE_LOW, "indirect_rate")
        assert_cents(award["indirect_pool_cents"], TIER_POOL_CENTS, "indirect_pool_cents")
        assert award["indirect_pool_cents"] != TIER_POOL_IF_KEYED_ON_OBLIGATED_CENTS, (
            "Keying the tier on the obligated total would have produced a pool of "
            f"{TIER_POOL_IF_KEYED_ON_OBLIGATED_CENTS}"
        )

    def test_obligated_total_exceeds_the_ceiling_the_tier_was_read_below(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        PRD §3.7: "To make the tier key concrete: an award of 10,000,000 allocation cents carrying a single professional-development line of 4,900,000 approved cents takes the 0.0812 tier, yielding an indirect pool of 397,880 cents, obligated cents of 5,297,880 and remaining cents of 4,702,120. Keying the tier on the resulting 5,297,880 would have picked 0.0650 and is wrong."

        Design: Difficulty/combinatorial_formula/indirect_rate_tier_keyed_on_direct_total_not_on_obligated_total
        """
        grant, line = _single_development_line(build)
        _certify(api, line["id"])

        award = _read_grant(api, grant.grant_id)

        assert_ledger(
            award,
            direct_cents=TIER_LINE_CENTS,
            indirect_rate=k.INDIRECT_RATE_LOW,
            pool_cents=TIER_POOL_CENTS,
            obligated_cents=TIER_OBLIGATED_CENTS,
            remaining_cents=TIER_REMAINING_CENTS,
        )
        assert award["obligated_cents"] >= k.INDIRECT_TIER_LOW_BOUND_CENTS, (
            "The obligated total this rebuild produced sits at or above the first "
            "tier ceiling the rate was nonetheless read below"
        )
        assert award["obligated_cents"] != TIER_OBLIGATED_IF_KEYED_ON_OBLIGATED_CENTS, (
            "Keying the tier on the obligated total would have produced "
            f"{TIER_OBLIGATED_IF_KEYED_ON_OBLIGATED_CENTS}"
        )

    def test_administrative_sub_ledger_caps_at_five_percent_of_the_allocation(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`, and `admin_cap_cents` is `allocation_cents` multiplied by five percent, rounded half-up to whole cents. After every rebuild, `allocation_cents` must equal `obligated_cents` plus `remaining_cents` exactly — that identity is the conserved quantity of the whole grant model."

        Design: Difficulty/combinatorial_formula/indirect_rate_tier_keyed_on_direct_total_not_on_obligated_total
        """
        grant, line = _single_development_line(build)
        _certify(api, line["id"])

        award = _read_grant(api, grant.grant_id)

        assert_cents(award["admin_cap_cents"], TIER_ADMIN_CAP_CENTS, "admin_cap_cents")
        assert_cents(award["admin_obligated_cents"], 0, "admin_obligated_cents")
        assert_ledger_identity(award)
