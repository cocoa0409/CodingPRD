"""Corner coverage: immediate consistency of computed responses, and the
RELOCATION / REPLACEMENT_CONSTRUCTION execution branches."""
from test_helpers import (
    TEST_USERS, assert_rent_bill, generate_bill, set_clock,
    setup_active_leased_oa, setup_expiring_lease_with_plan, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]


def test_bill_generation_response_is_immediately_final(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "Each generated bill carries the agreement's `oa_id` and is
    computed in a pinned, component-first order, every component rounded half
    up to whole cents before the subtotal is summed"

    The 201 response of bill generation already carries every computed
    component and the final total — no re-read or settling delay.

    Design: Corner/consistency_model/bill_generation_response_is_immediately_final
    """
    bundle = setup_active_leased_oa()  # 2027 stmt actual 460
    bill = generate_bill(bundle["oa"], "2027-04")
    assert_rent_bill(bill)
    assert bill["status"] == "ISSUED"
    assert bill["shell_cents"] == 17075000
    assert bill["operating_cents"] == 5122500
    assert bill["tax_escalation_cents"] == 341500
    assert bill["ti_amortization_cents"] == 649470
    assert bill["fee_cents"] == 1159424
    assert bill["total_cents"] == 24347894


def test_plan_execute_relocation_creates_followup_requirement(api):
    """PRD §3.9: "A `RELOCATION` execution creates a fresh space requirement in
    `DRAFT` for the same agency, its headcount and square-footage fields copied
    from the requirement that originated the expiring lease, its
    `delivery_method` left at `STANDARD` and its `source_plan_id` pointing back
    to the plan; `outcome_requirement_id` records it."
    PRD §3.9: "When the current date passes an `EXPIRING` lease's `end_date`,
    the sweep moves it to `SUCCEEDED` if its `executed_option` is
    `SUCCEEDING_LEASE`, and to `EXPIRED` otherwise — including when no option
    was ever executed."

    Design: Corner/consistency_model/plan_execute_relocation_creates_followup_requirement
    """
    bundle = setup_expiring_lease_with_plan(option="RELOCATION")
    lease, agency, plan = bundle["lease"], bundle["agency"], bundle["plan"]

    executed = validate_success(api.execute_plan(plan["id"], OFFICER), 200)
    assert executed["status"] == "EXECUTED"
    new_req_id = executed["outcome_requirement_id"]
    assert new_req_id is not None
    assert executed["outcome_lease_id"] is None

    new_req = validate_success(api.get_space_requirement(new_req_id, ADMIN), 200)
    assert new_req["status"] == "DRAFT"
    assert new_req["agency_id"] == agency["id"]
    assert new_req["delivery_method"] == "STANDARD"
    assert new_req["source_plan_id"] == plan["id"]
    assert new_req["base_headcount"] == 400, (
        "copied from the originating requirement")

    lease_mid = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert lease_mid["executed_option"] == "RELOCATION"

    set_clock("2037-01-01T00:00:00Z")
    lease_after = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert lease_after["status"] == "EXPIRED", "not SUCCEEDED"


def test_plan_execute_replacement_construction_creates_project(api):
    """PRD §3.9: "A `REPLACEMENT_CONSTRUCTION` execution creates both a new
    building in `UNDER_CONSTRUCTION` status and a fresh `DRAFT` requirement
    whose `delivery_method` is `NEW_CONSTRUCTION`; `outcome_building_id` and
    `outcome_requirement_id` record the pair."
    PRD §3.1: "The only other building status, `UNDER_CONSTRUCTION`, is never
    written directly — it appears only when expiration-plan execution spawns a
    replacement construction project (§3.9)."

    Design: Corner/consistency_model/plan_execute_replacement_construction_creates_project
    """
    bundle = setup_expiring_lease_with_plan(option="REPLACEMENT_CONSTRUCTION")
    lease, plan = bundle["lease"], bundle["plan"]

    executed = validate_success(api.execute_plan(plan["id"], OFFICER), 200)
    assert executed["status"] == "EXECUTED"
    new_bld_id = executed["outcome_building_id"]
    new_req_id = executed["outcome_requirement_id"]
    assert new_bld_id is not None
    assert new_req_id is not None

    new_bld = validate_success(api.get_building(new_bld_id, ADMIN), 200)
    assert new_bld["status"] == "UNDER_CONSTRUCTION", (
        "the only writer of that status is plan execution")

    new_req = validate_success(api.get_space_requirement(new_req_id, ADMIN), 200)
    assert new_req["delivery_method"] == "NEW_CONSTRUCTION"
    assert new_req["source_plan_id"] == plan["id"]

    lease_after = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert lease_after["executed_option"] == "REPLACEMENT_CONSTRUCTION"
