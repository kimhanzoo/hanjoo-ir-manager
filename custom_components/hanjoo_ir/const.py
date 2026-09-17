"""Constants for HanJoo IR Manager."""
from __future__ import annotations

DOMAIN = "hanjoo_ir"
NAME = "HanJoo IR Manager"
VERSION = "0.6.7"
AUTHOR_NAME = "HanJoo"
AUTHOR_FACEBOOK = "Kim Han Yuu"
AUTHOR_EMAIL = "kimhanzoo@gmail.com"

CORE_API_VERSION = 1
CORE_BASE_URL = "http://local-hanjoo-ir-core:8099"
CORE_REQUEST_TIMEOUT = 3.0

PANEL_TITLE = "HanJoo IR"
PANEL_ICON = "mdi:remote-tv"
PANEL_URL = "hanjoo-ir"
PANEL_FILENAME = "hanjoo-ir-panel.js"
PANEL_STATIC_PATH = f"/{DOMAIN}_panel/{PANEL_FILENAME}"

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = DOMAIN
WS_PREFIX = DOMAIN
DEFAULT_FREQUENCY = 38_000
DEFAULT_LEARN_TIMEOUT = 20
MAX_IMPORT_BYTES = 16_000_000
MAX_TIMINGS = 20_000
MAX_DURATION_US = 200_000
MAX_TOTAL_AIRTIME_US = 5_000_000
TRAILING_SPACE_US = 50_000

DEVICE_TYPE_REMOTE = "remote"
DEVICE_TYPE_MEDIA_PLAYER = "media_player"
DEVICE_TYPE_FAN = "fan"
DEVICE_TYPE_CLIMATE = "climate"
DEVICE_TYPES = {DEVICE_TYPE_REMOTE, DEVICE_TYPE_MEDIA_PLAYER, DEVICE_TYPE_FAN, DEVICE_TYPE_CLIMATE}

NATIVE_INTEGRATIONS = [
    {"domain":"lg_infrared","name":"LG Infrared","brand":"LG","device_types":["tv","air_conditioner"],"semantic_entities":["media_player","climate"],"note":"TV và điều hòa LG; có hỗ trợ receiver cho một số trạng thái/lệnh."},
    {"domain":"samsung_infrared","name":"Samsung Infrared","brand":"Samsung","device_types":["tv","air_conditioner"],"semantic_entities":["media_player","climate"],"note":"TV và điều hòa Samsung dùng giao thức native của Home Assistant."},
    {"domain":"dyson_infrared","name":"Dyson Infrared","brand":"Dyson","device_types":["fan"],"semantic_entities":["fan"],"note":"Quạt/máy lọc không khí Dyson điều khiển IR."},
    {"domain":"edifier_infrared","name":"Edifier Infrared","brand":"Edifier","device_types":["speaker","soundbar"],"semantic_entities":["media_player"],"note":"Loa Edifier có profile/model native."},
    {"domain":"marantz_infrared","name":"Marantz Infrared","brand":"Marantz","device_types":["receiver","amplifier"],"semantic_entities":["media_player"],"note":"Ampli/receiver Marantz điều khiển bằng IR."},
    {"domain":"led_infrared","name":"LED Infrared","brand":"Generic LED","device_types":["light"],"semantic_entities":["light"],"note":"LED strip/bulb dùng remote IR 13/24/40/44 nút được hỗ trợ native."},
    {"domain":"persang_infrared","name":"Persang Infrared","brand":"Persang","device_types":["speaker"],"semantic_entities":["media_player"],"note":"Loa Persang có mã native trong Home Assistant."},
]

REMOTE_TEMPLATES: dict[str, dict[str, str]] = {
    "tv": {"power":"Nguồn","on":"Bật","off":"Tắt","volume_up":"Âm lượng +","volume_down":"Âm lượng -","mute":"Tắt tiếng","input":"Nguồn vào","home":"Home","menu":"Menu","up":"Lên","down":"Xuống","left":"Trái","right":"Phải","ok":"OK","back":"Quay lại","channel_up":"Kênh +","channel_down":"Kênh -","play":"Phát","pause":"Tạm dừng","stop":"Dừng","num_0":"0","num_1":"1","num_2":"2","num_3":"3","num_4":"4","num_5":"5","num_6":"6","num_7":"7","num_8":"8","num_9":"9"},
    "projector": {"power":"Nguồn","on":"Bật","off":"Tắt","input":"Nguồn vào","menu":"Menu","up":"Lên","down":"Xuống","left":"Trái","right":"Phải","ok":"OK","back":"Quay lại","volume_up":"Âm lượng +","volume_down":"Âm lượng -","mute":"Tắt tiếng","freeze":"Đóng băng hình"},
    "speaker": {"power":"Nguồn","on":"Bật","off":"Tắt","volume_up":"Âm lượng +","volume_down":"Âm lượng -","mute":"Tắt tiếng","input":"Nguồn vào","play":"Phát","pause":"Tạm dừng","next":"Bài tiếp","previous":"Bài trước"},
    "fan": {"power":"Nguồn","on":"Bật","off":"Tắt","speed_1":"Tốc độ 1","speed_2":"Tốc độ 2","speed_3":"Tốc độ 3","oscillate":"Đảo gió","mode":"Chế độ","timer":"Hẹn giờ","light":"Đèn"},
    "washer": {"power":"Nguồn","start_pause":"Bắt đầu / Tạm dừng","program":"Chương trình","temperature":"Nhiệt độ","spin":"Vắt","delay":"Hẹn giờ","options":"Tùy chọn"},
    "dishwasher": {"power":"Nguồn","start_pause":"Bắt đầu / Tạm dừng","program":"Chương trình","delay":"Hẹn giờ","extra_dry":"Sấy tăng cường","half_load":"Nửa tải","sanitize":"Diệt khuẩn"},
    "custom": {},
}
REMOTE_TEMPLATES["soundbar"] = dict(REMOTE_TEMPLATES["speaker"])
REMOTE_TEMPLATES["receiver"] = dict(REMOTE_TEMPLATES["speaker"])

FALLBACK_KIND_TO_TYPE = {
    "tv": DEVICE_TYPE_MEDIA_PLAYER,
    "projector": DEVICE_TYPE_MEDIA_PLAYER,
    "speaker": DEVICE_TYPE_MEDIA_PLAYER,
    "soundbar": DEVICE_TYPE_MEDIA_PLAYER,
    "receiver": DEVICE_TYPE_MEDIA_PLAYER,
    "fan": DEVICE_TYPE_FAN,
    "air_conditioner": DEVICE_TYPE_CLIMATE,
    "washer": DEVICE_TYPE_REMOTE,
    "dishwasher": DEVICE_TYPE_REMOTE,
    "custom": DEVICE_TYPE_REMOTE,
}
