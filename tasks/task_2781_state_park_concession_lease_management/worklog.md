# Worklog — task_2781_state_park_concession_lease_management

## Step 1: Create task directory — 2026-09-04T20:31:22.883761610Z

Created tasks/task_2781_state_park_concession_lease_management and its workspace/ subdirectory (pre-assigned path, no index allocation performed).

## Step 2: Generate scaffold — 2026-09-04T22:22:45.969955376Z

All three scaffold artifacts are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2781_state_park_concession_lease_management/`

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2823 | §1.0–§1.7 only; flat top-level keys (`scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`). 14 entities, 13 state machines, 11 calculations, 82 validations, 76 endpoints, 74 errors, 6 roles, 2 OCC rules. Neither forbidden key (`scaffold_difficulty_design` / `scaffold_corner_design`) is present. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2405 | single key `scaffold_difficulty_design`; 9 `rule_id` blocks × 2 instances = 18 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5397 | single key `scaffold_corner_design`; all 9 sections in the guide's canonical order, 75 instances (59 with full `test_recipe`, 16 `excluded_because` stubs) |

Corner-design section breakdown: entities 12, state_machines 14 (4 stubs), calculations 11 (5), validations 9 (2), endpoints 5, errors 11 (2), rbac 6, cross_cutting_complexity_layers 6 (3), consistency_model 1.

## Verdict block (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2781_state_park_concession_lease_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2781_state_park_concession_lease_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2781_state_park_concession_lease_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1433

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Work completed this session

- Finished `cross_cutting_complexity_layers`: the second OCC rule (stale `expected_lease_version` on `POST /operating-plans` → 412), a version-precision instance asserting the lease counter advances 1→2→3 but **not** on `POST /operating-plans/{id}/approve` (which bumps only `OperatingPlan.version`) or on report creation, then 4 on report acceptance; plus stubs for `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`.
- Added `consistency_model` (immediate): the award fan-out read back by four different roles in the calls immediately after the write, field-for-field against the write's own body.
- Caught and fixed a genuine gap: the `errors` section was entirely missing. Added 11 instances covering envelope uniformity across 404/403/422, the 12-member not-found family (path *and* body references), 7 entity-specific `*_STATUS_INVALID` replay guards, the duplicate/panel-capacity family, both bond-posting bounds, the draw/reinstatement bounds against the *live* balance, the submission-window pair plus debarment/guarantee/no-responsive-proposal, settlement amount vs. status, and reporting-plan vs. remittance — plus 2 precedence stubs.
- Reordered the `errors` block into the guide's canonical position; verified the move was content-preserving by comparing parsed per-section instance lists before/after.

## Self-checks beyond the linter

Section set exactly the nine allowed values, no duplicates; all 82 instance names unique across both design files; every stub has exactly `{difficulty_instance, rationale}`, no `test_recipe`/`distinguishing_aspect`, and cites a name that exists in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; every non-stub has all four recipe keys; every `ERR_*` token referenced anywhere resolves to the §1.6 catalog (0 dangling); no forbidden concurrency vocabulary in any of the three files. 12 of the 74 catalog errors are still unnamed in the design docs (e.g. `ERR_TERM_NOT_ELAPSED`, `ERR_SUCCESSOR_ALREADY_ACTIVE`, `ERR_AUDIT_ALREADY_SETTLED`, `ERR_PERIOD_OUTSIDE_TERM`) — expected, since §1.9 designs representative corners rather than one instance per error; exhaustive per-error triggering is the test-generation step's job. One worth flagging for that step: `ERR_PERIOD_OUTSIDE_TERM` (rung 32) may be unreachable in practice because rung 22 (`ERR_NO_APPROVED_OPERATING_PLAN`) fires first for any period outside an approved season, and seasons are constrained inside the term.

Orchestrator note: verified the difficulty directive ("Generate task harder than expert level!") did NOT leak into SCAFFOLD.yaml's `scenario:` key — grep for "harder than expert" over the task dir returns nothing.

## Step 3: Copy shared files — 2026-09-04T22:22:45.982430064Z

Copied INSTRUCTION.md from project root to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T22:41:39.945486033Z

PRD generation for task 2781 is complete.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2781_state_park_concession_lease_management/workspace/PRD.md` — **506 lines**, written in 10 chunked appends. Structure: §1 Introduction; §2 Global Specifications (2.1 roles/identity, 2.2 verbatim response envelope, 2.3 pagination, 2.4 logical clock, 2.5 identity/timestamps/versions, 2.6 money & rounding, 2.7 stale lease version, 2.8 interval conventions, 2.9 the 51-band validation ladder, 2.10 cascades & two-dimensional lease state); §3 Business Logic in 9 subsections (park register → solicitation → proposals/revision → panel scoring & award → bonding/execution → operating seasons & rate ceilings → capital improvements & closure windows → receipts reporting/reconciliation/audit → default remedies, expiration & transfer settlement); §4 endpoint table; §5 error catalogue. The file ends on the last error-table row, no audit footer.

```
Field coverage check:
- entities[].fields: 138 required, 138 present, 0 missing
- endpoints[].request_body: 91 required, 91 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 82 checked, 82 expressed in prose (51 priority bands, all in §2.9 in order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (both write endpoints + expected_lease_version + ERR_STALE_LEASE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 75 checked, 75 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (formula, constants, evaluation order, precision), 0 missing
- validations[] conditions: 82 checked, 82 matchable to error_id in prose (all 74 catalogue error IDs named in §1–§3), 0 missing
- endpoints[].side_effects / applies_to: 48 endpoints with side effects + 82 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 138 fields checked (58 with constraints, 23 enums — every enum member present), all reconstructible, 0 missing
- sibling-branch symmetry: 10 groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 797
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Other verifications: §2.2 diffs against `section-2.2-response-structure.md` with zero content difference; §4 table is exactly 4 columns × 76 rows with no duplicates; §5 is exactly 2 columns × 74 rows with no duplicate IDs; no `§1.x` scaffold-internal cross-references, no "SCAFFOLD"/"test_recipe"/difficulty-directive strings leaked. Neither withheld design file was opened, and no sibling task directory was read.

**One assumption the orchestrator must reconcile:** `RATE_CEILING_MULTIPLIER` is referenced by the operating-plan rate-ceiling rule and by `ERR_RATE_EXCEEDS_CEILING`, but its numeric value is declared nowhere in `SCAFFOLD.yaml`. §3.6 originally stated the ceiling as the park benchmark rate times one and one quarter (1.25).

### Orchestrator reconciliation (decided without escalation, per AUTONOMY)

The doc generator's flagged assumption was checked against the withheld design indices, which the orchestrator (not the doc generator) may read. `SCAFFOLD_CORNER_DESIGN.yaml` pins the constant at **1.15** in two boundary instances (`rate_exactly_at_the_park_ceiling_multiplier_is_approved` and `plan_rate_one_cent_above_the_park_ceiling_is_rejected`: comparable 20,000 → ceiling 23,000; 3,000 → 3,450; 9,000 → 10,350 — all exactly ×1.15). Leaving 1.25 in the PRD would have made both boundary tests unfair-but-correct deletions in Step 7 and, worse, would have silently changed the domain rule. The orchestrator therefore edited the single §3.6 sentence from "one and one quarter" to "one and fifteen hundredths (1.15)". This is a one-constant reconciliation of an acknowledged generator gap, not a hand-patch of truncated output; no other PRD prose was touched.

### Truncation guard (per the orchestrator's standing instruction)

`tail` of PRD.md ends on the final row of the §5 error table (`| ERR_REINSTATEMENT_EXCEEDS_DRAWN | 422 |`) — a real section boundary, not mid-sentence. Heading scan shows all of §1, §2.1–§2.10, §3.1–§3.9, §4 and §5 present and in order. 105,171 bytes / 506 lines. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T00:01:04.361365922Z

Test suite generation for task 2781 is complete. Final state:

**Outputs (both directly under the task root, nothing written under `workspace/`)**

`/home/ubuntu/github/CodingPRD/tasks/task_2781_state_park_concession_lease_management/test_helpers/` — 9 modules, 2,174 lines (`api_client.py` 353, `fixtures.py` 471, `factories.py` 403, `types.py` 395, `assertions.py` 182, `api_errors.py` 141, `test_users.py` 87, `__init__.py` 73, `constants.py` 69).

`/home/ubuntu/github/CodingPRD/tasks/task_2781_state_park_concession_lease_management/test_suite/` — `conftest.py` + 18 test modules, 4,914 lines. Files finished this session: `test_15_errors.py` (737 lines, 9 tests), `test_16_rbac.py` (250, 6), `test_17_cross_cutting_complexity_layers.py` (190, 3), `test_18_consistency_model.py` (116, 1).

**Coverage against the two design indices — exactly on target**
- 95 tests / 77 distinct `Design:` tags: all 18 live difficulty instances at >=2 tests each (36), all 59 live corner instances at >=1 each.
- `corner missing: 0`, `nowhere: []`, `stub-tagged: []`, `difficulty under 2: []`. None of the 16 `excluded_because:` stubs was translated. No skip/xfail/placeholder anywhere.

**Verification run**
- Every docstring ends in exactly one `Design:` line; every double-quoted span appears verbatim (whitespace-normalised) in `workspace/PRD.md` — 0 bad.
- Every `PRD §X.Y:` label points at the section the quoted sentence actually lives in — `bad 0`.
- `pytest --collect-only` → 95 tests collected, no import errors; `pyflakes` clean on `test_suite/`; a static `X.*`/`F.*`/`api.*` attribute check against the helper modules and both client classes → 0 missing.

**PRD-first decisions worth flagging (recipe deviations, all resolved toward the PRD)**
- `draw_and_reinstatement_...`: the recipe wants two coexisting AGENCY_ISSUED notices, but §3.9 only admits a notice on a `COMPLIANT` lease, so the first notice makes a second impossible. Rewrote as one notice with an over-limit draw attempt first (3,000,001 vs available 3,000,000), then a valid 1,000,000 draw, then the reinstatement bounds (1,000,001 and 0 both refused, 1,000,000 restoring `ACTIVE`) — both bounds still tested, no ambiguity introduced.
- `bond_posting_errors_...`: used 50,000,001 rather than the recipe's 60,000,000 for the capacity breach, i.e. exactly one cent over the attested `bond_capacity_cents` of 50,000,000.
- `duplicate_and_panel_capacity_...`: `request-revision` is triggered while the proposal is still `UNDER_REVIEW` (one sheet), so ladder band 20 (`ERR_EVALUATION_ALREADY_STARTED`) is the lowest failing check rather than band 10.
- `score_sheets_...` and `consistency_model`: the recipes describe a proposal `UNDER_REVIEW` with two sheets, which §3.4 makes impossible (the second sheet scores it); used `SCORED` and asserted the composite instead. For the award-consistency test the losing bid was given uniform 75s so it stays responsive (75.00 >= min 70.00) while the canonical bid wins at 81.21 — rank 1 is unambiguous.
- No server was started and `workspace/implementation/` was never read or touched, so the suite has not been smoke-run against an implementation.

Orchestrator note: Steps 5 and 6 were launched back-to-back rather than in one message. Physical isolation held anyway — `test_suite/` did not yet exist when the impl generator started, and the impl generator's own report confirms it never read `test_suite/`, `test_helpers/`, or either withheld design file. Verified no stray `test_helpers/` or `test_suite/` was written under `workspace/`; both live at the task root as required. `__pycache__` dirs pruned before Step 7.

## Step 6: Generate implementation — 2026-09-05T00:01:04.368150217Z

Implementation for task 2781 is complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2781_state_park_concession_lease_management/workspace/implementation/` — 27 files, 2,952 lines of Python (Flask), plus `requirements.txt` and an executable `start.sh`.

- Core modules: `app.py` (80), `router.py` (10), `store.py` (126), `envelope.py` (117), `errors.py` (96), `auth.py` (56), `shape.py` (124), `money.py` (87), `calc.py` (221), `logic.py` (237)
- `routes/`: `clock.py` (16), `parks.py` (38), `opportunities.py` (83), `prospectuses.py` (206), `offerors.py` (52), `proposals.py` (203), `leases.py` (146), `bonds.py` (78), `improvements.py` (207), `plans.py` (138), `reports.py` (157), `reconciliations.py` (76), `audits.py` (249), `compliance.py` (138)

## Verification
- **Endpoint coverage: exact.** Cross-checked the registered Werkzeug url_map against `SCAFFOLD.yaml`: 76 declared method+path pairs, 76 registered, **0 missing / 0 extra**. Every rule is registered under both `/api/v1` and the bare prefix.
- **Fresh-boot cleanliness:** `PORT=<random> bash start.sh` boots in ~2s; every collection returns `total_count 0` and the logical clock starts at `2026-08-01T00:00:00.000Z`. Storage is in-memory dicts only — the only `json.dumps` in the tree is response serialization; no sqlite/file/`/tmp` I/O, no seeding.
- **Smoke run 1** (~60 assertions, full award→default lifecycle): `FAILURES: 0`.
- **Smoke run 2** (~75 assertions, second lifecycle: revision cycle, panel scoring, award, bond, execute, insurance re-cert, plan return/resubmit/approve + season overlap + rate ceiling, report reject/amend/accept, three improvements incl. reserve funding and closure-capacity refusal, place-in-service, reconciliation + settle, audit finalize + settle→CLOSED, holdover, expire, close-out, bond release, debar): all business assertions passed. Verified figures: required bond 3,125,000; assessed fee 431,500 on 5,100,000 receipts; reserve 25,500−20,000=5,500; reconciliation base_delta 12,068,500 with due_date 2029-08-30; underreport 1.96% / penalty false; unamortized 970,000 (compensable) and 12,333 (vested); possessory interest 970,000; settlement net 940,900 after the 3% admin fee.
- **GET sweep**: all 14 collections, every row read individually, unknown-id 404s with the correct per-collection `ERR_*_NOT_FOUND`, `limit=101` → 400, unknown query params ignored, `offset`/`limit` echoed in meta, missing headers → 401.

Two apparent mismatches in my throwaway smoke scripts turned out to be **script expectation bugs, not implementation defects**, both confirmed against the PRD:
1. A third score sheet on a 2-sheet proposal returns `ERR_PROPOSAL_STATUS_INVALID`, not `ERR_PANEL_ALREADY_COMPLETE` — PRD §3.4 says the panel guards "apply after the proposal's own status is checked", and the second sheet already moved the proposal to `SCORED`.
2. An unrecognized `X-User-Role` returns 401 `ERR_UNAUTHENTICATED`, not 403 — PRD §2.1 mandates 401 when the role is "not one of the six role names".

Also noted as intended-by-spec: when an audit finalizes over a lease year whose reconciliation was already `SETTLED`, hop two supersedes nothing but still mints the replacement invoice (PRD §3.8 allows the precondition row to be `PENDING_PAYMENT` **or** `SETTLED`, and `remitted_total_cents` sums only report remittances).

## Cleanup
All smoke servers were killed by specific PID/port only (23199, 23923→bound 10000 due to an unexported env var, 23907); no broad `pkill` was used and no listeners remain. `__pycache__` dirs removed.

Isolation was honored: `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and sibling task dirs were never read, listed, globbed or grepped; only `SKILL.md`, `INSTRUCTION.md`, `PRD.md` and `SCAFFOLD.yaml` were consulted. All writes stayed inside `implementation/` (smoke scripts live in `/tmp`).

## Step 7: Run tests and iterate — 2026-09-05T00:42:15.762346915Z

Clean 8-round sweep achieved. Summary:

## Iterations run: 3

Round-1 baseline: 89/95 in every round (6 deterministic failures, no flakiness anywhere in the 3 sweeps). Final sweep: **95/95 in all 8 parallel rounds, 0 failed / 0 errors / 0 skipped.**

## Tests deleted: none
Every failing assertion traced to a verbatim PRD sentence. One assertion was relaxed under the permitted error-precedence exception (below); no test was weakened, skipped, or removed.

## Fixes applied to `test_suite/`
- `test_suite/test_15_errors.py` — `test_duplicate_and_capacity_guards_are_distinct_from_one_another`: the test treated the `POST /proposals/{id}/evaluations` response as the *proposal* (`assert_status(..., "SCORED")`, `evaluation_count`). PRD §2.2/§4 make that response the newly created **score sheet** (which per §2.5 carries only `id`/`created_at` plus its own fields — and `test_10_entities.py` already relies on that). Now files the sheet, then re-reads the proposal.
- `test_suite/test_16_rbac.py` — `test_award_by_an_officer_who_filed_a_score_sheet_is_refused`: same score-sheet-vs-proposal confusion; same fix.
- `test_suite/test_18_consistency_model.py` — `test_the_award_cascade_is_readable_immediately_by_every_other_role`: same score-sheet-vs-proposal confusion; same fix.
- `test_suite/test_15_errors.py` — the third-score-sheet refusal relaxed to `validate_error_is_one_of(["ERR_PANEL_ALREADY_COMPLETE", "ERR_PROPOSAL_STATUS_INVALID"])`, keeping the HTTP-409 assertion. **Error-precedence ambiguity**: §3.4 names `ERR_PANEL_ALREADY_COMPLETE` for a third sheet, but the second sheet has already moved the proposal `UNDER_REVIEW → SCORED`, and §2.9 puts band 10 ("the path resource's own status") below band 21 ("panel capacity") while §3.4 itself says the two panel guards "apply after the proposal's own status is checked". Both error ids are derivable from PRD prose; `ERR_PANEL_ALREADY_COMPLETE` is in fact unreachable under the stated band order.

## Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — `assert_fields` now falls back to comparing ISO-8601 UTC instant strings as instants when a literal string comparison fails (new `_as_instant`). PRD §2.8 declares `cure_deadline`/`submission_deadline` to be ISO 8601 UTC timestamps but pins a three-digit fractional width only for `created_at`/`updated_at` (§2.5), so `...T00:00:00Z` and `...T00:00:00.000Z` are both faithful renderings of the system-minted cure deadline. This was the classic sub-second-width false signal in `test_04_transitive_cascade.py`.

## Fixes applied to `implementation/`
- `workspace/implementation/routes/audits.py` — `audits_create`: `penalty_applies` now initialised to `None` instead of `False`. PRD §2.5: "Computed and system fields that have not yet been established are returned as null rather than omitted"; `penalty_applies` is only established at issue-findings.
- `workspace/implementation/logic.py` — `build_reconciliation`: added `"payment_amount_cents": None` to the minted reconciliation row, per PRD §2.5 "every field named in this document, whether the client supplied it, the system stamped it, or a formula computed it, is present in the resource object returned for that entity".
- `workspace/implementation/routes/reconciliations.py` — `reconciliations_settle`: persists the accepted `payment_amount_cents` on the reconciliation before the `PENDING_PAYMENT → SETTLED` move.

No PRD-required check was removed or weakened, no endpoint/field/side-effect without a verbatim PRD sentence was added, and storage remains in-memory only with nothing seeded at boot.

### Orchestrator independent verification of the sweep artifacts

Per standing practice, the orchestrator did not take the subagent's green claim on faith. All eight `workspace/implementation/results.$i.json` files exist (28,046–28,061 bytes each, all stamped 2026-09-05 00:31) and were parsed individually: every one reports `passed 95 / total 95, failed 0, errors 0, skipped 0`. No round is missing and none is a truncated write. Step 7 is genuinely green.

## Step 8: Finalize PRD — 2026-09-05T00:53:12.235720701Z

Done. `PRD_FINALIZED.md` is a 3-line surgical patch of `PRD.md`.

## Line counts
- `PRD.md`: 506 lines / 105,171 bytes
- `PRD_FINALIZED.md`: 506 lines / 106,441 bytes
- Line delta: 0 lines (0.0%); 3 lines revised in place (0.59% of lines), +1,270 bytes (+1.21%)

## Changes
- **§2.8 (line 120) — revise** — added that a client-supplied instant is persisted/returned verbatim without renormalization, while a system-minted instant (the `SYSTEM_ISSUED` notice's `cure_deadline`) is rendered with exactly three fractional-second digits — `implementation/store.py:54-59` (`iso`), `implementation/logic.py:237-238`.
- **§3.4 (line 234) — revise** — replaced the false claim that a third score sheet is refused with `ERR_PANEL_ALREADY_COMPLETE`: since the second sheet moves the proposal out of `UNDER_REVIEW` and band 10 precedes band 21, a third sheet actually yields `ERR_PROPOSAL_STATUS_INVALID` (409) and `ERR_PANEL_ALREADY_COMPLETE` is unreachable; also pinned that the response body is the newly filed score sheet, not the proposal — `implementation/routes/proposals.py:158-179`.
- **§3.8 (line 312) — insert** — `payment_amount_cents` is a persisted reconciliation field, null from minting (officer-created and audit-minted alike) and set to the accepted payment on settlement; a reconciliation settled by the bond-draw cascade reaches `SETTLED` with it still null — `implementation/logic.py:139`, `implementation/routes/reconciliations.py:55`, `implementation/routes/compliance.py:118-125`.

## Step-7 items deliberately **not** patched
- **`audits.py penalty_applies = None`** — §2.5 already pins "Computed and system fields that have not yet been established are returned as null"; `penalty_applies` is established at issue-findings (`routes/audits.py:112`), so the impl fix brought impl to PRD, no PRD silence.
- **The three score-sheet-vs-proposal test fixes** — pure fixture bugs against §2.2/§4/§2.5; the only residual ambiguity (which object comes back from `POST /proposals/{id}/evaluations`) is now pinned inside the §3.4 edit.

## Per-edit pre-edit search log
**Edit 1 — §2.8 instant rendering**
- (a) Subject: the wire format of every instant-valued field, minted and client-supplied.
- (b) Enumerated: `grep -rn "iso(\|req_instant\|now_iso\|cure_deadline\|submission_deadline"` over all impl modules → `store.py:54` `iso()` (always 3 digits), `store.py:70-81` `insert` (`created_at`/`updated_at`), `store.py:90-105` `touch`, `envelope.py:33` `api_request_timestamp`, `logic.py:237` `cure_deadline_from_clock` (only system-minted instant), `routes/prospectuses.py:30` `submission_deadline` stored as raw `[0]`, `routes/compliance.py:38` `cure_deadline` stored as raw `[0]`, `routes/clock.py:13-16` `current_utc` echoed raw, `shape.py:118-124` `req_instant` (accepts `Z`, `+00:00`, naive; returns raw + parsed).
- (c) Adjustment: originally intended to state a single three-digit rule for all instants; that would have mis-described the three verbatim client echoes (prospectus, compliance notice, clock), so the sentence was split into a client-supplied clause ("exactly as the client wrote it") and a system-minted clause naming only the `SYSTEM_ISSUED` `cure_deadline`.

**Edit 2 — §3.4 panel guards / evaluation response**
- (a) Subject: score-sheet filing — guard order, the error a third sheet yields, and the response body.
- (b) Enumerated: `routes/proposals.py:149-179` (body shape → status check → panel-count check → duplicate-panelist check → `created(evaluation)`), `calc.REQUIRED_PANELIST_COUNT = 2`, every other status writer that could leave a complete panel in a non-terminal state — `proposals_begin_review:76` (only from `SUBMITTED`), `proposals_request_revision:92-95` (blocked by `evaluation_count != 0`), `proposals_resubmit:119` (only from `REVISION_REQUESTED`), `proposals_withdraw:141`, plus the award/close/debar cascades in `routes/prospectuses.py` and `routes/offerors.py` (all move `SCORED` to terminal values) — confirming no reachable state pairs a complete panel with `UNDER_REVIEW`; `envelope.py:51-61` for the 201 body; `store.py:70-81` `common_fields=False` for the sheet's field set.
- (c) Adjustment: kept `ERR_PANEL_ALREADY_COMPLETE` and §2.9 band 21 intact ("remains in the catalogue but is unreachable under that ordering") rather than deleting the band, so §2.9 and §5 stay truthful; the response clause was scoped to score-sheet filing alone so it cannot contradict award (which returns the lease) or the other creates.

**Edit 3 — §3.8 `payment_amount_cents`**
- (a) Subject: `payment_amount_cents` as persisted reconciliation state.
- (b) Enumerated: `logic.py:103-143` `build_reconciliation` (sole minting path, `payment_amount_cents: None`), its two callers `routes/reconciliations.py:34` and `routes/audits.py:159` (audit replacement), `routes/reconciliations.py:48-57` (the only writer of the field), `routes/compliance.py:118-125` (bond draw sets `SETTLED` without writing the field), `routes/audits.py:198-217` (withdraw voids the minted row and restores the superseded one, touching neither row's payment field), `logic.py:146-154` `supersede_pending`, `envelope.py:40-43` `_clean` (only `_`-prefixed keys are hidden, so the null is serialized).
- (c) Adjustment: a blanket "the payment is persisted on settlement" would have mis-described the §3.9 bond-draw settlement path, so an explicit carve-out sentence was added for a reconciliation that reaches `SETTLED` via the draw with the field still null.

Orchestrator verification: `PRD_FINALIZED.md` exists at 506 lines / 106,441 bytes and `diff` against `PRD.md` confirms three changed lines (120, 234, 312) — it is genuinely a patch, not a copy.

## Step 9: Complete PRD — 2026-09-05T01:15:36.755455309Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden from copying). Partition by implementation module so no two passes contend for the same file region:
- Pass 1 — core: `app.py`, `router.py`, `store.py`, `envelope.py`, `errors.py`, `auth.py`, `shape.py`, `money.py`, `calc.py`, `logic.py`, `routes/{clock,parks,opportunities}.py`
- Pass 2 — solicitation & lease: `routes/{prospectuses,offerors,proposals,leases,bonds}.py`
- Pass 3 — operations & compliance: `routes/{improvements,plans,reports,reconciliations,audits,compliance}.py`

### Pass 1 (core) — 19 ambiguity-pins, 1 mismatch-revision

506 lines / 106,441 chars → 506 lines / 109,938 chars (+3,497). 15 lines revised in place, Edit tool only, `cp` confirmed as first action.

- §2.1 — revise — ambiguity — a header present but empty counts as absent for `ERR_UNAUTHENTICATED` — auth.py:29
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus twenty random uppercase letters/digits — envelope.py:21
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock, so untouched-clock responses repeat the timestamp — envelope.py:35, store.py:62
- §2.3 — insert — ambiguity — non-integer or out-of-bound `limit`/`offset` → `ERR_INVALID_REQUEST` 400; empty value = absent → default — envelope.py:73-85
- §2.3 — insert — ambiguity — filters are exact string comparisons; a row whose filtered field is null never matches — envelope.py:99-102
- §2.4 — insert — ambiguity — clock response `data` is `{current_utc}` echoing the supplied instant verbatim — routes/clock.py:16
- §2.5 — revise — ambiguity — sub-millisecond clock precision is truncated, not rounded, to three digits — store.py:54-59
- §2.5 — insert — **mismatch** — `version` advances once per *request*, not per write; a row written twice in one cascade still advances by exactly one — store.py:90-105
- §2.6 — insert — ambiguity — two-decimal percentages serialise as bare JSON numbers without trailing zeros (12.50→12.5, integer 8→8.0); whole-point weights stay integers — envelope.py:24-27, shape.py:88-106
- §2.8 — insert — ambiguity — instants accepted with `Z`, `+00:00`, or no zone (read as UTC); non-zero offsets rejected — store.py:108-126
- §2.9 band 4 — insert — ambiguity — a body FK is resolved only when present as a string; missing/null/wrong-type falls through to band 6 `ERR_INVALID_REQUEST` — shape.py:39-45
- §2.9 band 6 — insert — ambiguity — JSON booleans never satisfy an integer/percentage field; an absent or empty body reads as `{}` — shape.py:14-30
- §3.1 — insert — ambiguity — no operation ever moves a park out of `OPERATING` — routes/parks.py (no writer for `status`)
- §3.1 — insert — ambiguity — `comparable_gross_receipts_cents` must not be negative (zero allowed) — routes/opportunities.py:40
- §3.1 — insert — ambiguity — a repeat market analysis omitting `analyst_note` clears the stored note to null — routes/opportunities.py:49
- §3.4 — insert — ambiguity — whole-year addition clamps an impossible day of month down (2028-02-29 + 1y → 2029-02-28) — money.py:59-69
- §3.4 — insert — ambiguity — lease-year numbering continues past `term_end`; a window before `term_start` records lease year 1 — calc.py:71-79
- §3.8 — insert — ambiguity — a zero frozen reported total restates every report but the last to zero, last absorbs the whole adjusted figure — calc.py:183-199
- §3.8 — revise — ambiguity — interest's whole-month count is the calendar-month difference less one when the clock's day of month precedes the `due_date`'s, floored at zero, with a single rounding at the end — money.py:77-82, calc.py:165-169
- §5 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404; undeclared method on a declared path → `ERR_METHOD_NOT_ALLOWED` 405 — app.py:55-62, errors.py:87-88

NO-NEW-MISMATCH note carried forward: `store.touch` is the only writer of `version` anywhere in the tree and is idempotent per row per request, so the §2.5 per-request claim holds globally. `logic.recompute_outstanding`'s change-detection (skips the touch when the balance is unchanged) was deliberately left unpinned by pass 1 as already covered by §2.10's conditional-cascade rule; pass 3 subsequently pinned it explicitly at the audit hop-three site.

### Pass 2 (solicitation & lease) — 8 ambiguity-pins, 4 mismatch-revisions

509,938 → 112,110 chars (506 lines throughout); 12 lines revised in place. Confirmed no `cp`/`Write` over the shared file; pass 1's 15 lines verified intact (diff vs FINALIZED went 15 → 27).

- §2.9 band 6 — insert — ambiguity — plain string fields (`legal_name`, `contact_email`, `surety_name`, `carrier_name`, notes) are accepted as any JSON string including the empty string, with no internal-shape test — shape.py:48-61
- §2.9 band 6 — insert — ambiguity — an optional field supplied as null is treated exactly as omitted, so `agency_maintenance_scope: null` still takes its `STRUCTURAL_ONLY` default — shape.py:55,82; leases.py:23
- §3.2 — insert — ambiguity — the drafting `opportunity_id` must resolve but the opportunity's own status is not tested at drafting time, only at issue — prospectuses.py:21-23
- §3.4 — insert — ambiguity — award's `term_start` is unconstrained beyond `YYYY-MM-DD` (may precede the clock's date) — prospectuses.py:95
- §3.4 — revise — ambiguity — candidate ranking's final tiebreak after `created_at` is insertion order (earlier-inserted first), which the logical clock makes reachable — prospectuses.py:131-135
- §3.4 — insert — ambiguity — lease minted with `agency_maintenance_scope` already at `STRUCTURAL_ONLY` (not null), the five ledger counters at 0, and `insurance_expires_on`/`carrier_name`/`possessory_interest_value_cents`/both `transfer_settlement_*` null — prospectuses.py:164-176
- §3.5 — insert — ambiguity — `penal_sum_cents` carries no shape-band bound; a non-positive figure reaches and fails `ERR_BOND_INSUFFICIENT` rather than `ERR_INVALID_REQUEST` — bonds.py:23,28
- §3.5 — insert — ambiguity — on `insurance-certificate`, an omitted or null `carrier_name` leaves the insurer on file untouched rather than clearing it — leases.py:58-59
- §3.9 — revise — **mismatch** — holdover preconditions reordered: `ERR_SUCCESSOR_ALREADY_ACTIVE` (band 16) is checked before `ERR_TERM_NOT_ELAPSED` (band 28); PRD had them in the opposite order, contradicting its own ladder — leases.py:72-77
- §3.9 — revise — **mismatch** — reinstatement is admissible only from `PARTIALLY_DRAWN`/`INSUFFICIENT`, and a **partial** reinstatement leaves the status exactly where it stood (an `INSUFFICIENT` bond stays `INSUFFICIENT`, even above the sufficiency floor); PRD claimed a partial always lands in `PARTIALLY_DRAWN` — bonds.py:52-65
- §3.9 — revise — ambiguity — close-out releases the bond only when the bond is *itself still* `ACTIVE` and nothing is owed; a drawn bond keeps its status — leases.py:126-129
- §4 `POST /proposals` — revise — **mismatch** — description said "against an issued prospectus"; impl checks only the submission deadline, never the prospectus status — proposals.py:28-69
- §4 `POST /performance-bonds/{id}/reinstate` — revise — **mismatch** — "a partial one leaves it `PARTIALLY_DRAWN`" → "leaves its status unchanged" — bonds.py:58-64

### Pass 3 (operations & compliance) — 9 ambiguity-pins, 2 mismatch-revisions

112,110 → 114,672 chars (506 lines throughout); 7 further lines revised plus 3 more edits inside an already-counted line. Confirmed no `cp`/`Write`; diff vs FINALIZED went 27 → 34 lines.

- §3.6 — revise — ambiguity — plan resubmission also does not re-test the lease's `contract_status` — routes/plans.py:99-126
- §3.7 — revise — ambiguity — `actual_cost_cents` at place-in-service "may be zero but not negative" (impl enforces `minimum=0`, a bound the PRD never declared) — routes/improvements.py:176
- §3.7 — insert — ambiguity — neither the completion report nor a resubmission re-tests the lease's `contract_status`, so an improvement may be revised/placed in service after `HOLDOVER` — routes/improvements.py:139-195
- §3.8 — insert — ambiguity — amendment re-runs none of the four filing checks (lease posture, season coverage, term containment, overlap) and keeps the originally resolved `operating_plan_id` — routes/reports.py:125-145
- §3.8 — insert — ambiguity — settlement tests nothing about the lease's `contract_status` — routes/reconciliations.py:41-64
- §3.8 — revise — ambiguity — the `ACTIVE/HOLDOVER/EXPIRED` posture test applies only at engagement opening; no later hop re-reads it — routes/audits.py:75-77
- §3.8 — insert — ambiguity — hop two's predecessor selection rule (earliest-created `PENDING_PAYMENT`/`SETTLED` row matching the lease-year index or containing `audit_period_start`, `PENDING_PAYMENT` preferred), only a `PENDING_PAYMENT` predecessor being superseded, and the replacement inheriting the predecessor's lease-year window and interest baseline — routes/audits.py:31-47,157-161
- §3.8 — insert — ambiguity — hop three: a recompute landing on the stored figure writes nothing and on its own advances neither `version` nor `updated_at` (same for the withdrawal unwind) — logic.py:63-71
- §3.8 — revise — ambiguity — hop four: the `COMPLIANT → DEFICIENT` hop fires only from `COMPLIANT`, the notice is minted whatever the standing, and its `deficiency_note` text pinned — routes/audits.py:169-183
- §3.9 — revise — **mismatch** — compliance-action issuance does *not* require `compliance_status` `COMPLIANT` (impl checks only `contract_status`; a second notice on a `DEFICIENT` lease is legal) — routes/compliance.py:43-46
- §3.9 — revise — **mismatch** — the `COMPLIANT → DEFICIENT` move and the lease `version` advance at issuance are conditional; an already `DEFICIENT`/`DEFAULT` lease is not written at all — routes/compliance.py:48-50
- §3.9 — insert — ambiguity — the bond-draw settlement path records no `payment_amount_cents` and does not close a `FINAL` audit (unlike `/settle`) — routes/compliance.py:118-125 vs routes/reconciliations.py:60-63

Pass 3's closing structural check — **PASS**: §1, §2.1–§2.10, §3.1–§3.9, §4, §5 all present and in order; §4 table exactly 76 rows; §5 catalogue exactly 74 rows; file ends on the final catalogue row (`ERR_REINSTATEMENT_EXCEEDS_DRAWN | 422`), a real section boundary. The 36 routes in pass 3's slice map 1:1 onto their §4 rows with matching authorized roles and 201/200 semantics.

### Step 9 totals and orchestrator verification

36 ambiguity-pins + 7 mismatch-revisions = 43 changes across the three passes, all in-paragraph; 0 new sections, 0 new lines. `PRD_COMPLETED.md` is 506 lines / 114,672 chars against `PRD_FINALIZED.md`'s 506 / 106,441 (+8,231 chars, +7.7%). `cmp` confirms the two files are **not** byte-identical and `diff` counts exactly 34 changed lines — the scan genuinely ran; this was not a silent `cp`.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
