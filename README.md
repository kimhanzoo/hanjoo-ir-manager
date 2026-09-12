# HanJoo IR Manager

Home Assistant custom integration for managing local IR devices through HanJoo IR Core.

## Installation with HACS

1. HACS → Integrations → Custom repositories.
2. Add this repository as **Integration**.
3. Install **HanJoo IR Manager**.
4. Restart Home Assistant.
5. Install the separate **HanJoo IR Core** add-on repository and start the add-on.
6. Add the HanJoo IR integration from Settings → Devices & services.

The Manager and Core are separate repositories because HACS installs custom integrations, while Home Assistant add-ons are installed through the Add-on Store.

## Runtime
- Local IR control.
- Remote identification uses local HanJoo Core only.
- SmartIR/Flipper may be used only in explicit brand/model search when enabled.

## License
HanJoo IR Manager is source-available for installation and personal use. See `LICENSE`.
