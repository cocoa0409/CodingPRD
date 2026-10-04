"""Entity corner tests: defaults, uniqueness, required fields, 404."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    make_account,
    make_account_with_va,
    make_device,
    make_pool,
    make_registered_device,
    make_va,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestSmartAccountDefaults:
    def test_new_account_defaults(self, api):
        """PRD §3.1: "The new account starts in `ACTIVE` status with its
        `compliance_posture` initialized to `COMPLIANT`." PRD §2.4: "Most
        entities additionally carry `updated_at` and an integer `version` that
        starts at 1 and increments by exactly 1 on every mutation of that
        row".

        Design: Corner/entities/smart_account_creation_defaults
        """
        account = validate_success(api.create_smart_account(
            {"account_ref": "ACCT-DEFAULTS", "display_name": "Defaults"}, ADMIN),
            expected_status=201)
        data = validate_success(api.get_smart_account(account["id"], ADMIN))
        assert data["status"] == "ACTIVE"
        assert data["compliance_posture"] == "COMPLIANT"
        assert data["version"] == 1


class TestUniqueness:
    def test_duplicate_serial_number_rejected(self, api):
        """PRD §2.7: "Uniqueness constraints are enforced at creation time and
        a violation is rejected with `ERR_DUPLICATE` (HTTP 409): `account_ref`
        on a smart account, `partner_ref` on a partner organization,
        `contract_number` on a service contract, and `serial_number` on a
        device are each globally unique".

        Design: Corner/entities/duplicate_serial_number_rejected
        """
        account, va = make_account_with_va()
        make_device(va["id"], serial_number="SN-DUP")

        resp = api.create_device({
            "virtual_account_id": va["id"],
            "serial_number": "SN-DUP",
            "product_family": "PF-DUP",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_va_name_unique_within_account_only(self, api):
        """PRD §2.7: "a virtual account's `name` is unique within its owning
        smart account; a license pool's `sku` is unique within its owning
        virtual account."

        Design: Corner/entities/virtual_account_name_scoped_uniqueness
        """
        account_a = make_account()
        account_b = make_account()
        make_va(account_a["id"], name="SEG")

        resp = api.create_virtual_account(
            {"smart_account_id": account_a["id"], "name": "SEG"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

        ok = validate_success(api.create_virtual_account(
            {"smart_account_id": account_b["id"], "name": "SEG"}, ADMIN), expected_status=201)
        assert ok["name"] == "SEG", "cross-account reuse of a VA name must be allowed"


class TestRequestShape:
    def test_missing_required_field_rejected(self, api):
        """PRD §2.7: "Requests missing a required field, carrying a
        wrong-typed value, or supplying an enum value outside its declared set
        are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/missing_required_field_rejected
        """
        account, va = make_account_with_va()

        resp = api.create_license_pool({
            "virtual_account_id": va["id"],
            "sku": "X",
            "license_model": "PERPETUAL",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_enum_value_rejected(self, api):
        """PRD §2.7: "Requests missing a required field, carrying a
        wrong-typed value, or supplying an enum value outside its declared set
        are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invalid_enum_value_rejected
        """
        account, va = make_account_with_va()

        resp = api.create_license_pool({
            "virtual_account_id": va["id"],
            "sku": "X",
            "license_model": "TRIAL",
            "purchased_quantity": 5,
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestUsageReportImmutability:
    def test_report_carries_no_version_field(self, api):
        """PRD §2.4: "Three entities are deliberately append-only or
        milestone-style and omit both `updated_at` and `version`:
        `UsageReport`, `ComplianceEvent`, and `ProductLifecycleMilestone`
        carry only `id` and `created_at`."

        Design: Corner/entities/usage_report_immutability
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=10)
        device = make_registered_device(va["id"])

        report = validate_success(api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-02T00:00:00Z",
            "lines": [{"license_pool_id": pool["id"], "quantity": 1}],
        }, ADMIN), expected_status=201)
        assert "version" not in report, "append-only UsageReport must omit version"
        assert "updated_at" not in report, "append-only UsageReport must omit updated_at"
        assert report["status"] == "ACCEPTED"
        assert "id" in report and "created_at" in report


class TestNotFound:
    def test_get_nonexistent_device_404(self, api):
        """PRD §2.7: "Foreign-key references — every `id` appearing in a URL
        path and every identifier field in a request body — are validated
        left-to-right, path parameters first and then body fields in their
        declared order; an unresolvable reference yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_nonexistent_device_404
        """
        resp = api.get_device(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
