"""Nurse registration, confidentiality reads, listing, and immutable attachments."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_certification_payload,
    create_nurse_payload,
)
from test_helpers.test_users import (
    ADMIN,
    make_candidate_headers,
    make_employer_headers,
)
from test_helpers.api_client import api_client


class TestNurseCreation:
    def test_create_returns_all_fields_in_draft_with_version_1(self, api):
        """PRD §3.1: "The new profile starts in `DRAFT` with `version` 1."
        PRD §2.5: "Every primary resource — Nurse, LicenseVerification, Employer, Requisition, Application, Interview, Offer, Screening, OnboardingDocument, Placement, and Invoice — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, refreshed on every mutation; and `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource."
        PRD §2.8: "A nurse's profile carries `confidentiality_exclusions`, an array of employer ids the nurse hides from; it defaults to an empty array at registration."

        Design: Corner/entities/nurse_create_returns_all_fields_in_draft_with_version_1
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(
            full_name="Nora Icu", email="nora@x.com", home_state="CA",
            primary_specialty="ICU", years_experience=8, desired_shift="DAY",
            desired_hourly_rate_cents=7000, max_commute_miles=40,
            current_employer_name="",
        )

        assert nurse["status"] == "DRAFT"
        assert nurse["version"] == 1
        assert nurse["license_verified"] is False
        assert nurse["active_application_count"] == 0
        assert nurse["confidentiality_exclusions"] == []
        assert is_valid_uuid(nurse["id"])
        assert is_iso8601_timestamp(nurse["created_at"])
        assert is_iso8601_timestamp(nurse["updated_at"])

    def test_create_with_duplicate_email_rejected(self, api):
        """PRD §3.1: "Registration captures `full_name`, a login `email` that must be unique across all nurses (a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`)"

        Design: Corner/entities/nurse_create_with_duplicate_email_rejected
        """
        fx.set_clock()
        fx.create_draft_nurse(email="nora@x.com", full_name="Nora Icu")

        resp = api_client.create_nurse(
            create_nurse_payload(
                full_name="Imposter", email="nora@x.com", home_state="OR",
                primary_specialty="ER", years_experience=2, desired_shift="NIGHT",
                desired_hourly_rate_cents=6000, max_commute_miles=10,
            ),
            make_candidate_headers("seed-imposter"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)

        rows, meta = validate_paginated(api_client.list_nurses(ADMIN))
        assert meta["total_count"] == 1, "the duplicate registration must not create a row"

    def test_create_with_missing_required_field_returns_validation_error(self, api):
        """PRD §3.1: "Malformed bodies, missing required fields, out-of-range enums, or numeric range violations (a rate below 2000 cents, for instance) are rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/nurse_create_with_missing_required_field_returns_validation_error
        """
        fx.set_clock()
        payload = {
            "full_name": "NoSpec", "email": "nospec@x.com", "home_state": "CA",
            "years_experience": 3, "desired_shift": "DAY",
            "desired_hourly_rate_cents": 7000, "max_commute_miles": 40,
            "current_employer_name": "",
        }
        resp = api_client.create_nurse(payload, make_candidate_headers("seed-nospec"))
        assert resp.status_code == 400
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_create_with_invalid_enum_and_low_rate_rejected(self, api):
        """PRD §3.1: "a `primary_specialty` drawn from `ICU`, `ER`, `MED_SURG`, `TELEMETRY`, `OR`, `PEDIATRICS`, `LABOR_DELIVERY`, or `ONCOLOGY`"
        PRD §3.1: "Malformed bodies, missing required fields, out-of-range enums, or numeric range violations (a rate below 2000 cents, for instance) are rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/nurse_create_with_invalid_enum_and_low_rate_rejected
        """
        fx.set_clock()
        bad_enum = api_client.create_nurse(
            create_nurse_payload(email="badenum@x.com", primary_specialty="BRAIN_SURGERY"),
            make_candidate_headers("seed-badenum"),
        )
        validate_error(bad_enum, ApiErrorId.ERR_VALIDATION, 400)

        low_rate = api_client.create_nurse(
            create_nurse_payload(email="lowrate@x.com", desired_hourly_rate_cents=1500),
            make_candidate_headers("seed-lowrate"),
        )
        validate_error(low_rate, ApiErrorId.ERR_VALIDATION, 400)

        rows, meta = validate_paginated(api_client.list_nurses(ADMIN))
        assert meta["total_count"] == 0

    def test_get_by_employer_confidentially_excluded_returns_404(self, api):
        """PRD §2.8: "At read time, an employer who is excluded receives `ERR_NOT_FOUND` when reading the nurse's profile — the cloak pretends the nurse does not exist rather than admitting the exclusion."
        PRD §3.1: "if `current_employer_name` is non-empty and an `Employer` row exists whose `legal_name` equals it, that employer's id is appended to the nurse's `confidentiality_exclusions`."

        Design: Corner/entities/nurse_get_by_employer_confidentially_excluded_returns_404
        """
        fx.set_clock()
        employer = fx.create_employer(legal_name="Bayview Medical")
        nurse = fx.create_draft_nurse(
            email="shy@x.com", full_name="Shy Nurse",
            current_employer_name="Bayview Medical",
        )
        lic = fx.add_license(nurse, license_number="RN-CA-800")
        fx.submit_nurse(nurse)
        fx.verify_license(lic)

        cloak_resp = api_client.get_nurse(nurse["id"], make_employer_headers(employer["id"]))
        assert cloak_resp.status_code == 404
        validate_error(cloak_resp, ApiErrorId.ERR_NOT_FOUND, 404)

        admin_view = validate_success(api_client.get_nurse(nurse["id"], ADMIN))
        assert employer["id"] in admin_view["confidentiality_exclusions"], (
            "activation must auto-add the current employer's id"
        )

    def test_nurses_list_paginates_with_defaults_and_filters(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Every list response's `meta` object carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/nurses_list_paginates_with_defaults_and_filters
        """
        fx.set_clock()
        for i in range(3):
            ctx = fx.setup_active_nurse(
                email=f"p{i}@x.com", primary_specialty="ICU", years_experience=4 + i,
            )
            assert ctx["nurse"]["status"] == "ACTIVE"
        er = fx.setup_active_nurse(email="p4@x.com", primary_specialty="ER")
        assert er["nurse"]["status"] == "ACTIVE"

        rows, meta = validate_paginated(
            api_client.list_nurses(ADMIN, params={"primary_specialty": "ICU", "limit": 2, "offset": 0})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        rows2, meta2 = validate_paginated(
            api_client.list_nurses(ADMIN, params={"primary_specialty": "ICU", "limit": 2, "offset": 2})
        )
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        rows3, meta3 = validate_paginated(
            api_client.list_nurses(ADMIN, params={"status": "ACTIVE"})
        )
        assert meta3["total_count"] == 4

        _, meta4 = validate_paginated(api_client.list_nurses(ADMIN))
        assert meta4["limit"] == 10
        assert meta4["offset"] == 0


class TestRequisitionRetrieval:
    def test_get_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/requisition_get_unknown_id_returns_not_found
        """
        fx.set_clock()
        resp = api_client.get_requisition(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestCertifications:
    def test_certification_is_immutable_no_version_field(self, api):
        """PRD §2.5: "**Certification** rows are immutable attachments: they carry `id` and `created_at` only — both `updated_at` and `version` are absent."

        Design: Corner/entities/certification_is_immutable_no_version_field
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")
        cert = validate_success(
            api_client.create_certification(
                create_certification_payload(nurse["id"], cert_code="ACLS", expires_on="2027-06-01"),
                make_candidate_headers(nurse["id"]),
            ),
            expected_status=201,
        )

        got = validate_success(
            api_client.get_certification(cert["id"], make_candidate_headers(nurse["id"]))
        )
        assert is_valid_uuid(got["id"])
        assert is_iso8601_timestamp(got["created_at"])
        assert got["nurse_id"] == nurse["id"]
        assert got["cert_code"] == "ACLS"
        assert got["expires_on"] == "2027-06-01"
        assert "version" not in got, "Certification rows carry no version field"
        assert "updated_at" not in got, "Certification rows carry no updated_at field"

    def test_certification_with_past_expiry_rejected(self, api):
        """PRD §3.1: "an `expires_on` date that must be strictly after the clock's current date at creation — a certification already lapsed is rejected with `ERR_LICENSE_EXPIRED`."

        Design: Corner/entities/certification_with_past_expiry_rejected
        """
        fx.set_clock()
        nurse = fx.create_draft_nurse(email="nora@x.com")

        resp = api_client.create_certification(
            create_certification_payload(nurse["id"], cert_code="PALS", expires_on="2026-09-01"),
            make_candidate_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRED)

        rows, meta = validate_paginated(
            api_client.list_nurse_certifications(nurse["id"], make_candidate_headers(nurse["id"]))
        )
        assert meta["total_count"] == 0, "the lapsed certification must not be persisted"
