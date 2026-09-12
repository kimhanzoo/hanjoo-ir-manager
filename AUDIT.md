# HanJoo IR Release Audit

## Result
Release packaging audit: PASS for static/syntax/source-leak checks.

## Source protection
- Public HACS repository necessarily contains Manager Python/JavaScript source.
- Public Add-on repository does NOT contain clear `core_backend.cjs`.
- Core logic is stored as compressed/XOR protected runtime. This prevents casual
  source disclosure but is not cryptographic DRM and can still be reverse-engineered.
- IRremoteESP8266 bridge/probe source is public because it is third-party-facing glue.

## Multi-architecture
- Add-on metadata supports `amd64` and `aarch64`.
- Core runtime itself is architecture-independent Node.js.
- IRremoteESP8266 helper is compiled natively inside the target Docker build.
- GitHub Actions is included to build-test both linux/amd64 and linux/arm64.
- This packaging environment did not execute a full networked Docker build;
  the included CI is the final architecture build gate after upload to GitHub.

## Licensing
- irtxrx is identified as MIT upstream.
- IRremoteESP8266 is pinned to commit
  `1e2f0f3ef0a93cbf2a8ddb2e95130f8f4c584b3f` and identified as LGPL-2.1.
- Exact upstream source links and notices are included.

## HACS/Add-on split
HACS cannot install a Home Assistant add-on. Publish the Manager and Add-on as
two separate GitHub repositories.
