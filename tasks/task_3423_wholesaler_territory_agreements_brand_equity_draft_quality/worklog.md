# Worklog — task_3423_wholesaler_territory_agreements_brand_equity_draft_quality

## Step 1: Create task directory — 2026-10-01T23:12:00.000Z

Task directory `./tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/` was pre-allocated by the invocation (already contained `workspace/`); verified it exists and used it as-is. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T00:16:00.000Z

All three scaffold artifacts are complete, parse clean, and pass the official lint on the final run.

**Files:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/SCAFFOLD.yaml` (70,775 bytes) — §1.0–§1.7 only: 11 entities, 10 state machines, 1 OCC concurrency rule, 7 calculations, 10 prioritized validations, 40 endpoints, 27 errors, 4 roles
- `/home/ubuntu/github/CodingPRD/tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (73,846 bytes) — single `scaffold_difficulty_design` key, 18 instances (2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/SCAFFOLD_CORNER_DESIGN.yaml` (107,632 bytes) — single `scaffold_corner_design` key, 41 active instances + 6 `excluded_because` stubs across all 9 taxonomy sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (446 calls scanned, 0 violations). Placeholder-closure, name-uniqueness, and stub-citation audits also pass.

**Domain coverage:** the Anheuser-Busch wholesaler scenario is modeled as a compliance/audit + multi-party-negotiation archetype with segregation of duties (BrewerAdmin creates, BrewerCompliance decides transfers/plans, entity-backed WholesalerPrincipal acts only on its own book, DraftAuditor only audits). The hardest mechanics: a 10-state transfer machine with ROFR windows (30d) and consummation deadlines (60d) swept by a logical clock (default 2026-09-01T00:00:00Z); dual-variant equity index (PROVISIONAL 77.00 vs AUDITED 71.00 on identical state) plus STANDARD/SHARE_TILTED composite weights; a pinned component-first rounding order (71.32 vs the forbidden 71.27); an iterative waterfall allocation with guarantee/tier/cap interplay (400/360/240 on 1000 cases); depth-3 cascades (critical audit → account suspension → wholesaler suspension at exactly 3 → allocation release) and consummation cascades; inclusive boundary checks (POS cap at exactly 30000 cents, audit gap at exactly 604800 s, keg age at exactly 90 days, qualification at exactly 70.00); two compensating invariants (case ledger and POS lifetime dollars); and a single true-race OCC rule on agreement amendments (`expected_agreement_version`, ERR_STALE_VERSION 412).

## Step 3: Copy shared files — 2026-10-02T00:18:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-02T00:37:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/workspace/PRD.md` — 328 lines, 7,220 words.

**Sections:** §1 Introduction (2 paragraphs); §2 Global Specifications in 10 subsections (2.1 RBAC with per-role identity prose, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Sweeps, 2.6 Precision & Rounding, 2.7 OCC on Amendments, 2.8 Three-Tier Guardrails, 2.9 Identifier Existence & Reverse Reachability, 2.10 Validation Ladder); §3 Business Logic in 9 workflow subsections (appointment, amendment/equity index, transfer application/qualification, ROFR/decision/consummation, allocation waterfall, draft audits/suspension, POS caps, reviews/corrective plans, promotion programs); §4 endpoint table (40 rows, 4 columns); §5 error catalogue (27 rows, 2 columns).

**Summary:** A lossless prose projection of the scaffold covering all 11 entities, 10 state machines, 7 calculations (equity index with PROVISIONAL/AUDITED variants, iterative tier-weighted waterfall with caps and remainder cycling, pinned-rounding composite, pooled freshness index, inclusive POS caps, qualification score, strict-greater-than concentration rule), the 10-tier validation ladder with explicit precedence, and the OCC rule including its state-check ordering. All formulas were translated to operator-free natural language with constants embedded in context.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 78 required, 78 present, 0 missing
- endpoints[].request_body/input/path/output ids: 70 required, 70 present, 0 missing
- nested sub-fields (supplier_book/amendment_log/requests/assignments/kegs/opt_ins): 11 required, 11 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: 10 tiers checked, 10 expressed as an explicit ordered ladder with worked examples, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (amendment endpoint + expected_agreement_version + ERR_STALE_VERSION/412 + TERMINATED-before-stale ordering), 0 missing
- state_machines[].transitions: 36 checked (incl. the explicit ROFR_OPEN decision non-transition), 36 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed in reconstruction-safe prose, 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 40 checked, 40 expressed (7 ownership scopes enumerated verbatim), 0 missing
- entities[].fields[] structured content: defaults (100-case guarantee, 0.40 cap, 14-day frequency, STANDARD profile, empty lists, null ROFR/deadlines) and computed-field semantics all reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (EXERCISE/WAIVE, 4x APPROVE sources, 4x REJECT sources, STANDARD/SHARE_TILTED, PROVISIONAL/AUDITED, CONFIRM/RELEASE, VERIFIED/FAILED, ACKNOWLEDGE/DISPUTE, 3 sweeps), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 477
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 matches the canonical `section-2.2-response-structure.md` byte-for-byte; all 62 enum/state values and all calculation constants appear; no fuzzy/approximating wording anywhere. One scaffold ambiguity was resolved by field-description fidelity: `last_audit_at` is specified as advancing only on accepted audits, so the PRD states that FAIL/CRITICAL_FAIL audits do not update it, and the 7-day `ERR_AUDIT_TOO_SOON` gate anchors to it (604800 s allowed, 604799 s rejected). The withheld design files were never opened.

## Step 5: Generate unit tests — 2026-10-02T00:55:00.000Z

All checks pass. Final summary:

**Files written** (11 helpers + 10 suite files, all under `/home/ubuntu/github/CodingPRD/tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/`):
- `test_helpers/`: `types.py`, `api_errors.py` (27 errors registered with framework), `api_client.py` (34 endpoint methods), `constants.py` (PRD-exact thresholds: 90/120-day keg ages, 604800 s audit gap, 70.00 qualify/corrective floors, tier multipliers 1.2/1.0/0.8, POS caps 30000/25000/20000, etc.), `factories.py`, `test_users.py` (entity-backed `make_wholesaler_headers`), `assertions.py` (incl. `assert_instant_equals` for format-tolerant clock-instant comparison), `fixtures.py` (composite setups: awarded territory, suspended wholesaler, locked events, qualified transfers, review+plan, POS grant ladders), `__init__.py`.
- `test_suite/`: `conftest.py` + `test_01_market_opening.py` … `test_09_rbac_ownership.py`.

**Collection**: `pytest --collect-only` → **76 tests, 0 errors** = 36 difficulty (18 instances × 2) + 40 corner.

**Tag audit (AST-walked)**: every test has exactly one `Design:` line resolving to a real instance; all 18 difficulty instances have ≥2 tests; all 40 translated corner instances have ≥1; all 6 `excluded_because` stubs left untranslated with cross-references verified. **PRD verbatim audit**: 113 quoted citations ≥8 words, all survive literal grep of PRD.md.

**Skips: 1** — `Corner/entities/wholesaler_create_system_fields_input_ignored`: its claim "client-supplied lifecycle fields are ignored" is not uniquely derivable — PRD §2.10 tier 4 ("unknown fields are rejected") leaves two faithful readings (400 vs 201-with-defaults) for system fields supplied on create.

**Design-vs-PRD deviation fixed during translation**: `draft_audit_result_and_counts_computed` asserted `last_audit_at == conducted_at` after a FAIL audit, contradicting PRD §3.6 ("audits that fail … do not update it"); the test asserts `last_audit_at is None` per PRD. Also made `supplier_book` factory entries carry the documented `added_at` member (safe under both required/optional readings).

Orchestrator spot-check: re-ran `pytest --collect-only -q test_suite/` — 76 tests collected, 0 errors. Confirmed.

## Step 6: Generate implementation — 2026-10-02T01:41:00.000Z

Implementation complete. All modules compile, constants verified defined-once, smoke test passed, no leftover processes.

## Modules (all in `/home/ubuntu/github/CodingPRD/tasks/task_3423_wholesaler_territory_agreements_brand_equity_draft_quality/workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| start.sh | 10 | Guarded pip install, `exec python3 app.py` |
| requirements.txt | 1 | flask>=2.2 |
| app.py | 60 | Blueprint registration, ApiError/HTTPException handlers, 0.0.0.0:$PORT |
| errors.py | 40 | ApiError + all 27 error IDs |
| clock.py | 44 | Logical clock (default 2026-09-01T00:00:00Z), ISO parse/format (3 frac digits) |
| db.py | 51 | Empty in-memory stores, stamped()/touch(), shared lookups |
| envelope.py | 89 | meta/response_type/data envelope, list pagination (limit 1-100 default 10) |
| validate.py | 92 | Tier-4 body validation (required/types/enums/unknown-field rejection) |
| auth.py | 58 | X-User-ID/X-User-Role checks, role decorator |
| calc.py | 169 | All 7 calculation rules with pinned constants (Decimal, ROUND_HALF_UP) |
| cascades.py | 70 | Pending-assignment release, suspension trigger, clock sweeps |
| routes_core.py | 151 | Clock + territories + wholesalers (9 endpoints) |
| routes_agreements.py | 201 | Agreements, OCC amendments, equity index (5) |
| routes_transfers.py | 238 | Transfer lifecycle incl. consummation cascade (5) |
| routes_reviews.py | 228 | Reviews + corrective plans (7) |
| routes_allocations.py | 186 | Allocation events, waterfall lock, decisions (5) |
| routes_field.py | 226 | Accounts, draft audits, POS grants (7) |
| routes_promotions.py | 96 | Promotion programs + opt-ins (2) |

**Endpoints: 40/40.** Smoke test on a dynamic free port: boot clean; missing-header 400, create 201s, unknown-route 404 envelope, wrong-role 403, equity index = 74.0 exactly (0.5·80+0.3·88+0.2·38), clock sweep counts — all correct; server killed by saved PID.

## PRD interpretations chosen where prose was ambiguous

1. **ROFR-holder-not-found on agreement create** → 404 ERR_NOT_FOUND (existence tier 5 beats tier-8 ERR_ROFR_HOLDER_CONFLICT per the §2.10 ladder; CONFLICT fires for holder==appointee or TERMINATED holder).
2. **`last_audit_at` advances only on PASS** — PRD §3.6 "audits that fail do not update it" wins over the scaffold endpoint line "on success updates last_audit_at". The 7-day spacing anchor therefore only constrains audits after a passing one.
3. **Event LOCKED→CLOSED only on assignment decisions** (scaffold trigger literal); cascade releases (suspension/termination) do not close a LOCKED event even at pending_qty 0.
4. **Review profile/target snapshot source**: earliest-created ACTIVE agreement when a wholesaler holds several (created_at asc, insertion-order tiebreak).
5. **decision_reason recorded on REJECT only** (scaffold per-transition side effects; APPROVE ignores `reason`).
6. **meta.api_request_timestamp uses the logical clock** (not wall clock) per §2.5's "never falls back to wall-clock time".
7. **Amendment `fields_changed`** = supplied amendable fields in canonical order; amendment with zero amendable fields still bumps version and logs an empty list; no ROFR-conflict revalidation on amendment (tier-8 applies_to excludes it).
8. **Input datetimes normalized** to `...T..:..:.. .mmmZ` on storage (consistent comparisons); equity-index AUDITED with no review returns null components plus null equity_index; invalid `variant` query → 400 ERR_INVALID_REQUEST.
9. **Consummation edge**: seller terminated only when status==APPOINTED with zero remaining ACTIVE agreements (a SUSPENDED seller stays SUSPENDED, matching the state machine's from-state).

Orchestrator spot-check: all 18 files re-compiled clean with py_compile. Confirmed.

## Step 7: Run tests and iterate — 2026-10-02T01:57:00.000Z

All 8 rounds pass 76/76 on the final tree state, with no edits after the sweep. Results files `results.1..8.json` remain in place in `workspace/implementation/`.

## Summary

**Iterations run:** 2 (initial sweep: 73/76 in all 8 rounds, identical failures — deterministic; post-fix sweep: 76/76 × 8 rounds, clean).

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage (the rest of each test is verbatim PRD-covered and stays):

- `test_03_transfers.py::TestConsummationCascadeTerminatesSeller::test_consummation_terminates_agreement_and_seller` — removed `assert event["status"] == "CLOSED"`. Collapse pattern: action-scoped trigger. PRD §3.5 (line 205) reads "When a **decision** leaves no `PENDING` assignments — `pending_qty` has reached zero — the event moves `LOCKED` → `CLOSED`", inside the paragraph defining decisions as wholesaler CONFIRM/RELEASE actions; the cascade rule (§3.4 line 185 / §3.5 line 207) exhaustively enumerates cascade effects ("`released_qty` increases … `pending_qty` decreases") with no status transition. A faithful PRD-only reader can keep the event `LOCKED` on a cascade release — exactly what the Step 6 implementation does (its interpretation #3, also matching SCAFFOLD's decision-scoped trigger "after any assignment decision leaves zero PENDING assignments"). Not uniquely derivable; the remaining counter assertions (RELEASED, released_qty=40, pending_qty=0, unassigned_remainder=60) are verbatim-covered by §3.4/§3.5 and were kept.
- `test_05_draft_quality.py::TestCriticalAuditCascade::test_suspension_releases_pending_assignments` — removed the same `assert event["status"] == "CLOSED"` and the decision-rule docstring quote backing it (same collapse pattern, suspension cascade instead of consummation cascade; generated from SCAFFOLD endpoint side-effect line 1091 "Event LOCKED -> CLOSED when pending_qty reaches 0", which PRD rendered decision-scoped).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_05_draft_quality.py::test_critical_audits_suspend_accounts_and_wholesaler` — the fixture collects `post_critical_audit(...)` which already validates 201 and returns the parsed data dict (`-> dict` per its contract); the test re-wrapped each dict in `validate_success(resp, 201)`, producing `AttributeError: 'dict' object has no attribute 'status_code'`. Changed the loop to assert directly on the dicts (`result == "CRITICAL_FAIL"`, `critical_keg_flag is True` — both verbatim PRD §3.6: 121-day keg ≥ 120-day critical threshold).

**Fixes applied to `implementation/`:** none.

**Sibling code paths no remaining test asserts (for Step 8), since test-side fixes outnumbered implementation fixes 3:0:**
- Allocation-event `status` after the **suspension cascade** releases the last PENDING assignment (cascades.py suspension trigger) — neither LOCKED nor CLOSED is now asserted on that path.
- Allocation-event `status` after the **consummation seller-termination cascade** releases the last PENDING assignment (cascades.py consummation path) — likewise unasserted.
- The decision-driven `LOCKED → CLOSED` transition remains fully asserted (`test_04_allocations.py`, confirm-last-assignment and release paths), so the gap is confined to the two cascade entry points.

Orchestrator verification: re-read all 8 results files — each `passed: 76, total: 76, failed: 0`; newest source mtime (01:54) predates oldest results file (01:57), confirming the final sweep ran on the final tree.

## Step 8: Finalize PRD — 2026-10-02T02:05:00.000Z

Done. PRD_FINALIZED.md written with exactly one targeted edit.

**Line counts / delta:** PRD.md 328 lines, PRD_FINALIZED.md 328 lines (0% delta — the single change is an in-paragraph append; `diff` shows 1 changed line, nothing else).

**Change (1 edit):**
- §3.5 (line 207, the two-lifecycle-events cascade paragraph) — revise/append — appended: "Within each affected event, such a cascade release changes only assignment statuses and the quantity ledger; the event's own `status` is not affected — the `LOCKED` → `CLOSED` transition occurs only in response to an assignment decision, never as part of a cascade." — impl: `workspace/implementation/cascades.py:8-21` (`release_pending_assignments` writes assignment status + `released_qty`/`pending_qty` only, never `event["status"]`), sole `CLOSED` write at `implementation/routes_allocations.py:183-184` inside the decision handler, cascade entry points `implementation/routes_transfers.py:235` and `implementation/routes_field.py:154`. This one edit pins both unasserted sibling paths (suspension cascade and consummation seller-termination cascade), since §3.4 line 185's release bullet defers to §3.5.

**Per-edit pre-edit search log:**
- (a) Subject: allocation-event `status` — every write path, specifically whether a cascade driving `pending_qty` to zero transitions the event.
- (b) Paths enumerated: `grep -rn 'event\["status"\]\|"status": "CLOSED"\|"status": "LOCKED"\|"status": "OPEN"'` over all of `implementation/` returned the complete writer set — `routes_allocations.py:36` (create → OPEN), `:134` (lock → LOCKED), `:160` (decisions admitted in LOCKED/CLOSED), `:183-184` (only CLOSED write, gated on decision + `pending_qty == 0`); cascade entry points `routes_transfers.py:227-235` (consummation → `cascades.release_pending_assignments`) and `routes_field.py:149-155` (CRITICAL_FAIL → count 3 → `maybe_suspend_wholesaler` → `release_pending_assignments`); read `cascades.py` in full to confirm the helper never writes event status. Also read `calc.py:34-36` for the third diff item.
- (c) Wording adjustment: first draft read "only when an assignment decision drives `pending_qty` to zero" — revised to "occurs only in response to an assignment decision" because the impl's edge case (RELEASE of a CONFIRMED assignment after a cascade already zeroed `pending_qty`) still closes the event inside the decision handler at `routes_allocations.py:183-184`; the final phrasing is consistent with every enumerated path including that edge.

**No-edit items:**
- `test_05_draft_quality.py` fixture fix — pure test artifact: `post_critical_audit` already returns a 201-validated dict; re-wrapping it in `validate_success` was the bug. The re-asserted values (`result == "CRITICAL_FAIL"`, `critical_keg_flag is True` for a 121-day keg) are verbatim PRD §3.6 line 213 (keg ≥ 120 days critical → `CRITICAL_FAIL`, `critical_keg_flag` true), matched by `routes_field.py:121-134` with `calc.py:34-35`. No PRD silence or mismatch.
- Both removed `CLOSED` assertions trace to the single §3.5 edit above; the decision-driven `LOCKED` → `CLOSED` rule at line 205 was already correct and remains verbatim (still asserted by `test_04_allocations.py`).

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the single claimed in-paragraph append at line 207; both files 328 lines. Confirmed.

## Step 9: Complete PRD — 2026-10-02T02:23:00.000Z

The diff is clean — 17 in-paragraph revisions, no new sections, no deletions, line count unchanged. All edits verified against the implementation source.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (328 lines / 52,930 chars) → `PRD_COMPLETED.md` (328 lines / 55,577 chars), char-delta **+2,647**. All changes are inline inserts/revisions inside existing paragraphs; no new sections.

**Counts:** 16 ambiguity-pins, 3 mismatch-revisions, 0 implementation fixes.

**Ambiguity-pins** (`{section} — insert — ambiguity — what — impl ref`):
- §2.3 — insert — ambiguity — invalid `limit`/`offset` → `ERR_INVALID_REQUEST` (400); ties keep insertion order; `total_count` counts the post-filter set; `has_more` = `offset + returned < total_count` — implementation/envelope.py:55-89
- §2.5 — insert — ambiguity — stored client-supplied timestamps (audit `conducted_at`/`line_cleaning_last_at`/keg `filled_at`, promotion `starts_at`/`ends_at`) re-rendered to canonical UTC with 3 fractional digits — routes_field.py:88,139-140; routes_promotions.py:55-56
- §2.9 — insert — ambiguity — exactly two operations (allocation request, promotion opt-in) resolve the caller's wholesaler record, 404 when `X-User-ID` names none; all other ops only compare — routes_allocations.py:66-68; routes_promotions.py:72-74
- §2.10 tier 3 — insert — ambiguity — governing resource resolves before the ownership comparison (unresolvable → tier-5 404); path-param ownership (`wholesalerId`) checked before any lookup — routes_transfers.py:38-49; routes_allocations.py:143-148
- §3.1 — revise — ambiguity — territory `state_code` stored as supplied, no format validation (was "the two-letter `state_code`") — routes_core.py:34-46
- §3.1 — insert — ambiguity — three qualification scores accepted as integers with no range check — routes_core.py:94-96
- §3.1 — revise — ambiguity — supplier_book `added_at` optional; malformed name/type → `ERR_INVALID_REQUEST` — routes_core.py:67-82
- §3.2 — insert — ambiguity — `fields_changed` lists supplied fields in the amendable-field enumeration order — routes_agreements.py:24-28,141
- §3.2 — insert — ambiguity — amendment stores `rofr_holder_wholesaler_id` without re-validation (§3.1 gate is creation-only) — routes_agreements.py:141-143
- §3.2 — insert — ambiguity — unknown equity `variant` → `ERR_INVALID_REQUEST` (400) — routes_agreements.py:158-161
- §3.2 — insert — ambiguity — `NO_REVIEW` also nulls the three component fields — routes_agreements.py:171-178
- §3.4 — insert — ambiguity — ROFR holder read afresh from the agreement at each step (mid-flight amendment binds later steps) — routes_transfers.py:124-129,163-165
- §3.5 — insert — ambiguity — allocation-request `201` carries the updated parent event — routes_allocations.py:91
- §3.5 — insert — ambiguity — remainder-cycle ties beyond `created_at` broken by filing order — calc.py:155-156
- §3.8 — insert — ambiguity — `dispute_reason` must be present and non-empty — routes_reviews.py:139-142
- §3.9 — insert — ambiguity — opt-in `201` carries the updated program — routes_promotions.py:96

**Mismatch-revisions** (adjudicated as over-specification reasonably resolved by impl, per the rule — no impl edits):
- §3.6 — revise — mismatch — suspension trigger: "count from 2 to 3" → "leaves an `APPOINTED` wholesaler's count at three or more" (impl guard is `APPOINTED and count >= 3`; reachable e.g. reinstate-at-3 then another CRITICAL_FAIL) — cascades.py:24-32
- §3.8 — revise — mismatch — `weighting_profile_snapshot`: "the wholesaler's ACTIVE agreement" (singular) → earliest-created ACTIVE agreement, `STANDARD` when none exists (reachable: SUSPENDED seller left with zero ACTIVE agreements post-consummation) — routes_reviews.py:91-93
- §3.8 — revise — mismatch — automatic plan spawn on composite < 70.00 is conditioned on an ACTIVE agreement existing (a `target_snapshot` cannot copy nonexistent targets; impl spawns none) — routes_reviews.py:112-113

**Dead-code findings** (all benign defensive redundancy, none PRD-required, no action taken):
- routes_transfers.py:136-139 and 187-190 — ROFR/consummation deadline re-checks are unreachable (the §2.5 sweep always moves the state first); observable outcome already matches PRD.
- routes_transfers.py:55-56, 98-99 — seller/buyer `None` guards unreachable (no delete exists).
- routes_allocations.py:109 — `BRONZE` tier fallback for a missing requester unreachable.
- No called-but-undefined symbols; every error in the §5 catalogue has a reachable trigger (including the TERMINATED-successor-at-consummation path via appoint→sell-elsewhere chains), so no PRD-required check is dead.

No implementation fixes were needed: every PRD-vs-impl divergence found was an ambiguity or an over-specification, not a forgotten deliberate requirement.

Orchestrator verification: PRD_COMPLETED.md exists (55,577 chars — matches claim); `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → differ, 32 changed lines consistent with 17 in-paragraph edits; implementation source mtimes (≤01:41) all predate the clean-sweep results files (01:57) — Step 9 made zero implementation writes, so the 76/76 × 8-round sweep evidence remains valid for the final tree.
