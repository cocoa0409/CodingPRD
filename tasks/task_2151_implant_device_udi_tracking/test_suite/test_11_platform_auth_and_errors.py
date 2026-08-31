"""Authentication, table-driven authorization, the not-found family, versioning."""

import re

from test_helpers import (
    ApiErrorId,
    CC,
    CO,
    IL,
    MISSING_UUID,
    RI,
    RT,
    build_user_headers,
    create_catalog_item,
    create_patient,
    create_vendor,
    is_iso8601_timestamp,
    make_vendor_rep_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestAuthentication:
    def test_blank_headers_and_an_unresolvable_vendor_identity_all_return_401(self, api):
        """PRD §2.1: "Every request to every endpoint — including the logical-clock
        endpoint — must carry two headers: `X-User-ID`, identifying the acting user,
        and `X-User-Role`, naming the role that user is acting under. If either
        header is absent, empty, or consists only of whitespace, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same rejection applies
        when `X-User-Role` carries a value that is not one of the six role names
        defined below."
        PRD §2.1: "The sixth role is **entity-backed**. When `X-User-Role` is
        `VendorRep`, `X-User-ID` is the `id` of the acting `Vendor`; if it does not
        resolve to an existing vendor, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401) exactly as a missing header would be."

        Design: Corner/validations/missing_or_bogus_auth_headers_return_unauthenticated
        """
        vendor = create_vendor()

        blank_role = validate_error(
            api.get_vendor(vendor["id"], build_user_headers("il-01", "")),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        blank_user = validate_error(
            api.get_vendor(vendor["id"], build_user_headers("", "InventoryLead")),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        unknown_vendor = validate_error(
            api.get_vendor(vendor["id"], make_vendor_rep_headers(MISSING_UUID)),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        for error in (blank_role, blank_user, unknown_vendor):
            assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
                "An authentication failure must never surface as a 403"
            )


class TestRoleAuthorization:
    def test_four_operations_owned_by_other_roles_are_all_refused(self, api):
        """PRD §2.1: "Authorization proper is table-driven: if the role named in
        `X-User-Role` does not appear in the authorized-roles list for the endpoint
        being called (see §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."
        PRD §2.1: "Two roles are additionally walled off from protected health
        information — `VendorRep` may not read patients at all, and `ReceivingTech`
        may read neither patients, charge captures, registry submissions, vendor
        invoices, explant records, recall notifications, nor the recall exposure
        view."

        Design: Corner/rbac/peer_role_boundaries_reject_operations_owned_by_other_roles
        """
        vendor = create_vendor()
        patient = create_patient()
        catalog_item = create_catalog_item(vendor["id"])

        validate_error(
            api.create_vendor({"name": "Rogue Vendor", "vendor_code": "ROGUE-1"}, RT),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(api.create_ops_run(CC), ApiErrorId.ERR_UNAUTHORIZED, 403)
        validate_error(
            api.create_field_action(
                {
                    "vendor_id": vendor["id"],
                    "catalog_item_id": catalog_item["id"],
                    "action_code": "FA-X",
                    "action_class": "CLASS_II",
                    "scope_type": "CATALOG",
                    "effective_from_utc": "2026-09-01T00:00:00Z",
                },
                RI,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.get_patient(patient["id"], make_vendor_rep_headers(vendor["id"])),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        _, vendors_meta = validate_paginated(api.list_vendors(IL))
        assert vendors_meta["total_count"] == 1, "The rogue vendor must not exist"

        _, actions_meta = validate_paginated(
            api.list_field_actions(CO, {"vendor_id": vendor["id"]})
        )
        assert actions_meta["total_count"] == 0


class TestNotFoundFamily:
    def test_core_inventory_path_parameters_each_carry_their_own_404(self, api):
        """PRD §2.6: "Path-parameter existence, left to right. Failure: the matching
        not-found code (404)."
        PRD §2.6: "The full set of path parameters is `vendor_id`, `agreement_id`,
        `catalog_item_id`, `lot_id`, `device_unit_id`, `patient_id`, `case_id`,
        `implant_record_id`, `charge_id`, `submission_id`, `field_action_id`,
        `notification_id`, `invoice_id` and `explant_record_id`; each maps to its own
        not-found code as catalogued in §5."

        Design: Corner/errors/not_found_probes_across_core_inventory_path_resources
        """
        _, meta = validate_paginated(api.list_vendors(IL, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

        probes = [
            (api.get_vendor(MISSING_UUID, IL), ApiErrorId.ERR_VENDOR_NOT_FOUND),
            (api.get_agreement(MISSING_UUID, IL), ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (
                api.get_catalog_item(MISSING_UUID, IL),
                ApiErrorId.ERR_CATALOG_ITEM_NOT_FOUND,
            ),
            (api.get_lot(MISSING_UUID, IL), ApiErrorId.ERR_LOT_NOT_FOUND),
            (api.get_patient(MISSING_UUID, CC), ApiErrorId.ERR_PATIENT_NOT_FOUND),
            (api.get_surgical_case(MISSING_UUID, CC), ApiErrorId.ERR_CASE_NOT_FOUND),
        ]
        for response, expected in probes:
            error = validate_error(response, expected, 404)
            assert response.json()["response_type"] == "error"
            assert error["error_id"] == expected.value

    def test_workflow_path_parameters_each_carry_their_own_404(self, api):
        """PRD §2.6: "Path parameters are resolved strictly left to right, and the
        leftmost segment that fails to resolve determines the error."
        PRD §2.6: "The full set of path parameters is `vendor_id`, `agreement_id`,
        `catalog_item_id`, `lot_id`, `device_unit_id`, `patient_id`, `case_id`,
        `implant_record_id`, `charge_id`, `submission_id`, `field_action_id`,
        `notification_id`, `invoice_id` and `explant_record_id`; each maps to its own
        not-found code as catalogued in §5."

        Design: Corner/errors/not_found_probes_across_workflow_path_resources
        """
        _, meta = validate_paginated(
            api.list_field_actions(CO, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0

        probes = [
            (
                api.get_implant_record(MISSING_UUID, CO),
                ApiErrorId.ERR_IMPLANT_RECORD_NOT_FOUND,
            ),
            (api.get_charge(MISSING_UUID, CO), ApiErrorId.ERR_CHARGE_NOT_FOUND),
            (
                api.get_registry_submission(MISSING_UUID, CO),
                ApiErrorId.ERR_REGISTRY_SUBMISSION_NOT_FOUND,
            ),
            (
                api.get_field_action(MISSING_UUID, CO),
                ApiErrorId.ERR_FIELD_ACTION_NOT_FOUND,
            ),
            (
                api.get_recall_notification(MISSING_UUID, CO),
                ApiErrorId.ERR_RECALL_NOTIFICATION_NOT_FOUND,
            ),
            (api.get_vendor_invoice(MISSING_UUID, CO), ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (
                api.get_explant_record(MISSING_UUID, CO),
                ApiErrorId.ERR_EXPLANT_RECORD_NOT_FOUND,
            ),
        ]
        for response, expected in probes:
            error = validate_error(response, expected, 404)
            assert error["error_id"] == expected.value


class TestVersioning:
    def test_a_single_patch_advances_the_patient_version_by_exactly_one(self, api):
        """PRD §2.4: "`version` is an integer that begins at 1 when the resource is
        created and increases by exactly 1 on every mutation of that resource,
        whether the mutation was requested directly or arrived as a cascade from
        another resource's transition."
        PRD §3.3: "Consent is not frozen: a demographic update, available to a
        `CircClinician` or a `ComplianceOfficer`, may revise `registry_consent` and
        `display_name`, and doing so advances the patient's `version` by one."
        PRD §2.4: "`created_at` and `updated_at` are ISO 8601 timestamps in UTC with
        exactly three fractional-second digits."

        Design: Corner/cross_cutting_layers/version_increments_by_one_on_every_mutation_of_an_entity
        """
        set_clock("2026-09-01T00:00:00Z", CC)
        created = validate_success(
            api.create_patient({"mrn": "MRN-1001", "display_name": "Pat One"}, CC), 201
        )
        assert created["version"] == 1
        assert created["registry_consent"] == "UNKNOWN"
        assert _THREE_FRACTIONAL_DIGITS.match(created["created_at"]), (
            f"created_at must carry exactly three fractional digits, got "
            f"{created['created_at']!r}"
        )
        assert _THREE_FRACTIONAL_DIGITS.match(created["updated_at"])

        patched = validate_success(
            api.update_patient(created["id"], {"registry_consent": "GRANTED"}, CO), 200
        )
        assert patched["version"] == 2
        assert patched["registry_consent"] == "GRANTED"
        assert patched["mrn"] == "MRN-1001"
        assert patched["created_at"] == created["created_at"], (
            "created_at must not move on an update"
        )
        assert is_iso8601_timestamp(patched["updated_at"])
        assert patched["updated_at"] >= patched["created_at"]
