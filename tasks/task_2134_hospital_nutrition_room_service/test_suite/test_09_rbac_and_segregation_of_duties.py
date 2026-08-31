"""Role authorisation and the three segregation-of-duties checkpoints."""
import pytest
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    DIETITIAN_1,
    DIETITIAN_2,
    TEST_USERS,
    TRAY_AIDE_1,
    assign_consult,
    assess_consult,
    create_meal_order_payload,
    diet_order_version,
    draft_diet_order,
    line,
    make_dietitian_headers,
    make_physician_headers,
    new_consult,
    new_diet_rule,
    new_patient,
    new_ward,
    read_consult,
    read_diet_order,
    read_meal_order,
    setup_accuracy_passed_tray,
    setup_tray_scenario,
    submit_diet_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
DIETITIAN_OTHER = TEST_USERS["dietitian_2_headers"]
AIDE_1 = TEST_USERS["tray_aide_headers"]

DUAL_IDENTITY = "u-dual-1"


class TestRoleAuthorisation:
    def test_dietitian_cannot_place_a_meal_order(self, api):
        """PRD §2.1: "A well-authenticated request whose role is not among the roles
        the target endpoint permits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.6: "Room service begins at the bedside, where a `DietClerk` takes an
        on-demand order and places a **meal order** — a tray."
        PRD §2.1: "Read access is deliberately broad — every listing and
        single-resource read endpoint is open to all five roles — while write access is
        narrow and specific, as §4 enumerates."

        Design: Corner/rbac/dietitian_cannot_place_a_meal_order_returns_forbidden_role
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AV01", "full_name": "Xu Chen",
                               "age_years": 44},
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
            place_order=False,
        )

        response = api.create_meal_order(
            create_meal_order_payload(
                scenario["patient"]["id"],
                scenario["period"]["id"],
                scenario["diet_order"]["id"],
                scenario["diet_order"]["version"],
                [line(scenario["menu"]["SOU-BRO"]["id"], 1)],
            ),
            DIETITIAN,
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        _, meta = validate_paginated(
            api.list_meal_orders(
                CLERK, params={"meal_period_id": scenario["period"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_diet_order(
            scenario["diet_order"]["id"]
        )["linked_meal_order_count"] == 0

    def test_tray_aide_cannot_cosign_a_diet_order(self, api):
        """PRD §2.1: "A well-authenticated request whose role is not among the roles
        the target endpoint permits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.3: "A `Dietitian` cosigns a `PENDING_COSIGN` order whose patient is
        still `ADMITTED`, and whose `ordering_physician_user_id` differs from the
        cosigner's own `X-User-ID` — a match is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/tray_aide_cannot_cosign_a_diet_order_returns_forbidden_role
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-AW01", full_name="Yaz Idris",
                              age_years=46)
        order = draft_diet_order(patient["id"], rule["id"])
        submit_diet_order(order["id"])

        response = api.cosign_diet_order(order["id"], AIDE_1)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        after = read_diet_order(order["id"])
        assert after["status"] == "PENDING_COSIGN"
        assert after["cosigned_by_user_id"] is None

    def test_request_without_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request to this API, without exception, carries two
        headers: `X-User-ID` identifies the acting person and `X-User-Role` declares
        the capacity in which they are acting."
        PRD §2.1: "A request that omits either header, or that supplies an
        `X-User-Role` value outside those five spellings, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.5: "1. **Authentication** — both headers present and the role
        recognised, else `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/request_missing_x_user_role_header_returns_unauthenticated
        """
        ward = new_ward()

        response = api.get_ward(ward["id"], ANONYMOUS_HEADERS)
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert error["error_id"] != "ERR_FORBIDDEN_ROLE", (
            "authentication is decided before authorisation and before existence"
        )


class TestSegregationOfDuties:
    def test_temperature_check_by_the_accuracy_checker_is_refused(self, api):
        """PRD §2.10: "Three actions in this system may not be performed by the person
        who performed the step they check. A diet order may not be cosigned by the same
        `X-User-ID` recorded as its `ordering_physician_user_id`. A tray's temperature
        check may not be recorded by the same `X-User-ID` recorded as its
        `accuracy_checked_by_user_id`. A nutrition consult may not be signed by the
        same `X-User-ID` recorded as its `requested_by_user_id`. In all three cases the
        rejection is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and in all three cases the
        comparison is on the raw identifier string, independent of role."
        PRD §3.7: "The **temperature check** is the segregation-of-duties point on the
        tray line: it requires the tray's quality dimension to be `ACCURACY_PASSED` or
        `TEMP_FAILED`, and it requires the acting `X-User-ID` to differ from the
        `accuracy_checked_by_user_id` already recorded on the tray, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/temperature_check_by_the_accuracy_checker_returns_segregation_of_duties
        """
        scenario = setup_accuracy_passed_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AX01", "full_name": "Zed Toma",
                               "age_years": 57},
        )
        tray_id = scenario["meal_order"]["id"]

        response = api.temperature_check(tray_id, {"hot_probe_celsius": 64.0}, AIDE_1)
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        tray = read_meal_order(tray_id)
        assert tray["qa_status"] == "ACCURACY_PASSED"
        assert tray["accuracy_checked_by_user_id"] == TRAY_AIDE_1
        assert tray["temperature_checked_by_user_id"] is None
        assert tray["hot_probe_celsius"] is None

    def test_consult_sign_by_the_requesting_user_is_refused(self, api):
        """PRD §2.10: "Three actions in this system may not be performed by the person
        who performed the step they check. A diet order may not be cosigned by the same
        `X-User-ID` recorded as its `ordering_physician_user_id`. A tray's temperature
        check may not be recorded by the same `X-User-ID` recorded as its
        `accuracy_checked_by_user_id`. A nutrition consult may not be signed by the
        same `X-User-ID` recorded as its `requested_by_user_id`. In all three cases the
        rejection is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and in all three cases the
        comparison is on the raw identifier string, independent of role."
        PRD §3.9: "**Signing** moves it `ASSESSED → SIGNED`, records
        `signed_by_user_id` from the acting `X-User-ID`, and requires that identifier
        to differ from `requested_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/consult_sign_by_the_requesting_user_returns_segregation_of_duties
        """
        ward = new_ward()
        patient = new_patient(ward["id"], mrn="MRN-AY01", full_name="Ana Weiss",
                              age_years=67)
        consult = new_consult(patient["id"], DIETITIAN, reason_code="SCREENING_ROUND")
        assign_consult(consult["id"], DIETITIAN_1)
        assess_consult(consult["id"], DIETITIAN_1, assessment_variant="SCREENING",
                       weight_loss_pct=8.0, intake_pct=60.0, bmi=17.0)

        refused = api.sign_consult(consult["id"], DIETITIAN)
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        midway = read_consult(consult["id"])
        assert midway["status"] == "ASSESSED"
        assert midway["signed_by_user_id"] is None

        signed = validate_success(api.sign_consult(consult["id"], DIETITIAN_OTHER), 200)
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == DIETITIAN_2
        assert signed["requested_by_user_id"] == DIETITIAN_1

    def test_diet_order_cosign_by_the_ordering_identifier_is_refused(self, api):
        """PRD §2.10: "Three actions in this system may not be performed by the person
        who performed the step they check. A diet order may not be cosigned by the same
        `X-User-ID` recorded as its `ordering_physician_user_id`. A tray's temperature
        check may not be recorded by the same `X-User-ID` recorded as its
        `accuracy_checked_by_user_id`. A nutrition consult may not be signed by the
        same `X-User-ID` recorded as its `requested_by_user_id`. In all three cases the
        rejection is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and in all three cases the
        comparison is on the raw identifier string, independent of role."
        PRD §3.3: "A `Dietitian` cosigns a `PENDING_COSIGN` order whose patient is
        still `ADMITTED`, and whose `ordering_physician_user_id` differs from the
        cosigner's own `X-User-ID` — a match is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/diet_order_cosign_by_the_ordering_user_returns_segregation_of_duties
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-AZ01", full_name="Bea Torres",
                              age_years=62)
        order = draft_diet_order(patient["id"], rule["id"], DUAL_IDENTITY)
        submit_diet_order(order["id"], DUAL_IDENTITY)

        refused = api.cosign_diet_order(
            order["id"], make_dietitian_headers(DUAL_IDENTITY)
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        assert read_diet_order(order["id"])["status"] == "PENDING_COSIGN"

        activated = validate_success(api.cosign_diet_order(order["id"], DIETITIAN), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["cosigned_by_user_id"] == DIETITIAN_1
        assert activated["ordering_physician_user_id"] == DUAL_IDENTITY
