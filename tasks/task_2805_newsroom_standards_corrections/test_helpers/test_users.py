"""Acting identities for the five roles of PRD §2.1.

Four roles are entity-backed: the ``X-User-ID`` must be the ``id`` of a real
``Journalist`` (Reporter / StandardsEditor / ExecutiveEditor) or of a real
``Reviewer`` with ``discipline`` ``LEGAL`` (LegalCounsel).  Tests therefore
build their headers from the persisted record's own id with the
``make_*_headers`` factories below, never from a fixed constant.

``TEST_USERS`` holds only the two identities that legitimately need no
persisted record:

* ``bootstrap_exec`` — for the two bootstrap endpoints of PRD §2.1
  (``POST /standards-desk/newsrooms`` and ``POST /standards-desk/journalists``),
  which "skip the entity-backed identity check entirely".
* ``public_editor`` — ``PublicEditor`` is "an opaque operator identifier for
  the reader-advocate desk and is not tied to any persisted entity".
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_EXECUTIVE_EDITOR,
    ROLE_LEGAL_COUNSEL,
    ROLE_PUBLIC_EDITOR,
    ROLE_REPORTER,
    ROLE_STANDARDS_EDITOR,
)

BOOTSTRAP_EXEC_USER_ID = "bootstrap-exec"
PUBLIC_EDITOR_USER_ID = "public-editor-1"
ALTERNATE_PUBLIC_EDITOR_USER_ID = "reader-advocate-desk"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "bootstrap_exec": build_user_headers(
        BOOTSTRAP_EXEC_USER_ID, ROLE_EXECUTIVE_EDITOR
    ),
    "public_editor": build_user_headers(
        PUBLIC_EDITOR_USER_ID, ROLE_PUBLIC_EDITOR
    ),
}


def make_reporter_headers(journalist_id: str) -> Dict[str, str]:
    """Headers for a ``Journalist`` whose ``role_title`` is ``REPORTER``."""
    return build_user_headers(journalist_id, ROLE_REPORTER)


def make_standards_editor_headers(journalist_id: str) -> Dict[str, str]:
    """Headers for a ``Journalist`` whose ``role_title`` is ``STANDARDS_EDITOR``."""
    return build_user_headers(journalist_id, ROLE_STANDARDS_EDITOR)


def make_executive_editor_headers(journalist_id: str) -> Dict[str, str]:
    """Headers for a ``Journalist`` whose ``role_title`` is ``EXECUTIVE_EDITOR``."""
    return build_user_headers(journalist_id, ROLE_EXECUTIVE_EDITOR)


def make_legal_counsel_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for a ``Reviewer`` whose ``discipline`` is ``LEGAL``."""
    return build_user_headers(reviewer_id, ROLE_LEGAL_COUNSEL)


def make_public_editor_headers(
    operator_id: str = PUBLIC_EDITOR_USER_ID,
) -> Dict[str, str]:
    """Headers for the opaque reader-advocate desk identity."""
    return build_user_headers(operator_id, ROLE_PUBLIC_EDITOR)


def make_bootstrap_exec_headers(
    operator_id: str = BOOTSTRAP_EXEC_USER_ID,
) -> Dict[str, str]:
    """Headers for the bootstrap-exempt executive editor."""
    return build_user_headers(operator_id, ROLE_EXECUTIVE_EDITOR)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers declaring a role but omitting ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying an acting id but omitting ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
