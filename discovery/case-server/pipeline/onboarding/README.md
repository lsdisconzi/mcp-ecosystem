# Onboarding Pipeline — Artifact Contracts

This directory holds the schemas and templates that drive the **7-phase onboarding flow**:

```
P0 Intake  →  P1 Blueprint v1  →  P2 Ingest (L1–L4)  →  P3 Blueprint v2
                                                              ↓
                P6 Full run  ←  P5 Pilot run  ←  P4.5 Pick root  ←  P4 Plan
```

## Files

| File | Phase | Role |
|---|---|---|
| `schemas/intake_spec.schema.json` | P0 | What the user told us up front (domain, goal, jurisdictions, expected file kinds). |
| `schemas/tree_blueprint.schema.json` | P1 + P3 | Proposed directory tree. `blueprint_version` distinguishes `template` / `v1` / `v2`. |
| `schemas/pipeline_plan.schema.json` | P4 | Per-directory layer config + destination root. Drives P5 + P6. |
| `templates/legal-case.json` | P0 → P1 | Multi-jurisdictional litigation template. |
| `templates/blank.json` | P0 → P1 | Minimal three-bucket fallback. |

## Storage layout (per session)

All onboarding artifacts live inside the discovery workspace under `.discovery/`:

```
<workspaceRoot>/
  .discovery/
    intake_spec.json
    tree_blueprint.v1.json
    tree_blueprint.v2.json   # written at P3, kept alongside v1 for diffing
    pipeline_plan.json
  _intelligence/
    pilot_report.json        # P5 output
```

Versioning: v1 is **never** overwritten when v2 is written. The UI diff view reads both.

## Templates are blueprints

Templates use the same `tree_blueprint.schema.json` with `blueprint_version: "template"`. To add a new template, drop a JSON file in `templates/` matching the schema. The intake step lists every file in this directory.

## Soft-required guard

`Node.required: true` is **soft**: P4 lets the user delete it, but the deletion is recorded in `pipeline_plan.guardrails.deleted_required_paths` with a user-supplied reason. This satisfies Q4 (free editing + warnings).

## Pilot run semantics (Q2)

`PipelinePlan.main_directories[].pilot.sample_count` defaults to 1. `pilot.deeper_sample: true` adds one file per child subdirectory. P5 executes the same layer config that P6 will use, so any failure surfaces *before* the full corpus is processed.

## Destination root timing (Q3)

`destination_root` is captured at P4.5 (after the user has reviewed the refined blueprint), not at P0. Up to that point, all work lives in the discovery session workspace. P6 materializes the final tree at `destination_root` honoring `destination_collision_policy`.
