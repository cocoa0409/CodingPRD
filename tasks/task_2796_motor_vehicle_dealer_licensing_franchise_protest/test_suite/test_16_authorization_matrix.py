"""The authorization matrix: each role's own exclusive operation, the denial
ladder from 401 through 403, per-row ownership for the two entity-backed roles,
and the board's separation of function on a complaint file.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BOARD_ADMIN,
    COMPLAINT_INVESTIGATOR,
    HEARING_CLERK,
    LICENSING_ANALYST,
    make_board_admin_headers,
    make_dealer_headers,
    make_investigator_headers,
    make_manufacturer_headers,
)


class TestEveryRolePerformsItsOwnExclusiveOperation:
    def test_one_chain_passes_through_all_five_acting_roles(self, api):
        """PRD 2.1: "When `X-User-Role` is `BoardAdmin`, `X-User-ID` identifies a board
        administrator/adjudicator." PRD 2.1: "Administrators create reference data,
        decide dealer applications, protests and rate disputes, resolve complaints, let
        franchise filings take effect and drive the logical clock." PRD 3.2 reserves the
        deficiency notice to the analyst: "The analyst may only do this from `SUBMITTED`
        and only when `deficiency_count` is at least 1; a `BoardAdmin` may not issue
        deficiency notices at all." PRD 3.4: "On a `TERMINATION`, service also moves the
        affected dealership's franchise dimension `FRANCHISED → TERMINATION_PENDING` and
        increments that dealership's `version`; the licence dimension is deliberately
        left alone, because the dealership keeps selling throughout the notice period."

        Design: Corner/rbac/every_role_performs_its_own_exclusive_operation
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        manufacturer = get_success_data(api.create_manufacturer(
            f.manufacturer_payload(), BOARD_ADMIN), 201)
        dealer = get_success_data(api.create_dealer(
            f.dealer_payload(), BOARD_ADMIN), 201)
        dealer_headers = make_dealer_headers(dealer["id"])

        application = get_success_data(api.create_license_application(
            f.license_application_payload(dealer["id"], facility_sqft=5000),
            dealer_headers), 201)
        assert application["status"] == "DRAFT"
        submitted = get_success_data(api.submit_license_application(
            application["id"], dealer_headers))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["deficiency_codes"] == ["FACILITY_TOO_SMALL"]

        returned = get_success_data(api.issue_deficiency_notice(
            application["id"],
            f.deficiency_notice_payload(
                deficiency_note="floor plan short of the statutory minimum"),
            LICENSING_ANALYST))
        assert returned["status"] == "DEFICIENT"
        assert returned["deficiency_note"] == "floor plan short of the statutory minimum"

        corrected = get_success_data(api.resubmit_license_application(
            application["id"], {"facility_sqft": 9000}, dealer_headers))
        assert corrected["status"] == "SUBMITTED"
        assert corrected["resubmission_count"] == 1
        assert corrected["deficiency_count"] == 0

        approved = get_success_data(api.decide_license_application(
            application["id"], f.application_decision_payload("APPROVED"),
            BOARD_ADMIN))
        assert approved["status"] == "APPROVED"
        assert approved["decision_outcome"] == "APPROVED"
        licensed = fx.read_dealer(dealer["id"])
        assert licensed["license_status"] == "LICENSED"
        assert licensed["franchise_status"] == "FRANCHISED"

        manufacturer_headers = make_manufacturer_headers(manufacturer["id"])
        filing = get_success_data(api.create_franchise_filing(
            f.termination_filing_payload(manufacturer["id"], dealer["id"],
                                         "2026-12-01"),
            manufacturer_headers), 201)
        assert filing["status"] == "DRAFT"
        served = get_success_data(api.serve_filing_notice(
            filing["id"], manufacturer_headers))
        assert served["status"] == "NOTICE_SERVED"

        complaint = get_success_data(api.create_consumer_complaint(
            f.complaint_payload(dealer["id"], allegation_code="DEPOSIT_RETENTION",
                                alleged_loss_cents=75000,
                                complainant_name="Rosa Ibarra"),
            make_investigator_headers("inv-r1")), 201)

        assert complaint["status"] == "RECEIVED"
        after = fx.read_dealer(dealer["id"])
        assert after["license_status"] == "LICENSED"
        assert after["franchise_status"] == "TERMINATION_PENDING"


class TestDenialLadder:
    def test_the_four_hundred_ones_outrank_the_four_hundred_threes(self, api):
        """PRD 2.1: "If either header is missing or empty, or if `X-User-Role` is not
        one of the six declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)." PRD 2.1: "If the headers are well-formed but
        the named role is not authorised for the endpoint being called, the request is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD 4: "The Authorized Role(s)
        column is exhaustive — a caller whose `X-User-Role` is not listed for the
        endpoint it addresses is refused with `ERR_UNAUTHORIZED`, and an entity-backed
        caller listed for the endpoint but acting on another party's record is refused
        with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/role_cannot_perform_another_roles_exclusive_operation_or_act_unauthenticated
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_used_only_dealer(legal_name="Lakeside Aurora")
        dealer_headers = make_dealer_headers(dealer["id"])
        application = get_success_data(api.create_license_application(
            f.used_only_application_payload(dealer["id"]), dealer_headers), 201)
        fx.submit_application(application["id"], dealer["id"])

        decision = f.application_decision_payload("APPROVED")
        for headers in (dealer_headers, LICENSING_ANALYST):
            refused = api.decide_license_application(
                application["id"], decision, headers)
            validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value,
                           expected_status=403)

        clerks_dealer = api.create_dealer(
            f.dealer_payload(legal_name="Clerk's Own Dealership",
                             dealer_type="USED_ONLY", county_tier="TIER_1",
                             site_x_km=1, site_y_km=1, line_make=""),
            HEARING_CLERK)
        validate_error(clerks_dealer, ApiErrorId.ERR_UNAUTHORIZED.value,
                       expected_status=403)

        wrong_desk = api.issue_deficiency_notice(
            application["id"], f.deficiency_notice_payload(
                deficiency_note="not my job"), COMPLAINT_INVESTIGATOR)
        validate_error(wrong_desk, ApiErrorId.ERR_UNAUTHORIZED.value,
                       expected_status=403)

        unauthenticated = [
            {"X-User-ID": "admin-op-1"},
            {"X-User-Role": "BoardAdmin"},
            {"X-User-ID": "super-op-1", "X-User-Role": "SuperRegulator"},
        ]
        for headers in unauthenticated:
            refused = api.decide_license_application(
                application["id"], decision, headers)
            validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED.value,
                           expected_status=401)

        assert fx.read_application(application["id"])["status"] == "SUBMITTED"
        assert fx.read_dealer(dealer["id"])["license_status"] == "PROSPECTIVE"
        _, meta = validate_paginated(api.list_dealers(BOARD_ADMIN))
        assert meta["total_count"] == 1


class TestOwnershipIsPerRowNotPerRole:
    def test_neither_entity_backed_caller_may_act_on_the_other_party_s_row(self, api):
        """PRD 2.1: "Ownership checks on any resource that references a dealership
        compare that resource's dealer-bearing foreign key to `X-User-ID`: the
        `dealer_id` of a licence application, the `sponsoring_dealer_id` of a
        salesperson, the `protestant_dealer_id` of a protest, the `dealer_id` of a
        warranty rate dispute, and the `dealer_id` of a consumer complaint whose
        restitution is being paid." PRD 2.1: "A franchisor may act only on a franchise
        filing whose `manufacturer_id` equals `X-User-ID`, only as the respondent on a
        warranty rate dispute whose `manufacturer_id` equals `X-User-ID`, and only on a
        protest whose protested filing names it as the franchisor." PRD 2.1: "This
        ownership scoping applies to write operations whose authorised roles include
        `Dealer` or `Manufacturer`; read operations are never owner-scoped, so any
        authenticated role may read any record it is authorised to read."

        Design: Corner/rbac/dealer_cannot_act_on_another_dealers_application_or_salesperson
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        aurora = fx.create_manufacturer()
        boreas = fx.create_manufacturer(legal_name="Boreas Motor Works",
                                        line_make="BOREAS",
                                        home_office_state="OH",
                                        posted_warranty_labor_rate_cents=5500)
        lakeside = fx.create_dealer(legal_name="Lakeside Aurora")
        northgate = fx.create_dealer(legal_name="Northgate Boreas",
                                     county_tier="TIER_1", site_x_km=5,
                                     site_y_km=0, line_make="BOREAS")
        owner = make_dealer_headers(lakeside["id"])
        stranger = make_dealer_headers(northgate["id"])

        application = get_success_data(api.create_license_application(
            f.license_application_payload(lakeside["id"]), owner), 201)
        filing = fx.open_termination_filing(aurora["id"], lakeside["id"],
                                            "2026-12-01")

        not_yours = api.submit_license_application(application["id"], stranger)
        validate_error(not_yours, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
                       expected_status=403)

        not_your_roster = api.create_salesperson(
            f.salesperson_payload(lakeside["id"], full_name="Not Mine"), stranger)
        validate_error(not_your_roster, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
                       expected_status=403)

        not_your_filing = api.serve_filing_notice(
            filing["id"], make_manufacturer_headers(boreas["id"]))
        validate_error(not_your_filing, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
                       expected_status=403)

        shared_read = get_success_data(api.get_license_application(
            application["id"], stranger))
        assert shared_read["id"] == application["id"]
        assert shared_read["status"] == "DRAFT"

        mine = get_success_data(api.submit_license_application(
            application["id"], owner))

        assert mine["status"] == "SUBMITTED"
        untouched = fx.read_filing(filing["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["notice_served_on"] is None
        _, meta = validate_paginated(api.list_salespersons(
            BOARD_ADMIN, params={"sponsoring_dealer_id": lakeside["id"]}))
        assert meta["total_count"] == 0


class TestSeparationOfFunction:
    def test_the_investigator_s_own_identifier_may_not_resolve_its_file(self, api):
        """PRD 2.1: "If the `X-User-ID` presented when a complaint is resolved equals
        the `investigator_user_id` stamped on it, the resolution is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." PRD 3.9: "**Resolution** is an
        administrator's act, admitted only from `UNDER_INVESTIGATION` and only from an
        `X-User-ID` other than the stamped `investigator_user_id`." PRD 3.9:
        "`points_assessed` is fixed by the sanction chosen: a `WARNING` carries 0
        points, a `CIVIL_PENALTY` carries 3, a `PROBATION` carries 6 and a
        `SUSPENSION_RECOMMENDED` carries 9." PRD 3.9: "The allegation bases are 200,000
        cents for `ODOMETER_MISREPRESENTATION`, 100,000 cents for
        `FAILURE_TO_TRANSFER_TITLE`, 50,000 cents for `ADVERTISING_VIOLATION`, 75,000
        cents for `DEPOSIT_RETENTION` and 150,000 cents for `UNLICENSED_SALESPERSON`."

        Design: Corner/rbac/same_user_cannot_investigate_and_then_resolve_one_complaint
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        dealer = fx.create_used_only_dealer(legal_name="Lakeside Aurora")
        complaint = fx.intake_complaint(
            dealer["id"], investigator_id="inv-r4",
            allegation_code="ODOMETER_MISREPRESENTATION",
            alleged_loss_cents=100000, complainant_name="Ola Fenn")
        investigating = fx.open_investigation(
            complaint["id"], investigator_id="inv-r4",
            findings_code="ODOMETER_ROLLBACK_CONFIRMED")
        assert investigating["investigator_user_id"] == "inv-r4"

        resolution = f.resolution_payload(substantiated=True,
                                         sanction_type="CIVIL_PENALTY")
        conflicted = api.resolve_consumer_complaint(
            complaint["id"], resolution, make_board_admin_headers("inv-r4"))
        validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                       expected_status=403)
        assert fx.read_complaint(complaint["id"])["status"] == "UNDER_INVESTIGATION"

        sanctioned = get_success_data(api.resolve_consumer_complaint(
            complaint["id"], resolution, make_board_admin_headers("adm-r4")))

        assert sanctioned["status"] == "SANCTIONED"
        assert sanctioned["restitution_ordered_cents"] == 100000
        assert sanctioned["civil_penalty_cents"] == 205000
        assert sanctioned["points_assessed"] == 3
        after = fx.read_dealer(dealer["id"])
        assert after["restitution_outstanding_cents"] == 100000
        assert after["disciplinary_points"] == 3
