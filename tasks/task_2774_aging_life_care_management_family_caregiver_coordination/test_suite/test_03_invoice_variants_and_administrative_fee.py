"""The provisional/final variant split, the two opposed rounding disciplines,
and the empty-final-line-set guard on issuing.
"""
from test_helpers import (
    BILLING_ADMINISTRATOR,
    api_client,
    approve_time_entry,
    invoice_state_payload,
    issue_invoice,
    log_time_entry,
    open_crisis_episode,
    open_invoice,
    read_client,
    read_invoice,
    read_time_entry,
    register_care_manager,
    register_client,
    register_supervisor,
    set_logical_clock,
    setup_active_care_plan_scenario,
    submit_time_entry,
    validate_error,
)


def _mixed_approval_month():
    """An ACTIVE_CARE client with 100,000 cents on retainer, two approved entries
    and one crisis entry left awaiting supervisory approval.
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-05T09:00:00Z",
        client_overrides={
            "full_name": "Eleanor Ashgrove-Petrakis",
            "residence_setting": "PRIVATE_HOME",
            "billing_increment_min": 15,
            "travel_billing_pct": 50,
            "retainer_floor_cents": 50_000,
            "authorized_concurrent_caregivers": 2,
        },
        deposit_cents=100_000,
        scores={
            "adl": 4,
            "cognition": 5,
            "medical_complexity": 3,
            "social_support": 2,
            "safety": 4,
            "finances": 1,
        },
    )
    episode = open_crisis_episode(
        scenario.client_id,
        scenario.care_manager_id,
        trigger_type="HOSPITAL_ADMISSION",
        hospital_name="Mercy General",
    )
    travel = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-08-05T13:00:00Z",
        "2026-08-05T13:25:00Z",
        service_type="TRAVEL",
        service_location_id="CLIENT_HOME",
    )
    coordination = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-08-05T14:00:00Z",
        "2026-08-05T15:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="CLIENT_HOME",
    )
    crisis = log_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        "2026-08-05T19:00:00Z",
        "2026-08-05T20:35:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert travel["billable_amount_cents"] == 5_625
    assert coordination["billable_amount_cents"] == 22_500
    assert crisis["billable_amount_cents"] == 70_875

    for entry in (travel, coordination):
        submit_time_entry(entry["id"], scenario.care_manager_id)
        approve_time_entry(entry["id"], scenario.supervisor_id)
    submit_time_entry(crisis["id"], scenario.care_manager_id)

    invoice = open_invoice(
        scenario.client_id, period_start="2026-08-01", period_end="2026-08-31"
    )
    return scenario, invoice, travel, coordination, crisis


def test_01_a_draft_invoice_bills_submitted_and_approved_time_as_a_projection():
    """The provisional read admits the still-unapproved crisis entry, so the draft
    shows the whole month, and the retainer draw it names is only a projection.

    PRD: "Under `PROVISIONAL`, which governs while the invoice is `DRAFT`, the candidate status filter admits entries that are `SUBMITTED` or `APPROVED`: unapproved-but-submitted time is included so the family sees the bill the practice expects to send, and `retainer_applied_cents` is a projection against which no money moves."

    Design: Difficulty/dual_variant_calc/invoice_provisional_versus_final_variant_divergence
    """
    scenario, invoice, travel, coordination, crisis = _mixed_approval_month()
    draft = read_invoice(invoice["id"])

    assert draft["status"] == "DRAFT"
    assert draft["variant"] == "PROVISIONAL"
    assert draft["line_entry_ids"] == [travel["id"], coordination["id"], crisis["id"]]
    assert draft["line_subtotal_cents"] == 99_000
    assert draft["admin_fee_cents"] == 6_930
    assert draft["total_due_cents"] == 105_930
    assert draft["retainer_applied_cents"] == 100_000
    assert draft["balance_due_cents"] == 5_930
    assert draft["issued_at"] is None

    # No money has moved: the projection has not touched the retainer.
    assert read_client(scenario.client_id)["retainer_balance_cents"] == 100_000


def test_02_issuing_recomputes_the_invoice_under_the_approved_only_final_variant():
    """Issuing drops the unapproved crisis entry from the line set and recomputes
    every money field, which is why the final total is far smaller.

    PRD: "Under `FINAL`, which governs once the invoice is `ISSUED` or `PAID`, the filter admits `APPROVED` entries only: supervisor-unapproved time is dropped, so the same invoice over the same data yields a strictly smaller `line_subtotal_cents` whenever any candidate is still `SUBMITTED`, and `retainer_applied_cents` is actually debited from the client's `retainer_balance_cents`."

    Design: Difficulty/dual_variant_calc/invoice_provisional_versus_final_variant_divergence
    """
    _scenario, invoice, travel, coordination, crisis = _mixed_approval_month()
    issued = issue_invoice(invoice["id"])

    assert issued["status"] == "ISSUED"
    assert issued["variant"] == "FINAL"
    assert issued["line_entry_ids"] == [travel["id"], coordination["id"]]
    assert crisis["id"] not in issued["line_entry_ids"]
    assert issued["line_subtotal_cents"] == 28_125
    assert issued["admin_fee_cents"] == 1_969
    assert issued["total_due_cents"] == 30_094
    assert issued["retainer_applied_cents"] == 30_094
    assert issued["balance_due_cents"] == 0
    assert issued["issued_at"] is not None


def test_03_the_divergence_between_the_two_variants_is_the_unapproved_entry():
    """The provisional subtotal exceeds the final subtotal by exactly the crisis
    entry's rated amount, and that entry stays out of the invoice entirely.

    PRD: "On success `variant` becomes `FINAL` and every computed money field is recomputed under the approved-only input set; `issued_at` is set to the logical clock's current instant; every time entry in `line_entry_ids` moves from `APPROVED` to `INVOICED` with its `invoice_id` set; the client's `retainer_balance_cents` decreases by `retainer_applied_cents` and its `unbilled_accrual_cents` is recomputed; and both the invoice's `version` and the client's `version` increase by 1."

    Design: Difficulty/dual_variant_calc/invoice_provisional_versus_final_variant_divergence
    """
    scenario, invoice, travel, coordination, crisis = _mixed_approval_month()
    provisional_subtotal = read_invoice(invoice["id"])["line_subtotal_cents"]
    issued = issue_invoice(invoice["id"])

    assert provisional_subtotal - issued["line_subtotal_cents"] == 70_875

    for entry in (travel, coordination):
        invoiced = read_time_entry(entry["id"])
        assert invoiced["status"] == "INVOICED"
        assert invoiced["invoice_id"] == invoice["id"]

    untouched = read_time_entry(crisis["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["invoice_id"] is None

    client = read_client(scenario.client_id)
    assert client["retainer_balance_cents"] == 69_906
    assert client["status"] == "ACTIVE_CARE"


def _two_quarter_hour_lines():
    """Two 15-minute submitted entries on a care manager rated at 18,081 cents
    an hour, chosen so that both rounding disciplines are observable.
    """
    set_logical_clock("2026-08-06T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Priya Nandan", credential="CMAC", hourly_rate_cents=18_081
    )
    supervisor = register_supervisor(full_name="Iris Ferreira", hourly_rate_cents=30_000)
    client = register_client(
        full_name="Rosalind Achterberg",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    first = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-06T14:00:00Z",
        "2026-08-06T14:15:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="CLIENT_HOME",
    )
    second = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-06T14:30:00Z",
        "2026-08-06T14:45:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="CLIENT_HOME",
    )
    submit_time_entry(first["id"], care_manager["id"])
    submit_time_entry(second["id"], care_manager["id"])
    invoice = open_invoice(
        client["id"], period_start="2026-08-01", period_end="2026-08-31"
    )
    return client, supervisor, invoice, first, second


def test_04_line_amounts_are_rounded_per_entry_and_then_plainly_summed():
    """Each quarter-hour line rounds to 4,520 cents when its entry is created, and
    the invoice subtotal is their plain sum.

    PRD: "Second, `line_subtotal_cents` is the plain sum of `billable_amount_cents` over those lines; each line amount was already rounded when its entry was created, so the discipline here is round per line, then sum."

    Design: Difficulty/combinatorial_formula/invoice_admin_fee_sum_then_round_order_mode_b
    """
    _client, _supervisor, invoice, first, second = _two_quarter_hour_lines()
    assert first["billable_amount_cents"] == 4_520
    assert second["billable_amount_cents"] == 4_520

    draft = read_invoice(invoice["id"])
    assert draft["line_entry_ids"] == [first["id"], second["id"]]
    assert draft["line_subtotal_cents"] == 9_040


def test_05_the_administrative_fee_is_rounded_once_on_the_summed_subtotal():
    """Seven percent of 9,040 cents rounds half up to 633; taking 7 percent of
    each 4,520-cent line and summing the roundings would have produced 632.

    PRD: "Third, `admin_fee_cents` is the practice's 7 percent administrative charge, computed as `line_subtotal_cents` multiplied by 7 and divided by 100, rounded half up **once on the summed subtotal** — computing the fee per line and summing the roundings is explicitly wrong and yields different cents — and `total_due_cents` is `line_subtotal_cents` plus `admin_fee_cents`."

    Design: Difficulty/combinatorial_formula/invoice_admin_fee_sum_then_round_order_mode_b
    """
    _client, _supervisor, invoice, _first, _second = _two_quarter_hour_lines()
    draft = read_invoice(invoice["id"])

    assert draft["admin_fee_cents"] == 633
    assert draft["admin_fee_cents"] != 632
    assert draft["total_due_cents"] == 9_673
    assert draft["variant"] == "PROVISIONAL"


def test_06_with_no_retainer_the_whole_total_falls_to_the_family():
    """A client holding no retainer draws nothing, so the waterfall leaves the
    entire total outstanding.

    PRD: "Fourth comes the retainer waterfall: `retainer_applied_cents` is the lesser of the client's `retainer_balance_cents` and `total_due_cents`, and `balance_due_cents` is `total_due_cents` less `retainer_applied_cents` — the retainer is drawn first and the family is billed only the remainder."

    Design: Difficulty/combinatorial_formula/invoice_admin_fee_sum_then_round_order_mode_b
    """
    client, _supervisor, invoice, _first, _second = _two_quarter_hour_lines()
    assert read_client(client["id"])["retainer_balance_cents"] == 0

    draft = read_invoice(invoice["id"])
    assert draft["retainer_applied_cents"] == 0
    assert draft["balance_due_cents"] == 9_673


def _draft_invoice_over_one_submitted_hour():
    """A single unapproved billable hour and the draft invoice that projects it."""
    set_logical_clock("2026-08-13T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Whitfield", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(full_name="Iris Ferreira", hourly_rate_cents=30_000)
    client = register_client(
        full_name="Ida Vandermolen",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        retainer_floor_cents=0,
    )
    entry = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-13T10:00:00Z",
        "2026-08-13T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="CLIENT_HOME",
    )
    submit_time_entry(entry["id"], care_manager["id"])
    invoice = open_invoice(
        client["id"], period_start="2026-08-01", period_end="2026-08-31"
    )
    return care_manager, supervisor, client, invoice, entry


def test_07_issuing_is_refused_while_the_final_line_set_would_be_empty():
    """The draft projects a bill from submitted time, but the final variant admits
    approved time only, so the issue request finds nothing to bill.

    PRD: "It requires that recomputing under the final variant still yields a non-empty `line_entry_ids`, else `ERR_NO_BILLABLE_ACTIVITY`, and that the client is not `DISCHARGED`."

    Design: Difficulty/boundary_precision_check/invoice_issue_with_empty_final_line_set_rejected
    """
    _cm, _supervisor, _client, invoice, entry = _draft_invoice_over_one_submitted_hour()
    draft = read_invoice(invoice["id"])
    assert draft["variant"] == "PROVISIONAL"
    assert draft["line_subtotal_cents"] == 22_500
    assert draft["admin_fee_cents"] == 1_575
    assert draft["total_due_cents"] == 24_075

    response = api_client.patch_invoice_state(
        invoice["id"], invoice_state_payload("ISSUED"), BILLING_ADMINISTRATOR
    )
    validate_error(response, "ERR_NO_BILLABLE_ACTIVITY", 422)

    unchanged = read_invoice(invoice["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["variant"] == "PROVISIONAL"
    assert unchanged["issued_at"] is None
    assert read_time_entry(entry["id"])["status"] == "SUBMITTED"


def test_08_the_same_issue_request_succeeds_once_the_hour_is_approved():
    """Approving the single hour populates the final line set, and the identical
    request then issues an invoice whose figures match the earlier projection.

    PRD: "`line_entry_ids` is that candidate set ordered by `start_at` ascending with ties broken by `created_at` ascending."

    Design: Difficulty/boundary_precision_check/invoice_issue_with_empty_final_line_set_rejected
    """
    _cm, supervisor, client, invoice, entry = _draft_invoice_over_one_submitted_hour()
    approve_time_entry(entry["id"], supervisor["id"])

    issued = issue_invoice(invoice["id"])
    assert issued["status"] == "ISSUED"
    assert issued["variant"] == "FINAL"
    assert issued["line_entry_ids"] == [entry["id"]]
    assert issued["line_subtotal_cents"] == 22_500
    assert issued["admin_fee_cents"] == 1_575
    assert issued["total_due_cents"] == 24_075
    assert issued["retainer_applied_cents"] == 0
    assert issued["balance_due_cents"] == 24_075

    assert read_time_entry(entry["id"])["status"] == "INVOICED"
    assert read_client(client["id"])["status"] == "PROSPECT"
