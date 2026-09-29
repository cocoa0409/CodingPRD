"""PRD 3.4 — TIA-606 identifier administration, shared by link design and MAC rename."""

import re

from errors import ApiError
from store import db

IDENTIFIER_PATTERNS = {
    "TIA_606_CLASS_1": r"^[A-Z]{2}[0-9]{2}-[A-Z][0-9]{2}$",
    "TIA_606_CLASS_2": r"^[0-9]{2}[A-Z]-[A-Z]{2}[0-9]{2}-[A-Z][0-9]{2}$",
}


def screen_identifier(project, identifier, exclude_link_id=None):
    """Full-string, case-sensitive, untrimmed format match, then project uniqueness."""
    pattern = IDENTIFIER_PATTERNS[project["identifier_scheme"]]
    if not isinstance(identifier, str) or re.match(pattern, identifier) is None:
        raise ApiError("ERR_IDENTIFIER_FORMAT_INVALID",
                       "The identifier does not match the project's identifier_scheme.")
    for link in db.links.values():
        if link["project_id"] != project["id"]:
            continue
        if exclude_link_id is not None and link["id"] == exclude_link_id:
            continue
        if link["identifier"] == identifier:
            raise ApiError("ERR_DUPLICATE_LINK_IDENTIFIER",
                           "Another link of this project already carries that identifier.")
