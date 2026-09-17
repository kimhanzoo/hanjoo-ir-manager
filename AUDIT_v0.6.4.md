# HanJoo IR v0.6.4 — Audit & QA

## Scope

This release focuses on the remote-identification dead end where HanJoo could recognize a protocol family (for example Samsung32) but the UI exposed a Test button without a sendable source.

## Logic audit

PASS:
- Recognition-only family candidates use captured RAW replay, not `protocol/profile` generation.
- Successful RAW replay is tracked separately from exact profile verification.
- Recognition-only candidates never become directly installable as a model/profile solely because RAW replay worked.
- Detected brand/model hints automatically seed a second-stage profile search.
- Protocol Engine, saved profiles, SmartIR and Flipper-IRDB suggestions are surfaced without adding them to Brain confidence evidence.
- Suggested model/profile must be physically Test-confirmed before the UI exposes `Use this profile`.
- Existing exact profile/protocol candidates still use their native test path.

## Local checks completed

PASS:
- Python AST/compile syntax for integration.
- Frontend JavaScript `node --check`.
- `run.sh` shell syntax.
- Brain payload `node --check`.
- Protocol sidecar JS syntax.
- Brain live `/health` smoke test on 0.6.4.
- Synthetic Samsung32 4/4 capture regression: family recognized consistently as Samsung32.
- Version consistency checks.
- Integration package hygiene: no `__pycache__` / `.pyc`; old public Python Fusion/RAW classifier files are absent.

## Remaining environment-specific check

The current workspace does not provide Docker/Podman, so the complete HAOS-style Docker build (`amd64` + `aarch64`) cannot be executed locally here. The included GitHub Actions workflow retains the build and three-service smoke test for Core :8099, Protocol :8101 and Brain :8102.
