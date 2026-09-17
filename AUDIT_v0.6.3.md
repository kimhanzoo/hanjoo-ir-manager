# HanJoo IR v0.6.3 — Audit & QA Report

## Scope
Full audit of the one-install Home Assistant add-on package after the v0.6.1 Brain failure.

## Fixed in v0.6.3

- Replaced Node SEA Brain startup with standard CommonJS Node execution to eliminate `ReferenceError: require is not defined` on HAOS/Alpine Node 22.
- Added strict startup health checks for Core `:8099`, protocol sidecar `:8101`, and Brain `:8102`. The add-on now exits if any mandatory service fails instead of reporting a false healthy startup.
- Added a runtime watchdog for all three services.
- Unified package/runtime version reporting through `HANJOO_VERSION=0.6.3`; stale `Core 0.5.0` and `Brain 0.6.0` strings are removed.
- Fixed protocol evidence accounting: if irtxrx and IRremoteESP8266 both recognize the same physical capture, it counts as **one capture with two evidence sources**, not two captures.
- Normalized protocol group IDs so different engines for the same protocol merge into one Fusion group.
- Preserved Daikin/multi-frame physical-button aggregation: receiver events are collected until a 450 ms quiet window, with an additional 250 ms frontend release guard.
- Improved one-install Manager ownership/update flow and backup of an existing unmanaged/HACS copy before replacement.
- Removed `__pycache__` / `.pyc` from the shipped integration.
- Added stronger CI validation including syntax checks, version consistency, amd64 Docker smoke test of all three `/health` endpoints, Manager auto-install verification, and arm64 image build.
- Expanded README with multi-library recognition, supported architectures, one-install instructions, hardware guidance, and ESPHome IR proxy example.

## Local audit results

PASS:
- Shell syntax (`sh -n`).
- Node syntax: Core wrapper, protocol sidecar, decoded Brain payload.
- Decoded protected Core runtime syntax.
- Python AST parse for all 18 integration Python modules.
- JSON parsing for integration metadata/translations.
- Frontend JavaScript syntax (`node --check`).
- Relative local-import consistency.
- No private `fusion_matcher.py` / `raw_protocol_classifier.py` modules in the thin integration.
- No shipped `.pyc` / `__pycache__`.
- Version consistency: add-on, Manager manifest, constants, runtime = 0.6.3.
- Brain `/health` reports 0.6.3.
- Synthetic LG timing classifier regression.
- Multi-engine duplicate-count regression: 3 physical Daikin captures recognized by two engines remain `matched_captures=3`, never 6.
- One-install smoke simulation: Manager 0.6.3 installs, bootstrap is added, and Core/Protocol/Brain all pass strict health checks.
- Upgrade regression: an unmanaged Manager 0.5.8 is backed up before 0.6.3 is installed.

## CI included in package
The repository includes `.github/workflows/validate.yml` to perform a real Docker build/smoke test on GitHub Actions for amd64 and an arm64 build. The current execution environment used to assemble this ZIP does not provide Docker, so the Docker build itself was not executed locally.

## Security note
The recognition Brain is kept out of the public Home Assistant integration, but because this repository builds the Brain from an encoded JavaScript payload, this is **not strong source-code secrecy** against a determined reverse engineer. Strong IP protection requires a private build repository producing prebuilt native/container artifacts (eventually Rust/native binary is the preferred path). v0.6.3 prioritizes runtime stability.
