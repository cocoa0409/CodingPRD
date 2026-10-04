"""Corner queue: calculations — QPA even-count median, SLA business-hours
calendar, UCR cap-at-billed, transparency aggregation."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_ucr_rate,
    create_policy, create_agreement, create_claim, add_line, reprice,
    setup_finalized_claim, issue_invoice,
    create_feed_batch_payload,
    make_payer_admin_headers, make_payer_rep_headers,
    TEST_USERS, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]
NET = TEST_USERS["network_admin_headers"]
FEED = TEST_USERS["feed_operator_headers"]


def _setup_qpa_world():
    """
    Four providers, each with an ACTIVE agreement and a CONTRACTED_NETWORK
    determination for 99283/R1 whose per-unit contracted rates are
    15000, 25000, 32000, 48000.
    """
    payer = create_payer()
    providers = [create_provider(npi=f"300000000{i}") for i in range(1, 5)]
    discounts = {providers[0]["id"]: 0.50, providers[1]["id"]: 0.50,
                 providers[2]["id"]: 0.20, providers[3]["id"]: 0.40}
    units = {providers[0]["id"]: 30000, providers[1]["id"]: 50000,
             providers[2]["id"]: 40000, providers[3]["id"]: 80000}
    for p in providers:
        create_agreement(p, network_name=f"A{p['npi']}",
                         discount_percent=discounts[p["id"]])
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx, claim_type="ANCILLARY",
                  network_status="OUT_OF_NETWORK", methodology="CONTRACTED_NETWORK",
                  percent_of_medicare=None, priority=1)
    for i, p in enumerate(providers):
        claim = create_claim(payer, p, ctx, external_claim_ref=f"Q{i+1}",
                             claim_type="ANCILLARY",
                             service_date="2026-09-02T00:00:00Z",
                             patient_responsibility_cents=0)
        add_line(claim["id"], ctx, quantity_units=1,
                 unit_charge_cents=units[p["id"]])
        get_success_data(reprice(claim["id"], claim["version"] + 1, ctx))
    return payer, providers, ctx


def _nsa_claim_with_expired_negotiation(payer, providers, ctx):
    """Add the NSA claim (on providers[0]), open a negotiation, expire it."""
    create_medicare_entry()  # 99283/R1 10000 @ 1.10
    create_policy(payer, ctx, claim_type="PROFESSIONAL",
                  network_status="OUT_OF_NETWORK",
                  methodology="PERCENT_OF_MEDICARE", percent_of_medicare=1.50,
                  priority=1)
    claim = create_claim(payer, providers[0], ctx, external_claim_ref="Q5",
                         nsa_flag=True, service_date="2026-09-02T00:00:00Z",
                         patient_responsibility_cents=0)
    add_line(claim["id"], ctx)  # 99283 qty 2 @ 30000
    get_success_data(reprice(claim["id"], claim["version"] + 1, ctx))
    on = get_success_data(api_client.create_open_negotiation(
        {"claim_id": claim["id"], "initiated_by": "PAYER"}, ctx["payer_rep"]))
    get_success_data(api_client.set_clock("2026-10-23T00:00:00Z", OPS))
    return claim, on


def test_qpa_median_even_count_takes_lower_middle():
    """PRD §3.7: "The `qpa_cents` is the median of the candidate rates: the
    rates are sorted ascending, an odd count takes the middle element, and an
    even count takes the lower-middle element (the element at index count
    divided by two minus one, zero-based); equal values simply collapse, so no
    tie-break is needed."
    PRD §3.7: "The QPA candidate set is every `ACTIVE` `NetworkAgreement` whose
    determination snapshots priced the claim's primary `procedure_code` under
    `CONTRACTED_NETWORK` in the claim's region, regardless of payer; each
    candidate contributes a per-unit contracted rate — the agreement's discount
    applied to the snapshotted gross unit charge recorded in its
    `input_snapshot`."

    Design: Corner/calculations/qpa_median_even_count_takes_lower_middle
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
    payer, providers, ctx = _setup_qpa_world()
    claim, on = _nsa_claim_with_expired_negotiation(payer, providers, ctx)
    idr = validate_success(api_client.create_idr_submission(
        {"claim_id": claim["id"], "open_negotiation_id": on["id"],
         "payer_offer_cents": 30000, "provider_offer_cents": 50000},
        ctx["payer_rep"]), 201)
    # candidates [15000, 25000, 32000, 48000] -> lower-middle = 25000
    assert idr["qpa_cents"] == 25000
    assert idr["status"] == "SUBMITTED"


def test_sla_business_hours_across_weekend():
    """PRD §3.10: "The business-hours calendar runs Monday through Friday, from
    09:00:00Z to 17:00:00Z. The turnaround budget is 4 business hours for
    `CLAIM_INTAKE` batches and 24 business hours for `REMITTANCE` and
    `ELIGIBILITY` batches. Hours accrue only inside the calendar window — time
    outside the window does not count — and a batch received outside business
    hours starts counting at the next 09:00:00Z."
    PRD §3.10: "`sla_met` is computed as true when `processed_at` is at or
    before `sla_due_at` — equality counts as met — and false otherwise"

    Design: Corner/calculations/sla_business_hours_across_weekend
    """
    payer = create_payer()
    # Friday 2026-09-25 15:30Z: 1.5h left Friday + 2.5h Monday -> due Mon 11:30Z.
    get_success_data(api_client.set_clock("2026-09-25T15:30:00Z", FEED))
    batch = validate_success(api_client.create_feed_batch(
        create_feed_batch_payload(payer["id"], feed_type="CLAIM_INTAKE",
                                  record_count=100), FEED), 201)
    assert batch["sla_due_at"].startswith("2026-09-28T11:30:00"), (
        f"sla_due_at {batch['sla_due_at']}")

    get_success_data(api_client.set_clock("2026-09-28T11:30:00Z", FEED))
    processed = validate_success(api_client.process_feed_batch(batch["id"], FEED), 200)
    assert processed["processed_at"].startswith("2026-09-28T11:30:00")
    assert processed["sla_met"] is True


def test_ucr_methodology_caps_allowed_at_billed():
    """PRD §3.4: "Under `UCR`, the per-line benchmark is the UCR row's
    `percentile_80_cents` when the policy's `ucr_percentile` is 80, or its
    `percentile_50_cents` when the percentile is 50, multiplied by the line's
    `quantity_units`; the line's allowed amount is the lesser of the line's
    gross and that benchmark."
    PRD §3.4: "`savings_cents` is `billed_amount_cents` minus
    `allowed_amount_cents` plus `patient_responsibility_cents`"

    Design: Corner/calculations/ucr_methodology_caps_allowed_at_billed
    """
    payer = create_payer()
    provider = create_provider(npi="3000000005")
    create_ucr_rate(percentile_50_cents=18000, percentile_80_cents=80000)
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx, methodology="UCR", ucr_percentile=80,
                  percent_of_medicare=None, priority=1)
    claim = create_claim(payer, provider, ctx, external_claim_ref="U9",
                         patient_responsibility_cents=0)
    add_line(claim["id"], ctx)
    get_success_data(reprice(claim["id"], claim["version"] + 1, ctx))

    claim = validate_success(api_client.get_claim(claim["id"], ctx["payer_rep"]), 200)
    # benchmark 80000 * 2 = 160000 > gross 60000 -> allowed capped at billed
    assert claim["allowed_amount_cents"] == 60000
    assert claim["savings_cents"] == 0
    assert claim["methodology_used"] == "UCR"


def test_transparency_report_aggregation_matches_invoice_claims():
    """PRD §3.9: "The published `TransparencyReport` is born in `PUBLISHED`
    status and aggregates across the invoice's claims: `total_billed_cents`
    sums the claims' `billed_amount_cents`, `total_allowed_cents` sums their
    `allowed_amount_cents`, `total_savings_cents` sums their `savings_cents`,
    and `total_fee_cents` captures the invoice's `gross_fee_cents` at publish
    time."

    Design: Corner/calculations/transparency_report_aggregation_matches_invoice_claims
    """
    env = setup_finalized_claim(
        payer_overrides={"transparency_reporting_enabled": True},
        claim_overrides={"external_claim_ref": "S9",
                         "patient_responsibility_cents": 5000},
        npi="3000000006")
    invoice = issue_invoice(env["payer"]["id"], [env["claim"]["id"]])
    report = validate_success(
        api_client.publish_transparency_report(invoice["id"], OPS), 201)
    assert report["status"] == "PUBLISHED"
    assert report["total_billed_cents"] == 60000
    assert report["total_allowed_cents"] == 33000
    assert report["total_savings_cents"] == 32000
    assert report["total_fee_cents"] == 5000
