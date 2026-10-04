"""State add-on returns: allocation math, residency windows, and uniqueness."""
from test_helpers import (
    add_form,
    add_state_return,
    create_account,
    create_return,
    get_return,
    make_taxpayer_headers,
    remove_state_return,
    seed_catalog,
    setup_return_with_forms,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestResidentVsNonResidentTax:
    def test_resident_variant_ignores_allocation_inputs(self, api):
        """PRD §3.4: "For a **resident** state return the allocation inputs
        are ignored entirely: `allocated_tax_cents` is the account's full AGI
        multiplied by 5%, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/resident_vs_nonresident_state_tax_variants
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(
            email=unique_email("dual2"), agi_cents=12000000, resident_state_code="CA"
        )
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        ca = add_state_return(
            ret,
            "CA",
            allocation_numerator_cents=3000000,
            allocation_denominator_cents=12000000,
        )
        assert ca["is_resident_state"] is True
        assert ca["allocated_tax_cents"] == 600000
        assert get_return(ret)["total_fees_due_cents"] == 0

    def test_nonresident_variant_applies_allocation_fraction(self, api):
        """PRD §3.4: "For a **non-resident** state return with a zero
        numerator, the allocated tax is zero; otherwise the allocation ratio —
        numerator over denominator — is carried as an exact rational and never
        pre-rounded to a percentage, and `allocated_tax_cents` is the
        account's AGI multiplied by that ratio and then by 5%, with only this
        final product rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/resident_vs_nonresident_state_tax_variants
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(
            email=unique_email("dual2b"), agi_cents=12000000, resident_state_code="CA"
        )
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        ny = add_state_return(
            ret,
            "NY",
            allocation_numerator_cents=3000000,
            allocation_denominator_cents=12000000,
        )
        assert ny["is_resident_state"] is False
        # 12000000 x (1/4) x 0.05 = 150000
        assert ny["allocated_tax_cents"] == 150000

    def test_exact_rational_rounding_not_prerounded(self, api):
        """PRD §3.4: "otherwise the allocation ratio — numerator over
        denominator — is carried as an exact rational and never pre-rounded to
        a percentage, and `allocated_tax_cents` is the account's AGI
        multiplied by that ratio and then by 5%, with only this final product
        rounded half-up to whole cents."

        Design: Corner/calculations/nonresident_allocation_exact_rational_rounding
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(
            email=unique_email("calc1"), agi_cents=12000000, resident_state_code="CA"
        )
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        ny = add_state_return(
            ret,
            "NY",
            allocation_numerator_cents=1000001,
            allocation_denominator_cents=3000000,
        )
        # Exact: 12000000 * 1000001/3000000 * 0.05 = 200000.2 -> 200000
        # (a pre-rounded 33% ratio would give 198000).
        assert ny["allocated_tax_cents"] == 200000


class TestResidencyWindows:
    def test_adjacent_window_accepted_overlapping_window_rejected(self, api):
        """PRD §3.4: "Windows are half-open — a window covers its start date
        and runs up to but not including its end date — and across the
        non-`REMOVED` state returns of one return, two windows overlap exactly
        when each window's start precedes the other's end; bare adjacency,
        where one window ends on the day the next begins, is permitted."
        PRD §3.4: "A colliding add is rejected with `ERR_RESIDENCY_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/half_open_residency_window_overlap_and_adjacency
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(email=unique_email("ovr1"), resident_state_code="CA")
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        sr_or = add_state_return(
            ret, "OR",
            residency_start_date="2026-01-01", residency_end_date="2026-06-30",
        )
        sr_wa = add_state_return(
            ret, "WA",
            residency_start_date="2026-06-30", residency_end_date="2026-12-31",
        )
        assert sr_wa["status"] == "DRAFT"
        resp = api.add_state_return(
            ret.id,
            {
                "state_code": "NV",
                "residency_start_date": "2026-03-01",
                "residency_end_date": "2026-09-01",
                "expected_return_version": ret.version,
            },
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_OVERLAP)
        assert get_return(ret)["total_fees_due_cents"] == 0

    def test_exact_overlap_rejected_adjacency_allowed_reverse_order(self, api):
        """PRD §3.4: "Windows are half-open — a window covers its start date
        and runs up to but not including its end date — and across the
        non-`REMOVED` state returns of one return, two windows overlap exactly
        when each window's start precedes the other's end; bare adjacency,
        where one window ends on the day the next begins, is permitted."
        PRD §3.4: "A colliding add is rejected with `ERR_RESIDENCY_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/half_open_residency_window_overlap_and_adjacency
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(email=unique_email("ovr1b"), resident_state_code="CA")
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        # Later window first.
        add_state_return(
            ret, "WA",
            residency_start_date="2026-06-30", residency_end_date="2026-12-31",
        )
        # Adjacent window ending exactly where the first begins: allowed.
        sr_or = add_state_return(
            ret, "OR",
            residency_start_date="2026-01-01", residency_end_date="2026-06-30",
        )
        assert sr_or["status"] == "DRAFT"
        # True overlap (start precedes the other's end and vice versa).
        resp = api.add_state_return(
            ret.id,
            {
                "state_code": "NV",
                "residency_start_date": "2026-05-01",
                "residency_end_date": "2026-07-01",
                "expected_return_version": ret.version,
            },
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_OVERLAP)


class TestStateReturnUniquenessAndAllocation:
    def test_duplicate_state_code_rejected_but_recreation_after_removal_allowed(self, api):
        """PRD §3.4: "Only one live state return per state is allowed —
        adding a second non-`REMOVED` row with the same `state_code` is
        rejected with `ERR_DUPLICATE_STATE_RETURN` (HTTP 409), and this
        uniqueness check runs before the residency-window and allocation
        checks described below."

        Design: Corner/validations/duplicate_state_code_rejected_but_removable_rereation_allowed
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("val2")
        )
        sr1 = add_state_return(ret, "CA")
        resp = api.add_state_return(
            ret.id,
            {"state_code": "CA", "expected_return_version": ret.version},
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_RETURN)
        removed = remove_state_return(ret, sr1["id"])
        assert removed["status"] == "REMOVED"
        sr2 = add_state_return(ret, "CA")
        assert sr2["status"] == "DRAFT"

    def test_allocation_numerator_above_denominator_rejected(self, api):
        """PRD §3.4: "The numerator may never exceed the denominator, and
        whenever the numerator is positive the denominator must be present and
        greater than zero; violations are rejected with
        `ERR_ALLOCATION_EXCEEDS_BASE` (HTTP 422)."

        Design: Corner/validations/allocation_numerator_above_denominator_rejected
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(
            email=unique_email("val3"), agi_cents=1000000, resident_state_code="CA"
        )
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        resp = api.add_state_return(
            ret.id,
            {
                "state_code": "NY",
                "allocation_numerator_cents": 2000001,
                "allocation_denominator_cents": 2000000,
                "expected_return_version": ret.version,
            },
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_BASE)
        ny = add_state_return(
            ret, "NY",
            allocation_numerator_cents=2000000,
            allocation_denominator_cents=2000000,
        )
        # Ratio 1: AGI 1000000 x 5% = 50000.
        assert ny["allocated_tax_cents"] == 50000
