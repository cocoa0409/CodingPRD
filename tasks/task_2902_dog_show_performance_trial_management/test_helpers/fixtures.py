"""Composite setup helpers for the Dog Show Trials API.

Every helper drives the real API and uses the lenient success validator, so a
broken preamble reports itself as a setup failure rather than as a confusing
assertion inside a test.

Two conventions run through the whole file:

* Ownership-gated calls always build their headers from the acting entity's own
  identifier — a club officer acts as `Club.id`, a judge as `Judge.id`, a
  handler as `Handler.id`.
* Optimistic-concurrency pins are re-read immediately before the write that
  needs them, because proposing a panel slot bumps the judge's `version` and
  almost every show write bumps the show's `version`.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SETUP_CLOCK_INSTANT
from .factories import (
    adjudicate_filing_payload,
    assign_judge_payload,
    check_in_payload,
    complete_class_payload,
    create_best_in_show_class_payload,
    create_breed_class_payload,
    create_club_payload,
    create_dog_payload,
    create_entry_payload,
    create_group_class_payload,
    create_handler_payload,
    create_judge_payload,
    create_panel_slot_payload,
    create_performance_class_payload,
    create_performance_run_payload,
    create_protest_payload,
    create_registry_filing_payload,
    create_ring_block_payload,
    create_show_payload,
    decide_protest_payload,
    measurement_payload,
    request_evidence_payload,
    respond_to_slot_payload,
    resubmit_evidence_payload,
    reschedule_ring_block_payload,
    return_show_payload,
    temperature_reading_payload,
)
from .test_users import (
    REGISTRY_OFFICER_ID,
    SANCTION_OFFICER_BETA_ID,
    SANCTION_OFFICER_ID,
    TEST_USERS,
    make_club_officer_headers,
    make_handler_headers,
    make_judge_headers,
    make_registry_officer_headers,
    make_sanction_officer_headers,
)

SO_HEADERS = TEST_USERS["sanction_officer_headers"]
SO_BETA_HEADERS = TEST_USERS["sanction_officer_beta_headers"]
SS_HEADERS = TEST_USERS["show_secretary_headers"]
RO_HEADERS = TEST_USERS["registry_officer_headers"]

PANEL_ROLE_FOR_LEVEL = {
    "BREED": "BREED_JUDGE",
    "GROUP": "GROUP_JUDGE",
    "BEST_IN_SHOW": "BIS_JUDGE",
    "PERFORMANCE": "PERFORMANCE_JUDGE",
}


# ─── Tier 0: single-call wrappers ─────────────────────────────────────────────

def set_clock(instant: str, headers: Optional[dict] = None) -> None:
    """Set the server's logical clock. Mutates no entity and bumps no version."""
    get_success_data(api_client.set_clock(instant, headers or SO_HEADERS))


def register_club(**overrides) -> dict:
    return get_success_data(
        api_client.create_club(create_club_payload(**overrides), SO_HEADERS)
    )


def register_judge(**overrides) -> dict:
    return get_success_data(
        api_client.create_judge(create_judge_payload(**overrides), SO_HEADERS)
    )


def register_handler(**overrides) -> dict:
    return get_success_data(
        api_client.create_handler(create_handler_payload(**overrides), SO_HEADERS)
    )


def register_dog(handler: dict, index: int = 0, **overrides) -> dict:
    return get_success_data(
        api_client.create_dog(
            create_dog_payload(handler["id"], index=index, **overrides),
            make_handler_headers(handler["id"]),
        )
    )


def measure_dog(dog: dict, judge: dict, measured_height_cm: float,
                card_type: str = "TEMP_CARD") -> dict:
    return get_success_data(
        api_client.record_dog_measurement(
            dog["id"], measurement_payload(measured_height_cm, card_type),
            make_judge_headers(judge["id"]),
        )
    )


def apply_for_show(club: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_show(
            create_show_payload(club["id"], **overrides),
            make_club_officer_headers(club["id"]),
        )
    )


def submit_show(show: dict, club: dict) -> dict:
    return get_success_data(
        api_client.submit_show(show["id"], make_club_officer_headers(club["id"]))
    )


def approve_show(show: dict, officer_id: str = SANCTION_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.approve_show(show["id"], make_sanction_officer_headers(officer_id))
    )


def return_application(show: dict, reason: str,
                       officer_id: str = SANCTION_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.return_show(
            show["id"], return_show_payload(reason),
            make_sanction_officer_headers(officer_id),
        )
    )


def open_day(show: dict) -> dict:
    return get_success_data(api_client.open_show_day(show["id"], SS_HEADERS))


def close_show(show: dict) -> dict:
    return get_success_data(api_client.close_show(show["id"], SS_HEADERS))


def read_club(club_or_id) -> dict:
    club_id = club_or_id["id"] if isinstance(club_or_id, dict) else club_or_id
    return get_success_data(api_client.get_club(club_id, SS_HEADERS))


def read_show(show_or_id) -> dict:
    show_id = show_or_id["id"] if isinstance(show_or_id, dict) else show_or_id
    return get_success_data(api_client.get_show(show_id, SS_HEADERS))


def read_judge(judge_or_id) -> dict:
    judge_id = judge_or_id["id"] if isinstance(judge_or_id, dict) else judge_or_id
    return get_success_data(api_client.get_judge(judge_id, SS_HEADERS))


def read_class(class_or_id) -> dict:
    class_id = class_or_id["id"] if isinstance(class_or_id, dict) else class_or_id
    return get_success_data(api_client.get_class(class_id, SS_HEADERS))


def read_entry(entry_or_id) -> dict:
    entry_id = entry_or_id["id"] if isinstance(entry_or_id, dict) else entry_or_id
    return get_success_data(api_client.get_entry(entry_id, SS_HEADERS))


def read_dog(dog_or_id) -> dict:
    dog_id = dog_or_id["id"] if isinstance(dog_or_id, dict) else dog_or_id
    return get_success_data(api_client.get_dog(dog_id, SS_HEADERS))


def read_slot(slot_or_id) -> dict:
    slot_id = slot_or_id["id"] if isinstance(slot_or_id, dict) else slot_or_id
    return get_success_data(api_client.get_panel_slot(slot_id, SS_HEADERS))


def read_ring_block(block_or_id) -> dict:
    block_id = block_or_id["id"] if isinstance(block_or_id, dict) else block_or_id
    return get_success_data(api_client.get_ring_block(block_id, SS_HEADERS))


def read_protest(protest_or_id) -> dict:
    protest_id = protest_or_id["id"] if isinstance(protest_or_id, dict) else protest_or_id
    return get_success_data(api_client.get_protest(protest_id, SS_HEADERS))


def read_filing(filing_or_id) -> dict:
    filing_id = filing_or_id["id"] if isinstance(filing_or_id, dict) else filing_or_id
    return get_success_data(api_client.get_registry_filing(filing_id, SS_HEADERS))


def read_show_version(show: dict) -> int:
    """Re-read the show and return the `version` a schedule write must pin."""
    return read_show(show)["version"]


def read_judge_version(judge: dict) -> int:
    """Re-read the judge and return the `version` a panel proposal must pin."""
    return read_judge(judge)["version"]


# ─── Tier 1: panel slots, classes, entries ────────────────────────────────────

def propose_slot(show: dict, judge: dict, panel_role: str = "BREED_JUDGE",
                 expected_judge_version: Optional[int] = None,
                 headers: Optional[dict] = None) -> dict:
    """Invite a judge onto a show's panel, pinning the judge's current version."""
    version = (
        expected_judge_version if expected_judge_version is not None
        else read_judge_version(judge)
    )
    return get_success_data(
        api_client.create_panel_slot(
            create_panel_slot_payload(
                show["id"], judge["id"], version, panel_role=panel_role
            ),
            headers or SS_HEADERS,
        )
    )


def respond_to_slot(slot: dict, judge: dict, decision: str = "ACCEPT",
                    decline_reason: Optional[str] = None) -> dict:
    payload = respond_to_slot_payload(decision)
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return get_success_data(
        api_client.respond_to_panel_slot(
            slot["id"], payload, make_judge_headers(judge["id"])
        )
    )


def confirmed_slot(show: dict, judge: dict, panel_role: str = "BREED_JUDGE") -> dict:
    """Propose a slot and have the invited judge accept it."""
    slot = propose_slot(show, judge, panel_role=panel_role)
    respond_to_slot(slot, judge, "ACCEPT")
    return read_slot(slot)


def offer_class(show: dict, class_level: str = "BREED", discipline: str = "OBEDIENCE",
                **overrides) -> dict:
    """Offer one line of the catalogue at the given class level."""
    if class_level == "BREED":
        payload = create_breed_class_payload(show["id"], **overrides)
    elif class_level == "GROUP":
        payload = create_group_class_payload(show["id"], **overrides)
    elif class_level == "BEST_IN_SHOW":
        payload = create_best_in_show_class_payload(show["id"], **overrides)
    elif class_level == "PERFORMANCE":
        payload = create_performance_class_payload(
            show["id"], discipline=discipline, **overrides
        )
    else:
        raise ValueError(f"unknown class_level {class_level!r}")
    return get_success_data(api_client.create_class(payload, SS_HEADERS))


def attach_judge(show_class: dict, slot: dict) -> dict:
    return get_success_data(
        api_client.assign_judge_to_class(
            show_class["id"], assign_judge_payload(slot["id"]), SS_HEADERS
        )
    )


def enter_dog(show: dict, show_class: dict, dog: dict, handler: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_entry(
            create_entry_payload(
                show["id"], show_class["id"], dog["id"], handler["id"], **overrides
            ),
            make_handler_headers(handler["id"]),
        )
    )


def confirm_entry(entry: dict) -> dict:
    return get_success_data(api_client.confirm_entry(entry["id"], SS_HEADERS))


def close_entries(show_class: dict) -> dict:
    return get_success_data(api_client.close_class_entries(show_class["id"], SS_HEADERS))


def check_in(entry: dict, attendance: str = "PRESENT") -> dict:
    return get_success_data(
        api_client.check_in_entry(entry["id"], check_in_payload(attendance), SS_HEADERS)
    )


def declare_season(entry: dict, handler: dict) -> dict:
    return get_success_data(
        api_client.declare_season(entry["id"], make_handler_headers(handler["id"]))
    )


def complete_class(show_class: dict, judge: dict, placements: List[str]) -> dict:
    return get_success_data(
        api_client.complete_class(
            show_class["id"], complete_class_payload(placements),
            make_judge_headers(judge["id"]),
        )
    )


def record_reading(show: dict, recorded_temp_c: float, relative_humidity_pct: int) -> dict:
    return get_success_data(
        api_client.record_temperature_reading(
            show["id"],
            temperature_reading_payload(recorded_temp_c, relative_humidity_pct),
            SS_HEADERS,
        )
    )


def plan_ring_block(show: dict, show_class: dict, slot: dict, ring_number: int = 1,
                    block_start_at: str = "2026-09-12T09:00:00Z",
                    expected_show_version: Optional[int] = None) -> dict:
    version = (
        expected_show_version if expected_show_version is not None
        else read_show_version(show)
    )
    return get_success_data(
        api_client.create_ring_block(
            create_ring_block_payload(
                show["id"], show_class["id"], slot["id"], version,
                ring_number=ring_number, block_start_at=block_start_at,
            ),
            SS_HEADERS,
        )
    )


def publish_ring_block(block: dict) -> dict:
    return get_success_data(api_client.publish_ring_block(block["id"], SS_HEADERS))


def reschedule_ring_block(block: dict, block_start_at: str,
                          expected_show_version: int) -> dict:
    return get_success_data(
        api_client.reschedule_ring_block(
            block["id"],
            reschedule_ring_block_payload(block_start_at, expected_show_version),
            SS_HEADERS,
        )
    )


def record_run(entry: dict, judge: dict, course_yardage_m: float = 90.0,
               standard_course_time_s: float = 60.0, actual_time_s: float = 58.0,
               **overrides) -> dict:
    return get_success_data(
        api_client.create_performance_run(
            create_performance_run_payload(
                entry["id"], course_yardage_m, standard_course_time_s,
                actual_time_s, **overrides
            ),
            make_judge_headers(judge["id"]),
        )
    )


def file_protest(show: dict, entry: dict, handler: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_protest(
            create_protest_payload(show["id"], entry["id"], handler["id"], **overrides),
            make_handler_headers(handler["id"]),
        )
    )


def begin_review(protest: dict, officer_id: str = SANCTION_OFFICER_BETA_ID) -> dict:
    return get_success_data(
        api_client.begin_protest_review(
            protest["id"], make_sanction_officer_headers(officer_id)
        )
    )


def request_evidence(protest: dict, evidence_request: str,
                     officer_id: str = SANCTION_OFFICER_BETA_ID) -> dict:
    return get_success_data(
        api_client.request_protest_evidence(
            protest["id"], request_evidence_payload(evidence_request),
            make_sanction_officer_headers(officer_id),
        )
    )


def resubmit_evidence(protest: dict, handler: dict, evidence_note: str) -> dict:
    return get_success_data(
        api_client.resubmit_protest_evidence(
            protest["id"], resubmit_evidence_payload(evidence_note),
            make_handler_headers(handler["id"]),
        )
    )


def decide_protest(protest: dict, decision: str, resolution_code: str,
                   officer_id: str = SANCTION_OFFICER_BETA_ID) -> dict:
    return get_success_data(
        api_client.decide_protest(
            protest["id"], decide_protest_payload(decision, resolution_code),
            make_sanction_officer_headers(officer_id),
        )
    )


def raise_filing(show: dict) -> dict:
    return get_success_data(
        api_client.create_registry_filing(
            create_registry_filing_payload(show["id"]), SS_HEADERS
        )
    )


def adjudicate_filing(filing: dict, decision: str = "ACCEPT",
                      reject_reason: Optional[str] = None,
                      officer_id: str = REGISTRY_OFFICER_ID) -> dict:
    return get_success_data(
        api_client.adjudicate_registry_filing(
            filing["id"], adjudicate_filing_payload(decision, reject_reason),
            make_registry_officer_headers(officer_id),
        )
    )

# ─── Tier 2: the workhorse show-with-a-class setup ────────────────────────────

def _dog_override_for(dog_overrides, index: int) -> dict:
    """Accept one override dict for every dog, or a per-dog list of them."""
    if dog_overrides is None:
        return {}
    if isinstance(dog_overrides, (list, tuple)):
        return dict(dog_overrides[index]) if index < len(dog_overrides) else {}
    return dict(dog_overrides)


def setup_show_with_class(
    num_dogs: int = 1,
    num_entries: Optional[int] = None,
    confirm_entries: bool = False,
    clock: Optional[str] = SETUP_CLOCK_INSTANT,
    club_overrides: Optional[dict] = None,
    judge_overrides: Optional[dict] = None,
    handler_overrides: Optional[dict] = None,
    show_overrides: Optional[dict] = None,
    class_overrides: Optional[dict] = None,
    class_level: str = "BREED",
    discipline: str = "OBEDIENCE",
    panel_role: Optional[str] = None,
    slot_state: str = "CONFIRMED",
    assign_class: bool = True,
    dog_overrides: Optional[dict] = None,
    approve: bool = True,
    close_class: bool = False,
    open_show: bool = False,
    check_in_attendance: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a sanctioned show with one judged class, some dogs and some entries.

    The single knob every scenario turns. `slot_state` selects how far the panel
    invitation is taken (`"PROPOSED"`, `"CONFIRMED"` or `"DECLINED"`), and the
    lifecycle flags run the show forward through closing entries, opening the day
    and checking every entry in.
    """
    if clock is not None:
        set_clock(clock)

    club = register_club(**(club_overrides or {}))
    judge = register_judge(**(judge_overrides or {}))
    handler = register_handler(**(handler_overrides or {}))

    show = apply_for_show(club, **(show_overrides or {}))
    if approve:
        submit_show(show, club)
        approve_show(show)

    slot = None
    if slot_state is not None and approve:
        role = panel_role or PANEL_ROLE_FOR_LEVEL[class_level]
        slot = propose_slot(show, judge, panel_role=role)
        if slot_state == "CONFIRMED":
            respond_to_slot(slot, judge, "ACCEPT")
            slot = read_slot(slot)
        elif slot_state == "DECLINED":
            respond_to_slot(
                slot, judge, "DECLINE",
                decline_reason="Travel conflict on that weekend",
            )
            slot = read_slot(slot)

    klass = offer_class(
        show, class_level=class_level, discipline=discipline, **(class_overrides or {})
    )
    if assign_class and slot is not None and slot_state == "CONFIRMED":
        klass = attach_judge(klass, slot)

    dogs = [
        register_dog(handler, index=i, **_dog_override_for(dog_overrides, i))
        for i in range(num_dogs)
    ]

    entry_count = num_dogs if num_entries is None else num_entries
    entries = [
        enter_dog(show, klass, dogs[i], handler) for i in range(entry_count)
    ]

    if confirm_entries:
        entries = [confirm_entry(entry) for entry in entries]

    if close_class:
        klass = close_entries(klass)
    if open_show:
        open_day(show)
    if check_in_attendance is not None:
        entries = [check_in(entry, check_in_attendance) for entry in entries]

    return {
        "club": club,
        "judge": judge,
        "handler": handler,
        "show": show,
        "slot": slot,
        "klass": klass,
        "dogs": dogs,
        "entries": entries,
    }


def setup_multi_dog_household(
    num_dogs: int = 3, entry_clocks: Optional[List[str]] = None,
    confirm: bool = True, **kwargs
) -> Dict[str, Any]:
    """One handler, several dogs, entries created at distinct logical instants.

    Used by the fee-assessment scenarios, where the ordinal of an entry within
    the handler's counted set changes the discount that entry attracts, so the
    entries must be created in a known order.
    """
    context = setup_show_with_class(num_dogs=num_dogs, num_entries=0, **kwargs)
    show, klass, handler = context["show"], context["klass"], context["handler"]
    clocks = entry_clocks or []
    entries = []
    for index, dog in enumerate(context["dogs"]):
        if index < len(clocks):
            set_clock(clocks[index])
        entries.append(enter_dog(show, klass, dog, handler))
    if confirm:
        entries = [confirm_entry(entry) for entry in entries]
    context["entries"] = entries
    context["klass"] = read_class(klass)
    context["show"] = read_show(show)
    return context


# ─── Tier 3: lifecycle shortcuts ──────────────────────────────────────────────

def setup_class_ready_to_judge(num_dogs: int = 2, attendance: str = "PRESENT",
                               judging_clock: str = "2026-09-12T10:00:00Z",
                               **kwargs) -> Dict[str, Any]:
    """Confirmed entries, entries closed, show day open, everyone checked in."""
    context = setup_show_with_class(
        num_dogs=num_dogs, confirm_entries=True, close_class=True,
        open_show=True, **kwargs
    )
    context["entries"] = [
        check_in(entry, attendance) for entry in context["entries"]
    ]
    if judging_clock is not None:
        set_clock(judging_clock)
    context["klass"] = read_class(context["klass"])
    return context


def setup_completed_class(num_dogs: int = 2, placements: Optional[List[str]] = None,
                          attendance: str = "PRESENT",
                          judging_clock: str = "2026-09-12T10:00:00Z",
                          **kwargs) -> Dict[str, Any]:
    """Run a class all the way to `COMPLETED`, awarding the given placement order."""
    context = setup_class_ready_to_judge(
        num_dogs=num_dogs, attendance=attendance, judging_clock=judging_clock, **kwargs
    )
    order = (
        placements if placements is not None
        else [entry["id"] for entry in context["entries"]][:4]
    )
    context["completion"] = complete_class(context["klass"], context["judge"], order)
    context["klass"] = read_class(context["klass"])
    context["entries"] = [read_entry(entry) for entry in context["entries"]]
    context["show"] = read_show(context["show"])
    return context


def setup_show_ready_for_filing(num_dogs: int = 2, **kwargs) -> Dict[str, Any]:
    """A completed class on a closed show — the state a registry filing needs."""
    context = setup_completed_class(num_dogs=num_dogs, **kwargs)
    context["show"] = close_show(context["show"])
    return context


def setup_accepted_filing(num_dogs: int = 2, **kwargs) -> Dict[str, Any]:
    """Carry a show through filing and registry acceptance."""
    context = setup_show_ready_for_filing(num_dogs=num_dogs, **kwargs)
    filing = raise_filing(context["show"])
    context["filing"] = adjudicate_filing(filing, "ACCEPT")
    context["show"] = read_show(context["show"])
    context["dogs"] = [read_dog(dog) for dog in context["dogs"]]
    return context


# ─── Tier 4: protest scenarios ────────────────────────────────────────────────

def setup_protest_under_review(
    num_dogs: int = 2,
    protest_entry_index: int = 0,
    protest_overrides: Optional[dict] = None,
    reviewer_id: str = SANCTION_OFFICER_BETA_ID,
    with_filing: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """A protest against one judged entry of a closed show, already under review.

    The reviewer defaults to a different sanction officer from the one who
    approved the show, because the officer stored in `approved_by_user_id` may
    not decide a protest concerning that show.
    """
    context = setup_show_ready_for_filing(num_dogs=num_dogs, **kwargs)
    if with_filing:
        filing = raise_filing(context["show"])
        context["filing"] = adjudicate_filing(filing, "ACCEPT")
    target = context["entries"][protest_entry_index]
    protest = file_protest(
        context["show"], target, context["handler"], **(protest_overrides or {})
    )
    context["protest"] = begin_review(protest, reviewer_id)
    return context


# ─── Tier 5: ring timetable scenarios ─────────────────────────────────────────

def setup_scheduling_ready_show(
    num_dogs: int = 3, num_classes: int = 1, dogs_per_class: Optional[List[int]] = None,
    judges: int = 1, class_level: str = "BREED", **kwargs
) -> Dict[str, Any]:
    """A sanctioned show with confirmed panel slots, classes and confirmed entries.

    Every class gets its own confirmed slot when `judges` matches `num_classes`,
    otherwise the single judge takes every class — the shape the judge-rest and
    ring-occupancy scenarios need. No entries are closed, so the caller may still
    add or withdraw before planning the timetable.
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    handler = register_handler()
    judge_numbers = [("J-77", "Rex Calder"), ("J-78", "Vera Lund"), ("J-79", "Iris Penn")]
    judge_overrides = kwargs.pop("judge_overrides", None) or {}
    judge_rows = [
        register_judge(judge_number=number, full_name=name, **judge_overrides)
        for number, name in judge_numbers[:max(1, judges)]
    ]
    show = apply_for_show(club, **kwargs.pop("show_overrides", {}))
    submit_show(show, club)
    approve_show(show)

    role = PANEL_ROLE_FOR_LEVEL[class_level]
    slots = []
    for index in range(num_classes):
        judge = judge_rows[index % len(judge_rows)]
        slots.append(confirmed_slot(show, judge, panel_role=role))

    class_codes = ["B1", "B2", "B3", "B4"]
    classes = []
    for index in range(num_classes):
        klass = offer_class(show, class_level=class_level, class_code=class_codes[index])
        classes.append(attach_judge(klass, slots[index]))

    per_class = dogs_per_class or [num_dogs]
    dogs, entries_by_class = [], []
    dog_index = 0
    for class_index, count in enumerate(per_class):
        class_entries = []
        for _ in range(count):
            dog = register_dog(handler, index=dog_index)
            dogs.append(dog)
            dog_index += 1
            entry = enter_dog(show, classes[class_index], dog, handler)
            class_entries.append(confirm_entry(entry))
        entries_by_class.append(class_entries)

    return {
        "club": club,
        "handler": handler,
        "judges": judge_rows,
        "judge": judge_rows[0],
        "show": show,
        "slots": slots,
        "slot": slots[0] if slots else None,
        "classes": classes,
        "klass": classes[0] if classes else None,
        "dogs": dogs,
        "entries_by_class": entries_by_class,
        "entries": [entry for group in entries_by_class for entry in group],
    }
