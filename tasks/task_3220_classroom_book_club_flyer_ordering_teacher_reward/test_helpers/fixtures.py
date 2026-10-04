"""Composite setup helpers.

The harness restarts the API server before every test, so every test starts
against an empty database and must build its whole world through the public
API. These helpers encapsulate the recurring multi-step chains: a NORMAL
school, a teacher, a published flyer cycle with offerings, an open class order
with lines, and a submitted class order.

Every helper uses the lenient ``get_success_data`` validator so that a failed
setup step raises a clear "Setup failed" error instead of a confusing
assertion failure deep inside a test. Identity threading rule: after creating
a Teacher, every ownership-gated call is made with headers built from the
teacher's own ``id`` via ``make_teacher_headers``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import DEFAULT_CYCLE_MONTH, DEFAULT_ENROLLED_ON
from .factories import (
    create_book_fair_payload,
    create_class_order_payload,
    create_donation_request_payload,
    create_flyer_cycle_payload,
    create_offering_payload,
    create_order_line_payload,
    create_promotion_payload,
    create_redemption_payload,
    create_school_payload,
    create_teacher_payload,
    create_title_payload,
    enroll_program_payload,
    set_clock_payload,
    submit_class_order_payload,
)
from .test_users import TEST_USERS, make_teacher_headers

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
SCHOOL_ADMIN = TEST_USERS["school_admin_headers"]
PARENT = TEST_USERS["parent_headers"]
DONOR = TEST_USERS["donor_headers"]


def _setup_failed(step: str, response) -> AssertionError:
    try:
        body = response.json()
    except Exception:
        body = response.text
    return AssertionError(
        f"Setup failed at step {step!r}: HTTP {response.status_code} body={body!r}"
    )


def _ok(response, step: str, expected_status: Optional[int] = None) -> Dict[str, Any]:
    try:
        data = get_success_data(response, expected_status)
    except Exception:
        raise _setup_failed(step, response)
    return data


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators
# ---------------------------------------------------------------------------

def create_school(
    api: ApiClient,
    name: str = "Test School",
    address: str = "1 Schoolhouse Ln",
    low_income_program: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a school. Returns the School row."""
    payload = create_school_payload(name=name, address=address, low_income_program=low_income_program)
    return _ok(api.create_school(payload, CLUB_ADMIN), f"create school {name!r}", 201)


def enroll_school(
    api: ApiClient,
    school_id: str,
    enrolled_on: str = DEFAULT_ENROLLED_ON,
) -> Dict[str, Any]:
    """Create an ACTIVE program enrollment for the school. Returns the enrollment."""
    return _ok(
        api.enroll_program(school_id, enroll_program_payload(enrolled_on), CLUB_ADMIN),
        f"enroll program for school {school_id}",
        201,
    )


def create_teacher(
    api: ApiClient,
    school_id: str,
    grade_band: str = "G3_5",
    full_name: str = "Test Teacher",
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a teacher at the school. Returns the Teacher row."""
    payload = create_teacher_payload(
        school_id, full_name=full_name, email=email, grade_band=grade_band
    )
    return _ok(api.create_teacher(payload, CLUB_ADMIN), f"create teacher {full_name!r}", 201)


def create_title(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Acquire a title. Returns the Title row."""
    return _ok(api.create_title(create_title_payload(**overrides), CLUB_ADMIN), "create title", 201)


def create_promotion(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a promotion. Returns the Promotion row."""
    return _ok(
        api.create_promotion(create_promotion_payload(**overrides), CLUB_ADMIN),
        "create promotion",
        201,
    )


def create_cycle(
    api: ApiClient,
    school_id: str,
    month: str = DEFAULT_CYCLE_MONTH,
    grade_band: str = "G3_5",
) -> Dict[str, Any]:
    """Create a DRAFT flyer cycle. Returns the FlyerCycle row."""
    return _ok(
        api.create_flyer_cycle(
            create_flyer_cycle_payload(school_id, month=month, grade_band=grade_band),
            CLUB_ADMIN,
        ),
        "create flyer cycle",
        201,
    )


def add_offering(api: ApiClient, cycle_id: str, title_id: str) -> Dict[str, Any]:
    """Add an offering to a DRAFT cycle. Returns the FlyerOffering row."""
    return _ok(
        api.add_offering(cycle_id, create_offering_payload(title_id), CLUB_ADMIN),
        "add offering",
        201,
    )


def publish_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    """Publish a DRAFT cycle. Returns the published FlyerCycle row."""
    return _ok(api.publish_cycle(cycle_id, CLUB_ADMIN), "publish flyer cycle", 200)


def close_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    """Close a cycle. Returns the closed FlyerCycle row."""
    return _ok(api.close_cycle(cycle_id, CLUB_ADMIN), "close flyer cycle", 200)


def create_book_fair(
    api: ApiClient,
    school_id: str,
    start_date: str = "2026-10-05",
    end_date: str = "2026-10-09",
) -> Dict[str, Any]:
    """Schedule a book fair. Returns the BookFair row."""
    return _ok(
        api.create_book_fair(
            create_book_fair_payload(school_id, start_date=start_date, end_date=end_date),
            SCHOOL_ADMIN,
        ),
        "create book fair",
        201,
    )


def add_fair_title(api: ApiClient, fair_id: str, title_id: str) -> Dict[str, Any]:
    """Feature a title at a fair. Returns the FairTitle row."""
    from .factories import create_fair_title_payload

    return _ok(
        api.add_fair_title(fair_id, create_fair_title_payload(title_id), SCHOOL_ADMIN),
        "add fair title",
        201,
    )


def create_donation_request(
    api: ApiClient,
    school_id: str,
    teacher_id: str,
    title_id: str,
    qty_requested: int = 1,
) -> Dict[str, Any]:
    """Create an OPEN donation request as the requesting teacher."""
    headers = make_teacher_headers(teacher_id)
    return _ok(
        api.create_donation_request(
            create_donation_request_payload(
                school_id, teacher_id, title_id, qty_requested=qty_requested
            ),
            headers,
        ),
        "create donation request",
        201,
    )


def create_redemption(
    api: ApiClient,
    teacher_id: str,
    kind: str = "BOOK",
    qty: int = 1,
    title_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a PENDING redemption as the owning teacher."""
    headers = make_teacher_headers(teacher_id)
    return _ok(
        api.create_redemption(
            create_redemption_payload(teacher_id, kind=kind, qty=qty, title_id=title_id),
            headers,
        ),
        "create redemption",
        201,
    )


def set_clock(api: ApiClient, to_iso8601: str) -> None:
    """Advance the logical clock."""
    _ok(api.set_clock(set_clock_payload(to_iso8601), CLUB_ADMIN), "set logical clock", 200)


def run_shipping(api: ApiClient) -> Dict[str, Any]:
    """Run the shipping sweep. Returns the run summary."""
    return _ok(api.run_shipping(CLUB_ADMIN), "run shipping sweep", 200)


def run_ops(api: ApiClient) -> Dict[str, Any]:
    """Run the monthly ops epoch. Returns the run summary."""
    return _ok(api.run_ops(CLUB_ADMIN), "run ops epoch", 200)


# ---------------------------------------------------------------------------
# Tier 1: school world and state progression
# ---------------------------------------------------------------------------

def make_school_world(
    api: ApiClient,
    school_name: str = "Test School",
    low_income: bool = False,
    grade_band: str = "G3_5",
    teacher_name: str = "Test Teacher",
    enroll: bool = True,
) -> Dict[str, Any]:
    """A school (enrolled, posture NORMAL) with one teacher of the given band.

    Returns {"school", "teacher", "teacher_headers"}.
    """
    school = create_school(api, name=school_name, low_income_program=low_income)
    if enroll:
        enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band=grade_band, full_name=teacher_name)
    return {
        "school": school,
        "teacher": teacher,
        "teacher_headers": make_teacher_headers(teacher["id"]),
    }


def setup_published_cycle(
    api: ApiClient,
    school_id: str,
    title_ids: List[str],
    month: str = DEFAULT_CYCLE_MONTH,
    grade_band: str = "G3_5",
) -> Dict[str, Any]:
    """Create a cycle, add one offering per title, and publish it.

    Returns {"cycle", "offerings"} where offerings is a list of FlyerOffering
    rows in the same order as ``title_ids``.
    """
    cycle = create_cycle(api, school_id, month=month, grade_band=grade_band)
    offerings = [add_offering(api, cycle["id"], tid) for tid in title_ids]
    cycle = publish_cycle(api, cycle["id"])
    return {"cycle": cycle, "offerings": offerings}


# ---------------------------------------------------------------------------
# Tier 2: class order with lines
# ---------------------------------------------------------------------------

def create_order(
    api: ApiClient,
    cycle_id: str,
    teacher_id: str,
) -> Dict[str, Any]:
    """Open a class order on a PUBLISHED cycle as the owning teacher."""
    headers = make_teacher_headers(teacher_id)
    return _ok(
        api.create_class_order(create_class_order_payload(cycle_id, teacher_id), headers),
        "create class order",
        201,
    )


def add_line(
    api: ApiClient,
    order_id: str,
    offering_id: str,
    qty: int = 1,
    student_name: str = "Test Student",
    submitted_by: str = "TEACHER",
    teacher_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a line to an OPEN order. Teacher-entered lines use the owning
    teacher's identity headers; parent lines use the opaque parent identity."""
    if submitted_by == "PARENT_ONLINE" and teacher_id is None:
        headers = PARENT
    else:
        if teacher_id is None:
            raise AssertionError("add_line needs teacher_id for TEACHER-submitted lines")
        headers = make_teacher_headers(teacher_id)
    return _ok(
        api.add_order_line(
            order_id,
            create_order_line_payload(
                offering_id, student_name=student_name, submitted_by=submitted_by, qty=qty
            ),
            headers,
        ),
        "add order line",
        201,
    )


def read_order(api: ApiClient, order_id: str, teacher_id: Optional[str] = None) -> Dict[str, Any]:
    """Read a class order with all computed aggregates."""
    headers = make_teacher_headers(teacher_id) if teacher_id else CLUB_ADMIN
    return _ok(api.get_class_order(order_id, headers), "read class order", 200)


def read_teacher(api: ApiClient, teacher_id: str) -> Dict[str, Any]:
    """Read a teacher including points balances."""
    return _ok(api.get_teacher(teacher_id, CLUB_ADMIN), "read teacher", 200)


def read_title(api: ApiClient, title_id: str) -> Dict[str, Any]:
    """Read a title including royalty and license state."""
    return _ok(api.get_title(title_id, CLUB_ADMIN), "read title", 200)


def read_school(api: ApiClient, school_id: str) -> Dict[str, Any]:
    """Read a school including posture and active_fair_id."""
    return _ok(api.get_school(school_id, CLUB_ADMIN), "read school", 200)


def order_version(api: ApiClient, order_id: str, teacher_id: Optional[str] = None) -> int:
    """The current OCC version of a class order."""
    return read_order(api, order_id, teacher_id)["version"]


def submit_order(api: ApiClient, order_id: str, teacher_id: str) -> Dict[str, Any]:
    """Submit an OPEN order with a fresh OCC version. Returns the submitted order."""
    headers = make_teacher_headers(teacher_id)
    version = read_order(api, order_id, teacher_id)["version"]
    return _ok(
        api.submit_class_order(order_id, submit_class_order_payload(version), headers),
        "submit class order",
        200,
    )


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_open_order(
    api: ApiClient,
    line_specs: Optional[List[Dict[str, Any]]] = None,
    school_name: str = "Order School",
    low_income: bool = False,
    grade_band: str = "G3_5",
    month: str = DEFAULT_CYCLE_MONTH,
    title_overrides: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """School + teacher + published cycle + open order with lines.

    ``line_specs`` is a list of {"offering_index", "qty", ...} dicts naming
    which offering (by position) and quantity each line carries; the default
    is a single 1x line on the first offering.

    Returns {"school", "teacher", "teacher_headers", "titles", "cycle",
    "offerings", "order", "lines"}.
    """
    world = make_school_world(
        api, school_name=school_name, low_income=low_income, grade_band=grade_band
    )
    overrides_list = title_overrides or [{}]
    titles = [
        create_title(api, grade_band=grade_band, **ov) for ov in overrides_list
    ]
    published = setup_published_cycle(
        api, world["school"]["id"], [t["id"] for t in titles], month=month, grade_band=grade_band
    )
    order = create_order(api, published["cycle"]["id"], world["teacher"]["id"])
    specs = line_specs if line_specs is not None else [{"offering_index": 0, "qty": 1}]
    lines = []
    for spec in specs:
        spec = dict(spec)
        offering = published["offerings"][spec.pop("offering_index", 0)]
        lines.append(
            add_line(
                api,
                order["id"],
                offering["id"],
                qty=spec.pop("qty", 1),
                teacher_id=world["teacher"]["id"],
                **spec,
            )
        )
    return {
        "school": world["school"],
        "teacher": world["teacher"],
        "teacher_headers": world["teacher_headers"],
        "titles": titles,
        "cycle": published["cycle"],
        "offerings": published["offerings"],
        "order": order,
        "lines": lines,
    }


def setup_submitted_order(
    api: ApiClient,
    line_specs: Optional[List[Dict[str, Any]]] = None,
    school_name: str = "Submitted School",
    low_income: bool = False,
    grade_band: str = "G3_5",
    month: str = DEFAULT_CYCLE_MONTH,
    title_overrides: Optional[List[Dict[str, Any]]] = None,
    clock_to: Optional[str] = None,
) -> Dict[str, Any]:
    """An open order walked through a successful submission.

    ``clock_to`` moves the logical clock immediately before submitting (to
    land inside or outside promotion windows). Returns the same world dict as
    ``setup_open_order`` plus the refreshed post-submit ``order``.
    """
    world = setup_open_order(
        api,
        line_specs=line_specs,
        school_name=school_name,
        low_income=low_income,
        grade_band=grade_band,
        month=month,
        title_overrides=title_overrides,
    )
    if clock_to is not None:
        set_clock(api, clock_to)
    world["order"] = submit_order(api, world["order"]["id"], world["teacher"]["id"])
    world["teacher"] = read_teacher(api, world["teacher"]["id"])
    return world
