"""Refusals: shape, expiry, quarantine, channel eligibility, holds and signatures."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AUTHORIZED_QUANTITY_EXCEEDED,
    ERR_BAY_BUFFER_VIOLATION,
    ERR_BAY_TYPE_MISMATCH,
    ERR_CHANNEL_GRADE_NOT_ACCEPTED,
    ERR_CHANNEL_MIN_LOT_NOT_MET,
    ERR_CHANNEL_NOT_HAZARD_CERTIFIED,
    ERR_DISPOSITION_DRIFT,
    ERR_DUAL_SIGNOFF_REQUIRED,
    ERR_FRAUD_HOLD_ACTIVE,
    ERR_LINE_NOT_REFURBISHABLE,
    ERR_NO_ELIGIBLE_CHANNEL,
    ERR_QUARANTINE_NOT_APPLICABLE,
    ERR_QUARANTINE_REQUIRED,
    ERR_RECALLED_ITEM_NOT_REFURBISHABLE,
    ERR_REFUND_HOLD_ACTIVE,
    ERR_REGULATED_DONATION_FORBIDDEN,
    ERR_RMA_ALREADY_RECEIVING,
    ERR_RMA_EXPIRED,
    ERR_RMA_EXPIRES_IN_PAST,
    ERR_RMA_NO_LINES,
    ERR_SERIAL_REQUIRED,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_line_states,
    assert_money,
    assert_pct_equals,
    plus_hours,
    plus_millis,
)
from test_helpers.constants import (
    BAY_TYPE_GENERAL,
    BAY_TYPE_QUARANTINE,
    CHANNEL_TYPE_BULK_LIQUIDATOR,
    CHECK_EMPTY_BOX,
    CHECK_REPEAT_RETURNER,
    CHECK_SERIAL_MISMATCH,
    CHECK_VALUE_ANOMALY,
    CLOCK_STARTUP_INSTANT,
    DEFAULT_FRAUD_TOLERANCE_CENTS,
    DEFAULT_REFUND_HOLD_HOURS,
    DISPOSITION_DESTROY,
    DISPOSITION_DONATE,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_PENDING,
    DISPOSITION_REFURBISH,
    DISPOSITION_RESTOCK,
    DO_APPROVED,
    DO_EXECUTED,
    DS_DISPOSITION_ASSIGNED,
    DS_RECEIVED_UNGRADED,
    FS_FRAUD_HOLD,
    FS_HOLD_PENDING_DISPOSITION,
    FS_REFUNDED,
    FS_RELEASE_PENDING,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    GRADE_SCRAP,
    GRADE_UNGRADED,
    HAZARD_AEROSOL,
    HAZARD_LITHIUM_BATTERY,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    REASON_DEFECTIVE,
    RECALL_MANDATORY,
    RMA_DRAFT,
    RMA_EXPIRED,
    RMA_ISSUED,
    RMA_PARTIALLY_RECEIVED,
    STANDARD_EXPIRES_AT,
    USER_GRADER,
    USER_SUPERVISOR,
    USER_SUPERVISOR_2,
    WO_ABANDONED,
    WO_IN_TEST,
    WO_OPEN,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    CLERK,
    GRADER,
    SUPERVISOR,
    SUPERVISOR_2,
    TECHNICIAN,
    TECHNICIAN_2,
)

# Instants pinned by the scenarios below. The startup clock reads
# 2026-08-01T00:00:00Z, so this expiry is already one day in the past.
EXPIRES_IN_THE_PAST = "2026-07-31T00:00:00Z"
LATER_EXPIRES_AT = "2026-10-01T00:00:00Z"
FIVE_AUGUST = "2026-08-05T00:00:00Z"
SERIAL_ONE = "SN-0001"

# A one-hour quarantine occupation on the day the clock starts.
QUARANTINE_START = "2026-08-01T01:00:00Z"
QUARANTINE_END = "2026-08-01T02:00:00Z"

# A lot window two days out, well clear of every other window in this file.
LOT_WINDOW_START = "2026-08-03T08:00:00Z"
LOT_WINDOW_END = "2026-08-03T12:00:00Z"

# Refurbishment test windows for the bay-buffer scenario.
FIRST_TEST_START = "2026-08-02T01:00:00Z"
FIRST_TEST_END = "2026-08-02T02:00:00Z"
INSIDE_BUFFER_START = "2026-08-02T02:29:00Z"
BUFFER_EDGE_START = "2026-08-02T02:30:00Z"
SECOND_TEST_END = "2026-08-02T03:00:00Z"
RECALLED_TEST_START = "2026-08-02T08:00:00Z"
RECALLED_TEST_END = "2026-08-02T10:00:00Z"


def test_an_authorization_expiring_before_now_is_refused(api):
    """PRD §3.2: "Both instants are checked against the logical clock at
    creation: `expires_at` must be strictly later than now and `order_placed_at`
    must not be later than now, or the request fails with
    `ERR_RMA_EXPIRES_IN_PAST`."

    Design: Corner/validations/corner_val_rma_expires_at_in_the_past_is_rejected
    """
    client = fx.make_client(api, name="Val One", client_code="VA1")
    body = f.rma_payload(
        client["id"],
        order_reference="ORD-VA1",
        customer_reference="CUST-VA1",
        expires_at=EXPIRES_IN_THE_PAST,
    )
    validate_error(api.create_rma(body, ADMIN), ERR_RMA_EXPIRES_IN_PAST, 422)

    _, meta = validate_paginated(
        api.list_rmas(ADMIN, {"client_id": client["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "the refused authorization stored nothing"

    body["expires_at"] = STANDARD_EXPIRES_AT
    accepted = validate_success(api.create_rma(body, ADMIN), 201)
    assert accepted["status"] == RMA_DRAFT, (
        "only the expiry instant separated the two requests"
    )


def test_a_serialized_sku_needs_a_declared_serial_on_its_authorization_line(api):
    """PRD §2.6: "Priority 42 requires a non-empty serial whenever the referenced
    catalogue item's `serialized` is true — `declared_serial` on an authorization
    line and `scanned_serial` on a scanned unit line — failing with
    `ERR_SERIAL_REQUIRED` (HTTP 422)."

    Design: Corner/validations/corner_val_serialized_item_authorization_line_requires_declared_serial
    """
    client = fx.make_client(api, name="Val Two", client_code="VA2")
    item = fx.make_catalog_item(
        api,
        client["id"],
        **fx.widget_item_kwargs(
            sku="SER-1", description="Serialized widget", serialized=True
        ),
    )
    rma = fx.make_draft_rma(
        api,
        client["id"],
        order_reference="ORD-VA2",
        customer_reference="CUST-VA2",
    )

    line_body = f.rma_line_payload(
        item["id"], authorized_quantity=1, reason_code=REASON_DEFECTIVE
    )
    validate_error(
        api.create_rma_line(rma["id"], line_body, ADMIN), ERR_SERIAL_REQUIRED, 422
    )

    _, meta = validate_paginated(
        api.list_rma_lines(ADMIN, {"rma_id": rma["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "no authorization line was declared"
    unchanged = fx.read_rma(api, rma["id"])
    assert unchanged["authorized_unit_total"] == 0
    assert unchanged["status"] == RMA_DRAFT

    line_body["declared_serial"] = SERIAL_ONE
    accepted = validate_success(
        api.create_rma_line(rma["id"], line_body, ADMIN), 201
    )
    assert accepted["declared_serial"] == SERIAL_ONE


def test_the_authorized_quantity_ceiling_is_cumulative_across_scans(api):
    """PRD §3.3: "The running total matters as much as the individual scan: the
    already-received quantity on that authorization line plus this scan must not
    exceed the line's `authorized_quantity`, and a breach fails with
    `ERR_AUTHORIZED_QUANTITY_EXCEEDED` even though each individual scan looked
    reasonable."

    Design: Corner/validations/corner_val_cumulative_scan_exceeding_authorized_quantity_rejected
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Val Three", "client_code": "VA3"},
        items=[fx.widget_item_kwargs()],
        lines=[
            {
                "authorized_quantity": 2,
                "reason_code": REASON_DEFECTIVE,
                "scan_quantity": 1,
            }
        ],
        tracking_reference="TRK-VA3",
    )
    receipt = world["receipt"]
    rma_line = world["rma_line"]

    # One unit is already in the building; two more would make three.
    response = api.create_receipt_line(
        receipt["id"],
        f.receipt_line_payload(
            rma_line["id"], quantity=2, reason_code=REASON_DEFECTIVE
        ),
        CLERK,
    )
    validate_error(response, ERR_AUTHORIZED_QUANTITY_EXCEEDED, 409)

    rows, meta = validate_paginated(
        api.list_return_lines(ADMIN, {"receipt_id": receipt["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
    assert rows[0]["quantity"] == 1

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["received_unit_total"] == 1
    assert rma["status"] == RMA_PARTIALLY_RECEIVED

    # Exactly one more unit fits, so the aggregate ceiling and not the per-scan
    # value was what refused the earlier request.
    accepted = validate_success(
        api.create_receipt_line(
            receipt["id"],
            f.receipt_line_payload(
                rma_line["id"], quantity=1, reason_code=REASON_DEFECTIVE
            ),
            CLERK,
        ),
        201,
    )
    assert accepted["quantity"] == 1


def test_a_reissue_is_barred_once_a_carton_has_arrived(api):
    """PRD §2.6: "Priority 22 requires that a reissue target has no `Receipt`
    rows at all, failing with `ERR_RMA_ALREADY_RECEIVING`."

    Design: Corner/validations/corner_val_reissue_after_a_receipt_exists_is_rejected
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Val Four", "client_code": "VA4"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        rma_kwargs={"order_reference": "ORD-VA4", "customer_reference": "CUST-VA4"},
        scan=False,
    )
    rma = world["rma"]
    fx.make_receipt(
        api,
        rma["id"],
        world["expected_weight_grams"],
        tracking_reference="TRK-VA4",
    )

    response = api.reissue_rma(
        rma["id"],
        f.reissue_payload(rma["version"], expires_at=LATER_EXPIRES_AT),
        ADMIN,
    )
    validate_error(response, ERR_RMA_ALREADY_RECEIVING, 409)

    _, meta = validate_paginated(
        api.list_rmas(ADMIN, {"supersedes_rma_id": rma["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "no replacement authorization was minted"

    unchanged = fx.read_rma(api, rma["id"])
    assert unchanged["status"] == RMA_ISSUED, (
        "the carton carried no scanned lines, so the authorization is still ISSUED"
    )
    assert unchanged["version"] == rma["version"], (
        "the guard version the caller supplied was the current one"
    )


def test_an_expiry_reached_exactly_counts_as_expired(api):
    """PRD §2.6: "Priority 21 requires the authorization not to have expired,
    guarding receipt creation and reissue: its status must not be `EXPIRED`, and
    while it is `ISSUED` or `PARTIALLY_RECEIVED` its `expires_at` must be
    strictly after the current logical time, so an `expires_at` exactly equal to
    now counts as expired."

    Design: Corner/validations/corner_val_receipt_at_exactly_expires_at_is_rejected_as_expired
    """
    client = fx.make_client(api, name="Val Five", client_code="VA5")
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    specs = [
        {
            "catalog_item_id": item["id"],
            "authorized_quantity": 1,
            "reason_code": REASON_DEFECTIVE,
        }
    ]
    weight = fx.expected_weight_grams((item["unit_weight_grams"], 1))
    expiring = fx.make_issued_rma(
        api,
        client["id"],
        specs,
        order_reference="ORD-VA5A",
        customer_reference="CUST-VA5A",
        expires_at=FIVE_AUGUST,
    )
    control = fx.make_issued_rma(
        api,
        client["id"],
        specs,
        order_reference="ORD-VA5B",
        customer_reference="CUST-VA5B",
        expires_at=FIVE_AUGUST,
    )

    # One millisecond before the expiry the window is still strictly open.
    fx.set_clock(api, plus_millis(FIVE_AUGUST, -1))
    validate_success(
        api.create_receipt(
            f.receipt_payload(
                control["rma"]["id"],
                tracking_reference="TRK-VA5B",
                gross_weight_grams=weight,
            ),
            CLERK,
        ),
        201,
    )

    fx.set_clock(api, FIVE_AUGUST)
    response = api.create_receipt(
        f.receipt_payload(
            expiring["rma"]["id"],
            tracking_reference="TRK-VA5A",
            gross_weight_grams=weight,
        ),
        CLERK,
    )
    validate_error(response, ERR_RMA_EXPIRED, 409)

    _, meta = validate_paginated(
        api.list_receipts(ADMIN, {"rma_id": expiring["rma"]["id"], "limit": 100})
    )
    assert meta["total_count"] == 0
    assert fx.read_rma(api, expiring["rma"]["id"])["status"] == RMA_EXPIRED


def test_a_hazardous_line_cannot_be_graded_before_a_quarantine(api):
    """PRD §3.4: "Grading directly out of `RECEIVED_UNGRADED` additionally
    requires that the item's `hazard_class` be `NONE` and its `recall_status` not
    be `MANDATORY` — anything hazardous or mandatorily recalled must have
    completed a quarantine occupation first, and skipping it returns
    `ERR_QUARANTINE_REQUIRED`."

    Design: Corner/validations/corner_val_hazardous_line_cannot_be_graded_without_quarantine
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Val Six", "client_code": "VA6"},
        items=[
            fx.widget_item_kwargs(
                sku="HAZ-1",
                description="Battery pack",
                hazard_class=HAZARD_LITHIUM_BATTERY,
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-VA6",
    )
    line = world["line"]

    response = api.grade_line(line["id"], f.grade_payload(GRADE_D), GRADER)
    validate_error(response, ERR_QUARANTINE_REQUIRED, 409)

    unchanged = fx.read_return_line(api, line["id"])
    assert_line_states(
        unchanged,
        disposition_state=DS_RECEIVED_UNGRADED,
        condition_grade=GRADE_UNGRADED,
        disposition=DISPOSITION_PENDING,
    )
    assert unchanged["graded_by_user_id"] is None

    _, meta = validate_paginated(
        api.list_refund_releases(ADMIN, {"return_line_id": line["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "no RefundRelease was stamped for the line"


def test_a_quarantined_hazardous_line_grades_straight_to_destroy(api):
    """PRD §3.4: "Otherwise, if the item's `hazard_class` is anything other than
    `NONE` and the line's `condition_grade` is `C`, `D` or `SCRAP`, the
    disposition is `DESTROY`."

    Design: Corner/validations/corner_val_hazardous_line_grades_normally_after_a_hazmat_quarantine
    """
    bay = fx.make_hazmat_bay(api, bay_code="HZ-VA7")
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Val Seven", "client_code": "VA7"},
        items=[
            fx.widget_item_kwargs(
                sku="HAZ-1",
                description="Battery pack",
                hazard_class=HAZARD_LITHIUM_BATTERY,
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-VA7",
    )
    line = world["line"]
    fx.quarantine_line(api, line["id"], bay["id"], QUARANTINE_START, QUARANTINE_END)

    graded = validate_success(
        api.grade_line(line["id"], f.grade_payload(GRADE_D), GRADER), 200
    )
    assert graded["condition_grade"] == GRADE_D
    assert graded["graded_by_user_id"] == USER_GRADER
    # The item is not under a mandatory recall, so D1 cannot be what fired.
    assert_line_states(
        graded,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        disposition=DISPOSITION_DESTROY,
    )
    assert graded["bay_id"] == bay["id"], (
        "the completed occupation stays on the line for audit"
    )

    # Grading moved only the physical dimension; the money dimension waits.
    read_back = fx.read_return_line(api, line["id"])
    assert_line_states(read_back, financial_state=FS_HOLD_PENDING_DISPOSITION)


def test_a_quarantine_cannot_occupy_a_general_bay(api):
    """PRD §3.4: "The bay must be `ACTIVE` and its `bay_type` must be `HAZMAT` or
    `QUARANTINE`, or the request fails with `ERR_BAY_TYPE_MISMATCH`."

    Design: Corner/validations/corner_val_quarantine_into_a_general_bay_is_rejected
    """
    general = fx.make_bay(api, bay_code="GN-VA8", bay_type=BAY_TYPE_GENERAL)
    quarantine = fx.make_bay(api, bay_code="QR-VA8", bay_type=BAY_TYPE_QUARANTINE)
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Val Eight", "client_code": "VA8"},
        items=[
            fx.widget_item_kwargs(
                sku="HAZ-1", description="Aerosol can", hazard_class=HAZARD_AEROSOL
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-VA8",
    )
    line = world["line"]

    response = api.quarantine_line(
        line["id"],
        f.quarantine_payload(general["id"], QUARANTINE_START, QUARANTINE_END),
        CLERK,
    )
    validate_error(response, ERR_BAY_TYPE_MISMATCH, 409)

    unchanged = fx.read_return_line(api, line["id"])
    assert unchanged["bay_id"] is None
    assert unchanged["quarantine_start_at"] is None
    assert_line_states(unchanged, disposition_state=DS_RECEIVED_UNGRADED)

    # The identical window against a correctly typed bay is admitted, isolating
    # bay_type as the sole cause of the refusal.
    occupied = validate_success(
        api.quarantine_line(
            line["id"],
            f.quarantine_payload(quarantine["id"], QUARANTINE_START, QUARANTINE_END),
            CLERK,
        ),
        200,
    )
    assert occupied["bay_id"] == quarantine["id"]


def test_an_ordinary_line_has_nothing_to_quarantine_for(api):
    """PRD §3.4: "Quarantine is only meaningful for a line whose item has a
    `hazard_class` other than `NONE` or a `recall_status` other than `NONE`;
    requesting it for an ordinary line is refused with
    `ERR_QUARANTINE_NOT_APPLICABLE`."

    Design: Corner/validations/corner_val_quarantining_an_ordinary_line_is_not_applicable
    """
    bay = fx.make_hazmat_bay(api, bay_code="HZ-VA9")
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "Val Nine", "client_code": "VA9"},
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-VA9",
    )
    line = world["line"]

    response = api.quarantine_line(
        line["id"],
        f.quarantine_payload(bay["id"], QUARANTINE_START, QUARANTINE_END),
        CLERK,
    )
    validate_error(response, ERR_QUARANTINE_NOT_APPLICABLE, 409)

    _, meta = validate_paginated(
        api.list_return_lines(ADMIN, {"bay_id": bay["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "the bay was never occupied"
    assert_line_states(
        fx.read_return_line(api, line["id"]),
        disposition_state=DS_RECEIVED_UNGRADED,
    )

    # No quarantine was ever owed, so grading proceeds straight away.
    graded = validate_success(
        api.grade_line(line["id"], f.grade_payload(GRADE_A), GRADER), 200
    )
    assert_line_states(
        graded, disposition_state=DS_DISPOSITION_ASSIGNED, condition_grade=GRADE_A
    )


def test_a_recall_permanently_bars_an_untouched_work_order_from_starting(api):
    """PRD §3.8: "A work order still in `OPEN` is deliberately **not** swept: it
    has consumed no bay time and no labour, so there is nothing to write off — it
    stays `OPEN` and is instead permanently barred from ever starting by the
    recall rule, which refuses it with `ERR_RECALLED_ITEM_NOT_REFURBISHABLE`."

    Design: Corner/validations/corner_val_open_work_order_cannot_start_after_a_mandatory_recall
    """
    bay = fx.make_general_bay(api, bay_code="GN-VB1")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB1", name="Val Ten"),
        items=[
            fx.widget_item_kwargs(
                sku="REF-1", description="Refurbishable widget", refurb_eligible=True
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_B,
        tracking_reference="TRK-VB1",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_REFURBISH)

    work_order = fx.open_work_order(api, line["id"], TECHNICIAN)
    assert work_order["status"] == WO_OPEN

    fx.file_recall(api, world["item"]["id"], RECALL_MANDATORY)

    response = api.start_test(
        work_order["id"],
        f.start_test_payload(bay["id"], RECALLED_TEST_START, RECALLED_TEST_END),
        TECHNICIAN,
    )
    validate_error(response, ERR_RECALLED_ITEM_NOT_REFURBISHABLE, 409)

    stranded = fx.read_work_order(api, work_order["id"])
    assert stranded["status"] == WO_OPEN, "the untouched order is not swept anywhere"
    assert stranded["bay_id"] is None
    assert stranded["labor_minutes_total"] == 0
    assert_money(stranded["total_cost_cents"], 0, "total_cost_cents")

    # The recall cascade still forced the line's commercial destination.
    assert_line_states(
        fx.read_return_line(api, line["id"]), disposition=DISPOSITION_DESTROY
    )
    assert fx.list_ledger(api, world["client"]["id"]) == [], (
        "an OPEN work order has no labour to write off"
    )

    abandoned = fx.abandon_work_order(api, work_order["id"], TECHNICIAN)
    assert abandoned["status"] == WO_ABANDONED
    assert fx.list_ledger(api, world["client"]["id"]) == [], (
        "abandoning straight out of OPEN appends no ledger entry at all"
    )


def test_a_regulated_item_cannot_be_overridden_into_a_donation(api):
    """PRD §3.4: "The override is refused when the item's `recall_status` is
    `MANDATORY`, with `ERR_RECALL_DISPOSITION_LOCKED`, and refused when the
    requested value is `DONATE` while the item's `regulated_flag` is true, with
    `ERR_REGULATED_DONATION_FORBIDDEN`."

    Design: Corner/validations/corner_val_regulated_item_cannot_be_overridden_to_donate
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "VB2", name="Val Eleven", donation_allowed=True
        ),
        items=[
            fx.widget_item_kwargs(
                sku="REG-1", description="Regulated goods", regulated_flag=True
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VB2",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE)

    response = api.override_disposition(
        line["id"], f.override_payload(DISPOSITION_DONATE), SUPERVISOR
    )
    validate_error(response, ERR_REGULATED_DONATION_FORBIDDEN, 409)

    unchanged = fx.read_return_line(api, line["id"])
    assert_line_states(
        unchanged,
        disposition=DISPOSITION_LIQUIDATE,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        condition_grade=GRADE_C,
    )
    assert_money(unchanged["recovery_value_cents"], 7200, "recovery_value_cents")

    # A destination other than DONATE is accepted for the very same line.
    overridden = validate_success(
        api.override_disposition(
            line["id"], f.override_payload(DISPOSITION_DESTROY), SUPERVISOR
        ),
        200,
    )
    assert overridden["disposition"] == DISPOSITION_DESTROY


def test_a_hazardous_unit_cannot_be_routed_to_an_uncertified_outlet(api):
    """PRD §2.6: "Priority 34 requires the resolved channel to carry
    `hazard_certified` true whenever the line's `hazard_class` is other than
    `NONE`, and `recall_certified` true whenever its `recall_status` is
    `MANDATORY`, failing disposition-order creation with
    `ERR_CHANNEL_NOT_HAZARD_CERTIFIED`."

    Design: Corner/validations/corner_val_hazardous_line_cannot_route_to_an_uncertified_channel
    """
    bay = fx.make_hazmat_bay(api, bay_code="HZ-VB3")
    uncertified = fx.make_destruction_channel(
        api,
        name="Plain Burn",
        channel_code="VB3A",
        accepted_grades=[GRADE_A, GRADE_B, GRADE_C, GRADE_D, GRADE_SCRAP],
        fee_pct=0.10,
        hazard_certified=False,
    )
    certified = fx.make_destruction_channel(
        api,
        name="Hazard Burn",
        channel_code="VB3B",
        accepted_grades=[GRADE_A, GRADE_B, GRADE_C, GRADE_D, GRADE_SCRAP],
        fee_pct=0.10,
        hazard_certified=True,
    )
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB3", name="Val Twelve"),
        items=[
            fx.widget_item_kwargs(
                sku="HAZ-1", description="Aerosol can", hazard_class=HAZARD_AEROSOL
            )
        ],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-VB3",
    )
    line_id = world["line"]["id"]
    fx.quarantine_line(api, line_id, bay["id"], QUARANTINE_START, QUARANTINE_END)
    graded = fx.grade_line(api, line_id, GRADE_D)
    assert_line_states(graded, disposition=DISPOSITION_DESTROY)

    payload = f.disposition_order_payload(
        line_id,
        graded["version"],
        channel_id=uncertified["id"],
        channel_window_start_at=LOT_WINDOW_START,
        channel_window_end_at=LOT_WINDOW_END,
    )
    validate_error(
        api.create_disposition_order(payload, SUPERVISOR),
        ERR_CHANNEL_NOT_HAZARD_CERTIFIED,
        409,
    )

    assert fx.orders_for_line(api, line_id) == [], "no order was recorded"
    unchanged = fx.read_return_line(api, line_id)
    assert unchanged["version"] == graded["version"], (
        "the refused proposal did not consume the line's version"
    )
    assert_line_states(unchanged, disposition_state=DS_DISPOSITION_ASSIGNED)

    # The same payload against the certified twin is accepted.
    order = validate_success(
        api.create_disposition_order(
            {**payload, "channel_id": certified["id"]}, SUPERVISOR
        ),
        201,
    )
    assert order["channel_id"] == certified["id"]
    assert order["disposition"] == DISPOSITION_DESTROY


def test_a_channel_refuses_a_grade_outside_its_accepted_list(api):
    """PRD §2.6: "Priority 48 requires the resolved channel's `accepted_grades` to
    contain the line's `condition_grade` and the channel's `channel_type` to be one
    of the types that serves the line's `disposition`, failing with
    `ERR_CHANNEL_GRADE_NOT_ACCEPTED`."

    Design: Corner/validations/corner_val_channel_refuses_a_grade_outside_accepted_grades
    """
    picky = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code="VB4",
            name="Picky Liquidator",
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_A, GRADE_B],
        ),
    )
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB4", name="Val Thirteen"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VB4",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE, condition_grade=GRADE_C)

    response = api.create_disposition_order(
        f.disposition_order_payload(
            line["id"],
            line["version"],
            channel_id=picky["id"],
            channel_window_start_at=LOT_WINDOW_START,
            channel_window_end_at=LOT_WINDOW_END,
        ),
        SUPERVISOR,
    )
    validate_error(response, ERR_CHANNEL_GRADE_NOT_ACCEPTED, 409)

    _, meta = validate_paginated(
        api.list_disposition_orders(ADMIN, {"channel_id": picky["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "the channel took no lot"
    unchanged = fx.read_return_line(api, line["id"])
    assert unchanged["version"] == line["version"]
    assert_line_states(unchanged, disposition_state=DS_DISPOSITION_ASSIGNED)


def test_an_empty_candidate_set_refuses_the_order_outright(api):
    """PRD §3.6: "When the candidate set is empty the request is refused with
    `ERR_NO_ELIGIBLE_CHANNEL`; there is no implicit fallback channel and no
    deferred queue."

    Design: Corner/validations/corner_val_selector_with_no_candidate_channel_rejects_the_order
    """
    fx.make_donation_channel(api, name="Only Charity", channel_code="VB5D")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB5", name="Val Fourteen"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VB5",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE)

    selector_payload = f.disposition_order_payload(
        line["id"],
        line["version"],
        channel_window_start_at=LOT_WINDOW_START,
        channel_window_end_at=LOT_WINDOW_END,
    )
    assert "channel_id" not in selector_payload, (
        "the selector runs precisely because no channel was named"
    )
    validate_error(
        api.create_disposition_order(selector_payload, SUPERVISOR),
        ERR_NO_ELIGIBLE_CHANNEL,
        409,
    )
    assert fx.orders_for_line(api, line["id"]) == []

    # Registering one channel that can serve LIQUIDATE at grade C is enough.
    liquidator = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code="VB5L",
            name="Late Liquidator",
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_C],
        ),
    )
    order = validate_success(
        api.create_disposition_order(selector_payload, SUPERVISOR), 201
    )
    assert order["channel_id"] == liquidator["id"]
    assert order["selected_by_policy"] is True


def test_a_lot_value_exactly_equal_to_the_channel_minimum_is_admitted(api):
    """PRD §2.6: "Priority 60 requires the lot's projected net recovery to be at
    least the channel's `min_lot_value_cents`, with exact equality satisfying the
    rule; it guards disposition-order creation and returns
    `ERR_CHANNEL_MIN_LOT_NOT_MET`."

    Design: Corner/validations/corner_val_channel_min_lot_value_is_satisfied_at_exact_equality
    """
    # Grade C carries a 7200-cent recovery value; a 12 percent commission on it
    # is 864 cents plus the 6 percent small-lot surcharge, netting 5904 cents.
    tight = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code="VB6T",
            name="Tight Liquidator",
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_C],
            min_lot_value_cents=5905,
        ),
    )
    exact = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code="VB6E",
            name="Exact Liquidator",
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_C],
            min_lot_value_cents=5904,
        ),
    )
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB6", name="Val Fifteen"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VB6",
    )
    line = world["line"]
    assert_money(line["recovery_value_cents"], 7200, "recovery_value_cents")

    payload = f.disposition_order_payload(
        line["id"],
        line["version"],
        channel_id=tight["id"],
        channel_window_start_at=LOT_WINDOW_START,
        channel_window_end_at=LOT_WINDOW_END,
    )
    validate_error(
        api.create_disposition_order(payload, SUPERVISOR),
        ERR_CHANNEL_MIN_LOT_NOT_MET,
        409,
    )
    _, meta = validate_paginated(
        api.list_disposition_orders(ADMIN, {"channel_id": tight["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "one cent short took no lot"

    admitted = validate_success(
        api.create_disposition_order(
            {**payload, "channel_id": exact["id"]}, SUPERVISOR
        ),
        201,
    )
    assert_money(admitted["unit_price_cents"], 7200, "unit_price_cents")
    assert admitted["quantity"] == 1
    assert admitted["selected_by_policy"] is False
    assert_pct_equals(admitted["effective_fee_pct"], 0.00, "effective_fee_pct")
    assert_money(admitted["channel_fee_cents"], 0, "channel_fee_cents")


def test_an_echoed_disposition_must_match_the_lines_own(api):
    """PRD §3.6: "`disposition` and `quantity` may be echoed back for
    confirmation, but they are never *inputs*: the order always copies
    `disposition` and `quantity` from the line itself and freezes them, and when
    the echo fields are supplied and disagree with the line the request is refused
    with `ERR_DISPOSITION_DRIFT`."

    Design: Corner/validations/corner_val_order_disposition_must_match_the_line_disposition
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB7", name="Val Sixteen"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VB7",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE)

    response = api.create_disposition_order(
        f.disposition_order_payload(
            line["id"],
            line["version"],
            disposition=DISPOSITION_RESTOCK,
            channel_window_start_at=LOT_WINDOW_START,
            channel_window_end_at=LOT_WINDOW_END,
        ),
        SUPERVISOR,
    )
    validate_error(response, ERR_DISPOSITION_DRIFT, 409)

    unchanged = fx.read_return_line(api, line["id"])
    assert_line_states(unchanged, disposition=DISPOSITION_LIQUIDATE)
    assert unchanged["version"] == line["version"]
    assert fx.orders_for_line(api, line["id"]) == []

    # Once the line itself is RESTOCK the identical echo agrees with it.
    overridden = validate_success(
        api.override_disposition(
            line["id"], f.override_payload(DISPOSITION_RESTOCK), SUPERVISOR
        ),
        200,
    )
    order = validate_success(
        api.create_disposition_order(
            f.disposition_order_payload(
                line["id"], overridden["version"], disposition=DISPOSITION_RESTOCK
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert order["disposition"] == DISPOSITION_RESTOCK
    assert order["channel_id"] is None, "restocking needs no secondary-market outlet"


def test_a_test_window_inside_the_bay_buffer_is_refused(api):
    """PRD §3.5: "Unlike a quarantine occupation, a test window is inclusive of
    both its endpoints, and the collision test is widened: each existing window in
    that bay is extended by the bay's `buffer_minutes` on **both** sides before the
    overlap is evaluated, so a window that begins exactly `buffer_minutes` after
    another ends is accepted while one starting a minute earlier is rejected with
    `ERR_BAY_BUFFER_VIOLATION`."

    Design: Corner/validations/corner_val_test_window_inside_the_bay_buffer_is_rejected
    """
    bay = fx.make_general_bay(api, bay_code="GN-VB8", buffer_minutes=30)
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VB8", name="Val Seventeen"),
        items=[
            fx.widget_item_kwargs(
                sku="REF-1", description="Refurbishable widget", refurb_eligible=True
            )
        ],
        lines=[
            {
                "authorized_quantity": 2,
                "reason_code": REASON_DEFECTIVE,
                "scan_quantity": 1,
            }
        ],
        tracking_reference="TRK-VB8",
    )
    second_unit = fx.scan_line(
        api, world["receipt"]["id"], world["rma_line"]["id"], quantity=1
    )
    first_line = fx.grade_line(api, world["line"]["id"], GRADE_B)
    second_line = fx.grade_line(api, second_unit["id"], GRADE_B)
    assert_line_states(first_line, disposition=DISPOSITION_REFURBISH)
    assert_line_states(second_line, disposition=DISPOSITION_REFURBISH)

    first_order = fx.open_work_order(api, first_line["id"], TECHNICIAN)
    second_order = fx.open_work_order(api, second_line["id"], TECHNICIAN_2)
    fx.start_test(
        api, first_order["id"], bay["id"], FIRST_TEST_START, FIRST_TEST_END, TECHNICIAN
    )

    # One minute inside the 30-minute decontamination gap that follows 02:00.
    response = api.start_test(
        second_order["id"],
        f.start_test_payload(bay["id"], INSIDE_BUFFER_START, SECOND_TEST_END),
        TECHNICIAN_2,
    )
    validate_error(response, ERR_BAY_BUFFER_VIOLATION, 409)

    stalled = fx.read_work_order(api, second_order["id"])
    assert stalled["status"] == WO_OPEN
    assert stalled["bay_id"] is None
    assert stalled["test_window_start_at"] is None

    # Exactly on the edge of the gap the bay is free again.
    started = fx.start_test(
        api,
        second_order["id"],
        bay["id"],
        BUFFER_EDGE_START,
        SECOND_TEST_END,
        TECHNICIAN_2,
    )
    assert started["status"] == WO_IN_TEST
    assert_instant_equals(
        started["test_window_start_at"], BUFFER_EDGE_START, "test_window_start_at"
    )
    _, meta = validate_paginated(
        api.list_work_orders(ADMIN, {"bay_id": bay["id"], "limit": 100})
    )
    assert meta["total_count"] == 2, "both windows now live in the same bay"


def test_an_authorization_with_no_lines_cannot_be_issued(api):
    """PRD §2.6: "Priority 40 refuses to issue an authorization carrying zero
    declared lines, with `ERR_RMA_NO_LINES`."

    Design: Corner/validations/corner_val_rma_with_no_lines_cannot_be_issued
    """
    client = fx.make_client(api, name="Val Eighteen", client_code="VB9")
    rma = fx.make_draft_rma(
        api, client["id"], order_reference="ORD-VB9", customer_reference="CUST-VB9"
    )

    validate_error(api.issue_rma(rma["id"], ADMIN), ERR_RMA_NO_LINES, 409)

    unchanged = fx.read_rma(api, rma["id"])
    assert unchanged["status"] == RMA_DRAFT
    assert unchanged["authorized_unit_total"] == 0
    assert unchanged["issued_at"] is None

    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    fx.add_rma_line(api, rma["id"], item["id"], authorized_quantity=1)
    issued = validate_success(api.issue_rma(rma["id"], ADMIN), 200)
    assert issued["status"] == RMA_ISSUED
    assert issued["authorized_unit_total"] == 1


def test_a_line_whose_item_is_not_refurbishable_cannot_open_a_work_order(api):
    """PRD §2.6: "Priority 44 permits a work order only for a line whose catalogue
    item is `refurb_eligible` and whose `disposition` is `REFURBISH`, failing with
    `ERR_LINE_NOT_REFURBISHABLE`."

    Design: Corner/validations/corner_val_non_refurb_eligible_line_cannot_open_a_work_order
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VC1", name="Val Nineteen"),
        items=[fx.widget_item_kwargs(refurb_eligible=False)],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VC1",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE)

    # The override satisfies the disposition half of the rule, leaving only the
    # item's own refurb_eligible flag to refuse the work order.
    overridden = validate_success(
        api.override_disposition(
            line["id"], f.override_payload(DISPOSITION_REFURBISH), SUPERVISOR
        ),
        200,
    )
    assert overridden["disposition"] == DISPOSITION_REFURBISH

    response = api.create_work_order(f.work_order_payload(line["id"]), TECHNICIAN)
    validate_error(response, ERR_LINE_NOT_REFURBISHABLE, 409)

    _, meta = validate_paginated(
        api.list_work_orders(ADMIN, {"return_line_id": line["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "no work order was opened"
    assert_line_states(
        fx.read_return_line(api, line["id"]),
        disposition=DISPOSITION_REFURBISH,
        disposition_state=DS_DISPOSITION_ASSIGNED,
    )


def test_a_refund_released_one_millisecond_early_is_refused(api):
    """PRD §2.6: "Priority 58 requires the current logical time to be at or after
    the refund release's `release_eligible_at`, failing with
    `ERR_REFUND_HOLD_ACTIVE`."

    Design: Corner/validations/corner_val_refund_released_one_millisecond_early_is_rejected
    """
    channel = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code="VC2",
            name="Hold Auction",
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_C],
        ),
    )
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VC2", name="Val Twenty"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VC2",
    )
    line = world["line"]
    order = fx.propose_and_approve(
        api,
        line["id"],
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
        approver=SUPERVISOR,
    )
    fx.execute_order(api, order["id"], headers=SUPERVISOR_2)

    # The 48-hour hold starts from the execution instant, which is the startup
    # clock, so the money comes due at 2026-08-03T00:00:00.000Z.
    eligible_at = plus_hours(CLOCK_STARTUP_INSTANT, DEFAULT_REFUND_HOLD_HOURS)
    release = fx.refund_release_for_line(api, line["id"])
    assert_instant_equals(
        release["release_eligible_at"], eligible_at, "release_eligible_at"
    )
    assert release["released_at"] is None
    assert_money(release["gross_refund_cents"], 20000, "gross_refund_cents")
    assert_pct_equals(release["restocking_fee_pct"], 0.10, "restocking_fee_pct")
    assert_money(release["restocking_fee_cents"], 2000, "restocking_fee_cents")
    assert_money(release["net_refund_cents"], 18000, "net_refund_cents")
    assert_line_states(
        fx.read_return_line(api, line["id"]), financial_state=FS_RELEASE_PENDING
    )

    fx.set_clock(api, plus_millis(eligible_at, -1))
    validate_error(
        api.release_refund(line["id"], ANALYST), ERR_REFUND_HOLD_ACTIVE, 409
    )
    assert fx.refund_release_for_line(api, line["id"])["released_at"] is None
    assert_line_states(
        fx.read_return_line(api, line["id"]), financial_state=FS_RELEASE_PENDING
    )

    fx.set_clock(api, eligible_at)
    validate_success(api.release_refund(line["id"], ANALYST), 200)
    released = fx.refund_release_for_line(api, line["id"])
    assert_instant_equals(released["released_at"], eligible_at, "released_at")
    assert_line_states(
        fx.read_return_line(api, line["id"]), financial_state=FS_REFUNDED
    )


def test_a_fraud_hold_blocks_the_refund_until_it_is_cleared(api):
    """PRD §2.6: "Priority 38 rejects a refund release while the line's
    `financial_state` is `FRAUD_HOLD` with `ERR_FRAUD_HOLD_ACTIVE`; the hold must
    first be cleared through the hold-clearing action."

    Design: Corner/validations/corner_val_fraud_hold_blocks_the_refund_release
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "VC3",
            name="Val Twenty One",
            fraud_tolerance_cents=DEFAULT_FRAUD_TOLERANCE_CENTS,
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        gross_weight_grams=100,
        tracking_reference="TRK-VC3",
    )
    line = world["line"]
    assert world["receipt"]["expected_weight_grams"] == 1400
    assert world["receipt"]["empty_box_suspected"] is True

    # 50 points at the dock for the empty box, plus 20 at grading because the
    # 20000-cent declared value exceeds the 7200-cent recovery by more than the
    # client's 5000-cent tolerance.
    assert line["fraud_score_receipt"] == 50
    assert line["fraud_score_release"] == 70
    assert_line_states(line, financial_state=FS_FRAUD_HOLD)

    checks = fx.fraud_checks_for_line(api, line["id"])
    assert len(checks) == 4, "two dock rows plus two grading rows"
    outcomes = {row["check_type"]: row["outcome"] for row in checks}
    assert outcomes == {
        CHECK_EMPTY_BOX: OUTCOME_FAIL,
        CHECK_SERIAL_MISMATCH: OUTCOME_PASS,
        CHECK_VALUE_ANOMALY: OUTCOME_FAIL,
        CHECK_REPEAT_RETURNER: OUTCOME_PASS,
    }

    validate_error(
        api.release_refund(line["id"], ANALYST), ERR_FRAUD_HOLD_ACTIVE, 409
    )
    assert fx.refund_release_for_line(api, line["id"])["released_at"] is None

    cleared = validate_success(
        api.clear_fraud_hold(line["id"], f.clear_fraud_hold_payload(), ANALYST), 200
    )
    assert_line_states(cleared, financial_state=FS_HOLD_PENDING_DISPOSITION)
    assert cleared["fraud_score_release"] == 70, (
        "the score is permanent evidence and only the state is the gate"
    )


def test_a_destruction_cannot_be_executed_by_its_own_approver(api):
    """PRD §3.6: "The channel must still be `ACTIVE`, or the request fails with
    `ERR_CHANNEL_PAUSED`, and when the order's disposition is `DESTROY` for a
    client whose `destroy_requires_dual_signoff` is true, the acting `X-User-ID`
    must differ from `approved_by_user_id` or the request fails with
    `ERR_DUAL_SIGNOFF_REQUIRED`."

    Design: Corner/validations/corner_val_destroy_execution_requires_a_second_signature
    """
    channel = fx.make_destruction_channel(
        api,
        name="Dual Burn",
        channel_code="VC4",
        accepted_grades=[GRADE_C, GRADE_D, GRADE_SCRAP],
    )
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "VC4", name="Val Twenty Two", destroy_requires_dual_signoff=True
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_SCRAP,
        tracking_reference="TRK-VC4",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_DESTROY)

    order = fx.propose_and_approve(
        api,
        line["id"],
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
        approver=SUPERVISOR,
    )
    assert order["approved_by_user_id"] == USER_SUPERVISOR

    validate_error(
        api.execute_disposition_order(order["id"], SUPERVISOR, f.execute_payload()),
        ERR_DUAL_SIGNOFF_REQUIRED,
        409,
    )

    stalled = fx.read_order(api, order["id"])
    assert stalled["status"] == DO_APPROVED
    assert stalled["approved_by_user_id"] == USER_SUPERVISOR
    assert stalled["executed_by_user_id"] is None
    assert stalled["executed_at"] is None
    _, meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"return_line_id": line["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, "no destruction was booked"

    executed = fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    assert executed["status"] == DO_EXECUTED
    assert executed["executed_by_user_id"] == USER_SUPERVISOR_2
