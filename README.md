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
3. Add `https://github.com/kimhanzoo/HanJoo_IR_Addon`.
4. Install **HanJoo IR Core** and start it.
5. The add-on automatically installs/updates this Manager integration.
6. Restart **Home Assistant Core once** after the first Manager install/update.
7. Open **HanJoo IR** from the Home Assistant sidebar.

## Recommended IR bridge configuration

HanJoo follows the same important capture principle used by IRremoteESP8266 `IRrecvDumpV2` and Tasmota: keep a complete physical button press together, especially for A/C remotes that can contain 20–40+ ms gaps between packets.

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
  tolerance: 25%
  filter: 50us
  idle: 50ms
  buffer_size: 4kb
  dump: all

infrared:
  - platform: ir_rf_proxy
    name: IR Transmitter
    remote_transmitter_id: ir_tx

  - platform: ir_rf_proxy
    name: IR Receiver
    receiver_frequency: 38kHz
    remote_receiver_id: ir_rx
```

Change GPIOs to match your hardware. Existing bridges using `idle: 10ms` should be reflashed once with `idle: 50ms` and the larger buffer for best A/C recognition. After that, device management stays in HanJoo IR Manager.

## Does this affect other HanJoo features?

- **Search by brand/model is unaffected.** It searches catalogs and profiles, not receiver timing boundaries.
- **Manual learning remains supported.** HanJoo stores and replays the complete RAW sequence; longer valid inter-packet gaps are preserved.
- **Simple TV/audio remotes remain supported.** A longer idle may capture repeats if a button is held, but HanJoo treats repeats as one physical capture for recognition.
- **A/C recognition improves most**, because Daikin, Panasonic, Mitsubishi and other stateful protocols reach the native decoder intact.

## Recognition flow

`Full physical capture → IRremoteESP8266 native A/C decoder → IRAc normalized HVAC state → HanJoo Brain/Fusion → irtxrx → SmartIR / Flipper-IRDB → Saved/Learned Custom`

For stateful A/C protocols, native results are converted to normalized state fields such as power, mode, temperature, fan and swing before they enter Brain. Generic RC/TV matches from a multi-frame climate capture are treated as diagnostics instead of automatic recommendations, reducing false positives such as RC5/RC6.

## Updating

The normal user updates **HanJoo IR Core** from the Home Assistant Add-on page. No uninstall/reinstall is required.
