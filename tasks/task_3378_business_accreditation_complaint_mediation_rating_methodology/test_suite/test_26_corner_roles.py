"""Corner queue — RBAC: role authorization denials (ERR_UNAUTHORIZED) and
entity-backed ownership denials (ERR_FORBIDDEN_OWNERSHIP) (PRD §2.1)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    business_respond,
    complaint_response_payload,
    create_application,
    create_bureau,
    create_business,
    create_consumer,
    create_rating_snapshot_payload,
    decide_application_payload,
    file_and_forward_complaint,
    file_complaint,
    forward_complaint,
    get_business,
    get_complaint,
    get_invoice,
    ledger_entry_payload,
    make_business_rep_headers,
    make_consumer_headers,
    set_clock,
    setup_approved_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _setup_world():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    return bureau, consumer, business


def test_consumer_cannot_forward_complaint(api):
    """PRD §2.1: "A request whose role is not listed among an operation's
    authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "A `BureauAdmin` forwards a received complaint to the business:
    the status moves from `RECEIVED` to `FORWARDED`, `forwarded_at` is
    stamped, and `response_deadline_at` is set exactly 14 days later —
    precisely 1209600 seconds after `forwarded_at`."

    Design: Corner/roles/consumer_cannot_forward_complaint
    """
    _bureau, consumer, business = _setup_world()
    complaint = file_complaint(consumer, business)
    # Even the filing consumer is outside the forward operation's role list.
    resp = api.forward_complaint(
        complaint["id"], make_consumer_headers(consumer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_complaint(complaint["id"])["status"] == "RECEIVED"


def test_businessrep_cannot_publish_rating_snapshot(api):
    """PRD §3.7: "Only a `BureauAdmin` publishes."
    PRD §2.1: "A request whose role is not listed among an operation's
    authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/roles/businessrep_cannot_publish_rating_snapshot
    """
    _bureau, _consumer, business = _setup_world()
    resp = api.create_rating_snapshot(
        business["id"], create_rating_snapshot_payload("PUBLISHED"),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    rows, meta = validate_paginated(
        api.list_rating_snapshots(business["id"], ADMIN))
    assert rows == [] and meta["total_count"] == 0


def test_standards_reviewer_cannot_run_daily_close(api):
    """PRD §2.1: "`StandardsReviewer` owns accreditation decisions and
    advertising-review conclusions — a duty segregated from bureau
    operations"
    PRD §2.1: "A request whose role is not listed among an operation's
    authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.4: "Each run increments the bureau's `ops_day_index` by exactly 1"

    Design: Corner/roles/standards_reviewer_cannot_run_daily_close
    """
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    resp = api.run_daily_close(bureau["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    # The rejected call performed no sweep: the first real close reports 1.
    assert validate_success(api.run_daily_close(bureau["id"], ADMIN),
                            200)["ops_day_index"] == 1


def test_businessrep_cannot_post_refund_ledger_entry(api):
    """PRD §3.3: "Refunds are the bureau's lever. A `BureauAdmin` posts an
    entry with `kind` `REFUND`, again with `amount_cents` of at least 1,
    bounded by the net amount actually collected: a refund larger than
    `paid_cents` minus `refunded_cents` is rejected with
    `ERR_REFUND_EXCEEDS_PAID`."
    PRD §2.1: "A request whose role is not listed among an operation's
    authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/roles/businessrep_cannot_post_refund_ledger_entry
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    business = create_business(legal_name="Refund Role Micro LLC",
                               home_state_code="IA", employee_count=2,
                               founded_on="2020-01-01T00:00:00Z")
    _app, invoice = setup_approved_application(business)
    validate_success(api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("PAYMENT", 40375),
        make_business_rep_headers(business["id"])), 201)
    # The owning BusinessRep may pay but never refunds: REFUND is
    # BureauAdmin-only.
    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("REFUND", 1000),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    current = get_invoice(business["id"], invoice["id"])
    assert current["status"] == "PAID"
    assert current["refunded_cents"] == 0


def test_businessrep_cannot_respond_to_other_business_complaint(api):
    """PRD §2.1: "When `X-User-Role` is `BusinessRep`, `X-User-ID` is the
    `id` of the acting Business; ownership checks on any resource that
    references a Business compare the resource's business field to
    `X-User-ID`."
    PRD §2.1: "An entity-backed role acting on a resource it does not own is
    rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/roles/businessrep_cannot_respond_to_other_business_complaint
    """
    _bureau, consumer, biz_a = _setup_world()
    biz_b = create_business(legal_name="Interloper B LLC",
                            home_state_code="IA", employee_count=250,
                            founded_on="2018-01-01T00:00:00Z")
    complaint = file_and_forward_complaint(consumer, biz_a,
                                           description="against A")
    # B's representative answers a complaint against A.
    resp = api.add_complaint_response(
        complaint["id"],
        complaint_response_payload(kind="BUSINESS_RESPONSE",
                                   body="B pretending to be A"),
        make_business_rep_headers(biz_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    current = get_complaint(complaint["id"])
    assert current["status"] == "FORWARDED"
    assert current["responses"] == []


def test_consumer_cannot_rebut_other_consumers_complaint(api):
    """PRD §2.1: "When `X-User-Role` is `Consumer`, `X-User-ID` is the `id`
    of the acting Consumer; ownership checks compare the filing consumer's
    `id` — the `consumer_id` on creation payloads, or the complaint's filer
    on response and mediation actions — to `X-User-ID`."
    PRD §2.1: "An entity-backed role acting on a resource it does not own is
    rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/roles/consumer_cannot_rebut_other_consumers_complaint
    """
    _bureau, consumer1, business = _setup_world()
    consumer2 = create_consumer(full_name="Second Consumer",
                                email="second@example.com",
                                home_state_code="IA")
    complaint = file_and_forward_complaint(consumer1, business)
    business_respond(complaint, business, body="offer")
    # A different consumer holds no verdict on this complaint.
    resp = api.add_complaint_response(
        complaint["id"],
        complaint_response_payload(kind="CONSUMER_REBUTTAL",
                                   body="not mine"),
        make_consumer_headers(consumer2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert get_complaint(complaint["id"])["rebuttal_count"] == 0
