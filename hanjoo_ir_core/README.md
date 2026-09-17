# HanJoo IR for Home Assistant

**HanJoo IR** turns Home Assistant into a practical IR remote manager that combines multiple protocol engines and community libraries instead of relying on a single database. The Manager correlates evidence from **HanJoo Core/Brain, IRremoteESP8266, irtxrx, SmartIR, Flipper-IRDB, saved profiles, and learned RAW signals** to identify the best-supported device/profile while keeping a manual-learning fallback.

## Highlights

- Multi-source IR recognition and profile matching.
- Native Home Assistant entities such as `climate`, `media_player`, `fan`, `remote`, and buttons where appropriate.
- Runtime learning/sending through ESPHome 2026.x infrared proxy entities; after the IR bridge is flashed, normal device management happens in HanJoo IR Manager.
- One-install model: install the **HanJoo IR Core add-on** and it installs/updates the thin Manager integration automatically. HACS is optional.
- Local-first. Learned codes, device configuration, and routing remain in Home Assistant storage so they follow Home Assistant backup/restore.
- Supported add-on architectures: **Intel/AMD x86-64 (`amd64`)** and **64-bit ARM (`aarch64`)**.

## Install in Home Assistant

1. Open **Settings → Add-ons → Add-on Store**.
2. Open the menu **⋮ → Repositories**.
3. Add this repository:

   `https://github.com/kimhanzoo/HanJoo_IR_Addon`

4. Install **HanJoo IR Core** and start it.
5. The add-on automatically installs/updates **HanJoo IR Manager** under `/config/custom_components/hanjoo_ir`.
6. After the first install or whenever the Manager version changes, restart **Home Assistant Core once**.
7. Open **HanJoo IR** from the Home Assistant sidebar and select your IR transmitter/receiver entities.

For developers or users who want HACS to own the integration, the separate Manager repository is still available; disable `install_manager` in the add-on options first.

## Hardware

You only need an inexpensive IR bridge. Two common choices are:

- an **ESP32/ESP8266-compatible board** plus an IR LED/transmitter stage and a 38 kHz IR receiver; or
- a low-cost **Tuya IR blaster using BK7231N** that is compatible with ESPHome/LibreTiny and can be reflashed. Hardware revisions vary, so verify the board/chip/pins before flashing.

Example ESPHome configuration:

```yaml
remote_transmitter:
  id: ir_tx
  pin: 7
  carrier_duty_percent: 50%

remote_receiver:
  id: ir_rx
  pin:
    number: 8
    inverted: true
    mode:
      input: true
      pullup: true
  tolerance: 55%
  filter: 50us
  idle: 10ms
  buffer_size: 2kb

  # Optional for debugging; HanJoo IR Manager does not require this log.
  dump: all

# ESPHome 2026.x native IR proxy. Home Assistant creates runtime infrared
# entities, so learning/sending new codes does not require recompiling firmware.
infrared:
  - platform: ir_rf_proxy
    name: IR Transmitter
    remote_transmitter_id: ir_tx

  - platform: ir_rf_proxy
    name: IR Receiver
    receiver_frequency: 38kHz
    remote_receiver_id: ir_rx
```

**Change GPIO 7 and GPIO 8 to match your hardware.** Once the device appears in Home Assistant as an IR transmitter and receiver, normal learning, device creation, routing, testing, and management are handled by HanJoo IR Manager.

## Recognition priority

Typical flow:

`Native Home Assistant → HanJoo Protocol Engine/Brain → SmartIR / Flipper-IRDB → Saved/Learned Custom`

The Fusion layer can compare several sources for the same physical remote instead of trusting the first protocol guess. Automatic recommendations only pass when the evidence clears safety/confidence checks; otherwise HanJoo keeps the user in search/manual-learning mode.

## Updating

Every release bumps the add-on version. Home Assistant then shows **Update** in the Add-on page. Updating the add-on also updates the bundled Manager integration. No uninstall/reinstall is required.
