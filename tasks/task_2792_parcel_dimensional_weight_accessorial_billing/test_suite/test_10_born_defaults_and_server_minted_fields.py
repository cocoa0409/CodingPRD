"""What the server writes when the client says nothing.

Every entity in this domain is born with values the request never supplied: a
ledger of five zeroes, a `DRAFT` contract nobody activated, a delivery-area
class of `NONE`, a scan row with no version at all. These tests read those
birth values back and check that omitted optionals landed on the defaults the
contract names rather than on nulls.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    BILLING_OPS_USER_ID,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    FULL_TIER_TABLE,
    RESIDENTIAL_OVERRIDE_540,
    ZONE2_RATE_ROWS,
    activate_rate_contract,
    add_scan,
    assert_common_fields,
    assert_created_only_fields,
    assert_envelope_meta,
    assert_fields,
    assert_instant,
    assert_money_equals,
    assert_null_fields,
    assert_pct,
    billing_adjustment_payload,
    create_express_service_level,
    create_shipper_account,
    create_surcharge_window,
    dispute_payload,
    draft_rate_contract,
    get_success_data,
    ids_of,
    induct_shipment,
    invoice_sweep_payload,
    line_for_shipment,
    make_shipper_user_headers,
    refresh_invoice,
    refresh_shipment,
    shipment_payload,
    shipper_account_payload,
    shipper_with_active_contract,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"
ACME_EMAIL = "ap@acme.example"

LEDGER_KEYS = [
    "total_shipment_count",
    "unbilled_shipment_count",
    "billed_shipment_count",
    "credit_balance_cents",
    "open_charges_cents",
]


def test_01_a_new_shipper_account_opens_active_with_every_aggregate_at_zero(api):
    """PRD §3.1: "A newly registered account opens with `status` set to `ACTIVE` and all five ledger aggregates — `total_shipment_count`, `unbilled_shipment_count`, `billed_shipment_count`, `credit_balance_cents`, and `open_charges_cents` — sitting at 0."
    PRD §2.5: "`id` (string): a server-minted UUID. It carries no type prefix of any kind."
    PRD §2.5: "`version` (integer): a counter that starts at 1 on creation and increments by exactly 1 on every mutation of the record, including mutations the server performs on its own initiative as a cascade from some other request."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §3.1: "Reading an account back returns those five figures computed live, so the account view is always the authoritative ledger snapshot."

    Design: Corner/entities/shipper_account_creation_returns_server_minted_ledger_defaults
    """
    response = api.create_shipper_account(
        shipper_account_payload(
            account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, billing_email=ACME_EMAIL
        ),
        CARRIER_ADMIN_HEADERS,
    )
    created = validate_success(response, 201)
    assert_envelope_meta(response)
    assert response.json()["response_type"] == "object", (
        "a single resource is returned under response_type object, got "
        f"{response.json()['response_type']!r}"
    )

    assert_fields(
        created,
        {
            "account_number": ACME_ACCOUNT_NUMBER,
            "name": ACME_NAME,
            "billing_email": ACME_EMAIL,
            "status": "ACTIVE",
        },
    )
    for key in LEDGER_KEYS:
        assert created[key] == 0, (
            f"{key} must be minted at 0 on an empty database, got {created[key]}"
        )
    assert_common_fields(created, expected_version=1)

    fetched = get_success_data(
        api.get_shipper_account(created["id"], CARRIER_ADMIN_HEADERS)
    )
    assert fetched == created, (
        "the follow-up read must return the same field values the create returned"
    )


def test_02_a_drafted_contract_round_trips_its_rate_and_tier_tables(api):
    """PRD §3.1: "Every new contract is created with `status` `DRAFT` and `activated_at` null."
    PRD §3.1: "Two optional levers refine the contract: `accessorial_rate_overrides` is a map from accessorial code to a cents amount that displaces the carrier default rate for that code, defaulting to an empty map; and `residential_waived`, defaulting to false, suppresses automatic residential assessment for this shipper entirely when set true."
    PRD §3.1: "A contract may also name `supersedes_contract_id`, a pointer to another contract of the same shipper that this one is intended to replace on activation; it defaults to null for a shipper's first contract."
    PRD §3.1: "Contracts may be listed with optional filters on `shipper_id`, on `supersedes_contract_id` (to find the successor of a given contract), and on `status`, and an individual contract read returns its full `rate_table` and `tier_discount_table`."

    Design: Corner/entities/rate_contract_retrieval_round_trips_the_rate_and_tier_tables
    """
    account = create_shipper_account(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME
    )
    contract = draft_rate_contract(
        api,
        account["id"],
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        dim_divisor=139,
        min_charge_cents=1195,
        rate_table=list(ZONE2_RATE_ROWS),
        tier_discount_table=list(FULL_TIER_TABLE),
        accessorial_rate_overrides=dict(RESIDENTIAL_OVERRIDE_540),
    )

    # The billing desk reads the contract it will be held to.
    fetched = get_success_data(api.get_rate_contract(contract["id"], BILLING_OPS_HEADERS))
    assert_fields(
        fetched,
        {
            "status": "DRAFT",
            "activated_at": None,
            "shipper_id": account["id"],
            "supersedes_contract_id": None,
            "dim_divisor": 139,
            "min_charge_cents": 1195,
            "residential_waived": False,
        },
    )

    rate_rows = fetched["rate_table"]
    assert len(rate_rows) == 3, f"three zone-2 rows were submitted, got {len(rate_rows)}"
    assert [
        (row["zone"], row["min_lbs"], row["max_lbs"], row["cents_per_lb"])
        for row in rate_rows
    ] == [(2, 1, 20, 380), (2, 21, 70, 340), (2, 71, 9999, 305)], (
        f"the submitted row order must survive the round trip, got {rate_rows}"
    )

    tier_rows = fetched["tier_discount_table"]
    assert [
        (row["min_transportation_subtotal_cents"], row["discount_bps"])
        for row in tier_rows
    ] == [(50000, 550), (250000, 1250)], (
        f"both tier rows must come back ascending by threshold, got {tier_rows}"
    )

    assert fetched["accessorial_rate_overrides"] == {"RESIDENTIAL": 540}, (
        "the override map must round-trip exactly, got "
        f"{fetched['accessorial_rate_overrides']}"
    )
    assert_common_fields(fetched, expected_version=1)


def test_03_omitted_induction_options_fall_back_to_their_declared_defaults(api):
    """PRD §3.3: "Two optional inputs complete the declaration: `delivery_area_class`, one of `NONE`, `DAS`, or `EXTENDED` and defaulting to `NONE`, classifying how far off the beaten path the destination sits; and `non_conveyable_declared`, defaulting to false, the shipper's own warning that the package cannot ride the automated sort belt."
    PRD §3.3: "All three status axes open at their initial values: `measurement_status` at `PENDING_SCAN`, `movement_status` at `IN_TRANSIT`, and `billing_status` at `UNBILLED`."
    PRD §3.3: "Until the first scan arrives, `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, `final_basis`, `dim_variance_pct`, and `weight_variance_lbs` are all null on the shipment."
    PRD §3.3: "`DELIVERY_AREA` is assessed whenever `delivery_area_class` is anything other than `NONE`."
    PRD §3.3: "It also computes `guarantee_deadline_utc` as `picked_up_at` advanced by the purchased service's `guarantee_hours`; when the purchased service has `guaranteed` set to false, `guarantee_deadline_utc` is null instead, because there is no commitment to miss."

    Design: Corner/entities/omitted_shipment_options_fall_back_to_their_declared_defaults
    """
    shipper = shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-D-0001",
        zone=2,
        residential_declared=False,
        declared_length_in=12,
        declared_width_in=10,
        declared_height_in=8,
        declared_weight_lbs=6.0,
    )
    shipment = parcel.shipment

    assert_fields(
        shipment,
        {
            "delivery_area_class": "NONE",
            "non_conveyable_declared": False,
            "measurement_status": "PENDING_SCAN",
            "movement_status": "IN_TRANSIT",
            "billing_status": "UNBILLED",
        },
    )
    assert_null_fields(
        shipment,
        [
            "scanned_cube_in3",
            "final_dim_weight_lbs",
            "final_billable_weight_lbs",
            "final_basis",
            "dim_variance_pct",
            "weight_variance_lbs",
            "delivered_at",
        ],
    )
    assert_money_equals(
        shipment["accessorial_total_cents"], 0, "accessorial_total_cents"
    )
    assert_instant(
        shipment["guarantee_deadline_utc"],
        "2026-08-02T00:00:00Z",
        "guarantee_deadline_utc",
    )

    charges = get_success_data(
        api.list_accessorials(parcel.shipment_id, BILLING_OPS_HEADERS, {"limit": 100})
    )
    assert charges == [], (
        "delivery_area_class NONE earns no DELIVERY_AREA row at all, got "
        f"{[row['code'] for row in charges]}"
    )


def test_04_a_second_scan_appends_an_immutable_row_carrying_no_version(api):
    """PRD §2.5: "Three resources are append-only records of an observation rather than mutable state, and they carry only `id` and `created_at` — both `updated_at` and `version` are absent from `ServiceLevel`, `DimensionScan`, and `EvidenceItem`."
    PRD §3.4: "Each capture creates an immutable `DimensionScan` record carrying a `shipment_id`, its inputs, its computed figures, and a `captured_at` instant read from the logical clock; the created scan record is what the operation returns."
    PRD §3.4: "A shipment may accumulate any number of scans, but exactly one **governs** its measurement picture: the most recently created scan, ordered by `captured_at` descending and then by `created_at` descending."
    PRD §3.4: "Every successful capture increments the shipment's `version` by 1."
    PRD §3.4: "The full measurement history of a package is readable as a list ordered oldest first, so the sequence of variances and verdicts that produced the current determination is auditable end to end."

    Design: Corner/entities/dimension_scans_are_append_only_rows_with_no_version_field
    """
    shipper = shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-I-0001",
        zone=2,
        residential_declared=False,
        declared_length_in=10,
        declared_width_in=10,
        declared_height_in=20,
        declared_weight_lbs=30.0,
    )

    first = add_scan(
        api,
        parcel.shipment_id,
        expected_version=parcel.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=20,
        scanned_weight_lbs=30.0,
    )
    assert_created_only_fields(first)
    assert first["tolerance_status"] == "WITHIN_TOLERANCE"

    # The capture bumped the parcel, so the next payload needs a re-read version.
    after_first = refresh_shipment(api, parcel.shipment_id)
    assert after_first["version"] == parcel.shipment_version + 1, (
        "a scan increments the shipment version even though the scan row itself "
        f"carries none, expected {parcel.shipment_version + 1}, got {after_first['version']}"
    )

    second = add_scan(
        api,
        parcel.shipment_id,
        expected_version=after_first["version"],
        scan_source="AUTOMATED_DWS",
        scanned_length_in=10,
        scanned_width_in=10,
        scanned_height_in=21,
        scanned_weight_lbs=30.0,
    )
    assert_created_only_fields(second)
    assert second["scanned_cube_in3"] == 2100
    assert_pct(second["dim_variance_pct"], 5.00, "dim_variance_pct")
    assert second["tolerance_status"] == "EXCEEDS_TOLERANCE"

    history = get_success_data(
        api.list_scans(parcel.shipment_id, CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert len(history) == 2, (
        f"the second capture must append rather than mutate, found {len(history)} rows"
    )
    assert ids_of(history) == [first["id"], second["id"]], (
        f"the history reads oldest first, got {ids_of(history)}"
    )
    assert history[0]["scanned_height_in"] == 20, (
        "the first row must still report the height it captured, got "
        f"{history[0]['scanned_height_in']}"
    )
    assert history[0]["tolerance_status"] == "WITHIN_TOLERANCE", (
        "the first row's verdict must survive the second capture, got "
        f"{history[0]['tolerance_status']}"
    )

    governed = refresh_shipment(api, parcel.shipment_id)
    assert governed["scanned_cube_in3"] == 2100, (
        "the newest row governs the shipment's measurement picture, got "
        f"{governed['scanned_cube_in3']}"
    )


def test_05_every_entity_of_one_chain_is_born_in_its_declared_initial_state(api):
    """PRD §3.2: "A window opens at `status` `SCHEDULED`, which means it is on the calendar but invisible to pricing."
    PRD §3.6: "It opens at `status` `OPEN` with `issued_at` and `dispute_deadline_utc` null and `payment_reference` null."
    PRD §3.8: "A proposal is created by `BillingOps` at `status` `PROPOSED` with `created_by_user_id` set to the proposing operator's `X-User-ID`, `applied_by_user_id` null, and `applied_at` null."
    PRD §3.9: "A new dispute opens at `status` `SUBMITTED` with `shipper_user_id` stamped from the filer's `X-User-ID`, `round_count` at 0, `required_item_type` null, `accepted_evidence_count` at 0, `granted_credit_cents` at 0, and `resolved_at` null."
    PRD §3.6: "Invoices carry two derived pending counters — `pending_adjustment_count`, the number of adjustments on their lines whose `status` is `PROPOSED`, and `has_pending_adjustments`, which is simply true when that count is greater than 0 — both opening at 0 and false."

    Design: Corner/state_machines/every_entity_is_born_in_its_declared_initial_state
    """
    account = create_shipper_account(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME
    )
    assert account["status"] == "ACTIVE", (
        f"a new shipper is immediately usable, got {account['status']}"
    )

    express = create_express_service_level(api)
    contract = draft_rate_contract(api, account["id"])
    assert contract["status"] == "DRAFT", (
        f"creation alone never activates a contract, got {contract['status']}"
    )
    assert contract["activated_at"] is None

    window = create_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-08-15",
        per_package_cents=150,
    )
    assert window["status"] == "SCHEDULED", (
        f"a window must be armed before it prices anything, got {window['status']}"
    )

    activate_rate_contract(api, contract["id"], account["version"])

    parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express["id"],
                tracking_number="1Z-N-0001",
                zone=2,
                residential_declared=False,
                declared_length_in=12,
                declared_width_in=10,
                declared_height_in=8,
                declared_weight_lbs=6.0,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    assert_fields(
        parcel,
        {
            "measurement_status": "PENDING_SCAN",
            "movement_status": "IN_TRANSIT",
            "billing_status": "UNBILLED",
        },
    )

    validate_success(api.deliver_shipment(parcel["id"], CARRIER_OPS_HEADERS))
    invoice = validate_success(
        api.create_invoice(
            invoice_sweep_payload(
                account["id"], period_start="2026-08-01", period_end="2026-08-01"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    assert invoice["status"] == "OPEN", (
        f"the sweep creates an OPEN invoice, never an ISSUED one, got {invoice['status']}"
    )
    assert_null_fields(
        invoice, ["issued_at", "dispute_deadline_utc", "payment_reference"]
    )
    assert invoice["pending_adjustment_count"] == 0
    assert invoice["has_pending_adjustments"] is False

    issued = validate_success(api.issue_invoice(invoice["id"], BILLING_OPS_HEADERS))
    line = line_for_shipment(api, invoice["id"], parcel["id"])

    adjustment = validate_success(
        api.create_billing_adjustment(
            billing_adjustment_payload(
                line["id"], -100, issued["version"], reason="MANUAL"
            ),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    assert adjustment["status"] == "PROPOSED", (
        f"a proposal is born PROPOSED, got {adjustment['status']}"
    )
    assert adjustment["created_by_user_id"] == BILLING_OPS_USER_ID
    assert_null_fields(adjustment, ["applied_by_user_id", "applied_at"])

    dispute = validate_success(
        api.create_dispute(
            dispute_payload(
                line["id"],
                claim_type="WEIGHT",
                claimed_reason="billed weight looks wrong",
            ),
            make_shipper_user_headers(account["id"]),
        ),
        201,
    )
    assert dispute["status"] == "SUBMITTED", (
        f"a filed dispute is born SUBMITTED, got {dispute['status']}"
    )
    assert dispute["round_count"] == 0
    assert dispute["accepted_evidence_count"] == 0
    assert_money_equals(dispute["granted_credit_cents"], 0, "granted_credit_cents")
    assert_null_fields(dispute, ["required_item_type", "resolved_at"])
    assert dispute["shipper_user_id"] == account["id"]

    final = refresh_invoice(api, invoice["id"])
    assert final["pending_adjustment_count"] == 1, (
        "the PROPOSED adjustment is counted even though no money has moved, got "
        f"{final['pending_adjustment_count']}"
    )
    assert final["has_pending_adjustments"] is True
