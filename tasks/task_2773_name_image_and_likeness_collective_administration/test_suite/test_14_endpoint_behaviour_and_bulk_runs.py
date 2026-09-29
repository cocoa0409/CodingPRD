"""Endpoint behaviour: ANDed list filters, restructure links, bulk runs and reads.

These cases exercise endpoints whose whole contract is the response they build — a
filtered listing, a report, a clock echo or a reconciled detail read — rather than a
single stored field.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CONTRIBUTION_STATE_INVALID,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import (
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contract_money,
    assert_contribution_money,
    assert_donor_ledger,
    assert_error_envelope_shape,
    assert_sequence_no_ascending,
    assert_timestamp_equals,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    billing_run_payload,
    clock_payload,
    commitment_payload,
    commitment_restructure_payload,
    contribution_payload,
    payment_release_payload,
    review_payload,
)
from test_helpers.fixtures import (
    add_evidence,
    build_active_contract,
    build_athlete,
    build_collective,
    build_deliverable,
    build_donor,
    build_funded_collective,
    build_open_tier,
    read_collective,
    read_contract,
    read_deliverable,
    read_donor,
    record_taxpayer_doc,
    submit_work,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_director_headers,
    make_treasury_headers,
)


def test_the_donor_status_and_tier_filters_are_anded_not_ored(api):
    """Each filter alone returns two rows; together they return the one row in both sets.

    PRD s3.3: "Donor listings may be filtered by `collective_id`, `membership_tier_id` and
    `status`", and "A donor in `PROSPECT` becomes `ACTIVE` the moment any contribution of
    theirs reaches `SETTLED`". PRD s2.3 fixes that "`total_count` is the number of rows
    matching the filters before pagination is applied".

    Design: Corner/endpoints/donor_member_list_filters_by_status_and_membership_tier
    """
    collective = build_collective(
        api,
        "024300",
        name="Filtered Collective",
        institution_name="Filtered Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    base_tier = build_open_tier(api, collective["id"], "T1", 20000, 1)
    club_tier = build_open_tier(api, collective["id"], "T2", 60000, 2)

    donor_one = build_donor(
        api,
        collective["id"],
        base_tier["id"],
        display_name="Filt Donor One",
        email="f1@example.com",
    )
    donor_two = build_donor(
        api,
        collective["id"],
        base_tier["id"],
        display_name="Filt Donor Two",
        email="f2@example.com",
    )
    donor_three = build_donor(
        api,
        collective["id"],
        club_tier["id"],
        display_name="Filt Donor Three",
        email="f3@example.com",
    )

    gift = read_data(
        api.create_contribution(
            contribution_payload(
                donor_one["id"],
                50000,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(
        gift, processing_fee_cents=1480, net_amount_cents=48520, status="SETTLED"
    )

    by_status = api.list_donor_members(
        {"collective_id": collective["id"], "status": "PROSPECT"}, make_director_headers()
    )
    validate_success(by_status)
    status_rows = rows_of(by_status)
    assert [row["id"] for row in status_rows] == [donor_two["id"], donor_three["id"]]
    assert by_status.json()["meta"]["total_count"] == 2

    by_tier = api.list_donor_members(
        {"collective_id": collective["id"], "membership_tier_id": base_tier["id"]},
        make_director_headers(),
    )
    validate_success(by_tier)
    tier_rows = rows_of(by_tier)
    assert [row["id"] for row in tier_rows] == [donor_one["id"], donor_two["id"]]
    assert by_tier.json()["meta"]["total_count"] == 2

    by_both = api.list_donor_members(
        {
            "collective_id": collective["id"],
            "membership_tier_id": base_tier["id"],
            "status": "PROSPECT",
        },
        make_director_headers(),
    )
    validate_success(by_both)
    both_rows = rows_of(by_both)
    assert [row["id"] for row in both_rows] == [donor_two["id"]]
    assert by_both.json()["meta"]["total_count"] == 1

    assert_donor_ledger(
        read_donor(api, donor_one["id"]), lifetime_settled_cents=48520, status="ACTIVE"
    )


def test_restructuring_returns_the_new_row_and_links_the_cancelled_original(api):
    """The response is the replacement, and only the original carries a forward link.

    PRD s3.4: "A brand-new commitment row is created on the same `donor_member_id`,
    carrying the same `kind` and the same `billing_interval` as the original, in `status`
    `ACTIVE`, with `installments_charged` reset to 0 and the next `sequence_no` — and it is
    that **new** row that the response returns. The original row's
    `superseded_by_commitment_id` is set to the new row's identifier and its own `status`
    becomes `CANCELLED` ... the new row's `superseded_by_commitment_id` is always null at
    creation." PRD s4 lists "a commitment restructuring" among the endpoints that "bring a
    new row into existence" and therefore "answer with HTTP 201 Created".

    Design: Corner/endpoints/commitment_restructure_supersedes_the_original_and_links_it
    """
    collective = build_collective(
        api,
        "024400",
        name="Restructure Collective",
        institution_name="Restructure Institution",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T3", 90000, 3)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Restr Donor",
        email="restr@example.com",
    )
    original = read_data(
        api.create_commitment(
            commitment_payload(
                donor["id"],
                "MAJOR_GIFT_PLEDGE",
                300000,
                "NONE",
                expected_donor_member_version=donor["version"],
                installments_total=3,
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert original["superseded_by_commitment_id"] is None
    assert original["status"] == "ACTIVE"

    replacement = read_data(
        api.restructure_commitment(
            original["id"],
            commitment_restructure_payload(180000, installments_total=2),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert replacement["id"] != original["id"]
    assert replacement["status"] == "ACTIVE"
    assert replacement["amount_cents"] == 180000
    assert replacement["kind"] == "MAJOR_GIFT_PLEDGE"
    assert replacement["billing_interval"] == "NONE"
    assert replacement["installments_charged"] == 0
    assert replacement["superseded_by_commitment_id"] is None
    assert replacement["sequence_no"] == original["sequence_no"] + 1

    cancelled = read_data(api.get_commitment(original["id"], make_director_headers()))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["superseded_by_commitment_id"] == replacement["id"]

    assert_donor_ledger(read_donor(api, donor["id"]), status="PROSPECT")

    chain = api.list_commitments(
        {"superseded_by_commitment_id": replacement["id"]}, make_director_headers()
    )
    validate_success(chain)
    assert [row["id"] for row in rows_of(chain)] == [original["id"]]

    refreshed_tier = read_data(api.get_membership_tier(tier["id"], make_director_headers()))
    assert refreshed_tier["active_commitment_count"] == 1


def test_a_subscription_charge_cycle_skips_the_pledge_and_charges_each_subscription(api):
    """Two subscriptions are charged with per-row fees; the pledge is untouched.

    PRD s3.6: "A `SUBSCRIPTION_CHARGE_CYCLE` walks every `RECURRING_SUBSCRIPTION`
    commitment of that collective whose `status` is `ACTIVE` or `PAST_DUE`, in ascending
    commitment `sequence_no`, and records one contribution per commitment with a
    `source_kind` of `SUBSCRIPTION_CHARGE` and a `processor_outcome` of `APPROVE`, each
    settled inline with all the fan-out of §3.5", and "Neither run kind touches the
    collective's `version`". The first band of §3.5 gives 5000 a fee of 175 and 12000 a fee
    of 378.

    Design: Corner/endpoints/subscription_charge_cycle_charges_only_recurring_commitments
    """
    collective = build_collective(
        api,
        "024500",
        name="Billing Collective",
        institution_name="Billing Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T2", 60000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Bill Donor",
        email="bill@example.com",
    )

    def commit(kind, amount_cents, billing_interval, installments_total=None):
        current = read_donor(api, donor["id"])
        return read_data(
            api.create_commitment(
                commitment_payload(
                    donor["id"],
                    kind,
                    amount_cents,
                    billing_interval,
                    expected_donor_member_version=current["version"],
                    installments_total=installments_total,
                ),
                make_director_headers(),
            ),
            expected_status=201,
        )

    # installments_total is the number of cycles a subscription runs before it is
    # "considered discharged" (PRD s3.4), and a commitment leaves ACTIVE for FULFILLED
    # "once `installments_charged` reaches `installments_total`". Two cycles are billed
    # below, so both subscriptions are written with a two-cycle budget.
    monthly = commit("RECURRING_SUBSCRIPTION", 5000, "MONTHLY", installments_total=2)
    annual = commit("RECURRING_SUBSCRIPTION", 12000, "ANNUAL", installments_total=2)
    pledge = commit("MAJOR_GIFT_PLEDGE", 300000, "NONE", installments_total=3)

    before = read_collective(api, collective["id"])
    assert before["settled_net_funds_cents"] == 0

    report = read_data(
        api.create_billing_run(
            collective["id"],
            billing_run_payload("SUBSCRIPTION_CHARGE_CYCLE"),
            make_treasury_headers(),
        )
    )
    assert report["run_kind"] == "SUBSCRIPTION_CHARGE_CYCLE"
    assert report["charged_commitment_count"] == 2
    assert report["settled_contribution_count"] == 2
    assert report["failed_contribution_count"] == 0
    assert report["recomputed_contribution_count"] == 0
    assert_timestamp_equals(report["executed_at"], "2026-08-01T00:00:00Z")

    assert read_data(api.get_commitment(monthly["id"], make_director_headers()))[
        "installments_charged"
    ] == 1
    assert read_data(api.get_commitment(annual["id"], make_director_headers()))[
        "installments_charged"
    ] == 1
    untouched_pledge = read_data(api.get_commitment(pledge["id"], make_director_headers()))
    assert untouched_pledge["installments_charged"] == 0
    assert untouched_pledge["status"] == "ACTIVE"

    listed = api.list_contributions({"donor_member_id": donor["id"]}, make_treasury_headers())
    validate_success(listed)
    charges = rows_of(listed)
    assert len(charges) == 2
    assert_sequence_no_ascending(charges)
    for charge in charges:
        assert charge["source_kind"] == "SUBSCRIPTION_CHARGE"
        assert charge["status"] == "SETTLED"
    assert_contribution_money(
        charges[0], gross_amount_cents=5000, processing_fee_cents=175, net_amount_cents=4825
    )
    assert_contribution_money(
        charges[1], gross_amount_cents=12000, processing_fee_cents=378, net_amount_cents=11622
    )

    after = read_collective(api, collective["id"])
    assert_collective_ledger(after, settled_net_funds_cents=16447)
    assert after["version"] == before["version"]

    second_report = read_data(
        api.create_billing_run(
            collective["id"],
            billing_run_payload("SUBSCRIPTION_CHARGE_CYCLE"),
            make_treasury_headers(),
        )
    )
    assert second_report["charged_commitment_count"] == 2
    assert read_data(api.get_commitment(monthly["id"], make_director_headers()))[
        "installments_charged"
    ] == 2
    assert read_data(api.get_commitment(annual["id"], make_director_headers()))[
        "installments_charged"
    ] == 2


def test_the_clock_starts_at_the_declared_default_and_reports_what_it_replaced(api):
    """Three collectives read three clock settings, forward then backward.

    PRD s2.5: "At startup that clock reads exactly `2026-08-01T00:00:00Z`, and until a
    `PlatformAdmin` moves it the server must report that default rather than falling back to
    real wall-clock time. The clock does not tick as requests arrive: it is static between
    explicit moves." PRD s2.5 also states that "the response reports the new `current_utc`
    alongside `previous_utc`, the instant the clock read before the call" and that "The clock
    may be moved backward as well as forward".

    Design: Corner/endpoints/clock_endpoint_reports_previous_and_new_utc
    """
    first = build_collective(
        api,
        "024600",
        name="Clock Collective",
        institution_name="Clock Institution",
        home_state_code="TX",
        association_ruleset="NCAA_2024",
    )
    assert_timestamp_equals(first["created_at"], "2026-08-01T00:00:00Z")

    forward = read_data(
        api.set_clock(clock_payload("2026-09-15T12:00:00Z"), make_admin_headers())
    )
    assert_timestamp_equals(forward["previous_utc"], "2026-08-01T00:00:00Z")
    assert_timestamp_equals(forward["current_utc"], "2026-09-15T12:00:00Z")

    second = build_collective(
        api,
        "024700",
        name="Clock Collective Two",
        institution_name="Clock Institution Two",
        home_state_code="OH",
        association_ruleset="NCAA_2026",
    )
    assert_timestamp_equals(second["created_at"], "2026-09-15T12:00:00Z")
    assert second["updated_at"] == second["created_at"]

    backward = read_data(
        api.set_clock(clock_payload("2026-08-05T00:00:00Z"), make_admin_headers())
    )
    assert_timestamp_equals(backward["previous_utc"], "2026-09-15T12:00:00Z")
    assert_timestamp_equals(backward["current_utc"], "2026-08-05T00:00:00Z")

    third = build_collective(
        api,
        "024800",
        name="Clock Collective Three",
        institution_name="Clock Institution Three",
        home_state_code="CA",
        association_ruleset="NAIA",
    )
    assert_timestamp_equals(third["created_at"], "2026-08-05T00:00:00Z")

    malformed = api.set_clock(clock_payload("not-a-timestamp"), make_admin_headers())
    validate_error(malformed, ERR_INVALID_REQUEST, expected_status=400)
    assert_error_envelope_shape(malformed)

    fourth = build_collective(
        api,
        "024801",
        name="Clock Collective Four",
        institution_name="Clock Institution Four",
        home_state_code="AL",
        association_ruleset="NAIA",
    )
    assert fourth["created_at"] == third["created_at"]


def test_one_contract_read_reconciles_releases_deliverable_value_and_payment(api):
    """A VERIFIED, a PENDING and a WAIVED sibling sit under one 50000-cent advance.

    PRD s3.8 defines `deliverable_value_total_cents` as "the sum of `unit_value_cents` over
    that contract's deliverables whose `status` is anything other than `FORFEITED`", and PRD
    s3.9 that "A deliverable's `payout_eligible_cents` is 0 unless its `status` is `VERIFIED`
    or `WAIVED`". PRD s3.9 also fixes the payment dimension: "from `UNPAID` to
    `PARTIALLY_PAID` when the contract's `released_total_cents` now stands strictly between
    zero and its `total_value_cents`". No completion fires, because PRD s3.8 requires
    "**every** deliverable in a terminal status".

    Design: Corner/endpoints/deal_contract_read_exposes_all_derived_totals_together
    """
    funded = build_funded_collective(
        api,
        "024900",
        500000,
        home_state_code="OH",
        association_ruleset="NCAA_2024",
        designation="UNRESTRICTED",
        tier_code="T3",
        annual_dues_cents=90000,
        benefit_rank=3,
        email="deriv@example.com",
        name="Derived Collective",
        institution_name="Derived Institution",
    )
    assert_contribution_money(
        funded["contribution"], processing_fee_cents=12530, net_amount_cents=487470
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-deriv",
        full_name="Deriv Athlete",
        sport="FOOTBALL",
        class_year=2028,
    )
    record_taxpayer_doc(api, athlete["id"], "W9")
    contract = build_active_contract(
        api,
        funded["collective_id"],
        athlete["id"],
        200000,
        funding_designation="UNRESTRICTED",
    )

    verified_row = build_deliverable(
        api, contract["id"], "APPEARANCE", 80000, "2026-09-01T00:00:00Z"
    )
    pending_row = build_deliverable(
        api, contract["id"], "SOCIAL_POST", 60000, "2026-09-01T00:00:00Z"
    )
    waived_row = build_deliverable(
        api, contract["id"], "AUTOGRAPH_SESSION", 60000, "2026-09-01T00:00:00Z"
    )

    add_evidence(api, verified_row["id"], "SIGNED_ATTENDANCE_SHEET", "deriv-sheet")
    submit_work(api, verified_row["id"], "2026-08-05T00:00:00Z")
    verified = read_data(
        api.review_deliverable(
            verified_row["id"],
            review_payload("VERIFY"),
            make_compliance_headers("compliance-deriv"),
        )
    )
    assert verified["status"] == "VERIFIED"

    waived = read_data(
        api.review_deliverable(
            waived_row["id"],
            review_payload("WAIVE"),
            make_compliance_headers("compliance-deriv"),
        )
    )
    assert waived["status"] == "WAIVED"

    before_release = read_contract(api, contract["id"])
    release = read_data(
        api.create_payment_release(
            payment_release_payload(
                contract["id"],
                "CONTRACT_ADVANCE",
                50000,
                expected_deal_contract_version=before_release["version"],
            ),
            make_treasury_headers("treasury-deriv"),
        ),
        expected_status=201,
    )
    assert release["status"] == "RELEASED"

    reconciled = read_data(api.get_deal_contract(contract["id"], make_treasury_headers()))
    assert_contract_money(
        reconciled,
        total_value_cents=200000,
        released_total_cents=50000,
        deliverable_value_total_cents=200000,
        clawback_amount_cents=0,
    )
    assert_contract_dimensions(
        reconciled, lifecycle_status="ACTIVE", payment_status="PARTIALLY_PAID"
    )

    assert read_deliverable(api, verified_row["id"])["payout_eligible_cents"] == 80000
    assert read_deliverable(api, waived_row["id"])["payout_eligible_cents"] == 60000
    assert read_deliverable(api, pending_row["id"])["payout_eligible_cents"] == 0
    assert read_deliverable(api, pending_row["id"])["status"] == "PENDING"

    assert_collective_ledger(
        read_collective(api, funded["collective_id"]),
        released_total_cents=50000,
        committed_unreleased_cents=150000,
    )


def test_a_refund_lands_only_on_a_settled_row_and_only_once(api):
    """Pending and already-refunded rows are both refused; the settled row refunds once.

    PRD s3.5: "A refund requires the contribution to be `SETTLED`, advancing it
    `SETTLED → REFUNDED`; a refund attempted against a pending, failed or already-refunded
    row is `ERR_CONTRIBUTION_STATE_INVALID`. The refund reduces the collective's
    `settled_net_funds_cents` by that row's `net_amount_cents`". PRD s2.10 confirms the row
    keeps its money for audit, since the collective figure is "the sum of `net_amount_cents`
    over the collective's contributions with status `SETTLED`, less the `net_amount_cents` of
    rows with status `REFUNDED`".

    Design: Corner/endpoints/refund_is_only_allowed_on_a_settled_contribution
    """
    collective = build_collective(
        api,
        "025000",
        name="Refund Collective",
        institution_name="Refund Institution",
        home_state_code="CA",
        association_ruleset="NCAA_2026",
    )
    tier = build_open_tier(api, collective["id"], "T2", 60000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Ref Donor",
        email="ref@example.com",
    )

    settled = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"], 100000, designation="UNRESTRICTED", processor_outcome="APPROVE"
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(settled, net_amount_cents=97470, status="SETTLED")
    pending = read_data(
        api.create_contribution(
            contribution_payload(
                donor["id"], 200000, designation="UNRESTRICTED", processor_outcome="DEFER"
            ),
            make_treasury_headers(),
        ),
        expected_status=201,
    )
    assert pending["status"] == "PENDING"

    on_pending = api.refund_contribution(pending["id"], None, make_treasury_headers())
    validate_error(on_pending, ERR_CONTRIBUTION_STATE_INVALID, expected_status=409)
    assert_error_envelope_shape(on_pending)

    refunded = read_data(
        api.refund_contribution(settled["id"], None, make_treasury_headers())
    )
    assert_contribution_money(refunded, status="REFUNDED", net_amount_cents=97470)

    replayed = api.refund_contribution(settled["id"], None, make_treasury_headers())
    validate_error(replayed, ERR_CONTRIBUTION_STATE_INVALID, expected_status=409)

    assert_collective_ledger(
        read_collective(api, collective["id"]),
        settled_net_funds_cents=0,
        funding_posture="OPEN",
    )
    assert_donor_ledger(read_donor(api, donor["id"]), lifetime_settled_cents=0)
    assert read_data(api.get_contribution(pending["id"], make_treasury_headers()))[
        "status"
    ] == "PENDING"
