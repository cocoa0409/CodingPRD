"""Auth and RBAC: missing context headers, forbidden roles, entity-backed
ownership, and cross-role denial."""
from test_helpers import (
    ApiErrorId,
    create_claim_payload,
    create_dealer_payload,
    create_fleet_payload,
    make_dealer_advisor_headers,
    make_parts_manager_headers,
    make_uptime_coordinator_headers,
    setup_case_in_state,
    setup_clock,
    setup_fleet,
    setup_full_environment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestContextHeaders:
    def test_missing_user_role_header_returns_400(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either is missing or malformed, the request is
        rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_role_header_returns_400
        """
        setup_clock()
        # Role value not in the RBAC matrix is malformed.
        bad_headers = {
            "X-User-ID": "intruder-1",
            "X-User-Role": "SuperAdmin",
            "Content-Type": "application/json",
        }
        resp = api.list_fleets(bad_headers)
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER.value,
            expected_status=400,
        )

    def test_missing_user_id_header_returns_400(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either is missing or malformed, the request is
        rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_role_header_returns_400
        """
        setup_clock()
        headers = {"X-User-Role": "FleetManager", "Content-Type": "application/json"}
        resp = api.list_fleets(headers)
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER.value,
            expected_status=400,
        )


class TestRoleAuthorization:
    def test_role_lacking_permission_returns_403(self, api):
        """PRD §2.1: "If the role named by `X-User-Role` is not authorized for
        the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/validations/role_lacking_permission_returns_403
        """
        setup_clock()
        resp = api.create_fleet(
            create_fleet_payload(fleet_name="Forbidden Fleet", home_region="SE"),
            make_parts_manager_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)
        fleets, meta = validate_paginated(api.list_fleets(make_parts_manager_headers()))
        assert meta["total_count"] == 0, "no fleet may be created by PartsManager"

    def test_fleet_manager_cannot_submit_claim(self, api):
        """PRD §2.1: "If the role named by `X-User-Role` is not authorized for
        the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD §4: "POST | `/fleets/{fleetId}/trucks/{truckId}/cases/{caseId}/claims/{claimId}/submit` |
        Submit a DRAFT claim (computes allowances; OCC against the case) |
        WarrantyAdmin"

        Design: Corner/roles/fleet_manager_cannot_submit_claim
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Role Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY", labor_minutes_claimed=100,
                    parts_claimed_cents=5000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        resp = api.submit_claim(
            fid, tid, case["id"], claim["id"],
            {"expected_case_version": case_now["version"]},
            env["fm"],  # FleetManager is not authorized for claim submit
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)
        after = validate_success(api.get_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        assert after["submission_status"] == "DRAFT"

    def test_uptime_coordinator_cannot_create_dealer(self, api):
        """PRD §2.1: "If the role named by `X-User-Role` is not authorized for
        the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD §4: "POST | `/dealers` | Onboard a dealer | FleetManager"

        Design: Corner/validations/role_lacking_permission_returns_403
        """
        setup_clock()
        resp = api.create_dealer(
            create_dealer_payload(), make_uptime_coordinator_headers()
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)


class TestEntityBackedIdentity:
    def test_dealer_advisor_entity_backed_ownership(self, api):
        """PRD §2.1: "When `X-User-Role` is `DealerAdvisor`, `X-User-ID` is the
        `id` of the acting `Dealer`; ownership checks on any resource that
        references a `Dealer` compare the resource's `dealer_id` foreign key
        against `X-User-ID`."

        Design: Corner/roles/dealer_advisor_entity_backed_ownership
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="EB Fleet", home_region="SE")
        dealer_a = validate_success(
            api.create_dealer(
                create_dealer_payload(dealer_name="Dealer A", hourly_labor_rate_cents=18500),
                fm,
            ),
            expected_status=201,
        )
        dealer_b = validate_success(
            api.create_dealer(
                create_dealer_payload(dealer_name="Dealer B", hourly_labor_rate_cents=20000),
                fm,
            ),
            expected_status=201,
        )
        # DealerAdvisor identified as dealer A attempts to create a bay under dealer B.
        resp = api.create_bay(
            dealer_b["id"],
            {"bay_code": "B9"},
            make_dealer_advisor_headers(dealer_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)
        bays = validate_paginated(
            api.list_bays(dealer_b["id"], make_dealer_advisor_headers(dealer_b["id"]))
        )[0]
        assert len(bays) == 0, "cross-tenant bay create must not persist anything"

    def test_dealer_advisor_with_unknown_id_returns_actor_not_found(self, api):
        """PRD §2.1: "For entity-backed roles (`FleetManager`, `DealerAdvisor`),
        if the `X-User-ID` value does not resolve to an existing entity of the
        matching type, the request is rejected with `ERR_ACTOR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/roles/dealer_advisor_entity_backed_ownership
        """
        setup_clock()
        fleet, fm = setup_fleet(fleet_name="EB2 Fleet", home_region="SE")
        dealer = validate_success(
            api.create_dealer(create_dealer_payload(dealer_name="Dealer C"), fm),
            expected_status=201,
        )
        # A DealerAdvisor id that resolves to no Dealer at all.
        resp = api.create_bay(
            dealer["id"],
            {"bay_code": "B9"},
            make_dealer_advisor_headers("00000000-0000-4000-8000-000000000000"),
        )
        validate_error(resp, ApiErrorId.ERR_ACTOR_NOT_FOUND.value, expected_status=404)
