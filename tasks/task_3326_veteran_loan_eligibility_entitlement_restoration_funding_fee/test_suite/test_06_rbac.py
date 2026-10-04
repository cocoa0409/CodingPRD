"""Corner tests for RBAC denials and segregation of duties."""
from __future__ import annotations

from test_helpers import (
    LOAN_OFFICER,
    PROGRAM_ADMIN,
    ApiErrorId,
    create_veteran_payload,
    make_underwriter_headers,
    make_veteran_headers,
    setup_loan_with_repairs_required,
    setup_submitted_loan,
    validate_error,
    validate_success,
)


class TestVeteranRoleDenials:
    def test_veteran_role_cannot_create_veterans(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST `/va-loans/veterans` is authorized for LoanOfficer,
        ProgramAdmin only.

        Design: Corner/roles/veteran_role_cannot_create_veterans
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V RB1")),
            expected_status=201,
        )
        validate_error(
            api.create_veteran(
                create_veteran_payload(full_name="V RB2"),
                headers=make_veteran_headers(veteran["id"]),
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403,
        )

    def test_veteran_ownership_scoping_on_reads(self, api):
        """PRD §2.1: "a `Veteran` acting anywhere outside the subtree of the
        veteran whose `id` equals `X-User-ID` is rejected with
        `ERR_FORBIDDEN_ROLE`"

        Design: Corner/roles/veteran_ownership_scoping_on_reads
        """
        veteran_1 = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Own1")),
            expected_status=201,
        )
        veteran_2 = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Own2")),
            expected_status=201,
        )
        validate_error(
            api.get_veteran(veteran_2["id"],
                            headers=make_veteran_headers(veteran_1["id"])),
            ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403,
        )
        own = validate_success(
            api.get_veteran(veteran_1["id"],
                            headers=make_veteran_headers(veteran_1["id"])))
        assert own["id"] == veteran_1["id"]


class TestRepairWaiverSegregation:
    def test_loan_officer_cannot_waive_repairs(self, api):
        """PRD §3.5: "Waiving is reserved for `ProgramAdmin`: an `OPEN` repair
        may be moved to the terminal `WAIVED` state, and a `LoanOfficer` may not
        waive."
        PRD §2.1: "The same separation-of-powers spirit bars a `LoanOfficer` from
        waiving repairs, submitting appraisal reports, or adjudicating COEs;
        those belong to `Appraiser` and `ProgramAdmin`."

        Design: Corner/roles/loan_officer_cannot_waive_repairs
        """
        ctx = setup_loan_with_repairs_required(
            repairs=[{"description": "Water heater",
                      "required_for_clearance": True}],
        )
        repair = ctx["repairs"][0]
        assert repair["status"] == "OPEN"

        # LoanOfficer waive attempt is forbidden; the repair stays OPEN.
        validate_error(api.waive_repair(repair["id"], headers=LOAN_OFFICER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        waived = validate_success(
            api.waive_repair(repair["id"], headers=PROGRAM_ADMIN))
        assert waived["status"] == "WAIVED"


class TestUnderwriterOriginatorSegregation:
    def test_underwriter_originator_segregation_enforced(self, api):
        """PRD §2.1: "An underwriting decision is rejected with
        `ERR_UNDERWRITER_IS_ORIGINATOR` (HTTP 403) whenever the deciding
        underwriter's `X-User-ID` equals the loan's `originator_user_id` — the
        officer who originated a loan may never decide it."
        PRD §3.3: "Creation stamps the loan's `originator_user_id` from the
        caller's `X-User-ID` — the segregation-of-duties marker consulted at
        underwriting time"

        Design: Corner/roles/underwriter_originator_segregation_enforced
        """
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 20000000},
            veteran_overrides={"full_name": "V Seg"},
            officer_user_id="lo-9",
        )
        loan = ctx["loan"]
        assert loan["originator_user_id"] == "lo-9"

        payload = {
            "gross_monthly_income_cents": 600000,
            "new_housing_payment_cents": 150000,
            "other_obligations_annual_cents": [],
            "family_size": 4,
            "region": "SOUTH",
        }
        validate_error(
            api.create_underwriting_decision(
                loan["id"], payload,
                headers=make_underwriter_headers("lo-9"),
            ),
            ApiErrorId.ERR_UNDERWRITER_IS_ORIGINATOR, expected_status=403,
        )
        decision = validate_success(
            api.create_underwriting_decision(
                loan["id"], payload,
                headers=make_underwriter_headers("uw-9"),
            ),
            expected_status=201,
        )
        assert decision["outcome"] == "APPROVED"
