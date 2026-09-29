"""Who may act, and in what capacity.

Authentication is a header check that precedes everything else, and authorization
is a per-operation role list that precedes every business rule. Both facts are
observable only through their precedence: a request that is wrong in several ways at
once must report the earliest defect, so these tests deliberately break two rules at
a time and pin down which error comes back.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    USER_IDS,
    fixtures as fx,
    ids_of,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    budget_adjustment_payload,
    clock_payload,
    create_moratorium_window_payload,
    create_pole_attachment_application_payload,
    create_route_payload,
    drop,
    owner_response_payload,
    permit_review_payload,
)
from test_helpers.test_users import (
    headers_blank_role,
    headers_blank_user_id,
    headers_missing_user_id,
)

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_DOCK_STREET = {
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}
_TELCO_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}


def test_a_surveyor_may_not_open_a_route_however_valid_the_body(
    api, surveyor_headers, engineer_headers
):
    """The deny is about the role: the identical body from an engineer is created.

    PRD: "Once the headers are accepted, the system checks that the acting
    `X-User-Role` appears in the authorized-role list for the addressed operation. A
    role that is authenticated but not authorized for that operation receives
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/route_create_by_a_field_surveyor_returns_unauthorized
    """
    fx.set_clock("2026-08-10T00:00:00Z")

    refused = api.create_route(create_route_payload(**_HARBOR_LOOP), headers=surveyor_headers)
    validate_error(refused, "ERR_UNAUTHORIZED", 403)
    body = refused.json()["data"]
    assert body["error_id"] == "ERR_UNAUTHORIZED"
    assert isinstance(body["message"], str) and body["message"] != ""

    created = validate_success(
        api.create_route(create_route_payload(**_HARBOR_LOOP), headers=engineer_headers), 201
    )
    assert created["status"] == "PLANNING"
    assert "role" not in created, "the acting role travels in a header, never in a payload"

    rows, meta = validate_paginated(api.list_routes(headers=engineer_headers))
    assert meta["total_count"] == 1
    assert ids_of(rows) == [created["id"]]


def test_the_coordinator_files_a_permit_but_may_not_decide_it(
    api, coordinator_headers, reviewer_headers, engineer_headers
):
    """The review decision belongs to the agency, so a self-approval is a 403.

    PRD: "**`AuthorityReviewer`** — acts for the municipal, railroad, highway or
    waterway agency reviewing a permit application."

    Design: Corner/rbac/permit_review_by_a_permit_coordinator_returns_unauthorized
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(
        headers=engineer_headers,
        name="Inland Spur",
        topology_objective="SPUR",
        target_in_service_date="2027-06-01",
        budget_authorized_cents=250000000,
    )
    segment = fx.create_segment(route["id"], headers=engineer_headers, **_DOCK_STREET)
    fx.accepted_walkout(
        segment["id"],
        [_TELCO_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="leg walked",
    )
    fx.lock_scope(route["id"], headers=engineer_headers)
    permit = fx.filed_permit(
        segment["id"],
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-15",
        work_window_end_on="2026-09-20",
    )
    assert permit["status"] == "UNDER_REVIEW"

    self_approved = api.review_permit_application(
        permit["id"],
        permit_review_payload("APPROVED", decision_note="self-approved"),
        headers=coordinator_headers,
    )
    validate_error(self_approved, "ERR_UNAUTHORIZED", 403)

    undecided = fx.read_permit(permit["id"])
    assert undecided["status"] == "UNDER_REVIEW"
    assert undecided["decided_at"] is None
    assert undecided["decided_by_user_id"] is None
    assert fx.read_segment(segment["id"])["permit_status"] == "PENDING"

    approved = validate_success(
        api.review_permit_application(
            permit["id"],
            permit_review_payload("APPROVED", decision_note="approved as filed"),
            headers=reviewer_headers,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == USER_IDS["authority_reviewer"]
    assert approved["deemed"] is False
    assert fx.read_segment(segment["id"])["permit_status"] == "CLEARED"


def test_the_budget_and_the_clock_belong_to_the_records_administrator_alone(
    api, engineer_headers, coordinator_headers, admin_headers
):
    """An engineer cannot self-fund and a coordinator cannot move time forward.

    PRD: "**`NetworkRecordsAdmin`** — maintains municipal moratorium records, route
    budget authorizations, and the server's logical clock."

    Design: Corner/rbac/records_admin_exclusive_writes_reject_every_other_role
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(
        headers=engineer_headers, **dict(_HARBOR_LOOP, budget_authorized_cents=1000000)
    )

    self_service = api.adjust_route_budget(
        route["id"],
        budget_adjustment_payload(500000, reason="engineer self-service"),
        headers=engineer_headers,
    )
    validate_error(self_service, "ERR_UNAUTHORIZED", 403)
    assert fx.read_route(route["id"])["budget_authorized_cents"] == 1000000

    time_travel = api.set_clock(clock_payload("2027-01-01T00:00:00Z"), headers=coordinator_headers)
    validate_error(time_travel, "ERR_UNAUTHORIZED", 403)

    still_now = validate_success(
        api.create_route(
            create_route_payload(**dict(_HARBOR_LOOP, name="Clock Probe")),
            headers=engineer_headers,
        ),
        201,
    )
    assert still_now["created_at"] == "2026-08-10T00:00:00Z", (
        "the refused clock move left the logical now where the admin had set it"
    )

    raised = validate_success(
        api.adjust_route_budget(
            route["id"],
            budget_adjustment_payload(500000, reason="supplemental authorization"),
            headers=admin_headers,
        )
    )
    assert raised["budget_authorized_cents"] == 1500000
    assert raised["budget_available_cents"] == 1500000
    assert raised["budget_committed_cents"] == 0
    assert raised["version"] == route["version"] + 1


def test_all_six_declared_roles_read_the_same_route_detail(api, engineer_headers):
    """Reads are shared even though every write is partitioned by role.

    PRD: "All six roles are authorized for every read operation in the system; write
    operations are partitioned as shown in the endpoint table of section 4."

    Design: Corner/rbac/every_declared_role_can_read_a_route_detail
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)

    readers = (
        TEST_USERS["route_engineer"],
        TEST_USERS["field_surveyor"],
        TEST_USERS["permit_coordinator"],
        TEST_USERS["authority_reviewer"],
        TEST_USERS["pole_owner"],
        TEST_USERS["network_records_admin"],
    )
    seen = []
    for headers in readers:
        read = validate_success(api.get_route(route["id"], headers=headers))
        seen.append(read)

    assert [row["status"] for row in seen] == ["PLANNING"] * 6
    assert {row["id"] for row in seen} == {route["id"]}
    assert {row["budget_authorized_cents"] for row in seen} == {250000000}
    assert {row["budget_available_cents"] for row in seen} == {250000000}


def test_a_missing_blank_or_undeclared_header_is_an_authentication_failure(
    api, engineer_headers
):
    """No id, an empty id and a role outside the six all collapse to one 401.

    PRD: "If either header is absent, is present but blank, or if `X-User-Role`
    holds a string that is not one of the six roles declared below, the request is
    rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/rbac/absent_user_id_header_and_undeclared_role_both_return_unauthenticated
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)

    no_id = api.get_route(route["id"], headers=headers_missing_user_id("RouteEngineer"))
    validate_error(no_id, "ERR_UNAUTHENTICATED", 401)

    blank_id = api.get_route(route["id"], headers=headers_blank_user_id("RouteEngineer"))
    validate_error(blank_id, "ERR_UNAUTHENTICATED", 401)

    blank_role = api.get_route(
        route["id"], headers=headers_blank_role(USER_IDS["route_engineer"])
    )
    validate_error(blank_role, "ERR_UNAUTHENTICATED", 401)

    undeclared = api.get_route(
        route["id"], headers=make_headers(USER_IDS["route_engineer"], "PLANT_MANAGER")
    )
    validate_error(undeclared, "ERR_UNAUTHENTICATED", 401)

    accepted = validate_success(api.get_route(route["id"], headers=engineer_headers))
    assert accepted["id"] == route["id"]


def test_the_owner_and_the_coordinator_cannot_take_each_others_steps(
    api, engineer_headers, coordinator_headers, owner_headers
):
    """The attachment workflow alternates between two peer roles, and neither may cross.

    PRD: "**`PoleOwner`** — acts for the utility that owns the poles, returning
    make-ready estimates, revision requests or denials."

    Design: Corner/rbac/pole_owner_and_permit_coordinator_cannot_take_each_others_steps
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    segment = fx.create_segment(route["id"], headers=engineer_headers, **_DOCK_STREET)
    fx.accepted_walkout(
        segment["id"],
        [_TELCO_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="one telco pole, grade B",
    )

    payload = create_pole_attachment_application_payload(
        segment["id"], pole_owner="TELCO", pole_count=4
    )
    owner_create = api.create_pole_attachment_application(payload, headers=owner_headers)
    validate_error(owner_create, "ERR_UNAUTHORIZED", 403)
    rows, _meta = validate_paginated(
        api.list_segment_pole_attachment_applications(segment["id"], headers=coordinator_headers)
    )
    assert rows == []

    application = validate_success(
        api.create_pole_attachment_application(payload, headers=coordinator_headers), 201
    )

    owner_submit = api.submit_pole_attachment_application(
        application["id"], headers=owner_headers
    )
    validate_error(owner_submit, "ERR_UNAUTHORIZED", 403)
    assert fx.read_pole_application(application["id"])["status"] == "DRAFT"
    assert fx.read_pole_application(application["id"])["submitted_at"] is None

    submitted = validate_success(
        api.submit_pole_attachment_application(application["id"], headers=coordinator_headers)
    )
    assert submitted["status"] == "SUBMITTED"

    items = [{"pole_tag": "P-001", "work_class": "TRANSFER", "quantity": 1}]
    coordinator_answer = api.respond_as_pole_owner(
        application["id"],
        owner_response_payload(
            "ESTIMATED", items, owner_note="coordinator answering for the owner"
        ),
        headers=coordinator_headers,
    )
    validate_error(coordinator_answer, "ERR_UNAUTHORIZED", 403)
    assert (
        validate_success(
            api.list_make_ready_items(application["id"], headers=coordinator_headers)
        )
        == []
    )

    estimated = validate_success(
        api.respond_as_pole_owner(
            application["id"],
            owner_response_payload("ESTIMATED", items, owner_note="one transfer"),
            headers=owner_headers,
        )
    )
    assert estimated["status"] == "MAKE_READY_ESTIMATED"
    assert estimated["make_ready_cost_cents"] == 47600
    assert estimated["revision_round"] == 0


def test_authentication_reports_before_the_addressed_route_is_even_looked_up(api):
    """A blank role against an id that does not exist is a 401, never a 404.

    PRD: "This check precedes every other check in the system, including whether the
    addressed resource exists."

    Design: Corner/validations/unauthenticated_request_for_a_missing_route_returns_401_and_not_404
    """
    fx.set_clock("2026-08-10T00:00:00Z")

    unauthenticated = api.get_route(
        NON_EXISTENT_UUID, headers=headers_blank_role(USER_IDS["route_engineer"])
    )
    validate_error(unauthenticated, "ERR_UNAUTHENTICATED", 401)
    assert "api_request_id" in unauthenticated.json()["meta"]
    assert "api_request_timestamp" in unauthenticated.json()["meta"]

    authenticated = api.get_route(
        NON_EXISTENT_UUID, headers=make_headers(USER_IDS["route_engineer"], "RouteEngineer")
    )
    validate_error(authenticated, "ERR_ROUTE_NOT_FOUND", 404)


def test_the_wrong_role_reports_before_the_malformed_body_is_inspected(
    api, engineer_headers, admin_headers
):
    """One request breaks the role rule and the shape rule, and the role rule wins.

    PRD: "This ordering is normative: a request that violates both a later and an
    earlier rule must report the **earlier** rule's error identifier."

    Design: Corner/validations/unauthorized_role_with_a_malformed_body_returns_403_and_not_400
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    malformed = drop(
        create_moratorium_window_payload(
            municipality_code="MUN-014",
            street_name="Slate Road",
            resurfaced_on="2026-08-30",
            starts_on="2026-09-01",
            ends_on="2026-10-31",
            moratorium_class="FULL_RESTORATION",
            surprise_field="unexpected",
        ),
        "ordinance_reference",
    )

    wrong_role = api.create_moratorium_window(malformed, headers=engineer_headers)
    validate_error(wrong_role, "ERR_UNAUTHORIZED", 403)

    right_role = api.create_moratorium_window(malformed, headers=admin_headers)
    validate_error(right_role, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(api.list_moratorium_windows(headers=admin_headers))
    assert rows == []
    assert meta["total_count"] == 0
