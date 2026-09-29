"""Calculation corners of the motor-carrier operating-authority API.

Five claims are exercised here: the second required insurance slot a
`HOUSEHOLD_GOODS` application mints, the ACTIVE-only input set of the
insurance-status recompute, the fifteen-seat break in the passenger BIPD base,
the running fee-ledger aggregation across a partial and a final payment, and
the sweep's three-step order, which defers a proceeding the same sweep opened.

Every chain is built through the public endpoints of PRD S4 from an empty
database, with the logical compliance clock of PRD S2.5 pinned at each step.
"""

from types import SimpleNamespace

from test_helpers import (
    COMPLIANCE_OFFICER,
    REGISTRY_ADMIN,
    T_ELIGIBLE,
    T_ENROLL,
    T_PUBLISH,
    activate_authority,
    application_payload,
    assert_authority_application,
    assert_carrier,
    assert_created_at_ascending,
    assert_fee_ledger_entry,
    assert_fee_ledger_identities,
    assert_insurance_filing,
    assert_operating_authority,
    assert_revocation_proceeding,
    assert_safety_audit,
    assert_sweep_result,
    authority_for_application,
    authority_version,
    cancel_filing_payload,
    create_carrier,
    create_draft_application,
    create_insurer,
    create_process_agent,
    designate_states,
    fee_payment_payload,
    file_insurance,
    filing_payload,
    make_carrier_headers,
    make_insurer_headers,
    read_authority,
    review_application,
    scheduled_audit,
    set_clock,
    settle_fee_balance,
    submit_application,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Local chains.  Each one walks the registry -> application -> publication ->
# designation -> insurance -> activation sequence of PRD S3 with the atomic
# steps, so every test starts from an empty database.
# ---------------------------------------------------------------------------
def _enrolled_carrier(api, **carrier_kwargs):
    """PRD S3.1: one enrolled carrier, clock parked on the enrolment instant."""
    set_clock(api, T_ENROLL)
    return create_carrier(api, **carrier_kwargs)


def _published_authority(api, *, application_kwargs=None, carrier_kwargs=None,
                         with_agent=False, with_insurer=False,
                         agent_kwargs=None, insurer_kwargs=None):
    """PRD S3.3 + S3.4: a PUBLISHED application and the authority it minted."""
    carrier = _enrolled_carrier(api, **(carrier_kwargs or {}))
    env = SimpleNamespace(
        carrier=carrier,
        carrier_id=carrier["id"],
        carrier_headers=make_carrier_headers(carrier["id"]),
        agent=None,
        insurer=None,
        insurer_headers=None,
    )
    if with_agent:
        env.agent = create_process_agent(api, **(agent_kwargs or {}))
    if with_insurer:
        env.insurer = create_insurer(api, **(insurer_kwargs or {}))
        env.insurer_headers = make_insurer_headers(env.insurer["id"])
    env.application = create_draft_application(
        api, env.carrier_id, **(application_kwargs or {})
    )
    env.application = submit_application(api, env.carrier_id, env.application["id"])
    env.application_id = env.application["id"]
    set_clock(api, T_PUBLISH)
    env.application = review_application(api, env.application_id, disposition="PUBLISH")
    env.authority = authority_for_application(api, env.application_id)
    env.authority_id = env.authority["id"]
    return env


def _active_authority(api, **kwargs):
    """PRD S3.6: an ACTIVE authority whose activation minted a SCHEDULED audit."""
    env = _published_authority(api, with_agent=True, with_insurer=True, **kwargs)
    designate_states(
        api,
        env.carrier_id,
        env.authority_id,
        env.agent["id"],
        state_codes=env.authority["required_jurisdictions"],
        effective_from=T_PUBLISH,
    )
    env.filing = file_insurance(
        api,
        env.insurer["id"],
        env.authority_id,
        env.authority["required_bipd_limit_cents"],
        filing_type="BIPD",
        effective_at=T_PUBLISH,
        policy_number="BIPD-1",
    )
    settle_fee_balance(api, env.carrier_id)
    set_clock(api, T_ELIGIBLE)
    env.authority = activate_authority(api, env.authority_id)
    return env


def test_household_goods_submission_freezes_a_cargo_slot_on_top_of_the_bipd_base(api):
    """PRD S3.2: "For every other class — `FOR_HIRE_PROPERTY`, `HOUSEHOLD_GOODS`
    and `FREIGHT_FORWARDER` — the base is $750,000."
    PRD S3.2: "Separately, `required_cargo_limit_cents` is $10,000 for a
    `HOUSEHOLD_GOODS` application and zero for every other class, and
    `required_bond_limit_cents` is $75,000 for a `PROPERTY_BROKER` or
    `FREIGHT_FORWARDER` application and zero for every other class."
    PRD S3.2: "Finally, the multi-jurisdiction uplift: if the base is greater
    than zero **and** `requested_operating_states` names 25 or more states, add
    a flat $250,000 to the base."
    PRD S3.2: "`filing_fee_cents` is the sum of those four already-rounded
    lines, and `filing_fee_breakdown` records all four of them under the keys
    `line_docket_cents`, `line_states_cents`, `line_type_cents` and
    `line_hazmat_cents`."
    PRD S3.3: "When `submission_count` becomes 1, the three required insurance
    minimums and the filing fee are recomputed and then **frozen**:
    `filing_fee_cents` and `filing_fee_breakdown` take their final values, a
    ledger entry with `entry_type` `FILING_FEE_DEBIT` and an `amount_cents`
    equal to positive `filing_fee_cents` is appended with its `docket_ref`
    naming this application, and both `fees_assessed_total_cents` and
    `fee_balance_cents` on the owning carrier increase by that amount."

    Design: Corner/calculations/household_goods_application_adds_a_cargo_slot_to_the_bipd_minimum
    """
    carrier = _enrolled_carrier(
        api, legal_name="Hill Country Household Movers LLC", domicile_state="TX"
    )
    draft = create_draft_application(
        api,
        carrier["id"],
        application_kind="NEW",
        transportation_type="HOUSEHOLD_GOODS",
        requested_operating_states=["TX", "OK", "NM"],
        hazmat_endorsement_requested=False,
        hazmat_bulk_capable=False,
    )

    submitted = validate_success(
        api.submit_application(draft["id"], make_carrier_headers(carrier["id"]))
    )
    assert_authority_application(submitted)

    assert submitted["required_bipd_limit_cents"] == 75000000, (
        "a HOUSEHOLD_GOODS application takes the $750,000 property base with no "
        f"hazmat lift and no uplift at 3 states, got "
        f"{submitted['required_bipd_limit_cents']}"
    )
    assert submitted["required_cargo_limit_cents"] == 1000000, (
        "HOUSEHOLD_GOODS is the one class that mints a $10,000 cargo minimum, got "
        f"{submitted['required_cargo_limit_cents']}"
    )
    assert submitted["required_bond_limit_cents"] == 0, (
        "only a PROPERTY_BROKER or FREIGHT_FORWARDER carries a bond minimum, got "
        f"{submitted['required_bond_limit_cents']}"
    )
    assert submitted["filing_fee_cents"] == 80879, (
        "the four lines round half-up on their own before summation, so the frozen "
        f"HOUSEHOLD_GOODS fee is 80879 cents, got {submitted['filing_fee_cents']}"
    )
    breakdown = submitted["filing_fee_breakdown"]
    assert sum(breakdown.values()) == 80879, (
        f"filing_fee_breakdown must sum to filing_fee_cents, got {breakdown}"
    )
    assert submitted["status"] == "SUBMITTED", (
        f"a successful submit moves DRAFT -> SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submission_count"] == 1, (
        f"the first submission sets submission_count to 1, got "
        f"{submitted['submission_count']}"
    )

    charged = validate_success(api.get_carrier(carrier["id"], REGISTRY_ADMIN))
    assert_carrier(charged)
    assert charged["fee_balance_cents"] == 80879, (
        f"the debit of 80879 cents must land on fee_balance_cents, got "
        f"{charged['fee_balance_cents']}"
    )
    assert charged["fees_assessed_total_cents"] == 80879, (
        f"fees_assessed_total_cents must carry the same debit, got "
        f"{charged['fees_assessed_total_cents']}"
    )
    assert_fee_ledger_identities(api, carrier["id"], REGISTRY_ADMIN)

    entries, meta = validate_paginated(
        api.list_fee_ledger_entries(carrier["id"], REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 1, (
        f"exactly one FILING_FEE_DEBIT is appended by the first submission, got "
        f"{meta['total_count']}"
    )
    assert_fee_ledger_entry(entries[0])
    assert entries[0]["entry_type"] == "FILING_FEE_DEBIT"
    assert entries[0]["amount_cents"] == 80879
    assert entries[0]["docket_ref"] == draft["id"], (
        "the debit's docket_ref names the application it was raised against, got "
        f"{entries[0]['docket_ref']}"
    )


def test_cancelled_cargo_filing_is_excluded_from_the_insurance_status_recompute(api):
    """PRD S3.5: "Those required slots are: `BIPD` whenever
    `required_bipd_limit_cents` is greater than zero, `CARGO` whenever
    `required_cargo_limit_cents` is greater than zero, and one filing of type
    either `SURETY_BOND` or `TRUST_FUND` whenever `required_bond_limit_cents`
    is greater than zero."
    PRD S3.5: "A required slot counts as satisfied when it holds an `ACTIVE`
    filing whose coverage interval contains the current logical time and whose
    `coverage_limit_cents` is at least that slot's required minimum."
    PRD S3.5: "`NOT_FILED → PARTIAL` when at least one, but not all, of the
    required slots is satisfied."
    PRD S3.5: "`PARTIAL → FILED` when every required slot is satisfied."
    PRD S3.5: "If, after the cancellation, at least one required slot no longer
    holds an `ACTIVE` filing whose interval contains the current logical time,
    `insurance_status` moves `FILED → LAPSED`."
    PRD S3.4: "The two dimensions are recomputed by different triggers and
    neither is derivable from the other: an authority may sit `SUSPENDED` while
    its `insurance_status` reads `FILED` — that is exactly what a designation
    gap looks like — and `insurance_status` moves on filing creates and cancels
    regardless of what `authority_status` currently reads."

    Design: Corner/calculations/cancelled_filings_are_excluded_from_the_insurance_status_recompute
    """
    env = _published_authority(
        api,
        carrier_kwargs={"legal_name": "Balcones Van Lines LLC", "domicile_state": "TX"},
        application_kwargs={
            "transportation_type": "HOUSEHOLD_GOODS",
            "requested_operating_states": ["TX", "OK", "NM"],
        },
        with_insurer=True,
        insurer_kwargs={"authorized_states": ["TX", "OK", "NM"]},
    )
    assert env.authority["required_bipd_limit_cents"] == 75000000
    assert env.authority["required_cargo_limit_cents"] == 1000000
    assert env.authority["insurance_status"] == "NOT_FILED", (
        f"a freshly published authority opens at NOT_FILED, got "
        f"{env.authority['insurance_status']}"
    )
    insurer_id = env.insurer["id"]

    bipd = validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                insurer_id,
                75000000,
                authority_version(api, env.authority_id),
                filing_type="BIPD",
                policy_number="BIPD-40",
                effective_at=T_PUBLISH,
            ),
            env.insurer_headers,
        ),
        201,
    )
    assert_insurance_filing(bipd)
    after_bipd = read_authority(api, env.authority_id)
    assert after_bipd["insurance_status"] == "PARTIAL", (
        "one of the two required slots is satisfied, so the coverage dimension "
        f"reads PARTIAL, got {after_bipd['insurance_status']}"
    )

    cargo = validate_success(
        api.create_filing(
            filing_payload(
                env.authority_id,
                insurer_id,
                1000000,
                authority_version(api, env.authority_id),
                filing_type="CARGO",
                policy_number="CARGO-40",
                effective_at=T_PUBLISH,
            ),
            env.insurer_headers,
        ),
        201,
    )
    after_cargo = read_authority(api, env.authority_id)
    assert after_cargo["insurance_status"] == "FILED", (
        "both required slots are covered at or above their minimums, so the "
        f"coverage dimension reads FILED, got {after_cargo['insurance_status']}"
    )

    cancelled = validate_success(
        api.cancel_filing(
            cargo["id"],
            cancel_filing_payload("2026-08-06T00:00:00Z"),
            env.insurer_headers,
        )
    )
    assert cancelled["status"] == "CANCELLED", (
        f"an explicit cancel moves the filing ACTIVE -> CANCELLED, got "
        f"{cancelled['status']}"
    )

    after_cancel = read_authority(api, env.authority_id)
    assert_operating_authority(after_cancel)
    assert after_cancel["insurance_status"] == "LAPSED", (
        "the CANCELLED CARGO row is outside the recompute's input set, so the "
        "CARGO slot is no longer satisfied and the coverage dimension lapses, got "
        f"{after_cancel['insurance_status']}"
    )
    assert after_cancel["authority_status"] == "PENDING", (
        "the authority dimension never moved: it was PENDING throughout, got "
        f"{after_cancel['authority_status']}"
    )

    rows, meta = validate_paginated(
        api.list_filings(
            REGISTRY_ADMIN, authority_id=env.authority_id, filing_type="CARGO"
        )
    )
    assert meta["total_count"] == 1, (
        "the cancelled CARGO row still exists and is still listed, got "
        f"total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == cargo["id"]
    assert rows[0]["status"] == "CANCELLED"
    assert rows[0]["cancellation_effective_at"] == "2026-08-06T00:00:00.000Z", (
        "the submitted cancellation instant is written onto the filing, got "
        f"{rows[0]['cancellation_effective_at']}"
    )
    assert bipd["status"] == "ACTIVE"


def test_passenger_seat_break_selects_the_small_or_the_large_bipd_base(api):
    """PRD S3.2: "For a `PASSENGER` application, the base is $1,500,000 when
    `passenger_seating_capacity` is at most 15 seats, and $5,000,000 when the
    seating capacity is 16 seats or more."
    PRD S3.2: "Separately, `required_cargo_limit_cents` is $10,000 for a
    `HOUSEHOLD_GOODS` application and zero for every other class, and
    `required_bond_limit_cents` is $75,000 for a `PROPERTY_BROKER` or
    `FREIGHT_FORWARDER` application and zero for every other class."
    PRD S3.2: "Finally, the multi-jurisdiction uplift: if the base is greater
    than zero **and** `requested_operating_states` names 25 or more states, add
    a flat $250,000 to the base."
    PRD S3.2: "Opening the draft immediately previews two calculations, and
    nothing is charged yet."

    Design: Corner/calculations/passenger_seat_break_constant_selects_the_small_or_large_bipd_limit
    """
    carrier = _enrolled_carrier(
        api, legal_name="Alamo Motorcoach Lines LLC", domicile_state="TX"
    )
    headers = make_carrier_headers(carrier["id"])

    def _passenger_draft(seats):
        return validate_success(
            api.create_application(
                application_payload(
                    carrier["id"],
                    application_kind="NEW",
                    transportation_type="PASSENGER",
                    requested_operating_states=["TX", "OK", "NM"],
                    passenger_seating_capacity=seats,
                    hazmat_endorsement_requested=False,
                    hazmat_bulk_capable=False,
                ),
                headers,
            ),
            201,
        )

    small = _passenger_draft(15)
    large = _passenger_draft(16)
    assert_authority_application(small)
    assert_authority_application(large)

    assert small["required_bipd_limit_cents"] == 150000000, (
        "15 seats is at most 15, so the small passenger base of $1,500,000 applies, "
        f"got {small['required_bipd_limit_cents']}"
    )
    assert large["required_bipd_limit_cents"] == 500000000, (
        "16 seats crosses the break, so the large passenger base of $5,000,000 "
        f"applies, got {large['required_bipd_limit_cents']}"
    )
    for label, application in (("15-seat", small), ("16-seat", large)):
        assert application["required_cargo_limit_cents"] == 0, (
            f"the {label} PASSENGER application carries no cargo minimum, got "
            f"{application['required_cargo_limit_cents']}"
        )
        assert application["required_bond_limit_cents"] == 0, (
            f"the {label} PASSENGER application carries no bond minimum, got "
            f"{application['required_bond_limit_cents']}"
        )
        assert application["passenger_seating_capacity"] in (15, 16)
        assert application["status"] == "DRAFT"
        assert application["submission_count"] == 0

    assert large["required_bipd_limit_cents"] - small["required_bipd_limit_cents"] == (
        350000000
    ), "the two branches differ by exactly the seat-break step"

    uncharged = validate_success(api.get_carrier(carrier["id"], REGISTRY_ADMIN))
    assert uncharged["fee_balance_cents"] == 0, (
        "opening a draft previews the calculations and charges nothing, got "
        f"fee_balance_cents {uncharged['fee_balance_cents']}"
    )


def test_fee_balance_aggregation_tracks_a_partial_then_a_final_payment(api):
    """PRD S3.1: "Two identities must hold at every instant, and both are
    re-asserted immediately after each entry is appended. First, a carrier's
    `fee_balance_cents` equals the signed sum of the `amount_cents` of every
    ledger entry belonging to that carrier. Second, `fee_balance_cents` equals
    `fees_assessed_total_cents` minus `fees_reversed_total_cents` minus
    `fees_paid_total_cents`, where `fees_assessed_total_cents` is the lifetime
    sum of that carrier's `FILING_FEE_DEBIT` amounts, `fees_reversed_total_cents`
    is the lifetime sum of the absolute values of its
    `FILING_FEE_REVERSAL_CREDIT` amounts, and `fees_paid_total_cents` is the
    lifetime sum of the absolute values of its `FEE_PAYMENT_CREDIT` amounts."
    PRD S3.1: "A payment is recorded by a `CarrierRep` acting for its own
    carrier or by a `RegistryAdmin`, and consists of an `amount_cents` figure
    plus an optional `memo`. Recording it appends a ledger entry whose
    `entry_type` is `FEE_PAYMENT_CREDIT` and whose `amount_cents` is the
    negation of the submitted amount, then increases `fees_paid_total_cents` by
    the submitted amount and decreases `fee_balance_cents` by the same amount."
    PRD S3.1: "The ledger is also the audit trail: listing a carrier's entries
    in `created_at` ascending order and summing `amount_cents` across the page
    set must reproduce `fee_balance_cents` exactly, and the listing may be
    narrowed to one `entry_type` at a time."
    PRD S3.1: "Each `FeeLedgerEntry` names the `carrier_id` whose balance it
    moves, an `entry_type` that is one of `FILING_FEE_DEBIT`,
    `FILING_FEE_REVERSAL_CREDIT` or `FEE_PAYMENT_CREDIT`, a signed
    `amount_cents` that is never zero — positive for a `FILING_FEE_DEBIT` and
    negative for both credit types — a `docket_ref` naming the application the
    entry was raised against (null for a bare payment), and a human-readable
    `memo` explaining it."

    Design: Corner/calculations/fee_balance_aggregation_tracks_a_partial_then_final_payment
    """
    carrier = _enrolled_carrier(
        api, legal_name="Pecos Freight Systems LLC", domicile_state="TX"
    )
    carrier_id = carrier["id"]
    carrier_headers = make_carrier_headers(carrier_id)
    application = create_draft_application(
        api,
        carrier_id,
        transportation_type="FOR_HIRE_PROPERTY",
        requested_operating_states=["TX", "OK", "NM"],
    )
    submitted = submit_application(api, carrier_id, application["id"])
    assert submitted["filing_fee_cents"] == 64791, (
        "the frozen FOR_HIRE_PROPERTY fee over 3 states is 64791 cents, got "
        f"{submitted['filing_fee_cents']}"
    )

    assessed = validate_success(api.get_carrier(carrier_id, REGISTRY_ADMIN))
    assert assessed["fee_balance_cents"] == 64791
    assert assessed["fees_assessed_total_cents"] == 64791
    assert assessed["fees_paid_total_cents"] == 0
    assert assessed["fees_reversed_total_cents"] == 0

    partly_paid = validate_success(
        api.record_fee_payment(
            carrier_id,
            fee_payment_payload(30000, memo="first instalment"),
            carrier_headers,
        ),
        201,
    )
    assert_carrier(partly_paid)
    assert partly_paid["fees_paid_total_cents"] == 30000, (
        f"the partial payment lifts fees_paid_total_cents to 30000, got "
        f"{partly_paid['fees_paid_total_cents']}"
    )
    assert partly_paid["fee_balance_cents"] == 34791, (
        "64791 assessed minus 30000 paid leaves 34791 outstanding, got "
        f"{partly_paid['fee_balance_cents']}"
    )
    assert partly_paid["fees_assessed_total_cents"] == 64791, (
        "a payment never moves the lifetime assessment total, got "
        f"{partly_paid['fees_assessed_total_cents']}"
    )
    assert partly_paid["fees_reversed_total_cents"] == 0
    assert_fee_ledger_identities(api, carrier_id, REGISTRY_ADMIN)

    fully_paid = validate_success(
        api.record_fee_payment(
            carrier_id,
            fee_payment_payload(34791, memo="final instalment"),
            REGISTRY_ADMIN,
        ),
        201,
    )
    assert fully_paid["fees_paid_total_cents"] == 64791, (
        "the two instalments accumulate into fees_paid_total_cents, got "
        f"{fully_paid['fees_paid_total_cents']}"
    )
    assert fully_paid["fee_balance_cents"] == 0, (
        f"the docket is settled exactly, got {fully_paid['fee_balance_cents']}"
    )
    assert fully_paid["fees_assessed_total_cents"] == 64791
    assert fully_paid["fees_reversed_total_cents"] == 0
    assert_fee_ledger_identities(api, carrier_id, REGISTRY_ADMIN)

    entries, meta = validate_paginated(
        api.list_fee_ledger_entries(carrier_id, REGISTRY_ADMIN)
    )
    assert meta["total_count"] == 3, (
        "one debit plus two payment credits are on the ledger, got "
        f"{meta['total_count']}"
    )
    assert_created_at_ascending(entries)
    for entry in entries:
        assert_fee_ledger_entry(entry)
        assert entry["carrier_id"] == carrier_id
    assert [e["entry_type"] for e in entries] == [
        "FILING_FEE_DEBIT",
        "FEE_PAYMENT_CREDIT",
        "FEE_PAYMENT_CREDIT",
    ], f"the ledger reads in creation order, got {[e['entry_type'] for e in entries]}"
    assert [e["amount_cents"] for e in entries] == [64791, -30000, -34791], (
        "each credit is stored as the negation of the submitted amount, got "
        f"{[e['amount_cents'] for e in entries]}"
    )
    assert sum(e["amount_cents"] for e in entries) == 0, (
        "the signed sum of the whole ledger reproduces fee_balance_cents"
    )
    assert entries[0]["docket_ref"] == application["id"], (
        f"the debit's docket_ref names its application, got {entries[0]['docket_ref']}"
    )

    credits, credit_meta = validate_paginated(
        api.list_fee_ledger_entries(
            carrier_id, REGISTRY_ADMIN, entry_type="FEE_PAYMENT_CREDIT"
        )
    )
    assert credit_meta["total_count"] == 2, (
        "narrowing the listing to one entry_type leaves the two credits, got "
        f"{credit_meta['total_count']}"
    )
    assert [e["amount_cents"] for e in credits] == [-30000, -34791]
    for entry in credits:
        assert entry["docket_ref"] is None, (
            "a bare payment is raised against no application, so docket_ref is null, "
            f"got {entry['docket_ref']}"
        )
    assert [e["memo"] for e in credits] == ["first instalment", "final instalment"]


def test_sweep_step_order_defers_a_freshly_opened_proceeding_to_a_later_sweep(api):
    """PRD S3.6: "The audit window runs 18 calendar months from `activated_at`,
    preserving the day of month and the time of day"
    PRD S3.8: "Exactly three steps run, in this order, and within each step rows
    are processed in `created_at` ascending order."
    PRD S3.8: "Every `SafetyAudit` whose `status` is `SCHEDULED` and whose
    `audit_deadline_at` is strictly earlier than the current logical time moves
    `SCHEDULED → MISSED`; audits that are `PASSED`, `FAILED` or already `MISSED`
    are excluded from consideration entirely."
    PRD S3.8: "Step two handles registration delinquency. Every `Carrier` whose
    `biennial_update_due_at` is strictly earlier than the current logical time
    and whose `biennial_delinquent` is still false has `biennial_delinquent` set
    to true, adding one to `carriers_flagged_delinquent_count` per carrier."
    PRD S3.1: "`biennial_update_due_at` is set to the carrier's `created_at`
    plus 730 days, `last_biennial_update_at` is null, and `biennial_delinquent`
    is false."
    PRD S3.8: "Nothing is processed twice within one sweep: a proceeding opened
    by step one is not eligible for step three in that same sweep, precisely
    because step three only considers proceedings whose `notice_issued_at` is
    strictly before this sweep's current logical time."
    PRD S3.8: "Each audit moved this way adds one to `audits_missed_count`."
    PRD S3.8: "Each proceeding revoked this way adds one to
    `authorities_revoked_count`, and the number of contracts the termination
    cascade moved in its second hop is added to `contracts_terminated_count`."
    PRD S3.8: "The response reports `swept_at` (the logical instant at which the
    sweep ran) alongside `audits_missed_count`,
    `carriers_flagged_delinquent_count`, `authorities_revoked_count` and
    `contracts_terminated_count`."
    PRD S3.8: "Step three handles expired cure deadlines. Every
    `RevocationProceeding` whose `status` is `NOTICE_ISSUED`, whose
    `notice_issued_at` is strictly earlier than this sweep's current logical time,
    and whose `cure_deadline_at` is strictly earlier than the current logical time
    moves `NOTICE_ISSUED → REVOKED` with `revoked_at` stamped"

    Design: Corner/calculations/sweep_step_order_defers_a_freshly_opened_proceeding_to_a_later_sweep
    """
    env = _active_authority(api)
    audit = scheduled_audit(api, env.carrier_id)
    assert_safety_audit(audit)
    assert audit["audit_deadline_at"] == "2028-02-26T00:00:00.000Z", (
        "18 calendar months after activation on 2026-08-26 preserves the day and "
        f"the time of day, got {audit['audit_deadline_at']}"
    )

    set_clock(api, "2028-02-27T00:00:00Z")
    first = validate_success(api.run_compliance_sweep(COMPLIANCE_OFFICER))
    assert_sweep_result(first)
    assert first["swept_at"] == "2028-02-27T00:00:00.000Z", (
        f"the sweep stamps the current logical time, got {first['swept_at']}"
    )
    assert first["audits_missed_count"] == 1, (
        "step one moves the one overdue SCHEDULED audit to MISSED, got "
        f"{first['audits_missed_count']}"
    )
    assert first["authorities_revoked_count"] == 0, (
        "the proceeding step one just opened is not eligible for step three in the "
        f"same sweep, got authorities_revoked_count {first['authorities_revoked_count']}"
    )
    assert first["contracts_terminated_count"] == 0, (
        "no authority was revoked, so step three's termination cascade never ran, got "
        f"{first['contracts_terminated_count']}"
    )
    assert first["carriers_flagged_delinquent_count"] == 0, (
        "the carrier enrolled on 2026-08-01, so its biennial deadline of "
        "2028-07-31 is not yet strictly earlier than 2028-02-27, got "
        f"{first['carriers_flagged_delinquent_count']}"
    )

    after_first = read_authority(api, env.authority_id)
    assert after_first["authority_status"] == "SUSPENDED", (
        "the missed window suspends the authority, got "
        f"{after_first['authority_status']}"
    )
    assert after_first["suspension_reason"] == "AUDIT_WINDOW_MISSED", (
        f"the defect that caused the suspension is recorded, got "
        f"{after_first['suspension_reason']}"
    )
    assert after_first["new_entrant_audit_status"] == "MISSED", (
        "the authority mirrors the audit's new state, got "
        f"{after_first['new_entrant_audit_status']}"
    )

    proceedings, meta = validate_paginated(
        api.list_authority_proceedings(env.authority_id, COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 1, (
        f"step one opened exactly one proceeding, got {meta['total_count']}"
    )
    proceeding = proceedings[0]
    assert_revocation_proceeding(proceeding)
    assert proceeding["reason"] == "AUDIT_WINDOW_MISSED"
    assert proceeding["status"] == "NOTICE_ISSUED", (
        "the proceeding survives its own sweep untouched by step three, got "
        f"{proceeding['status']}"
    )
    assert proceeding["notice_issued_at"] == "2028-02-27T00:00:00.000Z", (
        "the notice is stamped with this sweep's logical time, which is therefore "
        f"not strictly before it, got {proceeding['notice_issued_at']}"
    )
    assert proceeding["cure_deadline_at"] == "2028-03-28T00:00:00.000Z", (
        f"the cure window closes 30 days after the notice, got "
        f"{proceeding['cure_deadline_at']}"
    )
    assert proceeding["revoked_at"] is None

    missed_audits, _ = validate_paginated(
        api.list_carrier_safety_audits(env.carrier_id, REGISTRY_ADMIN)
    )
    assert [a["status"] for a in missed_audits] == ["MISSED"]

    set_clock(api, "2028-03-29T00:00:00Z")
    second = validate_success(api.run_compliance_sweep(COMPLIANCE_OFFICER))
    assert_sweep_result(second)
    assert second["audits_missed_count"] == 0, (
        "the already-MISSED audit is excluded from consideration entirely, got "
        f"{second['audits_missed_count']}"
    )
    assert second["authorities_revoked_count"] == 1, (
        "the deferred proceeding is now strictly older than the sweep and past its "
        f"cure deadline, got {second['authorities_revoked_count']}"
    )
    assert second["contracts_terminated_count"] == 0, (
        f"this authority holds no contracts, got {second['contracts_terminated_count']}"
    )

    after_second = read_authority(api, env.authority_id)
    assert after_second["authority_status"] == "REVOKED", (
        f"the later sweep completes the revocation, got "
        f"{after_second['authority_status']}"
    )
    assert after_second["revoked_at"] == "2028-03-29T00:00:00.000Z", (
        f"revoked_at is stamped with the later sweep's time, got "
        f"{after_second['revoked_at']}"
    )
    reread, _ = validate_paginated(
        api.list_authority_proceedings(env.authority_id, COMPLIANCE_OFFICER)
    )
    assert reread[0]["status"] == "REVOKED", (
        f"the proceeding closes as REVOKED, got {reread[0]['status']}"
    )
    assert reread[0]["revoked_at"] == "2028-03-29T00:00:00.000Z"
