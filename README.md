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

- local Core: about **90 structured codec entries** plus up to **128 IRremoteESP8266 recognition protocol IDs** at the pinned revision;
- optional SmartIR and Flipper-IRDB model/profile search;
- manual learning for devices not present in a catalog.

The protocol sets overlap, and online profile databases change over time, so adding all of those numbers would create a misleading "total devices" figure. The practical coverage spans many common air conditioners, TVs, fans, projectors, audio devices and generic IR appliances.

Common families include Daikin, Panasonic, LG, Mitsubishi Electric, Mitsubishi Heavy Industries, Samsung, Gree, Midea, Haier, Toshiba, Fujitsu, Hitachi, Carrier, Sharp, Sanyo, Whirlpool, TCL, Kelvinator, Electra, plus generic NEC/RC5/RC6/Sony/JVC-style protocols.

## Required companion add-on

HanJoo IR Manager requires **HanJoo IR Core** for protocol generation, decoding and local remote identification.

Core repository:

https://github.com/kimhanzoo/HanJoo_IR_Addon

Install the Core:

1. Home Assistant → **Settings** → **Add-ons** → **Add-on Store**.
2. Open **⋮ → Repositories**.
3. Add `https://github.com/kimhanzoo/HanJoo_IR_Addon`
4. Open **HanJoo IR Core**.
5. Install and start it.
6. Return to **Settings → Devices & services** and add/configure HanJoo IR Manager.

## Installation with HACS

1. HACS → **Integrations** → **Custom repositories**.
2. Add this repository as **Integration**.
3. Install **HanJoo IR Manager**.
4. Restart Home Assistant.
5. Install/start **HanJoo IR Core** using the steps above.
6. Add HanJoo IR from **Settings → Devices & services**.

## Typical workflow

1. **Identify by remote** if you still have the original remote.
2. If needed, use **Search by brand/model** and test compatible profiles.
3. If no profile works, use **Manual learning**.

## License

HanJoo IR Manager is source-available for installation and personal use. See `LICENSE`.
