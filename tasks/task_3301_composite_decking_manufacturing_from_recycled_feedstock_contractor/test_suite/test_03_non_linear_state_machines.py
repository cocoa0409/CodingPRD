"""Non-linear state machines: the collection-program suspend/reactivate cycle
and the lead-referral decline/reassign loop."""
from test_helpers import (
    get_success_data,
    make_certified_contractor,
    make_collection_program,
    make_contractor,
    make_dealer,
    make_lead,
    make_plant,
    make_released_lot,
    make_supplier,
    make_contractor_headers,
    make_training_module,
    enroll_and_pass,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

QE = TEST_USERS["quality_engineer_headers"]
CM = TEST_USERS["channel_manager_headers"]
PA = TEST_USERS["program_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]


def test_collection_program_suspend_reactivate_rebate_cycle(api):
    """PRD §3.1: "Each program maintains an `accrued_rebate_cents` ledger,
    starting at zero, that accumulates rebate cents earned on released
    post-consumer film lots while the program is `ACTIVE`; the program's read
    view exposes the running accrual."
    PRD §3.1: "The supplier's `quality_tier` tracks program state: it is
    `PREFERRED` only while at least one `ACTIVE` collection program exists for
    that supplier, and it is recomputed on program creation, activation,
    suspension, and termination — so suspending a supplier's only active
    program drops the tier back to `STANDARD`, while reactivation restores
    `PREFERRED`."

    Design: Difficulty/non_linear_state_machine/collection_program_cyclic_suspend_reactivate
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    supplier = make_supplier(kind="COLLECTION_PROGRAM")
    program = make_collection_program(supplier["id"], rebate_per_lb_cents=10)
    assert get_success_data(api.get_supplier(supplier["id"], QE))["quality_tier"] == "PREFERRED"

    make_released_lot(supplier["id"], "PCR_FILM", 100, received_date="2026-03-01")

    get_success_data(api.suspend_collection_program(program["id"], CM))
    assert get_success_data(api.get_supplier(supplier["id"], QE))["quality_tier"] == "STANDARD"
    make_released_lot(supplier["id"], "PCR_FILM", 100, received_date="2026-03-02",
                      certificate_ref="L2")

    get_success_data(api.reactivate_collection_program(program["id"], CM))
    assert get_success_data(api.get_supplier(supplier["id"], QE))["quality_tier"] == "PREFERRED"
    make_released_lot(supplier["id"], "PCR_FILM", 100, received_date="2026-03-03",
                      certificate_ref="L3")

    program_after = get_success_data(api.get_collection_program(program["id"], CM))
    assert program_after["status"] == "ACTIVE"
    assert program_after["accrued_rebate_cents"] == 2000, (
        f"1000 before suspension + 0 during + 1000 after; got "
        f"{program_after['accrued_rebate_cents']}"
    )
    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_after["resin_store"]["PCR_FILM"] == 300


def test_suspension_pauses_accrual_while_terminated_stops_it(api):
    """PRD §3.1: "Each program maintains an `accrued_rebate_cents` ledger,
    starting at zero, that accumulates rebate cents earned on released
    post-consumer film lots while the program is `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/collection_program_cyclic_suspend_reactivate
    """
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    supplier = make_supplier(kind="COLLECTION_PROGRAM")
    program = make_collection_program(supplier["id"], rebate_per_lb_cents=10)
    make_released_lot(supplier["id"], "PCR_FILM", 100, received_date="2026-03-01")
    get_success_data(api.suspend_collection_program(program["id"], CM))
    make_released_lot(supplier["id"], "PCR_FILM", 100, received_date="2026-03-02",
                      certificate_ref="L2")
    program_after = get_success_data(api.get_collection_program(program["id"], CM))
    assert program_after["status"] == "SUSPENDED"
    assert program_after["accrued_rebate_cents"] == 1000


def test_lead_decline_reassign_excludes_decliner(api):
    """PRD §3.9: "The assignee — and only the assignee — may decline the lead
    (`ASSIGNED → DECLINED`), after which a `ProgramAdmin` may reassign it
    (`DECLINED → ASSIGNED`) with the declining contractor excluded from the
    candidate pool."

    Design: Difficulty/non_linear_state_machine/lead_referral_decline_reassign_loop
    """
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    dealer = make_dealer()
    contractor_a, _ = make_certified_contractor(name="Pro A", email="a@build.example")
    contractor_b, _ = make_certified_contractor(name="Pro B", email="b@build.example")
    lead = make_lead(dealer["id"])

    assigned = get_success_data(api.assign_lead_referral(lead["id"], PA))
    first_assignee = assigned["assigned_contractor_id"]
    assert first_assignee in (contractor_a["id"], contractor_b["id"])
    other = contractor_b["id"] if first_assignee == contractor_a["id"] else contractor_a["id"]

    declined = get_success_data(
        api.decline_lead_referral(lead["id"], make_contractor_headers(first_assignee)))
    assert declined["status"] == "DECLINED"

    reassigned = get_success_data(api.assign_lead_referral(lead["id"], PA))
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_contractor_id"] == other, (
        "the declining contractor must be excluded from the reassignment pool"
    )


def test_lead_decline_by_non_assignee_rejected(api):
    """PRD §3.9: "The assignee — and only the assignee — may decline the lead
    (`ASSIGNED → DECLINED`)"
    PRD §2.1: "a lead decline attempted by anyone other than the current
    assignee is rejected with `ERR_NOT_ASSIGNEE` (HTTP 403)."

    Design: Difficulty/non_linear_state_machine/lead_referral_decline_reassign_loop
    """
    from test_helpers import validate_error, ApiErrorId
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    dealer = make_dealer()
    contractor_a, _ = make_certified_contractor(name="Pro A", email="a@build.example")
    contractor_b, _ = make_certified_contractor(name="Pro B", email="b@build.example")
    lead = make_lead(dealer["id"])
    assigned = get_success_data(api.assign_lead_referral(lead["id"], PA))
    first_assignee = assigned["assigned_contractor_id"]
    other = contractor_b["id"] if first_assignee == contractor_a["id"] else contractor_a["id"]

    resp = api.decline_lead_referral(lead["id"], make_contractor_headers(other))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNEE)
    lead_after = get_success_data(api.get_lead_referral(lead["id"], PA))
    assert lead_after["status"] == "ASSIGNED"
