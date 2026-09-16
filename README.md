# HanJoo IR Manager 0.6.0

This repository contains the **thin Home Assistant integration** only.

Recommended installation for normal users: install the **HanJoo IR Core add-on** from the HanJoo add-on repository. Since 0.6.0 the add-on can install/update this integration automatically; HACS is optional.

The public integration is intentionally limited to Home Assistant entities, panel/UI, IR emitter/receiver bridging, config entry lifecycle, and online-library transport. Raw protocol-family classification, profile scoring, and safe recommendation policy are delegated to the Core Brain service in the add-on.

HACS remains supported for developers and users who prefer to manage the integration independently. In that case disable `install_manager` in the add-on options so the add-on will not overwrite the HACS-managed copy.
