# HanJoo IR Core 0.6.4

## One-install setup
1. Add this repository to Home Assistant Add-on Store.
2. Install and start **HanJoo IR Core**.
3. Restart Home Assistant Core once when the add-on log says the Manager was installed/updated.
4. Open **HanJoo IR** from the sidebar.

You do not need HACS for the normal path. The add-on writes only the HanJoo integration directory and a small `hanjoo_ir:` bootstrap key in `configuration.yaml`. Existing unmanaged/HACS HanJoo integration is backed up before the add-on adopts it.

## Options
- `install_manager`: automatically install the thin integration (default true).
- `auto_update_manager`: keep the add-on-managed integration aligned to the add-on package (default true).

To return to HACS-managed mode, disable `install_manager`, restore/reinstall the HACS integration, and remove the managed bootstrap key if desired.
