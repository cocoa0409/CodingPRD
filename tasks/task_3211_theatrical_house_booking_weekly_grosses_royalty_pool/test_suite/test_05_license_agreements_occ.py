"""License agreement supersede cycle, live-agreement invariant, OCC rules."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_approved_booking, create_license, sign_license, booking_version,
    get_booking, get_license, list_licenses,
)

HM = TEST_USERS["house_manager_headers"]


class TestLicenseAgreementSupersedeCycle:
    def test_create_supersedes_existing_signed_agreement(self, api):
        """PRD §3.3: "There is at most one live agreement per booking: creating
        a new agreement while an existing one sits in `DRAFT` or `SIGNED`
        moves the existing one to `SUPERSEDED` as a cascade."

        Design: Difficulty/non_linear_state_machine/license_agreement_supersede_cycle
        """
        ctx = setup_approved_booking(company_name="SupCo", company_email="su@x.com")
        bk_id = ctx["booking"]["id"]
        lic1 = create_license(bk_id, booking_version(bk_id))
        sign_license(lic1["id"], booking_version(bk_id), ctx["company"]["id"])
        v3 = booking_version(bk_id)
        lic2 = validate_success(api_client.create_license_agreement(
            bk_id,
            {"weekly_rent_cents": 600000, "stop_clause_weekly_floor_cents": 80000,
             "stop_clause_consecutive_weeks": 3, "expected_booking_version": v3},
            HM), expected_status=201)
        assert get_license(lic1["id"])["status"] == "SUPERSEDED"
        assert lic2["status"] == "DRAFT"

    def test_create_bumps_booking_version_occ_touch(self, api):
        """PRD §2.8: "Both operations, on success, increment the booking's
        `version` by 1 (an OCC touch) in addition to their own mutations."

        Design: Difficulty/non_linear_state_machine/license_agreement_supersede_cycle
        """
        ctx = setup_approved_booking(company_name="SupCo", company_email="su@x.com")
        bk_id = ctx["booking"]["id"]
        lic1 = create_license(bk_id, booking_version(bk_id))
        sign_license(lic1["id"], booking_version(bk_id), ctx["company"]["id"])
        v3 = booking_version(bk_id)
        validate_success(api_client.create_license_agreement(
            bk_id,
            {"weekly_rent_cents": 600000, "stop_clause_weekly_floor_cents": 80000,
             "stop_clause_consecutive_weeks": 3, "expected_booking_version": v3},
            HM), expected_status=201)
        assert booking_version(bk_id) == v3 + 1, (
            f"each create bumps the OCC parent: expected {v3 + 1}, "
            f"got {booking_version(bk_id)}")


class TestLiveAgreementCountInvariant:
    def _setup(self, api):
        ctx = setup_approved_booking(company_name="Inv2Co", company_email="i2@x.com")
        bk_id = ctx["booking"]["id"]
        lic1 = create_license(bk_id, booking_version(bk_id))
        sign_license(lic1["id"], booking_version(bk_id), ctx["company"]["id"])
        return ctx, bk_id, lic1

    def test_supersede_pair_preserves_live_count(self, api):
        """PRD §3.3: "There is at most one live agreement per booking: creating
        a new agreement while an existing one sits in `DRAFT` or `SIGNED`
        moves the existing one to `SUPERSEDED` as a cascade."

        Design: Difficulty/compensating_invariant/license_supersede_preserves_signed_agreement_count
        """
        ctx, bk_id, lic1 = self._setup(api)
        lic2 = validate_success(api_client.create_license_agreement(
            bk_id,
            {"weekly_rent_cents": 600000,
             "stop_clause_weekly_floor_cents": 10000,
             "stop_clause_consecutive_weeks": 2,
             "expected_booking_version": booking_version(bk_id)},
            HM), expected_status=201)
        assert get_license(lic1["id"])["status"] == "SUPERSEDED"
        assert lic2["status"] == "DRAFT"
        live = [l for l in list_licenses(bk_id)
                if l["status"] in ("DRAFT", "SIGNED")]
        assert len(live) == 1, (
            f"exactly one non-terminal agreement per booking, got {len(live)}")

    def test_repeated_creates_keep_live_count_at_one(self, api):
        """PRD §3.3: "There is at most one live agreement per booking: creating
        a new agreement while an existing one sits in `DRAFT` or `SIGNED`
        moves the existing one to `SUPERSEDED` as a cascade."

        Design: Difficulty/compensating_invariant/license_supersede_preserves_signed_agreement_count
        """
        ctx, bk_id, lic1 = self._setup(api)
        for rent in (600000, 700000):
            validate_success(api_client.create_license_agreement(
                bk_id,
                {"weekly_rent_cents": rent,
                 "stop_clause_weekly_floor_cents": 10000,
                 "stop_clause_consecutive_weeks": 2,
                 "expected_booking_version": booking_version(bk_id)},
                HM), expected_status=201)
            live = [l for l in list_licenses(bk_id)
                    if l["status"] in ("DRAFT", "SIGNED")]
            assert len(live) == 1, (
                f"invariant must hold across repeated creates, got {len(live)}")


class TestOccStaleVersion:
    def test_stale_version_error_triggerable_on_license_create(self, api):
        """PRD §2.8: "Creating a license agreement for a booking. Because a
        newly created agreement legitimately supersedes any existing `DRAFT`
        or `SIGNED` agreement on the booking, a client whose view of the
        booking is stale must not be allowed to write. If
        `expected_booking_version` does not match the booking's current
        `version`, creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_error_triggerable_on_license_create
        """
        ctx = setup_approved_booking(company_name="OccCo", company_email="oc@x.com")
        bk_id = ctx["booking"]["id"]
        stale_v = ctx["booking"]["version"]
        create_license(bk_id, stale_v)  # succeeds, bumps booking version
        resp = api_client.create_license_agreement(
            bk_id,
            {"weekly_rent_cents": 600000,
             "stop_clause_weekly_floor_cents": 10000,
             "stop_clause_consecutive_weeks": 2,
             "expected_booking_version": stale_v},
            HM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_stale_version_on_license_sign(self, api):
        """PRD §2.8: "Signing a license agreement. If
        `expected_booking_version` does not match the booking's current
        `version` — for example because another agreement has been created in
        the meantime — signing is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_license_sign
        """
        ctx = setup_approved_booking(company_name="Occ2Co", company_email="o2@x.com")
        bk_id = ctx["booking"]["id"]
        create_license(bk_id, booking_version(bk_id))
        v_after_create = booking_version(bk_id)
        lic2 = create_license(bk_id, v_after_create,
                              weekly_rent_cents=550000)
        resp = api_client.sign_license_agreement(
            lic2["id"], {"expected_booking_version": v_after_create}, ctx["rep"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_sign_with_fresh_version_succeeds(self, api):
        """PRD §2.8: "Signing a license agreement. If
        `expected_booking_version` does not match the booking's current
        `version` — for example because another agreement has been created in
        the meantime — signing is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "The owning `CompanyRep` signs it — the second OCC-protected
        write, again requiring `expected_booking_version` — which is allowed
        only while the booking is `APPROVED` or `ACTIVE` and moves the
        agreement to `SIGNED`."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_license_sign
        """
        ctx = setup_approved_booking(company_name="Occ3Co", company_email="o3@x.com")
        bk_id = ctx["booking"]["id"]
        lic = create_license(bk_id, booking_version(bk_id))
        data = validate_success(api_client.sign_license_agreement(
            lic["id"], {"expected_booking_version": booking_version(bk_id)},
            ctx["rep"]))
        assert data["status"] == "SIGNED"
