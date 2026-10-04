"""Cross-entity state dependencies: project creation reads the teacher's
employment row, and shipping a purchase order reads the vendor's status row."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_instant,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.constants import BASE_CLOCK
from test_helpers.test_users import make_teacher_headers, make_vendor_headers


# ── Project creation requires a VERIFIED teacher ───────────────────────────


def test_pending_verification_teacher_cannot_create_a_project(api):
    """The create gate reads the acting teacher's employment_status.

    PRD: "A new teacher's `employment_status` is `PENDING_VERIFICATION`, and in that state they cannot create or submit a project — the attempt fails with `ERR_TEACHER_NOT_VERIFIED`."
    Design: Difficulty/cross_entity_state_dependency/project_creation_requires_verified_employment
    """
    world = fixtures.seed_school_teacher(api, verify=False)
    teacher = world["teacher"]
    assert teacher["employment_status"] == "PENDING_VERIFICATION"

    res = api.create_project(f.project_payload(), make_teacher_headers(teacher["id"]))
    validate_error(res, ApiErrorId.ERR_TEACHER_NOT_VERIFIED, 409)

    reread = fixtures.read_teacher(api, teacher["id"])
    assert reread["employment_status"] == "PENDING_VERIFICATION"
    assert fixtures.projects_for_teacher(api, teacher["id"]) == []


def test_verify_action_unlocks_project_creation(api):
    """Employment review flips the teacher to VERIFIED and opens the gate.

    PRD: "A `PlatformAdmin` resolves employment through a review action: `action` value `VERIFY` moves a `PENDING_VERIFICATION` teacher to `VERIFIED` (any other starting state fails with `ERR_INVALID_STATE`)"
    PRD: "Creation is gated: the teacher must be `VERIFIED` (not `PENDING_VERIFICATION`, not `SUSPENDED`)"
    Design: Difficulty/cross_entity_state_dependency/project_creation_requires_verified_employment
    """
    world = fixtures.seed_school_teacher(api, verify=False)
    teacher = world["teacher"]

    reviewed = fixtures.verify_teacher(api, teacher["id"])
    assert reviewed["employment_status"] == "VERIFIED"

    created = validate_success(
        api.create_project(f.project_payload(), make_teacher_headers(teacher["id"])), 201
    )
    assert created["status"] == "DRAFT"
    assert created["teacher_id"] == teacher["id"]
    assert created["school_id"] == world["school"]["id"]


# ── Shipping requires an ACTIVE vendor ─────────────────────────────────────


def test_suspended_vendor_cannot_ship_its_purchase_order(api):
    """The PO is ISSUED and the caller owns it, but the vendor row is
    SUSPENDED, so the ship action reports the state error.

    PRD: "The vendor ships its own orders: advancing the purchase order identified by `po_id` with `action` value `SHIP` requires the acting `X-User-ID` to equal the order's `vendor_id` (`ERR_FORBIDDEN` otherwise), the order to be `ISSUED` (`ERR_INVALID_STATE` otherwise), the vendor's `status` to be `ACTIVE` (a `SUSPENDED` vendor cannot ship — `ERR_INVALID_STATE`), and a `tracking_number` in the request (its absence fails with `ERR_INVALID_REQUEST`)."
    PRD: "Suspending a vendor moves it to `SUSPENDED`, which blocks adding new catalog items and blocks the shipment action on its purchase orders; existing purchase orders are otherwise unaffected."
    Design: Difficulty/cross_entity_state_dependency/po_ship_requires_active_vendor
    """
    world = fixtures.setup_funded_project(api)
    po = world["purchase_orders"][0]
    assert po["status"] == "ISSUED"

    suspended = validate_success(api.suspend_vendor(world["vendor"]["id"], ADMIN_HEADERS), 200)
    assert suspended["status"] == "SUSPENDED"

    res = api.advance_purchase_order(
        po["id"],
        f.po_advance_payload("SHIP", tracking_number="1Z999AA10123456784"),
        make_vendor_headers(world["vendor"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    po_after = fixtures.read_purchase_order(api, po["id"])
    assert po_after["status"] == "ISSUED"
    assert po_after["shipped_at"] is None
    assert fixtures.read_vendor(api, world["vendor"]["id"])["status"] == "SUSPENDED"


def test_active_vendor_ships_and_stamps_shipped_at(api):
    """The control case: an ACTIVE vendor ships its own ISSUED order.

    PRD: "Shipping moves the order to `SHIPPED` and stamps `shipped_at`."
    Design: Difficulty/cross_entity_state_dependency/po_ship_requires_active_vendor
    """
    world = fixtures.setup_funded_project(api)
    po = world["purchase_orders"][0]

    shipped = fixtures.ship_purchase_order(api, po)
    assert shipped["status"] == "SHIPPED"
    assert shipped["tracking_number"] == "1Z999AA10123456784"
    assert_instant(shipped["shipped_at"], BASE_CLOCK, "shipped_at")

    reread = fixtures.read_purchase_order(api, po["id"])
    assert reread["status"] == "SHIPPED"
