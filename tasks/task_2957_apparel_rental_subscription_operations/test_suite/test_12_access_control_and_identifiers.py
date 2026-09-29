"""The authentication ladder, the role matrix, ownership and the 404 vocabulary.

Covers the four rungs that run before any business rule — missing or unknown
role headers, unresolved entity-backed actors, endpoint permission and resource
ownership — together with the two identifier-resolution rungs and their
per-family not-found codes, both for path identifiers and for body foreign keys.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_FEE_ENTRY_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_JOB_NOT_FOUND,
    ERR_LISTING_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_MISSING_AUTH_HEADERS,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PLAN_NOT_FOUND,
    ERR_RENTAL_UNIT_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_STALE_UNIT_VERSION,
    ERR_STYLE_NOT_FOUND,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_fields,
    assert_list,
    assert_null,
    assert_ok,
)
from test_helpers.fixtures import Scenario, standard_catalog
from test_helpers.test_users import (
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_undeclared_role,
    make_member_headers,
    make_warehouse_tech_headers,
)


def test_every_path_identifier_family_answers_with_its_own_not_found_code(
    scenario: Scenario,
) -> None:
    """Twelve reads against an empty database return twelve different 404 codes.

    PRD §2.5: "Rank 6 resolves path identifiers. Nested paths are validated **strictly left to right**, so the outermost identifier is resolved before the one nested inside it and the client always learns about the outermost failure first. The identifiers are `plan_id` for a membership plan, `technician_id` for a technician, `style_id` for a style, `unit_id` for a rental unit, `member_id` for a member, `reservation_id` for a reservation, `shipment_id` for a shipment leg, `job_id` for a reverse-logistics job, `inspection_id` for an inspection record, `claim_id` for a damage claim, `listing_id` for a resale listing, `entry_id` for a fee-ledger entry and `feedback_id` for a fit-feedback record. An unresolvable identifier yields 404 with the error matching the missing resource kind: `ERR_PLAN_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_STYLE_NOT_FOUND`, `ERR_RENTAL_UNIT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LISTING_NOT_FOUND` or `ERR_FEE_ENTRY_NOT_FOUND`."

    Design: Corner/errors/errors_every_path_id_family_returns_its_own_not_found_code
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    client = scenario.client
    admin = scenario.admin
    ghost = K.UNKNOWN_UUID

    # One syntactically valid identifier that the server has never minted, sent
    # to every single-resource read the service exposes.
    cases = (
        (client.get_membership_plan(ghost, admin), ERR_PLAN_NOT_FOUND),
        (client.get_technician(ghost, admin), ERR_TECHNICIAN_NOT_FOUND),
        (client.get_style(ghost, admin), ERR_STYLE_NOT_FOUND),
        (client.get_rental_unit(ghost, admin), ERR_RENTAL_UNIT_NOT_FOUND),
        (client.get_member(ghost, admin), ERR_MEMBER_NOT_FOUND),
        (client.get_reservation(ghost, admin), ERR_RESERVATION_NOT_FOUND),
        (client.get_shipment(ghost, admin), ERR_SHIPMENT_NOT_FOUND),
        (client.get_job(ghost, admin), ERR_JOB_NOT_FOUND),
        (client.get_inspection(ghost, admin), ERR_INSPECTION_NOT_FOUND),
        (client.get_damage_claim(ghost, admin), ERR_CLAIM_NOT_FOUND),
        (client.get_resale_listing(ghost, admin), ERR_LISTING_NOT_FOUND),
        (client.get_fee_ledger_entry(ghost, admin), ERR_FEE_ENTRY_NOT_FOUND),
    )

    for response, expected in cases:
        assert_error(response, expected)

    # A single shared code for every family would satisfy eleven of the twelve
    # assertions above by accident, so pin the vocabulary size too.
    assert len({expected for _response, expected in cases}) == 12


def test_an_unresolvable_body_foreign_key_names_the_referenced_family(
    scenario: Scenario,
) -> None:
    """A bad plan id on enrolment is a plan 404, not a member 404 or a 412.

    PRD §2.5: "Rank 7 resolves foreign keys supplied in a request body, with the same 404 vocabulary. The body-borne references this covers are `membership_plan_id`, `style_id`, `reservation_id`, `rental_unit_id`, `preferred_unit_id` and `supersedes_listing_id`; a `preferred_unit_id` that does not name an existing rental unit yields `ERR_RENTAL_UNIT_NOT_FOUND`, and a `supersedes_listing_id` that does not name an existing listing yields `ERR_LISTING_NOT_FOUND`."
    PRD §5: "Every failing request returns the error envelope of §2.2 with one of the identifiers below in `data.error_id`, and the identifier is chosen by the first rule that fails in the evaluation order of §2.5. Where two candidate identifiers could describe the same request, the lower-ranked rule wins."

    Design: Corner/errors/errors_unresolvable_body_foreign_keys_report_the_referenced_family
    """
    catalog = standard_catalog(scenario)
    client = scenario.client
    member_headers = Scenario.member_headers(catalog.member)
    ghost = K.UNKNOWN_UUID

    scenario.retire_unit(catalog.unit["id"], K.RETIREMENT_PLANNED_REFRESH)
    unit_version = scenario.read_unit(catalog.unit["id"])["version"]

    # The family named is the family of the failed reference, not the family of
    # the resource the call was trying to create.
    assert_error(
        client.create_member(
            F.member_payload(ghost, K.MEMBER_PRIYA_NAME, K.MEMBER_PRIYA_EMAIL),
            scenario.admin,
        ),
        ERR_PLAN_NOT_FOUND,
    )
    assert_error(
        client.create_reservation(
            F.reservation_payload(ghost, K.SIZE_M, *K.WINDOW_AUG_05_09),
            member_headers,
        ),
        ERR_STYLE_NOT_FOUND,
    )
    assert_error(
        client.create_reservation(
            F.reservation_payload(
                catalog.style_id, K.SIZE_M, *K.WINDOW_AUG_05_09, preferred_unit_id=ghost
            ),
            member_headers,
        ),
        ERR_RENTAL_UNIT_NOT_FOUND,
    )
    assert_error(
        client.create_shipment(
            F.outbound_shipment_payload(ghost, K.SHIP_DATE_AUG_05), scenario.admin
        ),
        ERR_RESERVATION_NOT_FOUND,
    )

    # Rank 7 runs ahead of the rank-13 concurrency token, so an unresolvable
    # unit is a 404 even though the supplied version could never match.
    refused_unit = assert_error(
        client.create_resale_listing(
            F.resale_listing_payload(ghost, unit_version, K.CHANNEL_OUTLET),
            scenario.planner,
        ),
        ERR_RENTAL_UNIT_NOT_FOUND,
    )
    assert refused_unit["error_id"] != ERR_STALE_UNIT_VERSION
    assert_error(
        client.create_resale_listing(
            F.resale_listing_payload(
                catalog.unit["id"],
                unit_version,
                K.CHANNEL_OUTLET,
                supersedes_listing_id=ghost,
            ),
            scenario.planner,
        ),
        ERR_LISTING_NOT_FOUND,
    )

    # Every one of those calls was a refusal, so nothing was written.
    assert_list(client.list_members(scenario.admin), total_count=1)
    assert_list(client.list_reservations(member_headers), total_count=0)
    assert_list(client.list_resale_listings(scenario.planner), total_count=0)


def test_a_blank_role_header_and_an_undeclared_role_are_both_refused(
    scenario: Scenario,
) -> None:
    """An empty-string header fails at rank 1 and StyleCurator fails at rank 2.

    PRD §2.1: "Every request to every endpoint, including read-only ones, must carry two headers: `X-User-ID`, identifying the actor, and `X-User-Role`, naming the capability set the actor is claiming. If either header is absent or empty, the request fails at the very first rung of the validation ladder (rank 1) with `ERR_MISSING_AUTH_HEADERS`. If `X-User-Role` is present but is not one of the five declared roles, the request fails at rank 2 with `ERR_UNKNOWN_ROLE`. Both of these are 401 responses."
    PRD §4: "| GET | `/members/{member_id}` | Read one member with computed balance, slot and risk fields | Member, ClaimsAdjuster, PlatformAdmin |"

    Design: Corner/rbac/rbac_blank_and_unknown_role_headers_must_not_be_accepted
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    plan = scenario.create_plan()
    member = scenario.enrol_member(plan["id"])
    member_id = member["id"]
    client = scenario.client

    # The role header is present and its value is the empty JSON string, not a
    # whitespace-padded value, and the actor header names a real member.
    assert_error(
        client.get_member(member_id, headers_with_blank_role(member_id)),
        ERR_MISSING_AUTH_HEADERS,
    )
    # The same rung catches an empty actor header under a declared role.
    assert_error(
        client.get_member(member_id, headers_with_blank_user_id(K.ROLE_MEMBER)),
        ERR_MISSING_AUTH_HEADERS,
    )
    # StyleCurator sounds like a capability set this service might own, but the
    # matrix declares five roles and that is not one of them.
    assert_error(
        client.get_member(member_id, headers_with_undeclared_role(member_id)),
        ERR_UNKNOWN_ROLE,
    )

    # The identical read with a well-formed header pair is permitted, so the
    # three refusals above were about the headers and nothing else.
    read = assert_ok(client.get_member(member_id, make_member_headers(member_id)))
    assert_fields(read, id=member_id, status=K.MEMBER_ACTIVE)


def test_an_unknown_actor_id_is_refused_for_both_entity_backed_roles(
    scenario: Scenario,
) -> None:
    """Member and WarehouseTech resolve their actor against different tables.

    PRD §2.1: "For both of these roles, an `X-User-ID` that does not resolve to an existing `Member` row or `Technician` row respectively is rejected at rank 3 with `ERR_ACTOR_NOT_FOUND` (401), before any permission check runs."
    PRD §5: "Every failing request returns the error envelope of §2.2 with one of the identifiers below in `data.error_id`, and the identifier is chosen by the first rule that fails in the evaluation order of §2.5. Where two candidate identifiers could describe the same request, the lower-ranked rule wins."
    PRD §4: "| GET | `/technicians/{technician_id}` | Read one technician | WarehouseTech, ClaimsAdjuster, PlatformAdmin |"

    Design: Corner/rbac/rbac_unknown_actor_ids_must_not_be_accepted_for_entity_backed_roles
    """
    catalog = standard_catalog(scenario)
    client = scenario.client
    inspector_id = catalog.inspector["id"]

    assert_error(
        client.get_member(catalog.member_id, make_member_headers(K.UNKNOWN_UUID)),
        ERR_ACTOR_NOT_FOUND,
    )
    assert_error(
        client.get_technician(inspector_id, make_warehouse_tech_headers(K.UNKNOWN_UUID)),
        ERR_ACTOR_NOT_FOUND,
    )

    # Rank 3 is below rank 6, so an unknown actor is reported even when the path
    # identifier is unresolvable too and would otherwise produce its own 404.
    assert_error(
        client.get_member(K.SECOND_UNKNOWN_UUID, make_member_headers(K.UNKNOWN_UUID)),
        ERR_ACTOR_NOT_FOUND,
    )

    # Each role resolves its actor against its own table: a real technician id is
    # not a member, and a real member id is not a technician.
    assert_error(
        client.get_member(catalog.member_id, make_member_headers(inspector_id)),
        ERR_ACTOR_NOT_FOUND,
    )
    assert_error(
        client.get_technician(inspector_id, make_warehouse_tech_headers(catalog.member_id)),
        ERR_ACTOR_NOT_FOUND,
    )

    # The technician's own id resolves, so the same read succeeds.
    read = assert_ok(
        client.get_technician(inspector_id, make_warehouse_tech_headers(inspector_id))
    )
    assert_fields(read, id=inspector_id, employee_code=K.TECH_INSPECTOR_CODE)


def test_neither_the_member_nor_the_admin_may_reach_the_other_role_endpoints(
    scenario: Scenario,
) -> None:
    """Merchandising is closed to the member and reserving is closed to the admin.

    PRD §2.1: "Permission itself is checked at rank 4: if the acting role does not appear in the authorized-role list for the endpoint being called (see §4), the response is `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §4: "| POST | `/styles` | Acquire a style into the rental catalog with its depth plan inputs | InventoryPlanner |"
    PRD §4: "| POST | `/reservations` | Member requests a style for a rental window; the server matches a physically available unit or waitlists the request | Member |"

    Design: Corner/rbac/rbac_each_role_cannot_reach_another_role_exclusive_operation
    """
    catalog = standard_catalog(scenario)
    client = scenario.client
    member_headers = Scenario.member_headers(catalog.member)
    style_body = F.dress_style_payload()
    reservation_body = F.reservation_payload(
        catalog.style_id, K.SIZE_M, *K.WINDOW_AUG_05_09
    )

    assert_error(client.create_style(style_body, member_headers), ERR_ROLE_NOT_PERMITTED)
    # The five roles are peers: the most privileged role of the five still may
    # not raise subscription demand on a member's behalf.
    assert_error(
        client.create_reservation(reservation_body, scenario.admin),
        ERR_ROLE_NOT_PERMITTED,
    )

    assert_list(client.list_styles(scenario.planner), total_count=1)
    assert_list(client.list_reservations(scenario.admin), total_count=0)

    # The identical bodies succeed for the two authorized roles, so the refusals
    # were about the acting role and not about the payloads.
    assert_created(client.create_style(style_body, scenario.planner))
    assert_created(client.create_reservation(reservation_body, member_headers))


def test_the_technician_and_the_adjuster_cannot_reach_the_provisioning_endpoints(
    scenario: Scenario,
) -> None:
    """Plan creation is admin-only and fleet build-out is planner-only.

    PRD §2.1: "Permission itself is checked at rank 4: if the acting role does not appear in the authorized-role list for the endpoint being called (see §4), the response is `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §4: "| POST | `/membership-plans` | Create a membership plan tier | PlatformAdmin |"
    PRD §4: "| POST | `/styles/{style_id}/rental-units` | Add a physical rental unit to a style's depth | InventoryPlanner |"

    Design: Corner/rbac/rbac_each_role_cannot_reach_another_role_exclusive_operation
    """
    catalog = standard_catalog(scenario)
    client = scenario.client
    tech_headers = Scenario.tech_headers(catalog.inspector)
    plan_body = F.solo1_plan_payload()
    unit_body = F.rental_unit_payload(K.UNIT_GOWN_002, K.SIZE_M)

    assert_error(
        client.create_membership_plan(plan_body, tech_headers), ERR_ROLE_NOT_PERMITTED
    )
    assert_error(
        client.create_rental_unit(catalog.style_id, unit_body, scenario.adjuster),
        ERR_ROLE_NOT_PERMITTED,
    )

    assert_list(client.list_membership_plans(scenario.admin), total_count=1)
    assert_list(client.list_rental_units(scenario.planner), total_count=1)

    assert_created(client.create_membership_plan(plan_body, scenario.admin))
    assert_created(client.create_rental_unit(catalog.style_id, unit_body, scenario.planner))


def test_the_planner_cannot_enroll_a_member(scenario: Scenario) -> None:
    """Enrolment stays with the admin even for the role that owns the assets.

    PRD §2.1: "Permission itself is checked at rank 4: if the acting role does not appear in the authorized-role list for the endpoint being called (see §4), the response is `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §4: "| POST | `/members` | Enroll a member on a plan | PlatformAdmin |"

    Design: Corner/rbac/rbac_each_role_cannot_reach_another_role_exclusive_operation
    """
    catalog = standard_catalog(scenario)
    client = scenario.client
    member_body = F.member_payload(
        catalog.plan["id"], K.MEMBER_ILSE_NAME, K.MEMBER_ILSE_EMAIL
    )

    assert_error(
        client.create_member(member_body, scenario.planner), ERR_ROLE_NOT_PERMITTED
    )
    assert_list(client.list_members(scenario.admin), total_count=1)

    assert_created(client.create_member(member_body, scenario.admin))
    assert_list(client.list_members(scenario.admin), total_count=2)


def test_one_member_cannot_read_another_members_reservation(scenario: Scenario) -> None:
    """Two peers on the same plan and the same role, and only the owner may read.

    PRD §2.1: "Ownership is checked immediately afterwards at rank 5, and applies to every endpoint a `Member` may call: a `Member` may read or mutate only those members, reservations, shipments belonging to their own reservations, damage claims, fit-feedback records and fee-ledger entries whose owning member is themselves. A `Member` acting on another member's resource receives `ERR_NOT_RESOURCE_OWNER` (403)."
    PRD §3.4: "When a unit is selected, the reservation resolves `REQUESTED → MATCHED`, stamping `allocated_unit_id` with the chosen unit and `matched_at` with the current logical clock instant."

    Design: Corner/rbac/rbac_member_cannot_read_another_member_resources
    """
    catalog = standard_catalog(scenario)
    client = scenario.client
    nora_headers = Scenario.member_headers(catalog.member)

    # A second subscriber on the same plan, with her own distinct actor id.
    ilse = scenario.enrol_member(
        catalog.plan["id"], full_name=K.MEMBER_ILSE_NAME, email=K.MEMBER_ILSE_EMAIL
    )
    ilse_headers = Scenario.member_headers(ilse)
    assert ilse["id"] != catalog.member_id

    reservation = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )

    # Same role, different owner: this is an ownership failure, not a role one.
    assert_error(
        client.get_reservation(reservation["id"], ilse_headers), ERR_NOT_RESOURCE_OWNER
    )
    assert_error(
        client.get_member(catalog.member_id, ilse_headers), ERR_NOT_RESOURCE_OWNER
    )

    owner_read = assert_ok(client.get_reservation(reservation["id"], nora_headers))
    assert_fields(
        owner_read,
        id=reservation["id"],
        member_id=catalog.member_id,
        state=K.RES_MATCHED,
        allocated_unit_id=catalog.unit["id"],
    )

    # Ilse's own member record is hers to read, so the two refusals above were
    # about whose resource it was.
    own_read = assert_ok(client.get_member(ilse["id"], ilse_headers))
    assert_fields(own_read, id=ilse["id"])


def test_release_is_shared_between_the_owning_member_and_the_admin(
    scenario: Scenario,
) -> None:
    """The same endpoint accepts two roles and produces the identical cascade.

    PRD §4: "| POST | `/reservations/{reservation_id}/release` | Member gives up a reservation before dispatch | Member, PlatformAdmin |"
    PRD §3.4: "A member (or a `PlatformAdmin` acting for them) may abandon a reservation before it is dispatched, and the effect depends on which of the two pre-dispatch states it is in. A `MATCHED` reservation moves `MATCHED → RELEASED`; as a second hop its allocated unit moves `RESERVED → IN_STOCK` and the reservation's `allocated_unit_id` is set back to null; as a third hop the rank-1 `WAITLISTED` reservation for the freed unit's style and size is promoted `WAITLISTED → MATCHED` if one exists; and the member's `units_out_count` is recomputed while their `version` is bumped by 1."

    Design: Corner/rbac/rbac_shared_release_operation_works_for_the_member_and_for_the_admin
    """
    catalog = standard_catalog(scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002))
    client = scenario.client
    member_headers = Scenario.member_headers(catalog.member)

    first = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_05_09
    )
    second = scenario.create_reservation(
        catalog.member, catalog.style_id, K.WINDOW_AUG_20_24
    )
    # A RESERVED garment is not a candidate again, so the two turns hold two
    # different units and each release frees exactly one of them.
    assert first["allocated_unit_id"] != second["allocated_unit_id"]

    by_member = assert_ok(client.release_reservation(first["id"], member_headers))
    assert_fields(by_member, id=first["id"], state=K.RES_RELEASED)
    assert_null(by_member, "allocated_unit_id")

    by_admin = assert_ok(client.release_reservation(second["id"], scenario.admin))
    assert_fields(by_admin, id=second["id"], state=K.RES_RELEASED)
    assert_null(by_admin, "allocated_unit_id")

    # Identical effects from the two roles: both garments are back on the floor.
    for unit_id in (first["allocated_unit_id"], second["allocated_unit_id"]):
        assert_fields(
            scenario.read_unit(unit_id),
            availability_state=K.AVAIL_IN_STOCK,
            condition_state=K.COND_FLOOR_READY,
        )
