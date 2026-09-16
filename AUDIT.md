# HanJoo IR 0.6.0 architecture audit

- Thin Integration compiles successfully.
- Frontend JavaScript syntax check passes.
- `fusion_matcher.py` and `raw_protocol_classifier.py` are no longer shipped in the public integration.
- Recognition/scoring policy is delegated to Core Brain on internal port 8102.
- Add-on installer uses an atomic stage/replace flow and backs up an existing unmanaged/HACS integration before adopting it.
- Add-on writes only `/config/custom_components/hanjoo_ir` plus a `hanjoo_ir:` bootstrap key in `configuration.yaml`.
- The bootstrap creates the single config entry automatically on the next Home Assistant restart.
