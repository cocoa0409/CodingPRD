"""Service tickets: parallel state dimensions, the recall loop, the allergen
gate, the published-menu gate, modification policy, and void RBAC."""

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_menu_revision_with_recipes,
    create_service_ticket_payload,
    make_kitchen_manager_headers, make_line_cook_headers, menu_admin_headers,
)


def _published_menu_env(api, recipe_specs, station_type="GRILL"):
    """Restaurant + manager + line cook + published revision with the given
    recipe specs."""
    set_clock("2026-09-01T00:00:00Z")
    rest = create_restaurant()
    mgr = create_manager(rest["id"], certified_station_types=[station_type])
    line = create_cook(rest["id"], mgr["id"], name="Leo Line",
                       certified_station_types=[station_type])
    item = create_prep_item(name="Butter", station_type=station_type,
                            shelf_life_hours=48, min_batch_size=1,
                            batch_unit="EA")
    specs = []
    for spec in recipe_specs:
        full = {"name": spec["name"], "station_type": station_type,
                "components": [{"prep_item_id": item["id"],
                                "quantity_per_portion": 1, "unit": "EA"}]}
        for key in ("allergen_tags", "modification_policy"):
            if key in spec:
                full[key] = spec[key]
        specs.append(full)
    revision, recipes = create_menu_revision_with_recipes(
        rest["id"], specs, label="V1",
        effective_from="2026-09-15T00:00:00Z", publish=True)
    return {
        "rest": rest,
        "mh": make_kitchen_manager_headers(mgr["id"]),
        "lch": make_line_cook_headers(line["id"]),
        "line": line,
        "mgr": mgr,
        "item": item,
        "revision": revision,
        "recipes": recipes,
    }


def _open_ticket(api, env, recipe, modifications=None, allergen_flags=None):
    return validate_success(api.create_service_ticket(
        create_service_ticket_payload(
            env["rest"]["id"],
            [{"recipe_id": recipe["id"],
              "modifications": modifications or [],
              "allergen_flags": allergen_flags or []}]),
        env["lch"]), 201)


class TestParallelDimensionsAndRecallLoop:
    def _allergen_ticket(self, api):
        env = _published_menu_env(
            api, [{"name": "Butter Steak", "allergen_tags": ["DAIRY"],
                   "modification_policy": "ALLOWED"}])
        ticket = _open_ticket(api, env, env["recipes"]["Butter Steak"],
                              allergen_flags=["DAIRY"])
        return env, ticket

    def test_allergen_pending_blocks_fire_until_cleared(self, api):
        """PRD section 3.8: "The allergen dimension is initialized from the
        ticket's content — `allergen_review_status` starts at `PENDING` if
        any item's `allergen_flags` intersect its recipe's `allergen_tags`,
        and at `NOT_REQUIRED` otherwise."
        PRD section 3.8: "Firing a ticket moves its `fire_status` from `OPEN`
        to `FIRED` and enforces the allergen gate: the fire is rejected with
        `ERR_TICKET_INVALID_STATE` if the ticket is not `OPEN`, and with
        `ERR_ALLERGEN_REVIEW_REQUIRED` if its `allergen_review_status` is
        still `PENDING`."

        Design: Difficulty/non_linear_state_machine/service_ticket_parallel_dimensions_and_recall_loop
        """
        env, ticket = self._allergen_ticket(api)
        assert ticket["allergen_review_status"] == "PENDING"
        assert ticket["fire_status"] == "OPEN"
        resp = api.fire_ticket(ticket["id"], env["lch"])
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_REVIEW_REQUIRED, 422)
        blocked = validate_success(api.get_service_ticket(ticket["id"],
                                                          env["lch"]))
        assert blocked["fire_status"] == "OPEN"
        cleared = validate_success(api.clear_allergen_review(ticket["id"],
                                                             env["mh"]))
        assert cleared["allergen_review_status"] == "CLEARED"
        assert cleared["fire_status"] == "OPEN"
        fired = validate_success(api.fire_ticket(ticket["id"], env["lch"]))
        assert fired["fire_status"] == "FIRED"

    def test_recall_loop_increments_count_and_serves(self, api):
        """PRD section 3.8: "A ticket in `READY` may be recalled, which
        returns it to `FIRED` and increments its `recall_count` by one, or
        served, which moves it to the terminal `SERVED`; both require the
        `READY` state and reject anything else with `ERR_TICKET_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/service_ticket_parallel_dimensions_and_recall_loop
        """
        env, ticket = self._allergen_ticket(api)
        validate_success(api.clear_allergen_review(ticket["id"], env["mh"]))
        validate_success(api.fire_ticket(ticket["id"], env["lch"]))
        validate_success(api.mark_ticket_ready(ticket["id"], env["lch"]))
        recalled = validate_success(api.recall_ticket(ticket["id"], env["lch"]))
        assert recalled["fire_status"] == "FIRED"
        assert recalled["recall_count"] == 1
        validate_success(api.mark_ticket_ready(ticket["id"], env["lch"]))
        served = validate_success(api.serve_ticket(ticket["id"], env["lch"]))
        assert served["fire_status"] == "SERVED"


class TestTicketRequiresPublishedMenu:
    def test_recipe_from_unpublished_revision_rejected(self, api):
        """PRD section 3.8: "Every recipe referenced must belong to the
        restaurant's latest published menu revision; referencing a recipe
        from a superseded or unpublished menu is rejected with
        `ERR_RECIPE_NOT_ON_PUBLISHED_MENU`."

        Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_published_menu_revision
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        line = create_cook(rest["id"], mgr["id"], name="Leo Line",
                           certified_station_types=["GRILL"])
        lch = make_line_cook_headers(line["id"])
        item = create_prep_item(name="Butter", station_type="GRILL",
                                shelf_life_hours=48, min_batch_size=1,
                                batch_unit="EA")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "Steak", "station_type": "GRILL",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 1, "unit": "EA"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z")
        # APPROVED but never published.
        get_resp = api.submit_review(revision["id"], menu_admin_headers())
        assert get_resp.status_code == 200
        approve_resp = api.approve_revision(revision["id"], menu_admin_headers())
        assert approve_resp.status_code == 200
        resp = api.create_service_ticket(
            create_service_ticket_payload(
                rest["id"],
                [{"recipe_id": recipes["Steak"]["id"], "modifications": [],
                  "allergen_flags": []}]), lch)
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_ON_PUBLISHED_MENU, 409)
        data, meta = validate_paginated(api.list_service_tickets(
            lch, params={"restaurant_id": rest["id"]}))
        assert data == []
        assert meta["total_count"] == 0

    def test_recipe_from_draft_revision_rejected(self, api):
        """PRD section 3.8: "Every recipe referenced must belong to the
        restaurant's latest published menu revision; referencing a recipe
        from a superseded or unpublished menu is rejected with
        `ERR_RECIPE_NOT_ON_PUBLISHED_MENU`."

        Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_published_menu_revision
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["GRILL"])
        line = create_cook(rest["id"], mgr["id"], name="Leo Line",
                           certified_station_types=["GRILL"])
        lch = make_line_cook_headers(line["id"])
        item = create_prep_item(name="Butter", station_type="GRILL",
                                shelf_life_hours=48, min_batch_size=1,
                                batch_unit="EA")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "Steak", "station_type": "GRILL",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 1, "unit": "EA"}]}],
            label="V1", effective_from="2026-09-15T00:00:00Z")
        resp = api.create_service_ticket(
            create_service_ticket_payload(
                rest["id"],
                [{"recipe_id": recipes["Steak"]["id"], "modifications": [],
                  "allergen_flags": []}]), lch)
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_ON_PUBLISHED_MENU, 409)


class TestModificationPolicyGate:
    def test_forbidden_recipe_rejects_modifications_allowed_accepts(self, api):
        """PRD section 3.8: "The modification policy is enforced at creation:
        if any item carries a non-empty `modifications` list for a recipe
        whose `modification_policy` is `FORBIDDEN`, the ticket is rejected
        with `ERR_TICKET_MODIFICATION_FORBIDDEN`. The allergen dimension is
        initialized from the ticket's content — `allergen_review_status`
        starts at `PENDING` if any item's `allergen_flags` intersect its
        recipe's `allergen_tags`, and at `NOT_REQUIRED` otherwise."

        Design: Corner/validations/ticket_modification_forbidden_policy_rejected
        """
        env = _published_menu_env(
            api, [{"name": "F", "modification_policy": "FORBIDDEN"},
                  {"name": "A", "modification_policy": "ALLOWED"}])
        resp = api.create_service_ticket(
            create_service_ticket_payload(
                env["rest"]["id"],
                [{"recipe_id": env["recipes"]["F"]["id"],
                  "modifications": ["no salt"], "allergen_flags": []}]),
            env["lch"])
        validate_error(resp, ApiErrorId.ERR_TICKET_MODIFICATION_FORBIDDEN, 422)
        ok = validate_success(api.create_service_ticket(
            create_service_ticket_payload(
                env["rest"]["id"],
                [{"recipe_id": env["recipes"]["A"]["id"],
                  "modifications": ["no salt"], "allergen_flags": []}]),
            env["lch"]), 201)
        assert ok["allergen_review_status"] == "NOT_REQUIRED"


class TestLineCookCannotVoid:
    def test_line_cook_void_denied_manager_succeeds(self, api):
        """PRD section 2.1: "A request whose role is not in the endpoint's
        authorized role list is rejected with `ERR_FORBIDDEN`."
        PRD section 3.8: "A `KitchenManager` may void a ticket from `OPEN`,
        `FIRED`, or `READY`, landing it in the terminal `VOIDED`; any other
        fire state is again `ERR_TICKET_INVALID_STATE`."

        Design: Corner/rbac/line_cook_cannot_void_ticket
        """
        env = _published_menu_env(api, [{"name": "R"}])
        ticket = _open_ticket(api, env, env["recipes"]["R"])
        resp = api.void_ticket(ticket["id"], env["lch"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        now = validate_success(api.get_service_ticket(ticket["id"],
                                                      env["lch"]))
        assert now["fire_status"] == "OPEN"
        voided = validate_success(api.void_ticket(ticket["id"], env["mh"]))
        assert voided["fire_status"] == "VOIDED"
