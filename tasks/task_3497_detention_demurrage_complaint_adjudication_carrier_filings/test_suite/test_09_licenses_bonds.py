"""OTI licenses and the surety-bond ledger: type matching, bond_ref
uniqueness, the 402 ledger guards, coverage sufficiency boundaries, the
license-version OCC guard, and the bond-draw cascade into service contracts."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_bond_invariant,
    assert_oti_license,
    create_bond_payload,
    create_draw_payload,
    create_oti_license_payload,
    file_service_contract,
    get_license_state,
    make_carrier,
    make_carrier_rep_headers,
    make_counsel_headers,
    make_shipper,
    post_draw,
    set_logical_clock,
    setup_nvocc_license,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]


def _bond(license_data, bond_ref):
    for bond in license_data["surety_bonds"]:
        if bond["bond_ref"] == bond_ref:
            return bond
    raise AssertionError(f"bond {bond_ref} not embedded in license")


class TestLicenseTypeMatching:
    def test_license_type_must_match_organization_type(self):
        """PRD §3.4: "the type must equal the organization's `org_type`, and a
        mismatch — or an application from an organization whose type is not
        licensable at all — is rejected with `ERR_LICENSE_TYPE_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/license_type_must_match_organization_type
        """
        set_logical_clock()
        mto = make_carrier(org_type="MTO", org_name="Terminal Town Operators")
        nvocc = make_carrier(org_type="NVOCC", org_name="Almost Forwarders")

        r1 = api_client.create_oti_license(mto["id"],
            create_oti_license_payload(license_type="NVOCC"),
            make_carrier_rep_headers(mto["id"]))
        validate_error(r1, ApiErrorId.ERR_LICENSE_TYPE_MISMATCH)

        r2 = api_client.create_oti_license(nvocc["id"],
            create_oti_license_payload(license_type="OFF"),
            make_carrier_rep_headers(nvocc["id"]))
        validate_error(r2, ApiErrorId.ERR_LICENSE_TYPE_MISMATCH)

        for carrier in (mto, nvocc):
            rows, meta = validate_paginated(api_client.list_oti_licenses(
                carrier["id"], DOCKET))
            assert meta["total_count"] == 0


class TestBondAppend:
    def test_duplicate_bond_ref_rejected_on_same_license(self):
        """PRD §3.4: "the reference must be unique within the license, and a
        duplicate is rejected with `ERR_DUPLICATE_BOND_REF` (HTTP 409)."

        Design: Corner/validations/duplicate_bond_ref_rejected_on_same_license
        """
        env = setup_nvocc_license(bond_coverages=(1_000_000,),
                                  carrier_name="Refcheck Forwarders")
        license_ = env["license"]
        r = api_client.append_surety_bond(license_["id"],
            create_bond_payload(bond_ref="B1", surety_name="Atlantic Surety",
                                coverage_cents=7_000_000),
            make_carrier_rep_headers(env["carrier"]["id"]))
        validate_error(r, ApiErrorId.ERR_DUPLICATE_BOND_REF)

        state = get_license_state(env["carrier"]["id"], license_["id"])
        assert state["total_available_coverage_cents"] == 1_000_000
        assert state["license_status"] == "PENDING_BOND"


class TestBondCoverageBoundary:
    def test_bond_one_cent_short_leaves_license_pending(self):
        """PRD §3.4: "The license's `required_bond_cents` is fixed by type:
        7,500,000 cents for an `NVOCC`, 5,000,000 cents for an `OFF`." and "if
        total available coverage has reached `required_bond_cents` and the
        license is not `ACTIVE`, it becomes `ACTIVE`".

        Design: Difficulty/boundary_precision_check/bond_coverage_at_exact_required_minimum
        """
        env = setup_nvocc_license(bond_coverages=(7_499_999,),
                                  carrier_name="Precision Forwarders")
        license_ = env["license"]
        assert license_["required_bond_cents"] == 7_500_000
        assert license_["license_status"] == "PENDING_BOND", "1 cent short"
        assert license_["total_available_coverage_cents"] == 7_499_999

    def test_bond_at_exact_required_minimum_activates_license(self):
        """PRD §3.4: "After every mutation of the ledger the license
        re-evaluates coverage sufficiency in a fixed order: if total available
        coverage has reached `required_bond_cents` and the license is not
        `ACTIVE`, it becomes `ACTIVE`".

        Design: Difficulty/boundary_precision_check/bond_coverage_at_exact_required_minimum
        """
        env = setup_nvocc_license(bond_coverages=(7_499_999, 1),
                                  carrier_name="Precision Forwarders")
        license_ = env["license"]
        assert license_["license_status"] == "ACTIVE", (
            "exact equality with required_bond_cents satisfies the >= rule")
        assert license_["total_available_coverage_cents"] == 7_500_000
        assert_oti_license(license_)


class TestBondDrawCascade:
    def test_bond_append_activates_at_exact_required_minimum(self):
        """PRD §3.4: "if total available coverage has reached
        `required_bond_cents` and the license is not `ACTIVE`, it becomes
        `ACTIVE`".

        Design: Difficulty/transitive_cascade/bond_exhaustion_suspends_license_then_service_contracts
        """
        env = setup_nvocc_license(bond_coverages=(7_500_000,),
                                  carrier_name="Nightowl Logistics")
        license_ = env["license"]
        assert license_["license_status"] == "ACTIVE", (
            "the bond append activates the license at exactly 7500000")
        assert license_["total_available_coverage_cents"] == 7_500_000

    def test_bond_exhaustion_suspends_license_then_service_contracts(self):
        """PRD §2.10: "When a draw leaves a license's total available coverage
        below its requirement, the license moves from `ACTIVE` to `SUSPENDED`,
        and every `EFFECTIVE` service contract of the carrier moves to
        `SUSPENDED` with it".
        PRD §3.4: "`bond_status`, which reads `EXHAUSTED` exactly when the bond
        is fully drawn and `ACTIVE` otherwise."

        Design: Difficulty/transitive_cascade/bond_exhaustion_suspends_license_then_service_contracts
        """
        env = setup_nvocc_license(bond_coverages=(7_500_000,),
                                  carrier_name="Nightowl Logistics")
        carrier = env["carrier"]
        license_ = env["license"]
        shipper = make_shipper()
        set_logical_clock("2026-09-03T00:00:00Z")
        contract = file_service_contract(carrier["id"], shipper["id"],
                                         contract_reference="SC-1")
        assert contract["contract_status"] == "EFFECTIVE"

        drawn = post_draw(license_["id"], carrier["id"], "B1", 7_500_000,
                          license_["version"], reason="unpaid reparation order")
        bond = _bond(drawn, "B1")
        assert bond["drawn_cents"] == 7_500_000
        assert bond["available_cents"] == 0
        assert bond["bond_status"] == "EXHAUSTED"
        assert drawn["license_status"] == "SUSPENDED"
        assert drawn["total_available_coverage_cents"] == 0

        rows, _meta = validate_paginated(api_client.list_service_contracts(
            DOCKET, params={"carrier_id": carrier["id"]}))
        assert rows[0]["id"] == contract["id"]
        assert rows[0]["contract_status"] == "SUSPENDED"


class TestBondLedgerGuardsAndOcc:
    def test_bond_ledger_limit_violations_return_402(self):
        """PRD §3.4: "A positive amount draws down coverage and may not exceed
        the bond's `available_cents`; a larger draw is rejected with
        `ERR_BOND_COVERAGE_EXCEEDED` (HTTP 402). A negative amount reverses a
        prior draw, and its magnitude may not exceed the bond's `drawn_cents`; a
        larger reversal is rejected with `ERR_BOND_REVERSAL_EXCEEDED`
        (HTTP 402)."

        Design: Corner/validations/bond_ledger_limit_violations_return_402
        """
        env = setup_nvocc_license(bond_coverages=(7_500_000,),
                                  carrier_name="Ledger Limit Forwarders")
        license_ = env["license"]
        counsel = make_counsel_headers("ec-1")
        v = license_["version"]

        r1 = api_client.post_bond_draw(license_["id"],
            create_draw_payload("B1", 8_000_000, v, reason="oversized claim"),
            counsel)
        validate_error(r1, ApiErrorId.ERR_BOND_COVERAGE_EXCEEDED)

        r2 = api_client.post_bond_draw(license_["id"],
            create_draw_payload("B1", -1, v, reason="reversal with nothing drawn"),
            counsel)
        validate_error(r2, ApiErrorId.ERR_BOND_REVERSAL_EXCEEDED)

        # Rejections perform no mutation, so the observed version stays valid.
        data = validate_success(api_client.post_bond_draw(license_["id"],
            create_draw_payload("B1", 7_500_000, v, reason="full coverage claim"),
            counsel), 200)
        assert data["total_available_coverage_cents"] == 0
        assert _bond(data, "B1")["bond_status"] == "EXHAUSTED"
        assert data["license_status"] == "SUSPENDED", "0 < 7500000 required"

    def test_bond_draw_stale_license_version_returns_412(self):
        """PRD §2.9: "Posting a draw or reversal against an OTI license requires
        `expected_license_version`, the caller's last observed `version` of that
        license; a prior draw, reversal, or bond append legitimately advances the
        license's version and changes remaining coverage, so a stale assertion is
        likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller
        must re-observe the ledger before posting."

        Design: Corner/complexity_layers/bond_draw_stale_license_version_returns_412
        """
        env = setup_nvocc_license(bond_coverages=(8_000_000,),
                                  carrier_name="Stale Ledger Forwarders")
        license_ = env["license"]
        v0 = license_["version"]

        post_draw(license_["id"], env["carrier"]["id"], "B1", 100, v0,
                  reason="claim 1")
        r2 = api_client.post_bond_draw(license_["id"],
            create_draw_payload("B1", 100, v0, reason="claim 2"),
            make_counsel_headers("ec-1"))
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)

        current = get_license_state(env["carrier"]["id"], license_["id"])
        data = post_draw(license_["id"], env["carrier"]["id"], "B1", 200,
                         current["version"], reason="claim 2 retry")
        assert data["total_available_coverage_cents"] == 7_999_700, (
            "8000000 - 100 - 200")
        assert data["license_status"] == "ACTIVE", "7999700 >= 7500000"


class TestBondConservation:
    def test_draw_conserve_coverage_identity_and_suspends(self):
        """PRD §3.4: "the per-bond invariant that `available_cents` plus
        `drawn_cents` equals `coverage_cents` holds after every draw and every
        reversal." and "otherwise, if total available coverage has fallen below
        `required_bond_cents` while the license is `ACTIVE`, it becomes
        `SUSPENDED`."
        PRD §2.9: "Both guarded writes increment the parent resource's `version`
        by one on success".

        Design: Difficulty/compensating_invariant/bond_draw_and_reversal_conserve_coverage_identity
        """
        env = setup_nvocc_license(bond_coverages=(7_500_000,),
                                  carrier_name="Ledger Lines")
        license_ = env["license"]
        drawn = post_draw(license_["id"], env["carrier"]["id"], "B1", 3_000_000,
                          license_["version"], reason="claim CAM-1")
        bond = _bond(drawn, "B1")
        assert bond["drawn_cents"] == 3_000_000
        assert bond["available_cents"] == 4_500_000
        assert_bond_invariant(bond)
        assert drawn["license_status"] == "SUSPENDED", "4500000 < 7500000"
        assert drawn["version"] == license_["version"] + 1

    def test_reversal_restores_exact_pre_draw_state(self):
        """PRD §3.4: "the per-bond invariant that `available_cents` plus
        `drawn_cents` equals `coverage_cents` holds after every draw and every
        reversal." and "if total available coverage has reached
        `required_bond_cents` and the license is not `ACTIVE`, it becomes
        `ACTIVE`".

        Design: Difficulty/compensating_invariant/bond_draw_and_reversal_conserve_coverage_identity
        """
        env = setup_nvocc_license(bond_coverages=(7_500_000,),
                                  carrier_name="Ledger Lines")
        license_ = env["license"]
        drawn = post_draw(license_["id"], env["carrier"]["id"], "B1", 3_000_000,
                          license_["version"], reason="claim CAM-1")
        restored = post_draw(license_["id"], env["carrier"]["id"], "B1",
                             -3_000_000, drawn["version"],
                             reason="claim CAM-1 repaid")
        bond = _bond(restored, "B1")
        assert bond["drawn_cents"] == 0
        assert bond["available_cents"] == 7_500_000
        assert_bond_invariant(bond)
        assert restored["license_status"] == "ACTIVE", (
            "the compensating action restored the exact pre-draw state")
        assert restored["total_available_coverage_cents"] == 7_500_000
