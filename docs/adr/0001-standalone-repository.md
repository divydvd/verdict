# ADR-0001: Standalone repository

## Status
Accepted

## Context
The SmarType app repo (`smartype/`) is an Android/Kotlin/Gradle project. The testing platform is
Python tooling (orchestration, LLM calls, MCP server) with a different release cadence, different
contributor audience, and potentially reusable value beyond SmarType.

## Decision
The testing platform lives in its own repository (e.g. `verdict`), separate from
`smartype/`, as a single repo (not split further into e.g. `smartype-agent` + `verdict`).

## Consequences
**Positive:**
- Independent versioning and CI pipeline (Python tooling vs. Gradle/Android build) without
  polluting either repo's build matrix.
- Cleaner contributor experience for people who want to work on the testing platform without
  cloning/building the Android app.
- No forced coupling between the platform's release cadence and the app's.

**Negative:**
- Cross-repo coordination is needed when the SmarType app changes in ways that affect scenarios
  (new resource-ids, new screens). Mitigated by treating the APK path/build as a runtime input to
  the testing platform (a CLI/MCP argument), not a git submodule or build-time dependency — the
  platform never needs to check out `smartype/` source.
- A single-repo split (not two) means the Agent Interface (MCP layer) cannot be
  independently versioned/distributed from the core engine. Acceptable: there is no current
  requirement for that, and splitting later if it becomes necessary is a mechanical extraction,
  not a redesign, given the existing internal module boundaries (see architecture.md §11).

## Alternatives Considered
- **Monorepo subdirectory inside `smartype/`.** Rejected: forces Python and Gradle tooling into
  one CI matrix, and couples the platform's commit history/versioning to an unrelated Android app.
- **Two repos (`smartype-agent` + `verdict`) from day one.** Rejected as premature: the
  "agent interface" is a thin layer over the testing engine with the same contributors and release
  cadence; splitting now would mean cross-repo versioning overhead before there's an actual
  boundary forcing it.
