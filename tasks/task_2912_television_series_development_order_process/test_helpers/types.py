"""Light type aliases and the scenario context object shared by the fixtures.

``ScenarioContext`` carries the ids the composite fixtures create as they walk the
development pipeline, so a test can name any resource the fixture reached without
re-deriving it.
"""

from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]
Headers = Dict[str, str]


class ScenarioContext:
    """Ids and captured values produced by a composite fixture walk."""

    def __init__(self) -> None:
        self.agency_id: Optional[str] = None
        self.agency2_id: Optional[str] = None
        self.slate_id: Optional[str] = None
        self.slate2_id: Optional[str] = None
        self.writer_id: Optional[str] = None
        self.writer2_id: Optional[str] = None
        self.pitch_id: Optional[str] = None
        self.pitch2_id: Optional[str] = None
        self.rights_check_id: Optional[str] = None
        self.project_id: Optional[str] = None
        self.project2_id: Optional[str] = None
        self.deal_id: Optional[str] = None
        self.deal2_id: Optional[str] = None
        self.step_ids: List[str] = []
        self.pilot_order_id: Optional[str] = None
        self.pilot_order2_id: Optional[str] = None
        self.pilot_order_version: Optional[int] = None
        self.screening_id: Optional[str] = None
        self.negotiation_id: Optional[str] = None
        self.greenlight_id: Optional[str] = None
        self.project_version: Optional[int] = None
        self.holding_deal_id: Optional[str] = None
        self.extra: JsonDict = {}

    # Convenience aliases used by the tests for readability.
    @property
    def step1_id(self) -> str:
        return self.step_ids[0]

    @property
    def step2_id(self) -> str:
        return self.step_ids[1]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        parts = {
            k: v
            for k, v in self.__dict__.items()
            if v not in (None, [], {}) and k != "extra"
        }
        return f"ScenarioContext({parts})"


# The ordered stages of the development pipeline the composite fixtures walk.
PIPELINE_STAGES = (
    "bootstrap",
    "writer",
    "pitch",
    "covered",
    "project",
    "deal",
    "script_complete",
    "pilot_ordered",
    "green_to_shoot",
    "wrapped",
    "screened",
    "certified",
    "negotiation",
    "agreed",
    "greenlight",
)
