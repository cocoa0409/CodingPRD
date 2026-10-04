"""Code-change descriptor rules and the system-driven transitions.

Sources: PRD.md 2.7, 2.8, 3.1, 3.2 and SCAFFOLD.yaml `CodeChange` transitions.
"""

from clock import logical_now
from errors import (
    ERR_CODE_FORMAT_INVALID,
    ERR_DELEGATION_REQUIRED,
    ERR_EVIDENCE_INSUFFICIENT,
    ERR_MISSING_DESCRIPTOR,
    ERR_SUPPORT_DATA_REQUIRED,
    ApiError,
)
import store

CODE_LENGTH = 5
LETTER_FIRST = "A"
LETTER_LAST = "J"

EVIDENCE_TIERS = ("TIER_I", "TIER_II", "TIER_III", "TIER_IV")
CHANGE_TYPES = ("ADDITION", "REVISION", "DELETION")
CATEGORIES = ("CATEGORY_I", "CATEGORY_II", "CATEGORY_III")

# The category that puts a change on the delegation track and therefore
# requires parenthetical instructions (PRD.md 2.7).
DELEGATION_CATEGORY = "CATEGORY_II"

TIER_IV_MINIMUM_VOLUME = 100


def validate_code_format(code):
    """Exactly 5 characters, and a trailing letter must fall in A through J."""
    text = code if isinstance(code, str) else ""
    if len(text) != CODE_LENGTH:
        raise ApiError(ERR_CODE_FORMAT_INVALID,
                       "descriptor number must be exactly 5 characters")
    last = text[-1]
    if last.isalpha():
        if last.upper() < LETTER_FIRST or last.upper() > LETTER_LAST:
            raise ApiError(ERR_CODE_FORMAT_INVALID,
                           "descriptor letter suffix must fall within A through J")
    return text


def code_already_exists(code):
    for change in store.code_changes.values():
        if change.get("code") == code:
            return True
    return False


def code_exists_error():
    from errors import ERR_CODE_ALREADY_EXISTS

    raise ApiError(ERR_CODE_ALREADY_EXISTS,
                   "descriptor number is already on file")


def evidence_sufficient(change_type, tier, volume):
    """TIER_IV is acceptable for a REVISION or DELETION without further
    qualification, and for an ADDITION only when the change also declares a
    `procedure_volume_threshold` of at least 100 procedures annually."""
    if tier != "TIER_IV":
        return True
    if change_type in ("REVISION", "DELETION"):
        return True
    volume = volume or 0
    return volume >= TIER_IV_MINIMUM_VOLUME


def evidence_error():
    raise ApiError(ERR_EVIDENCE_INSUFFICIENT,
                   "TIER_IV addition below the annual procedure volume floor")


def support_data_present(change):
    """A CATEGORY_III emerging-technology addition must declare supporting data
    in its evidence packet before it can be advanced."""
    if change.get("category") != "CATEGORY_III":
        return True
    if change.get("change_type") != "ADDITION":
        return True
    index = change.get("evidence_sufficiency_index") or 0
    return float(index) > 0


def support_data_error():
    raise ApiError(ERR_SUPPORT_DATA_REQUIRED,
                   "category III addition requires supporting evidence data")


def descriptor_text_complete(change):
    """A REVISION must supply `descriptor_proposed`; a change on the delegation
    track must supply `parenthetical_instructions`."""
    if change.get("change_type") == "REVISION" and not change.get("descriptor_proposed"):
        return False
    if change.get("category") == DELEGATION_CATEGORY and not change.get(
        "parenthetical_instructions"
    ):
        return False
    return True


def descriptor_text_error():
    raise ApiError(ERR_DELEGATION_REQUIRED,
                   "descriptor text is incomplete for this change")


def code_index(character):
    """Position of the terminal descriptor character: digits then A..J."""
    if character.isdigit():
        return int(character)
    if character.isalpha():
        return 10 + (ord(character.upper()) - ord("A"))
    return None


def missing_descriptor_present(cycle_id):
    """A hole in the descriptor numbering inside a range the release would
    publish (PRD.md 2.7).

    The published range is read from the CodeValue rows bound to the cycle,
    grouped by their shared four-character prefix so that unrelated descriptor
    families never form a range with one another.
    """
    groups = {}
    for value in store.code_values.values():
        if value.get("release_id") != cycle_id:
            continue
        code = value.get("code") or ""
        if len(code) != CODE_LENGTH:
            continue
        groups.setdefault(code[:4], []).append(code[4])

    for tails in groups.values():
        positions = [code_index(t) for t in tails]
        positions = [p for p in positions if p is not None]
        if len(positions) < 2:
            continue
        low, high = min(positions), max(positions)
        present = set(positions)
        for position in range(low, high + 1):
            if position not in present:
                return True
    return False


def missing_descriptor_error():
    raise ApiError(ERR_MISSING_DESCRIPTOR,
                   "a descriptor hole falls inside the range this release publishes")


# --- system-driven transitions --------------------------------------------

def apply_comment_window_closures():
    """The comment window on a change closes on its own.

    When the logical clock reaches a change's `comment_period_close_at` while
    its `posting_state` is COMMENT_OPEN, the change moves from
    POSTED_FOR_COMMENT to ADMIN_REVIEW without any client request: the posting
    state goes back to POSTED, every unwithdrawn PublicComment row stands, and
    the change is docketed at the earliest SCHEDULED meeting listed in its
    cycle's `meeting_ids`.
    """
    now = logical_now()
    touched = False
    for change in list(store.code_changes.values()):
        if change.get("review_status") != "POSTED_FOR_COMMENT":
            continue
        if change.get("posting_state") != "COMMENT_OPEN":
            continue
        close_at = change.get("comment_period_close_at")
        if close_at is None or now < close_at:
            continue
        change["review_status"] = "ADMIN_REVIEW"
        change["posting_state"] = "POSTED"
        change["meeting_id"] = _earliest_scheduled_meeting(change.get("cycle_id"))
        store.bump(change)
        touched = True
    return touched


def _earliest_scheduled_meeting(cycle_id):
    cycle = store.release_cycles.get(cycle_id) if cycle_id else None
    if cycle is None:
        return None
    for meeting_id in cycle.get("meeting_ids") or []:
        meeting = store.meetings.get(meeting_id)
        if meeting is None:
            continue
        if meeting.get("meeting_status") == "SCHEDULED":
            return meeting_id
    return None


def apply_time_triggered_transitions():
    """Every time-triggered transition whose precondition the clock satisfies."""
    return apply_comment_window_closures()