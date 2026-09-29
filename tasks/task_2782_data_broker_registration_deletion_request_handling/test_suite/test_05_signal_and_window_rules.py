"""Opt-out preference signals, suppression lifts, fee deposits and interval bounds.

Each test builds its own broker and consumer from scratch: the harness restarts
the API and wipes the database before every individual test.
"""

import pytest

from test_helpers import (
    CLOCK_TEST_INSTANT,
    REVIEWER_ALPHA_HEADERS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_cents_equals,
    assert_instant_equals,
    create_suppression_entry,
    fetch_broker,
    fetch_consumer,
    fetch_suppression_entry,
    make_consumer_headers,
    onboard_broker,
    open_deletion_request,
    record_consumer,
    validate_error,
    validate_paginated,
    validate_success,
)

INTAKE_AGENT_HEADERS = TEST_USERS["intake_agent_headers"]


def _audit_event_count(broker_id, headers, event_type):
    """total_count of one broker's audit events narrowed to a single type."""
    _, meta = validate_paginated(
        api_client.list_audit_events(
            broker_id, headers, params={"event_type": event_type}
        )
    )
    return meta["total_count"]


def _list_total_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _broker_with_consumer(identity_hash, deposit_cents=0):
    """One broker and one CA consumer of it, at the standard clock instant."""
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=deposit_cents)
    ctx["consumer"] = record_consumer(
        ctx["broker_id"],
        identity_hash=identity_hash,
        source_label="OWNERSHIP_FEED_D",
        derived_profile_count=0,
    )
    ctx["consumer_id"] = ctx["consumer"]["id"]
    ctx["consumer_headers"] = make_consumer_headers(ctx["consumer"]["id"])
    return ctx


@pytest.mark.parametrize(
    "signal_type,scope,credentials,acts_as_consumer",
    [
        ("GPC_BROWSER", "SALE_AND_SHARING", {"gpc_header_value": "0"}, True),
        ("AGENT_SUBMITTED", "SALE", {}, False),
    ],
    ids=["gpc_browser_header_zero", "agent_submitted_without_reference"],
)
def test_unrecognized_opt_out_signal_is_refused(
    signal_type, scope, credentials, acts_as_consumer
):
    """PRD §3.7: "A `GPC_BROWSER` signal must carry a `gpc_header_value` exactly
    equal to the string `1`, and an `AGENT_SUBMITTED` signal must carry a
    non-empty `agent_reference`; any other combination answers
    `ERR_OPT_OUT_SIGNAL_UNRECOGNIZED`."
    PRD §3.3: "Creation also sets `opt_out_sale` and `opt_out_sharing` to false
    and `last_purged_at` to null, and appends a `CONSUMER_RECORDED` audit event."
    PRD §3.7: "An accepted signal is created in `RECEIVED` with `honored_at` null
    and `honor_deadline_at` set to the creation clock instant advanced by 45 whole
    days, which is the statutory outer limit for acting on it, and the parent
    consumer's `version` increases by one."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"

    Design: Corner/validations/unrecognized_opt_out_signals_rejected
    """
    ctx = _broker_with_consumer("sha256:gpc00001gpc00001")
    assert ctx["consumer"]["version"] == 1

    payload = {
        "broker_id": ctx["broker_id"],
        "consumer_id": ctx["consumer_id"],
        "signal_type": signal_type,
        "scope": scope,
        "expected_consumer_version": ctx["consumer"]["version"],
    }
    payload.update(credentials)
    headers = ctx["consumer_headers"] if acts_as_consumer else INTAKE_AGENT_HEADERS

    response = api_client.create_opt_out_signal(payload, headers)
    validate_error(response, ApiErrorId.ERR_OPT_OUT_SIGNAL_UNRECOGNIZED, 422)

    assert (
        _list_total_count(
            api_client.list_opt_out_signals(
                ctx["broker_headers"], params={"consumer_id": ctx["consumer_id"]}
            )
        )
        == 0
    )
    refreshed = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert refreshed["opt_out_sale"] is False
    assert refreshed["opt_out_sharing"] is False
    assert refreshed["version"] == 1


def test_gpc_browser_signal_with_value_one_is_honored_in_the_creating_request():
    """PRD §3.7: "Two mechanisms are honored **inside the creating request**
    rather than deferred: a `GPC_BROWSER` signal carrying the value `1`, and any
    `PLATFORM_BULK` signal, because a browser control and a bulk platform
    submission are both machine-readable and need no human handling."
    PRD §3.7: "For those the signal moves `RECEIVED → HONORED` immediately,
    `honored_at` is set to the current clock instant, the consumer's
    `opt_out_sale` is set true when `scope` is `SALE` or `SALE_AND_SHARING`, the
    consumer's `opt_out_sharing` is set true when `scope` is `SHARING` or
    `SALE_AND_SHARING`, and an `OPT_OUT_HONORED` audit event is appended after
    the `OPT_OUT_RECEIVED` one, in that order."
    PRD §3.7: "An accepted signal is created in `RECEIVED` with `honored_at` null
    and `honor_deadline_at` set to the creation clock instant advanced by 45 whole
    days, which is the statutory outer limit for acting on it, and the parent
    consumer's `version` increases by one."
    PRD §2.7: "Adding n days to an instant advances it by exactly n times
    twenty-four hours and preserves the time-of-day component of the base
    instant; the result is stored as ISO 8601 UTC with three fractional digits."

    Design: Corner/validations/gpc_browser_signal_with_value_one_is_honored_in_the_creating_request
    """
    ctx = _broker_with_consumer("sha256:gpc00002gpc00002")

    signal = validate_success(
        api_client.create_opt_out_signal(
            {
                "broker_id": ctx["broker_id"],
                "consumer_id": ctx["consumer_id"],
                "signal_type": "GPC_BROWSER",
                "scope": "SALE_AND_SHARING",
                "expected_consumer_version": ctx["consumer"]["version"],
                "gpc_header_value": "1",
            },
            ctx["consumer_headers"],
        ),
        201,
    )

    assert signal["status"] == "HONORED"
    assert_instant_equals(signal["honored_at"], "2026-09-01T00:00:00Z", "honored_at")
    assert_instant_equals(
        signal["honor_deadline_at"], "2026-10-16T00:00:00Z", "honor_deadline_at"
    )

    refreshed = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    assert refreshed["opt_out_sale"] is True
    assert refreshed["opt_out_sharing"] is True
    assert refreshed["version"] == 2

    assert (
        _audit_event_count(ctx["broker_id"], ctx["broker_headers"], "OPT_OUT_RECEIVED")
        == 1
    )
    assert (
        _audit_event_count(ctx["broker_id"], ctx["broker_headers"], "OPT_OUT_HONORED")
        == 1
    )


def test_lift_justification_shorter_than_twenty_characters_is_refused():
    """PRD §3.7: "A `PrivacyReviewer` or a `PlatformAdmin` lifts an `ACTIVE` entry,
    supplying a `lift_justification` of at least 20 and at most 400 characters, or
    `ERR_LIFT_JUSTIFICATION_REQUIRED` answers"
    PRD §3.7: "The entry is created `ACTIVE` with `blocked_recollection_count` at
    zero and `lift_justification` null, and a `SUPPRESSION_CREATED` audit event is
    appended."
    PRD §3.7: "The entry moves `ACTIVE → LIFTED`, the justification is stored, and
    a `SUPPRESSION_LIFTED` audit event is appended."
    PRD §2.4: "`version`, an integer that begins at 1 when the resource is
    created and increases by one on every mutation of that resource"

    Design: Corner/validations/lift_justification_shorter_than_twenty_characters_rejected
    """
    ctx = _broker_with_consumer("sha256:lift0001lift0001")
    request = open_deletion_request(
        ctx["broker_id"],
        ctx["consumer"],
        intake_channel="EMAIL",
        requested_scope="DELETE_ALL",
    )
    entry = create_suppression_entry(
        ctx["broker_id"],
        ctx["consumer_id"],
        originating_request_id=request["id"],
        source_scope="ALL_SOURCES",
    )
    assert entry["status"] == "ACTIVE"
    assert entry["lift_justification"] is None
    assert entry["version"] == 1

    too_short = "Fresh opt-in filed."
    assert len(too_short) == 19
    response = api_client.lift_suppression_entry(
        entry["id"], {"lift_justification": too_short}, REVIEWER_ALPHA_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_LIFT_JUSTIFICATION_REQUIRED, 422)

    unchanged = fetch_suppression_entry(entry["id"], REVIEWER_ALPHA_HEADERS)
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["lift_justification"] is None
    assert unchanged["version"] == 1

    long_enough = "Fresh opt-in on file"
    assert len(long_enough) == 20
    lifted = validate_success(
        api_client.lift_suppression_entry(
            entry["id"], {"lift_justification": long_enough}, REVIEWER_ALPHA_HEADERS
        ),
        200,
    )
    assert lifted["status"] == "LIFTED"
    assert lifted["lift_justification"] == long_enough
    assert lifted["version"] == 2


@pytest.mark.parametrize("amount_cents", [0, 10000001])
def test_fee_deposit_amount_outside_the_declared_band_is_refused(amount_cents):
    """PRD §3.1: "A `BrokerAdmin` or a `PlatformAdmin` credits the account by
    supplying an `amount_cents` figure, which must be a positive integer no greater
    than 10000000 — a hundred thousand dollars in a single deposit — or the deposit
    is refused with `ERR_FEE_DEPOSIT_INVALID`."
    PRD §3.1: "An accepted deposit increases both `fee_deposited_cents` and
    `fee_credit_cents` by that amount, leaving `fee_paid_cents` untouched, and
    appends a `FEE_DEPOSITED` audit event."
    PRD §3.1: "Every counter on the broker starts at zero: `fee_deposited_cents`,
    `fee_paid_cents`, `fee_credit_cents`, `open_breach_count`,
    `request_intake_total`, `request_open_count`, `request_completed_count`,
    `request_terminated_count`, and `audit_sequence_high_water`."
    PRD §2.6: "`amount_cents` on a fee deposit is a positive integer of at most
    10000000 — otherwise `ERR_FEE_DEPOSIT_INVALID` (422)."

    Design: Corner/validations/fee_deposit_amount_outside_the_declared_band_rejected
    """
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=0)

    response = api_client.create_fee_deposit(
        ctx["broker_id"], {"amount_cents": amount_cents}, ctx["broker_headers"]
    )
    error = validate_error(response, ApiErrorId.ERR_FEE_DEPOSIT_INVALID, 422)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_deposited_cents"], 0, "fee_deposited_cents")
    assert_cents_equals(broker["fee_credit_cents"], 0, "fee_credit_cents")
    assert broker["version"] == 1
    assert (
        _audit_event_count(ctx["broker_id"], ctx["broker_headers"], "FEE_DEPOSITED") == 0
    )


def test_registration_with_a_backwards_coverage_period_is_refused():
    """PRD §2.6: "`coverage_period_start` is strictly before
    `coverage_period_end`, and `window_start` is strictly before `window_end` —
    otherwise `ERR_COVERAGE_PERIOD_INVALID` (422)."
    PRD §3.2: "The filing is created in `DRAFT` with a
    `disclosure_completeness_score` of 0.00, a `revision_count` of 0, a
    `charged_fee_cents` of 0, a `provisional_filing_fee_cents` of 0, a null
    `final_filing_fee_cents`, null `submitted_at` and `accepted_at`, and a null
    `rejection_reason_code`."
    PRD §3.1: "An accepted deposit increases both `fee_deposited_cents` and
    `fee_credit_cents` by that amount, leaving `fee_paid_cents` untouched, and
    appends a `FEE_DEPOSITED` audit event."

    Design: Corner/validations/inverted_coverage_and_suppression_windows_rejected
    """
    ctx = onboard_broker(clock=CLOCK_TEST_INSTANT, deposit_cents=500000)
    assert ctx["broker"]["version"] == 2

    response = api_client.create_registration(
        {
            "broker_id": ctx["broker_id"],
            "state_code": "CA",
            "coverage_period_start": "2027-03-01T00:00:00Z",
            "coverage_period_end": "2026-09-01T00:00:00Z",
            "business_description": (
                "California registry filing whose coverage period is stated back "
                "to front."
            ),
            "expected_broker_version": ctx["broker"]["version"],
        },
        ctx["broker_headers"],
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_PERIOD_INVALID, 422)

    assert (
        _list_total_count(
            api_client.list_registrations(
                ctx["broker_headers"], params={"broker_id": ctx["broker_id"]}
            )
        )
        == 0
    )
    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_credit_cents"], 500000, "fee_credit_cents")
    assert broker["version"] == 2


def test_suppression_entry_with_a_backwards_window_is_refused():
    """PRD §3.7: "`window_start` must be strictly before `window_end`, or
    `ERR_COVERAGE_PERIOD_INVALID` answers."
    PRD §3.7: "The entry is created `ACTIVE` with `blocked_recollection_count` at
    zero and `lift_justification` null, and a `SUPPRESSION_CREATED` audit event is
    appended."
    PRD §3.1: "An accepted deposit increases both `fee_deposited_cents` and
    `fee_credit_cents` by that amount, leaving `fee_paid_cents` untouched, and
    appends a `FEE_DEPOSITED` audit event."

    Design: Corner/validations/inverted_coverage_and_suppression_windows_rejected
    """
    ctx = _broker_with_consumer("sha256:win00001win00001", deposit_cents=500000)

    response = api_client.create_suppression_entry(
        {
            "broker_id": ctx["broker_id"],
            "consumer_id": ctx["consumer_id"],
            "originating_request_id": None,
            "source_scope": "ALL_SOURCES",
            "window_start": "2028-08-31T00:00:00Z",
            "window_end": "2026-09-01T00:00:00Z",
        },
        REVIEWER_ALPHA_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_PERIOD_INVALID, 422)

    assert (
        _list_total_count(
            api_client.list_suppression_entries(
                REVIEWER_ALPHA_HEADERS, params={"broker_id": ctx["broker_id"]}
            )
        )
        == 0
    )
    broker = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    assert_cents_equals(broker["fee_credit_cents"], 500000, "fee_credit_cents")
    assert (
        _audit_event_count(
            ctx["broker_id"], ctx["broker_headers"], "SUPPRESSION_CREATED"
        )
        == 0
    )
