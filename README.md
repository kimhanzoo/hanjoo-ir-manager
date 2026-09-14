# HanJoo IR Manager

HanJoo IR Manager is a Home Assistant integration for discovering, learning and controlling infrared devices through **HanJoo IR Core**.

## Highlights

- **Automatic remote identification**: capture several commands from an existing remote and let the local Core analyze the protocol and recommend a compatible device profile.
- **Brand/model search**: search by manufacturer or model and test profiles from HanJoo's protocol engine plus optional online libraries such as **SmartIR** and **Flipper-IRDB**.
- **Manual learning fallback**: if a device is unknown or unsupported, learn individual IR commands directly and create a usable device anyway.
- **Home Assistant-native entities**: device functions are exposed with familiar HA entity models where possible, for example `climate` for air conditioners, `fan` for fans, `media_player` for supported media equipment, and buttons/remotes for generic commands.
- **Automation and voice assistant friendly**: once a device is represented as normal Home Assistant entities, it can be used in dashboards, automations, Assist/voice workflows and other HA integrations.
- **Local-first runtime**: remote identification uses the local HanJoo Core. Online libraries are only used when you explicitly search by brand/model and enable them.

## Coverage

HanJoo uses several complementary coverage layers:

- the local Core includes a structured HVAC codec set from `irtxrx` plus broader IR recognition from IRremoteESP8266;
- SmartIR and Flipper-IRDB can add many model-specific profiles during explicit brand/model search;
- manual learning supports devices that are not yet present in any catalog.

These sources overlap heavily, so there is no honest single number of unique devices that can be added together without double-counting. In practice, the combination covers a broad range of common air conditioners, TVs, fans, projectors, audio equipment and generic IR appliances, while manual learning provides the fallback for unknown devices.

## Required companion add-on

HanJoo IR Manager requires **HanJoo IR Core** for protocol generation, decoding and local remote identification.

Add-on repository:

https://github.com/kimhanzoo/HanJoo_IR_Addon

Install the Core first or immediately after installing the Manager:

1. Home Assistant → **Settings** → **Add-ons** → **Add-on Store**.
2. Open the **⋮** menu → **Repositories**.
3. Add: `https://github.com/kimhanzoo/HanJoo_IR_Addon`
4. Open **HanJoo IR Core**.
5. Install it and start it.
6. Return to **Settings → Devices & services** and add/configure HanJoo IR Manager.

## Installation with HACS

1. HACS → **Integrations** → **Custom repositories**.
2. Add this repository as **Integration**.
3. Install **HanJoo IR Manager**.
4. Restart Home Assistant.
5. Install and start **HanJoo IR Core** using the steps above.
6. Add the HanJoo IR integration from **Settings → Devices & services**.

## Typical workflow

1. Try **Identify by remote** if you still have the original remote.
2. If that is not enough, use **Search by brand/model** and test compatible profiles.
3. If no profile works, use **Manual learning** to capture the commands yourself.

## License

HanJoo IR Manager is source-available for installation and personal use. See `LICENSE`.
