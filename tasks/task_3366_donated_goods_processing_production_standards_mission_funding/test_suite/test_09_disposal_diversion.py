"""Disposal costing, diversion-rate accounting, and the depth-3 cascade that
gates salvage-lot creation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_org_diversion_invariants,
    create_disposal_ticket,
    create_lot,
    create_org,
    create_site,
    create_sorted_items,
    get_org,
    make_member_admin_headers,
    sell_lot,
    sort_item_descriptor,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_org_at_diversion_boundary():
    """Org (floor 7500) with diverted exactly 300 lbs via a SOLD 300-lb bale,
    plus one spare 5-lb SALVAGED textile still unassigned to any lot."""
    org = create_org("Org Div", diversion_floor_bps=7500)
    site = create_site(org["id"], name="Site D")
    _donation, items = create_sorted_items(
        site["id"],
        [sort_item_descriptor(category="TEXTILES", condition_grade="UNSALABLE",
                              estimated_value_cents=0, weight_lbs=300.0),
         sort_item_descriptor(category="TEXTILES", condition_grade="UNSALABLE",
                              estimated_value_cents=0, weight_lbs=5.0)],
        donor_name="Donor D")
    bale = create_lot(org["id"], "TEXTILE_BALE", [items[0]["id"]])
    sell_lot(org["id"], bale["id"])
    spare = items[1]
    return org, spare


class TestDisposalCost:
    def test_disposal_cost_uses_per_material_rates(self, api):
        """PRD 3.6: "The ticket's `cost_cents` is the weight multiplied by the
        per-pound rate for its material — 9 cents for `MIXED_UNSALABLE`, 40 for
        `HAZARD`, and 15 for `FURNITURE` — rounded half-up to whole cents."
        PRD 3.6: "Recording the ticket adds its weight to `total_disposed_lbs`,
        which recomputes `diversion_rate_bps` and `diversion_compliant` — this
        is the depth-3 cascade that can flip an organization out of compliance
        and block its next salvage lot — and advances the org's `version` by
        one."

        Design: Corner/calculations/disposal_cost_uses_per_material_rates
        """
        org = create_org("Org DC", diversion_floor_bps=10000)
        hazard = create_disposal_ticket(org["id"], "HAZARD", 10)
        mixed = create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 10)
        assert hazard["cost_cents"] == 400, "10 * 40"
        assert mixed["cost_cents"] == 90, "10 * 9"
        org_after = get_org(org["id"])
        assert org_after["total_disposed_lbs"] == 20
        assert org_after["diversion_rate_bps"] == 0, "all disposal, no diversion"
        assert_org_diversion_invariants(org_after)

    def test_diversion_empty_denominator_defaults_fully_diverted(self, api):
        """PRD 2.9: "The `diversion_rate_bps` is the diverted share expressed
        in basis points: when the two totals sum to zero the rate is defined as
        10000; otherwise it is the floor of `total_diverted_lbs` multiplied by
        10000 and divided by the sum of the two totals."

        Design: Corner/calculations/diversion_empty_denominator_defaults_fully_diverted
        """
        org = create_org("Org Fresh", diversion_floor_bps=7500)
        reread = get_org(org["id"])
        assert reread["total_diverted_lbs"] == 0
        assert reread["total_disposed_lbs"] == 0
        assert reread["diversion_rate_bps"] == 10000
        assert reread["diversion_compliant"] is True


class TestDisposalCascadeBreachGate:
    def test_disposal_ticket_drives_rate_below_floor(self, api):
        """PRD 2.9: "For example, with 300 pounds diverted and 100 disposed the
        rate floors to 7500 basis points, compliant against a floor of 7500; a
        single additional disposed pound drops it to 7481 and breaks
        compliance."
        PRD 2.9: "An organization is `diversion_compliant` — a boolean
        recomputed whenever either total changes — exactly when its
        `diversion_rate_bps` is at least its configured `diversion_floor_bps`,
        with the boundary inclusive: an organization whose rate lands exactly
        on its floor remains compliant."

        Design: Difficulty/transitive_cascade/disposal_ticket_diversion_breach_gate
        """
        org, _spare = _setup_org_at_diversion_boundary()
        create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 100)
        at_floor = get_org(org["id"])
        assert at_floor["total_disposed_lbs"] == 100
        assert at_floor["diversion_rate_bps"] == 7500, "floor(3000000/400)"
        assert at_floor["diversion_compliant"] is True

        create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 1)
        breached = get_org(org["id"])
        assert breached["total_disposed_lbs"] == 101
        assert breached["diversion_rate_bps"] == 7481, "floor(3000000/401)"
        assert breached["diversion_compliant"] is False, (
            "derived flag flips with no direct write to it")

    def test_non_compliant_org_cannot_open_salvage_lot(self, api):
        """PRD 2.9: "Only an organization that is currently
        `diversion_compliant` may open a new salvage lot; the attempt is
        otherwise rejected with `ERR_DIVERSION_BREACH` (HTTP 409)."
        PRD 3.6: "Recording the ticket adds its weight to `total_disposed_lbs`,
        which recomputes `diversion_rate_bps` and `diversion_compliant` — this
        is the depth-3 cascade that can flip an organization out of compliance
        and block its next salvage lot — and advances the org's `version` by
        one."

        Design: Difficulty/transitive_cascade/disposal_ticket_diversion_breach_gate
        """
        org, spare = _setup_org_at_diversion_boundary()
        create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 100)
        create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 1)
        assert get_org(org["id"])["diversion_compliant"] is False
        resp = api_client.create_salvage_lot(
            {"member_org_id": org["id"], "channel": "OUTLET_BIN",
             "item_ids": [spare["id"]]},
            make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_DIVERSION_BREACH)


class TestDiversionFloorInclusiveBoundary:
    def test_rate_landing_exactly_on_floor_stays_compliant(self, api):
        """PRD 2.9: "An organization is `diversion_compliant` — a boolean
        recomputed whenever either total changes — exactly when its
        `diversion_rate_bps` is at least its configured `diversion_floor_bps`,
        with the boundary inclusive: an organization whose rate lands exactly
        on its floor remains compliant."
        PRD 2.9: "For example, with 300 pounds diverted and 100 disposed the
        rate floors to 7500 basis points, compliant against a floor of 7500; a
        single additional disposed pound drops it to 7481 and breaks
        compliance."

        Design: Difficulty/boundary_precision_check/diversion_floor_inclusive_boundary
        """
        org, _spare = _setup_org_at_diversion_boundary()
        create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 100)
        org_after = get_org(org["id"])
        assert org_after["diversion_rate_bps"] == 7500, "floor(3000000/400)"
        assert org_after["diversion_compliant"] is True, (
            "the floor comparison is >=, not >")

    def test_lot_creation_allowed_at_exact_floor(self, api):
        """PRD 2.9: "Only an organization that is currently
        `diversion_compliant` may open a new salvage lot; the attempt is
        otherwise rejected with `ERR_DIVERSION_BREACH` (HTTP 409)."
        PRD 2.9: "For example, with 300 pounds diverted and 100 disposed the
        rate floors to 7500 basis points, compliant against a floor of 7500; a
        single additional disposed pound drops it to 7481 and breaks
        compliance."

        Design: Difficulty/boundary_precision_check/diversion_floor_inclusive_boundary
        """
        org, spare = _setup_org_at_diversion_boundary()
        create_disposal_ticket(org["id"], "MIXED_UNSALABLE", 100)
        resp = api_client.create_salvage_lot(
            {"member_org_id": org["id"], "channel": "OUTLET_BIN",
             "item_ids": [spare["id"]]},
            make_member_admin_headers(org["id"]))
        lot = validate_success(resp, 201)
        assert lot["status"] == "OPEN"
        assert lot["total_weight_lbs"] == 5.0
