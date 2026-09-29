"""Lookup tables, tier boundaries and the rounding of every derived figure.

The rules exercised here are the arithmetic the PRD pins with worked examples:
the per-category federal share table, the input set of the grant obligation
roll-up, the administrative cost cap, the alignment index formula and its two
variants, and the attendance resolution behind a quorum count.
"""

from test_helpers import (
    STOP_CLNA_CERTIFIED,
    STOP_DRAFT,
    STOP_STATE_APPROVED,
    NON_EXISTENT_UUID,
    assert_alignment_index,
    assert_cents,
    assert_credit_totals,
    assert_ledger,
    assert_quorum_figures,
    assert_rate,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_unpaginated,
)

MEETING_HELD_AT = "2026-08-12T16:00:00.000Z"


def _certify_line(api, expenditure_id):
    """Rule CERTIFY on one requested line and return the stored expenditure."""
    return validate_unpaginated(
        api.certify_allowability(
            expenditure_id,
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        ),
        200,
    )


def _disallow_line(api, expenditure_id, finding_code):
    """Rule DISALLOW on one requested line and return the stored expenditure."""
    return validate_unpaginated(
        api.certify_allowability(
            expenditure_id,
            f.certification_payload(k.DECISION_DISALLOW, finding_code=finding_code),
            users.headers(users.FISCAL_OFFICER),
        ),
        200,
    )


def _read_award(api, grant_id):
    """Read the award back so its rebuilt ledger can be asserted."""
    return validate_unpaginated(
        api.get_grant(grant_id, users.headers(users.FISCAL_OFFICER)), 200
    )


def _program_with_award(build, cip_code, allocation_cents=5000000, fiscal_year=2027):
    """A state-approved program plus an open award to charge it against."""
    scenario = build.program(cip_code, stop_at=STOP_STATE_APPROVED)
    grant = build.grant(fiscal_year=fiscal_year, allocation_cents=allocation_cents)
    return scenario, grant


class TestFederalSharePerCategory:
    """The per-category share table and the once-per-line rounding it feeds."""

    def test_professional_development_is_reimbursed_at_the_full_share(self, api, build):
        """PRD §3.7: "The federal share of a purchase is fixed by its category. `PROFESSIONAL_DEVELOPMENT` is reimbursed in full at a share of 1.0000." "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**."

        Design: Corner/calculations/federal_share_pct_is_looked_up_per_category_for_all_five_categories
        """
        scenario, grant = _program_with_award(build, "51.3902")
        line = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
            250010,
        )
        assert_cents(line["gross_cents"], 250010, "gross_cents")

        ruled = _certify_line(api, line["id"])
        assert ruled["status"] == k.EXP_CERTIFIED
        assert_rate(
            ruled["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_PROFESSIONAL_DEVELOPMENT],
            "federal_share_pct",
        )
        assert_cents(ruled["approved_cents"], 250010, "approved_cents")

    def test_equipment_takes_the_eighty_five_percent_share_rounded_once_per_line(
        self, api, build
    ):
        """PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "Aggregating gross amounts across lines and rounding the product once at the end is forbidden: two lines of 250,010 gross cents at a 0.8500 share round to 212,509 cents each for a total of 425,018, whereas rounding a combined 500,020 gross at 0.8500 would yield 425,017 — and 425,018 is the correct figure."

        Design: Corner/calculations/federal_share_pct_is_looked_up_per_category_for_all_five_categories
        """
        scenario, grant = _program_with_award(build, "51.3902")
        first = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_EQUIPMENT, 250010
        )
        second = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_EQUIPMENT, 250010
        )

        for line in (first, second):
            ruled = _certify_line(api, line["id"])
            assert_rate(
                ruled["federal_share_pct"],
                k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_EQUIPMENT],
                "federal_share_pct",
            )
            assert_cents(ruled["approved_cents"], 212509, "approved_cents")

        award = _read_award(api, grant.grant_id)
        assert_ledger(award, 425018, k.INDIRECT_RATE_LOW, 34511, 459529, 4540471, 0)

    def test_consumable_takes_the_eighty_five_percent_share(self, api, build):
        """PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**."

        Design: Corner/calculations/federal_share_pct_is_looked_up_per_category_for_all_five_categories
        """
        scenario, grant = _program_with_award(build, "51.3902")
        line = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 250010
        )

        ruled = _certify_line(api, line["id"])
        assert_rate(
            ruled["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_CONSUMABLE],
            "federal_share_pct",
        )
        assert_cents(ruled["approved_cents"], 212509, "approved_cents")

    def test_administration_takes_the_eighty_five_percent_share(self, api, build):
        """PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500." "Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`"

        Design: Corner/calculations/federal_share_pct_is_looked_up_per_category_for_all_five_categories
        """
        scenario, grant = _program_with_award(build, "51.3902")
        line = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 250010
        )

        ruled = _certify_line(api, line["id"])
        assert_rate(
            ruled["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_ADMINISTRATION],
            "federal_share_pct",
        )
        assert_cents(ruled["approved_cents"], 212509, "approved_cents")

        award = _read_award(api, grant.grant_id)
        assert_cents(award["admin_obligated_cents"], 212509, "admin_obligated_cents")

    def test_entertainment_carries_a_zero_share_and_never_earns_an_approved_amount(
        self, api, build
    ):
        """PRD §3.7: "`ENTERTAINMENT` carries a share of 0.0000 and, as described below, never reaches the point where that number matters." "The `category` must not be `ENTERTAINMENT`: entertainment is never an allowable federal use, so the only lawful ruling on such a line is `DISALLOW` with `finding_code` `ENTERTAINMENT_PROHIBITED`, and an attempt to certify one is `ERR_UNALLOWABLE_USE`." "It requires a non-null `finding_code` in the request, moves the expenditure `REQUESTED → DISALLOWED`, records that `finding_code` and `certified_by_user_id`, and **leaves `approved_cents` null**."

        Design: Corner/calculations/federal_share_pct_is_looked_up_per_category_for_all_five_categories
        """
        scenario, grant = _program_with_award(build, "51.3902")
        line = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ENTERTAINMENT, 250010
        )
        assert_rate(
            line["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_ENTERTAINMENT],
            "federal_share_pct",
        )

        ruled = _disallow_line(api, line["id"], k.FINDING_ENTERTAINMENT_PROHIBITED)
        assert ruled["status"] == k.EXP_DISALLOWED
        assert ruled["finding_code"] == k.FINDING_ENTERTAINMENT_PROHIBITED
        assert ruled["approved_cents"] is None
        assert_rate(
            ruled["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_ENTERTAINMENT],
            "federal_share_pct",
        )

    def test_the_ledger_sums_the_already_rounded_share_of_every_certified_category(
        self, api, build
    ):
        """PRD §3.7: "The award ledger then sums those already-rounded integers." "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation." "a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812"

        Design: Corner/calculations/federal_share_pct_is_looked_up_per_category_for_all_five_categories
        """
        scenario, grant = _program_with_award(build, "51.3902")
        certified = [
            k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
            k.CATEGORY_EQUIPMENT,
            k.CATEGORY_CONSUMABLE,
            k.CATEGORY_ADMINISTRATION,
        ]
        for category in certified:
            line = build.expenditure(
                grant.grant_id, scenario.program_id, category, 250010
            )
            _certify_line(api, line["id"])
        entertainment = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ENTERTAINMENT, 250010
        )
        _disallow_line(api, entertainment["id"], k.FINDING_ENTERTAINMENT_PROHIBITED)

        award = _read_award(api, grant.grant_id)
        assert_ledger(
            award, 887537, k.INDIRECT_RATE_LOW, 72068, 959605, 4040395, 212509
        )
        assert_cents(award["admin_cap_cents"], 250000, "admin_cap_cents")


class TestObligationRollupInputSet:
    """Only CERTIFIED and OBLIGATED rows may reach the roll-up."""

    @staticmethod
    def _void(api, expenditure_id):
        return validate_unpaginated(
            api.void_expenditure(
                expenditure_id,
                f.void_payload("Purchase order cancelled by the district"),
                users.headers(users.FISCAL_OFFICER),
            ),
            200,
        )

    def test_a_disallowed_row_is_excluded_from_the_direct_total(self, api, build):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation." "It requires a non-null `finding_code` in the request, moves the expenditure `REQUESTED → DISALLOWED`, records that `finding_code` and `certified_by_user_id`, and **leaves `approved_cents` null**."

        Design: Corner/calculations/disallowed_and_voided_and_requested_rows_are_excluded_from_the_rollup
        """
        scenario, grant = _program_with_award(build, "01.0201")
        countable = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
        )
        _certify_line(api, countable["id"])
        refused = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ENTERTAINMENT, 40000
        )
        ruled = _disallow_line(api, refused["id"], k.FINDING_ENTERTAINMENT_PROHIBITED)
        assert ruled["status"] == k.EXP_DISALLOWED
        assert ruled["approved_cents"] is None

        award = _read_award(api, grant.grant_id)
        assert_ledger(award, 85000, k.INDIRECT_RATE_LOW, 6902, 91902, 4908098, 0)

    def test_a_still_requested_row_is_excluded_from_the_direct_total(self, api, build):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation." "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification"

        Design: Corner/calculations/disallowed_and_voided_and_requested_rows_are_excluded_from_the_rollup
        """
        scenario, grant = _program_with_award(build, "01.0201")
        countable = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
        )
        _certify_line(api, countable["id"])
        pending = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 200000
        )
        assert pending["status"] == k.EXP_REQUESTED
        assert pending["approved_cents"] is None

        award = _read_award(api, grant.grant_id)
        assert_ledger(award, 85000, k.INDIRECT_RATE_LOW, 6902, 91902, 4908098, 0)

    def test_voiding_a_certified_row_restores_the_previous_remaining_figure(
        self, api, build
    ):
        """PRD §3.7: "The void records that reason, sets `approved_cents` back to null so the row can never re-enter the roll-up, and — on the two-step path — retains the `obligation_reference` already stamped on the row for the audit trail. It then rebuilds the ledger identically to a certification, which restores `remaining_cents` to exactly the figure it held before the certification being undone."

        Design: Corner/calculations/disallowed_and_voided_and_requested_rows_are_excluded_from_the_rollup
        """
        scenario, grant = _program_with_award(build, "01.0201")
        kept = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
        )
        _certify_line(api, kept["id"])
        before = _read_award(api, grant.grant_id)
        assert_ledger(before, 85000, k.INDIRECT_RATE_LOW, 6902, 91902, 4908098, 0)

        undone = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
        )
        _certify_line(api, undone["id"])
        during = _read_award(api, grant.grant_id)
        assert_ledger(during, 170000, k.INDIRECT_RATE_LOW, 13804, 183804, 4816196, 0)

        voided = self._void(api, undone["id"])
        assert voided["status"] == k.EXP_VOIDED
        assert voided["approved_cents"] is None

        after = _read_award(api, grant.grant_id)
        assert_ledger(after, 85000, k.INDIRECT_RATE_LOW, 6902, 91902, 4908098, 0)
        assert_cents(after["remaining_cents"], before["remaining_cents"], "remaining_cents")

    def test_only_the_certified_row_survives_a_mixed_award(self, api, build):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation." "Every addend is an already-rounded integer, so summation order is immaterial." "Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`"

        Design: Corner/calculations/disallowed_and_voided_and_requested_rows_are_excluded_from_the_rollup
        """
        scenario, grant = _program_with_award(build, "01.0201")
        certified = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
        )
        _certify_line(api, certified["id"])
        disallowed = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ENTERTAINMENT, 40000
        )
        _disallow_line(api, disallowed["id"], k.FINDING_ENTERTAINMENT_PROHIBITED)
        requested = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 200000
        )
        voided = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
        )
        _certify_line(api, voided["id"])
        self._void(api, voided["id"])

        statuses = {}
        for row in (certified, disallowed, requested, voided):
            stored = validate_unpaginated(
                api.get_expenditure(row["id"], users.headers(users.FISCAL_OFFICER)), 200
            )
            statuses[row["id"]] = stored["status"]
        assert statuses[certified["id"]] == k.EXP_CERTIFIED
        assert statuses[disallowed["id"]] == k.EXP_DISALLOWED
        assert statuses[requested["id"]] == k.EXP_REQUESTED
        assert statuses[voided["id"]] == k.EXP_VOIDED

        award = _read_award(api, grant.grant_id)
        assert_ledger(award, 85000, k.INDIRECT_RATE_LOW, 6902, 91902, 4908098, 0)


class TestAdministrativeCostCap:
    """The five-percent administrative cap and its half-cent rounding."""

    @staticmethod
    def _open_award(api, fiscal_year, allocation_cents):
        return validate_unpaginated(
            api.create_grant(
                f.grant_payload(fiscal_year, allocation_cents),
                users.headers(users.FISCAL_OFFICER),
            ),
            201,
        )

    def test_a_half_cent_cap_product_rounds_up(self, api):
        """PRD §3.7: "`admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents." PRD §2.11: "Money in this system is always an integer number of cents — `allocation_cents`, `unit_cost_cents`, `gross_cents`, `approved_cents`, `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents`, `remaining_cents`, `admin_cap_cents` and `admin_obligated_cents` are all whole cents, and every monetary product is rounded to whole cents using round-half-up."

        Design: Corner/calculations/admin_cap_cents_is_five_percent_of_allocation_rounded_half_up
        """
        award = self._open_award(api, 2027, 4999990)
        assert_cents(award["allocation_cents"], 4999990, "allocation_cents")
        assert_cents(award["admin_cap_cents"], 250000, "admin_cap_cents")

    def test_a_cap_product_below_the_half_cent_rounds_down(self, api):
        """PRD §3.7: "`admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents." PRD §2.11: "every monetary product is rounded to whole cents using round-half-up."

        Design: Corner/calculations/admin_cap_cents_is_five_percent_of_allocation_rounded_half_up
        """
        award = self._open_award(api, 2027, 4999989)
        assert_cents(award["allocation_cents"], 4999989, "allocation_cents")
        assert_cents(award["admin_cap_cents"], 249999, "admin_cap_cents")

    def test_a_whole_cent_cap_product_is_unchanged_by_rounding(self, api):
        """PRD §3.7: "`admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        Design: Corner/calculations/admin_cap_cents_is_five_percent_of_allocation_rounded_half_up
        """
        award = self._open_award(api, 2027, 5000000)
        assert_cents(award["admin_cap_cents"], 250000, "admin_cap_cents")

    def test_a_new_award_opens_zeroed_at_the_tier_for_a_direct_total_of_zero(self, api):
        """PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents." "a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812"

        Design: Corner/calculations/admin_cap_cents_is_five_percent_of_allocation_rounded_half_up
        """
        award = self._open_award(api, 2027, 4999990)
        assert award["status"] == k.GRANT_OPEN
        assert_ledger(award, 0, k.INDIRECT_RATE_LOW, 0, 0, 4999990, 0)
        assert_cents(award["admin_cap_cents"], 250000, "admin_cap_cents")


class TestAlignmentIndexCeilingAndBreadthBonus:
    """The clamp at 1.0000 and the three-credit floor under the breadth bonus."""

    @staticmethod
    def _submit(api, program_id, director_headers):
        return validate_unpaginated(
            api.submit_program(program_id, f.submit_payload(), director_headers), 200
        )

    def test_a_doubled_secondary_subtotal_cannot_push_the_index_past_one(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The **depth factor** is the smaller of 1.0 and the secondary credit subtotal divided by the four credit hours of secondary coursework a full pathway is expected to carry. The **bridge factor** is the smaller of 1.0 and the articulated subtotal divided by the larger of 1.0 and the postsecondary credit subtotal — the denominator floor of 1.0 keeps the factor finite when the postsecondary side is empty. The **breadth bonus** is 0.10 when the secondary credit subtotal is greater than zero, the postsecondary credit subtotal is greater than zero, and the articulated subtotal is at least the three articulated credit hours that mark a genuine dual-credit bridge; otherwise the bonus is 0.0. The weighted combination is then formed by multiplying the depth factor by 0.60, multiplying the bridge factor by 0.30, and adding the breadth bonus. That sum is clamped to at most 1.0, and the clamped value is rounded half-up to four decimal places exactly once." PRD §3.4: "recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        Design: Corner/calculations/alignment_index_reaches_its_ceiling_and_loses_the_breadth_bonus_below_the_articulation_floor
        """
        scenario = build.program(
            "01.0201",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_AGRICULTURE,
            secondary_credit_hours=8.0,
            postsecondary_credit_hours=3.0,
            articulated_credit_hours=3.0,
            articulation_verified=True,
        )

        submitted = self._submit(api, scenario.program_id, director_headers)
        assert_alignment_index(submitted["alignment_index"], 1.0)
        assert submitted["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_credit_totals(submitted, 8.00, 3.00, 3.00)

    def test_the_index_already_reaches_one_at_the_expected_four_secondary_credits(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The **depth factor** is the smaller of 1.0 and the secondary credit subtotal divided by the four credit hours of secondary coursework a full pathway is expected to carry." "The weighted combination is then formed by multiplying the depth factor by 0.60, multiplying the bridge factor by 0.30, and adding the breadth bonus. That sum is clamped to at most 1.0, and the clamped value is rounded half-up to four decimal places exactly once."

        Design: Corner/calculations/alignment_index_reaches_its_ceiling_and_loses_the_breadth_bonus_below_the_articulation_floor
        """
        scenario = build.program(
            "01.0201",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_AGRICULTURE,
            secondary_credit_hours=4.0,
            postsecondary_credit_hours=3.0,
            articulated_credit_hours=3.0,
            articulation_verified=True,
        )

        submitted = self._submit(api, scenario.program_id, director_headers)
        assert_alignment_index(submitted["alignment_index"], 1.0)
        assert_credit_totals(submitted, 4.00, 3.00, 3.00)

    def test_an_articulated_subtotal_one_hundredth_short_loses_the_breadth_bonus(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The **breadth bonus** is 0.10 when the secondary credit subtotal is greater than zero, the postsecondary credit subtotal is greater than zero, and the articulated subtotal is at least the three articulated credit hours that mark a genuine dual-credit bridge; otherwise the bonus is 0.0. The weighted combination is then formed by multiplying the depth factor by 0.60, multiplying the bridge factor by 0.30, and adding the breadth bonus. That sum is clamped to at most 1.0, and the clamped value is rounded half-up to four decimal places exactly once. Neither the depth factor nor the bridge factor is rounded on the way through, and no rounding happens before the clamp."

        Design: Corner/calculations/alignment_index_reaches_its_ceiling_and_loses_the_breadth_bonus_below_the_articulation_floor
        """
        scenario = build.program(
            "01.0201",
            stop_at=STOP_CLNA_CERTIFIED,
            cluster=k.CLUSTER_AGRICULTURE,
            secondary_credit_hours=8.0,
            postsecondary_credit_hours=3.0,
            articulated_credit_hours=2.99,
            articulation_verified=True,
        )

        submitted = self._submit(api, scenario.program_id, director_headers)
        assert_alignment_index(submitted["alignment_index"], 0.8990)
        assert submitted["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_credit_totals(submitted, 8.00, 3.00, 2.99)


class TestQuorumAttendanceResolution:
    """Attendance is resolved against committee and term before it is counted."""

    @staticmethod
    def _committee_with_a_lapsed_seat(build):
        """An ACTIVE committee of three in-term members plus one lapsed seat."""
        scenario = build.program(
            "46.0412", stop_at=STOP_DRAFT, cluster=k.CLUSTER_CONSTRUCTION
        )
        chartered = build.charter_committee(
            scenario.program_id, quorum_min_members=3, employer_seat_min=2
        )
        committee = build.seat_roster(chartered["id"])
        lapsed = build.seat_member(
            committee.committee_id,
            "Hal Brix",
            k.SECTOR_LABOR,
            "LAB-1",
            term_start_on="2025-01-01",
            term_end_on="2026-01-01",
        )
        meeting = build.schedule_meeting(
            committee.committee_id,
            committee.chair_member_id,
            k.AGENDA_EQUIPMENT_REVIEW,
            MEETING_HELD_AT,
        )
        return committee, lapsed, meeting

    @staticmethod
    def _file(api, meeting_id, chair_member_id, attendees):
        return validate_unpaginated(
            api.file_minutes(
                meeting_id,
                f.minutes_payload(MEETING_HELD_AT, attendees, 2, 1),
                users.chair_headers(chair_member_id),
            ),
            200,
        )

    def test_an_identifier_that_resolves_to_no_member_is_silently_discarded(
        self, api, build
    ):
        """PRD §3.3: "A submitted attendee identifier is *eligible* only when it names a `CommitteeMember` whose `committee_id` is this meeting's committee and whose term covers the calendar date of `held_at` — that is, whose `term_start_on` is on or before that date and whose `term_end_on` is strictly after it. Identifiers that do not resolve to such a member are silently discarded rather than raising an error, so a roster typo shrinks the count instead of failing the filing. `eligible_attendee_count` is then the number of eligible attendees, and `employer_attendee_count` is the number of those whose `sector` is `EMPLOYER`." PRD §2.6: "The elements of `attendee_member_ids` supplied with meeting minutes are **not** existence-checked; an identifier that does not resolve to a qualifying member is silently dropped when quorum is evaluated, rather than raising an error."

        Design: Corner/calculations/attendee_ids_outside_the_committee_or_outside_their_term_are_dropped_from_quorum
        """
        committee, _lapsed, meeting = self._committee_with_a_lapsed_seat(build)

        filed = self._file(
            api,
            meeting["id"],
            committee.chair_member_id,
            list(committee.member_ids) + [NON_EXISTENT_UUID],
        )
        assert_quorum_figures(filed, 3, 2, True, True)

    def test_a_member_outside_their_term_on_the_held_date_is_dropped(self, api, build):
        """PRD §3.3: "A submitted attendee identifier is *eligible* only when it names a `CommitteeMember` whose `committee_id` is this meeting's committee and whose term covers the calendar date of `held_at` — that is, whose `term_start_on` is on or before that date and whose `term_end_on` is strictly after it." "Quorum requires three things simultaneously: `eligible_attendee_count` at least `quorum_min_members`, `employer_attendee_count` at least `employer_seat_min`, and employer parity — twice `employer_attendee_count` at least `eligible_attendee_count`, meaning employers must hold at least half of the eligible attendance."

        Design: Corner/calculations/attendee_ids_outside_the_committee_or_outside_their_term_are_dropped_from_quorum
        """
        committee, lapsed, meeting = self._committee_with_a_lapsed_seat(build)

        filed = self._file(
            api,
            meeting["id"],
            committee.chair_member_id,
            list(committee.member_ids) + [lapsed["id"]],
        )
        assert_quorum_figures(filed, 3, 2, True, True)

    def test_the_filed_attendance_list_keeps_every_submitted_identifier(
        self, api, build
    ):
        """PRD §3.3: "A filing without an `amendment_reason` moves the meeting `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and `endorsement_passed`." "Identifiers that do not resolve to such a member are silently discarded rather than raising an error, so a roster typo shrinks the count instead of failing the filing."

        Design: Corner/calculations/attendee_ids_outside_the_committee_or_outside_their_term_are_dropped_from_quorum
        """
        committee, lapsed, meeting = self._committee_with_a_lapsed_seat(build)
        submitted = list(committee.member_ids) + [lapsed["id"], NON_EXISTENT_UUID]

        filed = self._file(api, meeting["id"], committee.chair_member_id, submitted)
        assert filed["minutes_status"] == k.MINUTES_FINALIZED
        assert len(filed["attendee_member_ids"]) == len(submitted)
        assert set(filed["attendee_member_ids"]) == set(submitted)
        assert filed["eligible_attendee_count"] == 3


class TestIndirectRateTiers:
    """The tier lookup keyed only on the direct obligated total."""

    @staticmethod
    def _certify_direct_total(api, build, scenario, grant, unit_costs):
        """Certify one professional-development line per amount, in order."""
        awards = []
        for unit_cost_cents in unit_costs:
            line = build.expenditure(
                grant.grant_id,
                scenario.program_id,
                k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
                unit_cost_cents,
            )
            _certify_line(api, line["id"])
            awards.append(_read_award(api, grant.grant_id))
        return awards

    def test_a_direct_total_one_cent_below_five_million_takes_the_lowest_tier(
        self, api, build
    ):
        """PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500." "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value."

        Design: Corner/calculations/indirect_rate_tier_boundaries_at_five_million_and_twenty_million
        """
        scenario, grant = _program_with_award(
            build, "11.0201", allocation_cents=30000000
        )

        award = self._certify_direct_total(api, build, scenario, grant, [4999999])[-1]
        assert_ledger(award, 4999999, k.INDIRECT_RATE_LOW, 406000, 5405999, 24594001, 0)

    def test_a_direct_total_of_exactly_five_million_takes_the_middle_tier(
        self, api, build
    ):
        """PRD §3.7: "a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650" "The lookup is never keyed on `obligated_cents` or `remaining_cents`, even though `obligated_cents` contains the pool this rate produces — that circularity is precisely the mistake the pinning forbids."

        Design: Corner/calculations/indirect_rate_tier_boundaries_at_five_million_and_twenty_million
        """
        scenario, grant = _program_with_award(
            build, "11.0201", allocation_cents=30000000
        )

        below, at_boundary = self._certify_direct_total(
            api, build, scenario, grant, [4999999, 1]
        )
        assert_ledger(below, 4999999, k.INDIRECT_RATE_LOW, 406000, 5405999, 24594001, 0)
        assert_ledger(
            at_boundary, 5000000, k.INDIRECT_RATE_MID, 325000, 5325000, 24675000, 0
        )
        assert at_boundary["obligated_cents"] < below["obligated_cents"]

    def test_a_direct_total_one_cent_below_twenty_million_stays_in_the_middle_tier(
        self, api, build
    ):
        """PRD §3.7: "a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500." "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value."

        Design: Corner/calculations/indirect_rate_tier_boundaries_at_five_million_and_twenty_million
        """
        scenario, grant = _program_with_award(
            build, "11.0201", allocation_cents=30000000
        )

        award = self._certify_direct_total(
            api, build, scenario, grant, [4999999, 1, 14999999]
        )[-1]
        assert_ledger(
            award, 19999999, k.INDIRECT_RATE_MID, 1300000, 21299999, 8700001, 0
        )

    def test_a_direct_total_of_exactly_twenty_million_takes_the_highest_tier(
        self, api, build
    ):
        """PRD §3.7: "anything at or above 20,000,000 cents takes 0.0500." "Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Corner/calculations/indirect_rate_tier_boundaries_at_five_million_and_twenty_million
        """
        scenario, grant = _program_with_award(
            build, "11.0201", allocation_cents=30000000
        )

        below, at_boundary = self._certify_direct_total(
            api, build, scenario, grant, [4999999, 1, 14999999, 1]
        )[-2:]
        assert_ledger(
            below, 19999999, k.INDIRECT_RATE_MID, 1300000, 21299999, 8700001, 0
        )
        assert_ledger(
            at_boundary, 20000000, k.INDIRECT_RATE_HIGH, 1000000, 21000000, 9000000, 0
        )
        assert_cents(at_boundary["admin_cap_cents"], 1500000, "admin_cap_cents")

    def test_the_pinned_award_example_keys_its_tier_on_the_direct_total(
        self, api, build
    ):
        """PRD §3.7: "To make the tier key concrete: an award of 10,000,000 allocation cents carrying a single professional-development line of 4,900,000 approved cents takes the 0.0812 tier, yielding an indirect pool of 397,880 cents, obligated cents of 5,297,880 and remaining cents of 4,702,120. Keying the tier on the resulting 5,297,880 would have picked 0.0650 and is wrong."

        Design: Corner/calculations/indirect_rate_tier_boundaries_at_five_million_and_twenty_million
        """
        scenario, grant = _program_with_award(
            build, "11.0201", allocation_cents=10000000
        )

        award = self._certify_direct_total(api, build, scenario, grant, [4900000])[-1]
        assert_ledger(award, 4900000, k.INDIRECT_RATE_LOW, 397880, 5297880, 4702120, 0)


def _two_variant_program(build):
    """Author a program whose two variants disagree, stopping at a certified needs
    assessment.

    One secondary course is `DRAFT` and the postsecondary articulation is not
    countersigned, so the `PROVISIONAL_LOCAL` include set is strictly larger than
    the `FEDERAL_CERTIFIED` one.
    """
    program = build.create_program(
        "51.3902", title="Nursing Assistant", cluster=k.CLUSTER_HEALTH_SCIENCE
    )
    program_id = program["id"]
    secondary = build.add_course(
        program_id, f.secondary_course("NUR-1", 1, 3.0, status=k.COURSE_ACTIVE)
    )
    build.add_course(
        program_id,
        f.secondary_course(
            "NUR-2",
            2,
            1.0,
            status=k.COURSE_DRAFT,
            prerequisite_course_id=secondary["id"],
        ),
    )
    postsecondary = build.add_course(
        program_id,
        f.postsecondary_course(
            "NUR-9",
            3,
            3.0,
            3.0,
            False,
            status=k.COURSE_ACTIVE,
            prerequisite_course_id=secondary["id"],
        ),
    )
    build.add_credential(program_id, "CNA-1", tier=k.TIER_NATIONAL)
    educator = build.add_educator(program_id)
    build.verify_hours(educator["id"], 4200)
    chartered = build.charter_committee(program_id)
    committee = build.seat_roster(chartered["id"])
    for instant in ("2026-08-04T14:00:00.000Z", "2026-08-05T14:00:00.000Z"):
        build.quorate_meeting(committee, k.AGENDA_CLNA_STAKEHOLDER, instant)
    build.certify_clna(program_id)
    return program_id, postsecondary["id"], committee


def _two_variant_program_at_committee_review(build):
    """The same program, submitted and endorsed, waiting on the state."""
    program_id, postsecondary_course_id, committee = _two_variant_program(build)
    build.submit(program_id)
    build.quorate_meeting(
        committee, k.AGENDA_POS_ENDORSEMENT, "2026-08-10T15:00:00.000Z"
    )
    return program_id, postsecondary_course_id, committee


class TestAlignmentVariantPersistence:
    """Submission persists the provisional score; approval replaces it."""

    def test_submission_stores_the_provisional_variant_and_its_include_set(
        self, api, build, director_headers
    ):
        """PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`." PRD §3.1: "Under the `PROVISIONAL_LOCAL` variant the include set is courses whose `status` is `DRAFT` or `ACTIVE`, and the articulated sum ignores `articulation_verified` entirely, counting every qualifying postsecondary course's `articulated_credit_hours`."

        Design: Corner/calculations/submit_stores_the_provisional_variant_and_approval_overwrites_it_with_the_certified_one
        """
        program_id, _postsecondary_course_id, _committee = _two_variant_program(build)

        submitted = validate_unpaginated(
            api.submit_program(program_id, f.submit_payload(), director_headers), 200
        )
        assert submitted["approval_status"] == k.APPROVAL_SUBMITTED
        assert submitted["approval_round"] == 1
        assert submitted["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_alignment_index(submitted["alignment_index"], 1.0)
        assert_credit_totals(submitted, 4.00, 3.00, 3.00)

    def test_approval_is_refused_while_the_certified_variant_sits_below_the_floor(
        self, api, build, reviewer_headers
    ):
        """PRD §3.4: "And the alignment index recomputed under the `FEDERAL_CERTIFIED` variant must reach the federal floor of 0.7500, inclusive — an index of exactly 0.7500 passes, anything strictly below it fails with `ERR_ALIGNMENT_INDEX_BELOW_FLOOR`. Only the `FEDERAL_CERTIFIED` variant is ever compared against that floor, which is why a program can submit comfortably on its provisional score and then fail approval on unverified articulation or `DRAFT` coursework." PRD §3.1: "Under the `FEDERAL_CERTIFIED` variant the include set is courses whose `status` is `ACTIVE` only, and the articulated sum counts a postsecondary course's `articulated_credit_hours` solely when that course's `articulation_verified` is true."

        Design: Corner/calculations/submit_stores_the_provisional_variant_and_approval_overwrites_it_with_the_certified_one
        """
        program_id, _postsecondary_course_id, _committee = (
            _two_variant_program_at_committee_review(build)
        )

        validate_error(
            api.state_approve(program_id, f.state_approve_payload(), reviewer_headers),
            errors.ERR_ALIGNMENT_INDEX_BELOW_FLOOR,
        )

    def test_a_refused_approval_leaves_the_provisional_index_in_place(
        self, api, build, director_headers, reviewer_headers
    ):
        """PRD §3.4: "anything strictly below it fails with `ERR_ALIGNMENT_INDEX_BELOW_FLOOR`." "State approval then does four things. It overwrites `alignment_index` with the `FEDERAL_CERTIFIED` result, sets `alignment_index_variant` to `FEDERAL_CERTIFIED`, and overwrites all three credit subtotals with that variant's sums. It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`"

        Design: Corner/calculations/submit_stores_the_provisional_variant_and_approval_overwrites_it_with_the_certified_one
        """
        program_id, _postsecondary_course_id, _committee = (
            _two_variant_program_at_committee_review(build)
        )
        validate_error(
            api.state_approve(program_id, f.state_approve_payload(), reviewer_headers),
            errors.ERR_ALIGNMENT_INDEX_BELOW_FLOOR,
        )

        stored = validate_unpaginated(
            api.get_program(program_id, director_headers), 200
        )
        assert stored["approval_status"] == k.APPROVAL_COMMITTEE_REVIEW
        assert stored["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_alignment_index(stored["alignment_index"], 1.0)
        assert_credit_totals(stored, 4.00, 3.00, 3.00)
        assert stored["federal_reporting_eligible"] is False

    def test_approval_overwrites_the_index_and_subtotals_with_the_certified_variant(
        self, api, build, director_headers, reviewer_headers
    ):
        """PRD §3.4: "State approval then does four things. It overwrites `alignment_index` with the `FEDERAL_CERTIFIED` result, sets `alignment_index_variant` to `FEDERAL_CERTIFIED`, and overwrites all three credit subtotals with that variant's sums. It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`, and it is what determines whether the program appears in the federal Perkins submission." PRD §3.1: "Under the `FEDERAL_CERTIFIED` variant the include set is courses whose `status` is `ACTIVE` only, and the articulated sum counts a postsecondary course's `articulated_credit_hours` solely when that course's `articulation_verified` is true."

        Design: Corner/calculations/submit_stores_the_provisional_variant_and_approval_overwrites_it_with_the_certified_one
        """
        program_id, postsecondary_course_id, _committee = (
            _two_variant_program_at_committee_review(build)
        )
        countersigned = validate_unpaginated(
            api.patch_course(
                postsecondary_course_id,
                f.course_patch(articulation_verified=True),
                director_headers,
            ),
            200,
        )
        assert countersigned["articulation_verified"] is True

        approved = validate_unpaginated(
            api.state_approve(program_id, f.state_approve_payload(), reviewer_headers),
            200,
        )
        assert approved["approval_status"] == k.APPROVAL_STATE_APPROVED
        assert approved["alignment_index_variant"] == k.ALIGNMENT_VARIANT_FEDERAL_CERTIFIED
        assert_alignment_index(approved["alignment_index"], 0.8500)
        assert_credit_totals(approved, 3.00, 3.00, 3.00)
        assert approved["federal_reporting_eligible"] is True
