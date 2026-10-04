"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server before every test. Identity
threading: LibraryAdmin calls use make_library_admin_headers(library["id"])
and Patron calls use make_patron_headers(patron["id"]).
"""
import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO, TEST_DEFAULTS
from .factories import (
    create_consortium_payload,
    create_fund_payload,
    create_library_payload,
    create_patron_payload,
    create_title_payload,
)
from .test_users import (
    TEST_USERS,
    make_library_admin_headers,
    make_patron_headers,
)

ADMIN = TEST_USERS["consortium_admin_headers"]
ANALYST = TEST_USERS["system_analyst_headers"]

_counter = [0]


def _uniq(prefix: str) -> str:
    _counter[0] += 1
    return f"{prefix}-{_counter[0]}-{_uuid.uuid4().hex[:8]}"


def set_clock(to_iso8601: str = CLOCK_DEFAULT_ISO):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"clock set failed: {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_consortium(**overrides) -> dict:
    payload = create_consortium_payload(**overrides)
    data = get_success_data(api_client.create_consortium(payload, ADMIN))
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def create_library(consortium_id: str, **overrides) -> dict:
    overrides.setdefault("name", _uniq("Library"))
    payload = create_library_payload(**overrides)
    data = get_success_data(api_client.create_library(consortium_id, payload, ADMIN))
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def create_fund(library_id: str, **overrides) -> dict:
    payload = create_fund_payload(**overrides)
    data = get_success_data(
        api_client.create_fund(library_id, payload, make_library_admin_headers(library_id))
    )
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def create_patron(library_id: str, **overrides) -> dict:
    overrides.setdefault("external_card_number", _uniq("CARD"))
    overrides.setdefault("full_name", _uniq("Patron"))
    payload = create_patron_payload(**overrides)
    data = get_success_data(
        api_client.create_patron(
            library_id, payload, make_library_admin_headers(library_id)
        )
    )
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def create_title(consortium_id: str, **overrides) -> dict:
    payload = create_title_payload(**overrides)
    data = get_success_data(api_client.create_title(consortium_id, payload, ADMIN))
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def fund_version(library_id: str, fund_id: str) -> int:
    data = get_success_data(
        api_client.get_fund(fund_id, make_library_admin_headers(library_id))
    )
    return data["version"]


def create_order(library_id: str, fund_id: str, title_id: str,
                 model: str = "OCOU", copies: int = 1,
                 prepaid_balance_cents=None) -> dict:
    payload = {
        "library_id": library_id,
        "budget_fund_id": fund_id,
        "title_id": title_id,
        "model": model,
        "expected_budget_fund_version": fund_version(library_id, fund_id),
    }
    if model == "OCOU":
        payload["copies"] = copies
    if prepaid_balance_cents is not None:
        payload["prepaid_balance_cents"] = prepaid_balance_cents
    data = get_success_data(
        api_client.create_order(payload, make_library_admin_headers(library_id))
    )
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def propose_order(library_id: str, order_id: str) -> dict:
    return get_success_data(
        api_client.propose_order(order_id, make_library_admin_headers(library_id))
    )


def approve_order(library_id: str, order_id: str) -> dict:
    return get_success_data(
        api_client.approve_order(order_id, make_library_admin_headers(library_id))
    )


def fulfill_order(library_id: str, order_id: str, invoiced_cost_cents: int) -> dict:
    return get_success_data(
        api_client.fulfill_order(
            order_id,
            {"invoiced_cost_cents": invoiced_cost_cents},
            make_library_admin_headers(library_id),
        )
    )


def create_license_via_order(library_id: str, fund_id: str, title_id: str,
                             model: str = "OCOU", copies: int = 1,
                             prepaid_balance_cents=None,
                             invoiced_cost_cents=None,
                             title: dict = None) -> dict:
    """Create an order for the title, propose, approve, fulfill; return the
    freshly created License (looked up via the filtered license list)."""
    order = create_order(
        library_id, fund_id, title_id, model=model, copies=copies,
        prepaid_balance_cents=prepaid_balance_cents,
    )
    propose_order(library_id, order["id"])
    approve_order(library_id, order["id"])
    if invoiced_cost_cents is None:
        invoiced_cost_cents = order["estimated_cost_cents"]
    fulfill_order(library_id, order["id"], invoiced_cost_cents)
    listed = get_success_data(
        api_client.list_licenses(
            make_library_admin_headers(library_id),
            params={"title_id": title_id, "acquisition_order_id": order["id"]},
        )
    )
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows, f"setup failed: no license created for order {order['id']}"
    return rows[0]


def checkout(patron_id: str, title_id: str, skip_the_line: bool = False) -> dict:
    payload = {"patron_id": patron_id, "title_id": title_id}
    if skip_the_line:
        payload["skip_the_line"] = True
    data = get_success_data(
        api_client.checkout(payload, make_patron_headers(patron_id))
    )
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def place_hold(patron_id: str, title_id: str) -> dict:
    data = get_success_data(
        api_client.place_hold(
            {"patron_id": patron_id, "title_id": title_id},
            make_patron_headers(patron_id),
        )
    )
    assert isinstance(data, dict) and data.get("id"), f"setup failed: {data}"
    return data


def setup_base(clock: str = CLOCK_DEFAULT_ISO,
               library_overrides: dict = None,
               fund_overrides: dict = None,
               consortium_overrides: dict = None,
               set_clock_first: bool = True) -> dict:
    """Consortium + one library + one OPEN fund. Returns a context dict."""
    if set_clock_first:
        set_clock(clock)
    consortium = create_consortium(**(consortium_overrides or {}))
    library = create_library(consortium["id"], **(library_overrides or {}))
    fund = create_fund(library["id"], **(fund_overrides or {}))
    return {"consortium": consortium, "library": library, "fund": fund}


def setup_base_with_title(title_overrides: dict = None, **base_kwargs) -> dict:
    ctx = setup_base(**base_kwargs)
    ctx["title"] = create_title(ctx["consortium"]["id"], **(title_overrides or {}))
    return ctx


def setup_ocou_library(title_overrides: dict = None, copies: int = 1,
                       **base_kwargs) -> dict:
    """Base + title + one fulfilled OCOU license with `copies` copies."""
    ctx = setup_base_with_title(title_overrides=title_overrides, **base_kwargs)
    ctx["license"] = create_license_via_order(
        ctx["library"]["id"], ctx["fund"]["id"], ctx["title"]["id"],
        model="OCOU", copies=copies,
    )
    return ctx
