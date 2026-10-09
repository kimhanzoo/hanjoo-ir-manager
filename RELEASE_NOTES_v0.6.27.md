# HanJoo IR 0.6.27 — learning and replay audit

Audited both manual device creation and learning/relearning buttons on an existing device, against Manager 0.6.26 (`b82418861646fd999c4b3cee4f666591cd7dc735`).

## Fixes

- A late capture result or cancellation error cannot overwrite a newly opened learning dialog. Stale capture tokens are discarded.
- Device creation awaits integration reload before returning success; a client cannot start learning against the manager about to be unloaded. Active captures are canceled on unload.
- Save validates the token's device, age and signal quality before using it. A failed storage write restores the previous command/climate state and preserves the token for retry. The dialog offers another save attempt. Relearning keeps the old command until the replacement is saved; canceling leaves it intact.
- Serialize complete logical transmit requests, including multiple codes/repetitions. Validate all codes before transmitting any of them, avoiding a partial press followed by a malformed-code error.
- Release the receiver reservation and pending future when subscribing to a receiver fails.
- Reject unsupported carrier frequencies during conversion, before allowing a capture to be saved. Preserve signed mark/space phases, trim leading receiver idle, and reject malformed phases rather than silently changing their signs.
- Learning a new command through Home Assistant's remote action also creates its button through the registered live button adder.
- Add “Phát thử” to the learning preview. It sends the full pending capture through the same transmitter path as a saved button without replacing the old command or consuming the token.

## What “learned” means

A successful capture checks timing structure, not whether the appliance accepted the command. ESPHome's HA infrared receiver adapter currently supplies timings without measuring carrier modulation. The preview labels an assumed frequency; 38 kHz is the fallback, not a measurement. A remote requiring another carrier may still fail to control its appliance.

Receiver events can split one press into bursts. When an inter-burst gap is missing, the existing 10 ms fallback cannot reconstruct its true duration. Such captures now show a warning instead of appearing fully verified. Test the capture; if it fails, configure receiver idle to retain a complete command, obtain a known compatible code, and check the transmitter/receiver routing. Do not treat a structural “good” result as appliance acknowledgement.

## Validation

13 asynchronous Python regression tests cover manual device creation/new command, full preview replay, JSON persistence/reload/replay, relearn cancellation/replacement, storage failure rollback/retry for commands and climate cells, wrong-device token preservation, concurrent multi-code transmission, prevalidation, receiver subscription failure/cancellation, real callback capture collection, frequency/phase validation, and creation-response/reload ordering. Two Node scenarios verify stale success/error isolation. Existing climate/timer regressions also pass.

The old 0.6.26 source reproduces seven failures in the initial ten backend tests and the stale-dialog failure in Node; the preview-test feature is absent in that version. Tests use HA transport/storage doubles and extracted production methods, not a full HA instance. No live transmitter/appliance or HAOS restart was available. These fixes establish code behavior; they do not establish the cause of every user report or prove hardware compatibility.

## Updating

Update the Core add-on to 0.6.27, start it so its bundled Manager is installed, then restart Home Assistant to load the Python integration. A standalone install must update `custom_components/hanjoo_ir` and restart HA. Reload the browser to refresh the panel. Existing learned data is retained; signals already captured with missing/wrong timings still need to be learned again.
