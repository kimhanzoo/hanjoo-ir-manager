# HanJoo IR Manager

**HanJoo IR Manager** is a Home Assistant integration for discovering, learning and controlling infrared devices through **HanJoo IR Core**.

## Main features

- **Automatic identification from an existing remote**: capture several commands from the original remote and let the local HanJoo Core analyze the signal, protocol family and candidate device profile.
- **Search by brand/model**: search known manufacturers or model names and test compatible profiles from HanJoo's protocol engine plus optional online libraries such as **SmartIR** and **Flipper-IRDB**.
- **Manual learning for unknown devices**: if no profile exists, learn individual IR commands directly from the physical remote and create a usable device anyway.
- **Home Assistant-native entities**: HanJoo maps supported device functions to familiar entity types where possible, such as `climate` for air conditioners, `fan` for fans, `media_player` for TVs/audio equipment, and buttons/remotes for generic learned commands.
- **Automation and voice assistant friendly**: once added as Home Assistant entities, devices can be used in dashboards, automations, scripts, scenes and Assist/voice workflows.
- **Local-first identification**: automatic remote identification uses HanJoo Core locally. SmartIR/Flipper are only used when you explicitly choose brand/model search and enable those sources.

## Coverage

HanJoo combines several overlapping layers:

- local structured protocol support from `irtxrx`;
- broader local protocol recognition from IRremoteESP8266;
- optional SmartIR and Flipper-IRDB model/profile search;
- manual learning for devices not present in any catalog.

Because these sources overlap, there is no truthful single unique-device count that can simply be added together. The practical coverage spans many common air conditioners, TVs, fans, projectors, audio devices and generic IR appliances.

Common protocol/device families include Daikin, Panasonic, LG, Mitsubishi Electric, Mitsubishi Heavy Industries, Samsung, Gree, Midea, Haier, Toshiba, Fujitsu, Hitachi, Carrier, Sharp, Sanyo, Whirlpool, TCL, Kelvinator, Electra, plus generic NEC / RC5 / RC6 / Sony / JVC-style IR protocols.

## Install HanJoo IR Manager with HACS

Manager repository:

https://github.com/kimhanzoo/hanjoo-ir-manager

1. Open **HACS → Integrations**.
2. Open the **⋮** menu → **Custom repositories**.
3. Add:
   `https://github.com/kimhanzoo/hanjoo-ir-manager`
4. Select category **Integration**.
5. Install **HanJoo IR Manager**.
6. Restart Home Assistant.
7. Then install and start **HanJoo IR Core** using the instructions below.
8. Go to **Settings → Devices & services** and add/configure HanJoo IR Manager.

## Required HanJoo IR Core add-on

HanJoo IR Manager requires **HanJoo IR Core** for protocol generation, decoding and local remote identification.

Core repository:

https://github.com/kimhanzoo/HanJoo_IR_Addon

Install Core:

1. Home Assistant → **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu → **Repositories**.
3. Add:
   `https://github.com/kimhanzoo/HanJoo_IR_Addon`
4. Open **HanJoo IR Core**.
5. Install it and start it.
6. Return to **Settings → Devices & services** and configure HanJoo IR Manager.

## Recommended workflow

1. **Identify by remote** if you still have the original remote.
2. If needed, use **Search by brand/model** and test candidate profiles.
3. If nothing matches, use **Manual learning** to capture the commands yourself.

## License

HanJoo IR Manager is source-available for installation and personal use. See `LICENSE`.
