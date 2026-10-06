# HanJoo IR 0.6.26

Based on Manager commit 7907d02469edfbaa3fa5188c3518099dd85d661f (0.6.25).

- Apply each receiver sequence once. Unrelated updates no longer revert a local climate command to old received state.
- Discard delayed decode results superseded by a later capture, local transmission, or integration unload.
- Ignore empty native HVAC results; normalize numeric and camel-case HVAC enums; recognize a separate Power ON frame; clear disabled decoded presets.
- Learn horizontal swing and presets through the complete panel → websocket → storage path. Include these dimensions in cell identity; normalize integer/float temperatures.
- Add configurable on/off timers in the device panel and the hanjoo_ir.set_timer action. 0 minutes cancels; at most 7 days. Pending schedules restore from climate state after restart if still in the future. Expired schedules are discarded. Only one timer per climate entity. Failures are exposed in hanjoo_timer_error.

## Timer use

Open HanJoo IR → Devices → select the air conditioner → Hẹn giờ bật/tắt.
For an automation:

```yaml
action: hanjoo_ir.set_timer
target:
  entity_id: climate.your_air_conditioner
data:
  minutes: 60
  action: "off"
```

This timer is executed by Home Assistant and sends a normal power command at expiry. HA and the transmitter must be running. A learned Timer button continues to replay the appliance's native timer code; arbitrary appliance-side timer encoding is not implemented by this patch.

## Install

Add-on: use the packaged repository source in place of your current add-on source, rebuild/start the add-on, then restart Home Assistant once. The bundled Manager is identical to the standalone Manager package. Existing .storage HanJoo data is preserved.
Standalone Manager: replace custom_components/hanjoo_ir and restart Home Assistant. Retain your existing Core add-on; update the bundle to 0.6.26 if using add-on managed installation.

## Validation and limits

Python AST syntax, both frontend JS bundles, run.sh, probe server, protected core loader and decoded Brain syntax checked. Regression tests exercise production methods with stubbed Home Assistant infrastructure: receiver normalization, enum mapping, empty results, stale decoding, duplicate receiver sequences, separate Power ON, learned dimensions, timer validation/replacement/cancellation/expiry/error handling.
No Docker engine or live HAOS/hardware is available here. Full HA setup/service registration, actual IR decode/transmit, timer restart recovery and frontend browser behavior must be checked on a real HA installation. Receiver feedback remains remote-derived state, not confirmation that the appliance actually accepted a command. Native decode requires a compatible protocol/profile and a functioning configured receiver.
