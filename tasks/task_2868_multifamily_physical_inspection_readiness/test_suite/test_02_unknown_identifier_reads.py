"""Single-resource reads addressed with well-formed but unknown identifiers.

Every one of these probes a different resource type, because the contract gives
each type its own 404 error identifier rather than a shared one.
"""

from test_helpers import ApiErrorId, assert_error
from test_helpers.test_users import (
    make_appeals_officer_headers,
    make_housing_agency_inspector_headers,
    make_maintenance_technician_headers,
    make_platform_admin_headers,
    make_property_owner_headers,
    make_quality_assurance_reviewer_headers,
)

ADMIN = make_platform_admin_headers()
INSPECTOR = make_housing_agency_inspector_headers()
TECHNICIAN = make_maintenance_technician_headers()
REVIEWER = make_quality_assurance_reviewer_headers()
APPEALS = make_appeals_officer_headers()


class TestUnknownIdentifierReads:
    """Each resource type answers an unknown id with its own 404."""

    def test_unknown_unit_id_returns_unit_not_found(self, api):
        """An unknown unit id resolves to `ERR_UNIT_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_unit_with_unknown_id_returns_unit_not_found
        """
        response = api.get_unit("00000000-0000-4000-8000-000000000002", ADMIN)

        assert_error(response, ApiErrorId.UNIT_NOT_FOUND)

    def test_unknown_inspection_id_returns_inspection_not_found(self, api):
        """An unknown inspection id resolves to `ERR_INSPECTION_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_inspection_with_unknown_id_returns_inspection_not_found
        """
        response = api.get_inspection(
            "00000000-0000-4000-8000-000000000003", INSPECTOR
        )

        assert_error(response, ApiErrorId.INSPECTION_NOT_FOUND)

    def test_unknown_sample_selection_id_returns_sample_selection_not_found(self, api):
        """An unknown slot id resolves to `ERR_SAMPLE_SELECTION_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_sample_selection_with_unknown_id_returns_sample_selection_not_found
        """
        response = api.get_sample_selection(
            "00000000-0000-4000-8000-000000000004", INSPECTOR
        )

        assert_error(response, ApiErrorId.SAMPLE_SELECTION_NOT_FOUND)

    def test_unknown_deficiency_id_returns_deficiency_not_found(self, api):
        """An unknown deficiency id resolves to `ERR_DEFICIENCY_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_deficiency_with_unknown_id_returns_deficiency_not_found
        """
        response = api.get_deficiency(
            "00000000-0000-4000-8000-000000000005", INSPECTOR
        )

        assert_error(response, ApiErrorId.DEFICIENCY_NOT_FOUND)

    def test_unknown_sweep_id_returns_sweep_not_found(self, api):
        """An unknown sweep id resolves to `ERR_SWEEP_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_sweep_with_unknown_id_returns_sweep_not_found
        """
        response = api.get_sweep(
            "00000000-0000-4000-8000-000000000006",
            make_property_owner_headers("owner-unknown"),
        )

        assert_error(response, ApiErrorId.SWEEP_NOT_FOUND)

    def test_unknown_work_order_id_returns_work_order_not_found(self, api):
        """An unknown work order id resolves to `ERR_WORK_ORDER_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_work_order_with_unknown_id_returns_work_order_not_found
        """
        response = api.get_work_order(
            "00000000-0000-4000-8000-000000000007", TECHNICIAN
        )

        assert_error(response, ApiErrorId.WORK_ORDER_NOT_FOUND)

    def test_unknown_appeal_id_returns_appeal_not_found(self, api):
        """An unknown appeal id resolves to `ERR_APPEAL_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_appeal_with_unknown_id_returns_appeal_not_found
        """
        response = api.get_appeal("00000000-0000-4000-8000-000000000008", APPEALS)

        assert_error(response, ApiErrorId.APPEAL_NOT_FOUND)

    def test_unknown_plan_id_returns_cap_not_found(self, api):
        """An unknown plan id resolves to `ERR_CAP_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_corrective_action_plan_with_unknown_id_returns_cap_not_found
        """
        response = api.get_cap("00000000-0000-4000-8000-000000000009", REVIEWER)

        assert_error(response, ApiErrorId.CAP_NOT_FOUND)

    def test_unknown_capital_need_id_returns_capital_need_not_found(self, api):
        """An unknown item id resolves to `ERR_CAPITAL_NEED_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/errors/get_capital_need_item_with_unknown_id_returns_capital_need_not_found
        """
        response = api.get_capital_need(
            "00000000-0000-4000-8000-00000000000a", ADMIN
        )

        assert_error(response, ApiErrorId.CAPITAL_NEED_NOT_FOUND)

    def test_unknown_property_id_returns_property_not_found(self, api):
        """An unknown property id resolves to `ERR_PROPERTY_NOT_FOUND`.

        PRD: "identifiers embedded in the URL are resolved left to right, and
        the first one that names no existing row produces its own 404".

        Design: Corner/entities/get_property_with_unknown_id_returns_not_found
        """
        response = api.get_property(
            "00000000-0000-4000-8000-000000000000", ADMIN
        )

        body = assert_error(response, ApiErrorId.PROPERTY_NOT_FOUND)
        assert isinstance(body["message"], str) and body["message"]
