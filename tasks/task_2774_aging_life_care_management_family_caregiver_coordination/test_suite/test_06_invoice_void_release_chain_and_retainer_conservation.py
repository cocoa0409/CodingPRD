"""The release chain a voided invoice sets off, and the conservation of the
retainer ledger across an issue-then-void pair.
"""
from test_helpers import (
    activate_service_authorization,
    approve_time_entry,
    assert_retainer_money_conserved,
    authorize_service_authorization,
    create_approved_time_entry,
    deposit_retainer,
    issue_invoice,
    log_time_entry,
    open_crisis_episode,
    open_invoice,
    propose_service_authorization,
    read_authorization,
    read_client,
    read_invoice,
    read_time_entry,
    register_care_manager,
    register_client,
    register_supervisor,
    set_logical_clock,
    setup_active_care_plan_scenario,
    submit_time_entry,
    uniform_domain_scores,
    void_invoice,
)

_VOID_REASON = "Billed against the wrong engagement letter."


def _issued_invoice_that_suspended_the_client():
    """An ISSUED invoice whose retainer draw exhausted the deposit, suspending the
    client for nonpayment and with it the live vendor coverage.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-05T09:00:00Z",
        client_overrides={
            "full_name": "Eleanor Ashgrove-Petrakis",
            "residence_setting": "PRIVATE_HOME",
            "billing_increment_min": 15,
            "retainer_floor_cents": 50_000,
            "authorized_concurrent_caregivers": 2,
        },
        deposit_cents=60_000,
        scores=uniform_domain_scores(2),
    )
    authorization = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )
    authorize_service_authorization(authorization["id"], scenario.supervisor_id)
    authorization = activate_service_authorization(
        authorization["id"], scenario.care_manager_id
    )
    assert authorization["auth_status"] == "ACTIVE"
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 8

    episode = open_crisis_episode(
        scenario.client_id, scenario.care_manager_id, trigger_type="FALL"
    )
    entry = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-08-05T19:00:00Z",
        "2026-08-05T20:35:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert entry["billable_amount_cents"] == 70_875
    submit_time_entry(entry["id"], scenario.care_manager_id)
    approve_time_entry(entry["id"], scenario.supervisor_id)

    invoice = open_invoice(
        scenario.client_id, period_start="2026-08-01", period_end="2026-08-31"
    )
    invoice = issue_invoice(invoice["id"])
    return scenario, authorization, entry, invoice


def test_01_issuing_exhausts_the_retainer_and_suspends_the_live_coverage():
    """The final draw empties the retainer below the floor while a balance is still
    outstanding, so the client is suspended and its active coverage with it.

    PRD: "If, after that final retainer draw, the client's recomputed `retainer_balance_cents` has fallen below its `retainer_floor_cents` and the invoice's `balance_due_cents` is greater than zero, an `ACTIVE_CARE` client slides to `SUSPENDED_NONPAYMENT`, which in turn moves every authorization of that client whose `auth_status` is `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `NONPAYMENT` and recomputes the client's `authorized_coverage_hours` downward as those rows leave the authorized set."

    Design: Difficulty/transitive_cascade/invoice_void_five_hop_release_cascade
    """
    scenario, authorization, _entry, invoice = _issued_invoice_that_suspended_the_client()

    assert invoice["status"] == "ISSUED"
    assert invoice["total_due_cents"] == 75_836
    assert invoice["retainer_applied_cents"] == 60_000
    assert invoice["balance_due_cents"] == 15_836

    client = read_client(scenario.client_id)
    assert client["retainer_deposits_total_cents"] == 60_000
    assert client["retainer_balance_cents"] == 0
    assert client["unbilled_accrual_cents"] == 0
    assert client["status"] == "SUSPENDED_NONPAYMENT"
    assert client["authorized_coverage_hours"] == 0

    suspended = read_authorization(authorization["id"])
    assert suspended["auth_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "NONPAYMENT"


def test_02_voiding_releases_the_invoiced_entry_back_to_approved():
    """The first two hops: the invoice becomes void with its reason recorded, and
    because of that every entry it carried returns to approved and unlinked.

    PRD: "Because of that, every time entry whose `invoice_id` names this invoice moves from `INVOICED` back to `APPROVED` and has its `invoice_id` cleared."

    Design: Difficulty/transitive_cascade/invoice_void_five_hop_release_cascade
    """
    _scenario, _auth, entry, invoice = _issued_invoice_that_suspended_the_client()
    assert read_time_entry(entry["id"])["status"] == "INVOICED"

    voided = void_invoice(invoice["id"], reason=_VOID_REASON)
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == _VOID_REASON

    released = read_time_entry(entry["id"])
    assert released["status"] == "APPROVED"
    assert released["invoice_id"] is None


def test_03_voiding_restores_the_retainer_balance_and_the_unbilled_accrual():
    """The third hop: the released entry re-enters the accrual set and the drawn
    retainer comes back, because a voided invoice leaves the drawn set.

    PRD: "Because of that, the client's `unbilled_accrual_cents` is recomputed upward by exactly the released entries and the client's `retainer_balance_cents` is recomputed upward by exactly this invoice's `retainer_applied_cents`, since a voided invoice leaves the drawn set."

    Design: Difficulty/transitive_cascade/invoice_void_five_hop_release_cascade
    """
    scenario, _auth, _entry, invoice = _issued_invoice_that_suspended_the_client()
    void_invoice(invoice["id"], reason=_VOID_REASON)

    client = read_client(scenario.client_id)
    assert client["retainer_balance_cents"] == 60_000
    assert client["unbilled_accrual_cents"] == 70_875
    assert client["retainer_deposits_total_cents"] == 60_000


def test_04_the_restored_balance_reinstates_the_client_and_its_coverage():
    """The last two hops: the recomputed balance has reached the floor again, so the
    client returns to active care and the nonpayment suspension is lifted.

    PRD: "And because of that, every authorization of that client whose `auth_status` is `SUSPENDED` with `suspension_reason` of `NONPAYMENT` returns to `ACTIVE` with `suspension_reason` reset to `NONE`, and the client's `authorized_coverage_hours` is recomputed upward."

    Design: Difficulty/transitive_cascade/invoice_void_five_hop_release_cascade
    """
    scenario, authorization, _entry, invoice = _issued_invoice_that_suspended_the_client()
    void_invoice(invoice["id"], reason=_VOID_REASON)

    client = read_client(scenario.client_id)
    assert client["status"] == "ACTIVE_CARE"
    assert client["authorized_coverage_hours"] == 8

    reinstated = read_authorization(authorization["id"])
    assert reinstated["auth_status"] == "ACTIVE"
    assert reinstated["suspension_reason"] == "NONE"


def _one_hour_against_a_deposit():
    """A 60,000-cent deposit, one approved billable hour worth 22,500 cents, and a
    single-day draft invoice over it.
    """
    set_logical_clock("2026-08-18T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Whitfield", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(full_name="Iris Ferreira", hourly_rate_cents=30_000)
    client = register_client(
        full_name="Julia Nakagawa-Oyelaran",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=50_000,
    )
    client = deposit_retainer(client["id"], 60_000, received_at="2026-08-18T09:00:00Z")
    entry = create_approved_time_entry(
        client["id"],
        care_manager["id"],
        supervisor["id"],
        "2026-08-18T10:00:00Z",
        "2026-08-18T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="CLIENT_HOME",
    )
    assert entry["billable_amount_cents"] == 22_500
    invoice = open_invoice(
        client["id"], period_start="2026-08-18", period_end="2026-08-18"
    )
    return client, entry, invoice


def test_05_a_draft_invoice_projects_a_draw_without_moving_any_money():
    """At the first checkpoint the whole deposit is still on the client, because a
    draft invoice contributes no draw at all.

    PRD: "The client's `retainer_balance_cents` is that deposit total less the sum of `retainer_applied_cents` over that client's invoices whose `status` is `ISSUED` or `PAID` — invoices still in `DRAFT` and invoices that have been `VOIDED` contribute no draw at all."

    Design: Difficulty/compensating_invariant/retainer_money_conserved_across_invoice_issue_and_void
    """
    client, _entry, invoice = _one_hour_against_a_deposit()
    draft = read_invoice(invoice["id"])
    assert draft["status"] == "DRAFT"
    assert draft["retainer_applied_cents"] == 24_075

    observed = read_client(client["id"])
    assert observed["retainer_deposits_total_cents"] == 60_000
    assert observed["retainer_balance_cents"] == 60_000
    assert_retainer_money_conserved(observed, 0)


def test_06_issuing_debits_exactly_the_applied_amount_and_the_ledger_still_closes():
    """At the second checkpoint the balance has fallen by precisely the applied
    figure, and balance plus draw still equals every deposit ever accepted.

    PRD: "Money is conserved across the retainer ledger: the client's remaining retainer balance plus the total retainer drawn by invoices in `ISSUED` or `PAID` status always equals the total of every retainer deposit ever accepted, because deposits are append-only and are never deleted or reversed."

    Design: Difficulty/compensating_invariant/retainer_money_conserved_across_invoice_issue_and_void
    """
    client, entry, invoice = _one_hour_against_a_deposit()
    issued = issue_invoice(invoice["id"])

    assert issued["variant"] == "FINAL"
    assert issued["line_subtotal_cents"] == 22_500
    assert issued["admin_fee_cents"] == 1_575
    assert issued["total_due_cents"] == 24_075
    assert issued["retainer_applied_cents"] == 24_075
    assert issued["balance_due_cents"] == 0

    observed = read_client(client["id"])
    assert observed["retainer_balance_cents"] == 35_925
    assert observed["retainer_deposits_total_cents"] == 60_000
    assert observed["unbilled_accrual_cents"] == 0
    assert observed["status"] == "PROSPECT"
    assert_retainer_money_conserved(observed, 24_075)
    assert read_time_entry(entry["id"])["status"] == "INVOICED"


def test_07_voiding_returns_the_draw_and_the_ledger_closes_on_the_deposit_total():
    """At the third checkpoint the void has put the balance back exactly where the
    deposit left it, while the voided row keeps the figure it once drew.

    PRD: "Deposits are append-only and are never deleted or reversed, so the client's `retainer_deposits_total_cents` is simply the sum of `amount_cents` over every deposit ever accepted for that client."

    Design: Difficulty/compensating_invariant/retainer_money_conserved_across_invoice_issue_and_void
    """
    client, entry, invoice = _one_hour_against_a_deposit()
    issue_invoice(invoice["id"])
    voided = void_invoice(invoice["id"], reason="Billed in error")

    assert voided["status"] == "VOIDED"
    assert voided["retainer_applied_cents"] == 24_075

    observed = read_client(client["id"])
    assert observed["retainer_balance_cents"] == 60_000
    assert observed["retainer_deposits_total_cents"] == 60_000
    assert observed["unbilled_accrual_cents"] == 22_500
    assert_retainer_money_conserved(observed, 0)

    released = read_time_entry(entry["id"])
    assert released["status"] == "APPROVED"
    assert released["invoice_id"] is None
