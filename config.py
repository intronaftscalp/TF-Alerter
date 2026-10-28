import os
import sys
import shutil
import json
import hashlib


# --- 1. СИСТЕМНЫЕ НАСТРОЙКИ ---
def get_base_path():
    """
    Определяет базовую папку программы:
    - Если запущено из exe (PyInstaller): использует _MEIPASS
    - Если запущено из launcher.py: использует переменную окружения TFALER_HOME
    - Иначе: использует директорию текущего скрипта
    """
    # Проверяем переменную окружения (для launcher.py)
    if "TFALER_HOME" in os.environ:
        return os.environ["TFALER_HOME"]

    if hasattr(sys, "_MEIPASS"):
        # PyInstaller: используем _MEIPASS как базовую директорию
        return sys._MEIPASS

    # Разработка: используем директорию скрипта
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_path()
SOUNDS_DIR = os.path.join(BASE_DIR, "Sounds")
SOUND_DIR_VOICE = os.path.join(SOUNDS_DIR, "Voice")
SOUND_DIR_TICK = os.path.join(SOUNDS_DIR, "Tick")
SOUND_DIR_TRANSITION = os.path.join(SOUNDS_DIR, "Transition")
SOUND_DIR_ALERTS = os.path.join(SOUNDS_DIR, "Alerts")
SOUND_DIR_FUNDING = os.path.join(SOUND_DIR_ALERTS, "Funding")
SOUND_DIR_LISTING = os.path.join(SOUND_DIR_ALERTS, "Listing")
SOUND_DIR_SESSIONS = os.path.join(SOUND_DIR_ALERTS, "Sessions")
LOGO_DIR = os.path.join(BASE_DIR, "Logo")
LOGO_PATH = os.path.join(LOGO_DIR, "Logo.png")


# Проверяем наличие файлов и выводим путь для отладки
def _validate_paths():
    if not os.path.exists(LOGO_PATH):
        print(f"⚠️ Логотип не найден: {LOGO_PATH}")
        print(f"BASE_DIR: {BASE_DIR}")
        print(f"LOGO_DIR: {LOGO_DIR}")
        alt_logo = os.path.join(BASE_DIR, "..", "..", "Logo", "Logo.png")
        if os.path.exists(alt_logo):
            return os.path.abspath(alt_logo)
    return LOGO_PATH


LOGO_PATH = _validate_paths()

# --- 2. НАСТРОЙКИ ПРИЛОЖЕНИЯ ---
APP_NAME = "TF-Alerter"
APP_VERSION = "1.3"
WINDOW_SIZE = (360, 580)

# --- ИНФОРМАЦИЯ ОБ АВТОРЕ ---
AUTHOR_NAME = "intronaft"
SMART_LINK_URL = "https://linktr.ee/intronaft"
YOUTUBE_URL = SMART_LINK_URL

# --- КРИПТОАДРЕСА ДЛЯ ДОНАТОВ ---
CRYPTO_ADDRESSES = {
    "BTC": {
        "label": "Bitcoin (BTC)",
        "network": "Bitcoin",
        "address": "bc1qrzyz9j44hj0ex9q33fhghwxhg2clysxyq0ps9f",
    },
    "ETH": {
        "label": "Ethereum (ETH)",
        "network": "ERC20",
        "address": "0x416E6544D8DCD9C4dDa2C10D394480F89642FaD7",
    },
    "BNB": {
        "label": "BNB (Binance Coin)",
        "network": "BEP20 (BSC)",
        "address": "0x416E6544D8DCD9C4dDa2C10D394480F89642FaD7",
    },
    "USDT_BEP20": {
        "label": "USDT",
        "network": "BEP20 (BNB Smart Chain)",
        "address": "0x416E6544D8DCD9C4dDa2C10D394480F89642FaD7",
    },
    "USDT_TRC20": {
        "label": "USDT",
        "network": "TRC20 (Tron)",
        "address": "TPuCWaaHgdCJEjhRp1wG1wQbWHgkd9Rpdq",
    },
    "USDT_ERC20": {
        "label": "USDT",
        "network": "ERC20 (Ethereum)",
        "address": "0x416E6544D8DCD9C4dDa2C10D394480F89642FaD7",
    },
}

_EXPECTED_CRYPTO_ADDRESSES_HASH = (
    "576bc9e88e7b7dca9e19ea1b24b59eff391523fce8bf354f2f2d56880d104d3c"
)


def _crypto_addresses_hash() -> str:
    payload = {
        key: {
            "address": value.get("address", ""),
            "network": value.get("network", ""),
            "label": value.get("label", ""),
        }
        for key, value in CRYPTO_ADDRESSES.items()
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_crypto_addresses_integrity() -> bool:
    try:
        return _crypto_addresses_hash() == _EXPECTED_CRYPTO_ADDRESSES_HASH
    except Exception:
        return False


# --- 3. ЦВЕТОВАЯ СХЕМА ---
COLORS = {
    "background": "#121212",
    "panel": "#1e1e1e",
    "text": "#e0e0e0",
    "accent": "#1e90ff",
    "danger": "#e81123",
    "danger_hover": "#f1707a",
    "border": "#333333",
    "hover": "#3e3e42",
}

# --- 4. НАСТРОЙКИ ТАЙМЕРА И ЗВУКА ---
# За сколько секунд до закрытия включать ГОЛОС
VOICE_LEAD_TIME = 10

# 💡 СОВЕТ О ЗВУКАХ:
# Громкость в программе идёт от 0% до 100% для чистого звучания.
# Если нужно громче - увеличьте громкость в настройках Windows.
# Добавляйте звуки в формате WAV или MP3.

# Файлы тиканья (должны лежать в папке sounds)
SOUND_TICK = "tick.wav"  # Обычный тик (5, 4, 3, 2 сек)
SOUND_TICK_LONG = "transition.wav"  # Длинный тик (1 сек)
SOUND_FUNDING_ALERT = "funding_alert.wav"
SOUND_LISTING_ALERT = "listing_alert.wav"
SOUND_SESSION_ALERT = "session_alert.wav"
ALLOWED_SOUND_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".ogg",
    ".m4a",
    ".aac",
    ".flac",
    ".wma",
    ".opus",
}
MAX_SOUND_FILENAME_LENGTH = 96

# Верхний предел выходной громкости для предотвращения клиппинга/хрипа на пиках.
# 1.0 в сумме с системным микшером и наложением нескольких потоков может давать перегруз.
AUDIO_MAX_OUTPUT_VOLUME = 0.86


def clamp_audio_volume(volume_01, max_output=AUDIO_MAX_OUTPUT_VOLUME):
    """Clamps volume to [0.0, max_output] for cleaner playback."""
    try:
        value = float(volume_01)
    except Exception:
        value = 0.0

    value = max(0.0, min(1.0, value))
    try:
        max_value = float(max_output)
    except Exception:
        max_value = float(AUDIO_MAX_OUTPUT_VOLUME)
    max_value = max(0.0, min(1.0, max_value))
    return min(value, max_value)


def slider_to_audio_volume(volume_percent, max_output=AUDIO_MAX_OUTPUT_VOLUME):
    """Converts 0..100 slider value to a safe output volume with headroom."""
    try:
        percent = float(volume_percent)
    except Exception:
        percent = 0.0
    return clamp_audio_volume(percent / 100.0, max_output=max_output)


def sanitize_sound_filename(filename: str, fallback: str = "") -> str:
    """Returns a safe sound filename (basename + allowed extension) or fallback."""
    candidate = str(filename or "").replace("\x00", "").strip()
    backup = str(fallback or "").replace("\x00", "").strip()
    if not candidate:
        candidate = backup

    candidate = os.path.basename(candidate).strip()
    if not candidate or candidate in (".", ".."):
        return ""
    if len(candidate) > MAX_SOUND_FILENAME_LENGTH:
        return ""
    if any(ch in candidate for ch in ("/", "\\", ":")):
        return ""

    name_root, ext = os.path.splitext(candidate)
    if not name_root:
        return ""
    if ext.lower() not in ALLOWED_SOUND_EXTENSIONS:
        return ""

    for ch in candidate:
        if ch.isalnum() or ch in ("-", "_", ".", " ", "(", ")"):
            continue
        return ""
    return candidate


def _safe_join_under(base_dir: str, filename: str) -> str:
    """Joins a filename under base_dir and guarantees the result stays inside base_dir."""
    if not filename:
        return ""
    base_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(os.path.normpath(os.path.join(base_abs, filename)))
    try:
        if os.path.commonpath([base_abs, target_abs]) != base_abs:
            return ""
    except Exception:
        return ""
    return target_abs


def get_sound_dir(kind: str) -> str:
    if kind in ("main", "voice"):
        return SOUND_DIR_VOICE
    if kind == "tick":
        return SOUND_DIR_TICK
    if kind == "funding":
        return SOUND_DIR_FUNDING
    if kind == "listing":
        return SOUND_DIR_LISTING
    if kind == "session":
        return SOUND_DIR_SESSIONS
    if kind == "transition":
        return SOUND_DIR_TRANSITION
    return SOUNDS_DIR


def get_sound_path(kind: str, filename: str) -> str:
    safe_filename = sanitize_sound_filename(filename)
    if not safe_filename:
        return ""

    preferred = _safe_join_under(get_sound_dir(kind), safe_filename)
    if preferred and os.path.exists(preferred):
        return preferred

    # Backward compatibility: allow files in legacy folders
    if kind in ("funding", "listing"):
        legacy = _safe_join_under(SOUND_DIR_TRANSITION, safe_filename)
        if legacy and os.path.exists(legacy):
            return legacy

    # Backward compatibility: allow files in the base Sounds folder
    fallback = _safe_join_under(SOUNDS_DIR, safe_filename)
    return fallback or ""


def _ensure_sound_dirs():
    for path in (
        SOUNDS_DIR,
        SOUND_DIR_VOICE,
        SOUND_DIR_TICK,
        SOUND_DIR_TRANSITION,
        SOUND_DIR_ALERTS,
        SOUND_DIR_FUNDING,
        SOUND_DIR_LISTING,
        SOUND_DIR_SESSIONS,
    ):
        os.makedirs(path, exist_ok=True)


def _migrate_sound_file(kind: str, filename: str):
    safe_filename = sanitize_sound_filename(filename)
    if not safe_filename:
        return
    src = _safe_join_under(SOUNDS_DIR, safe_filename)
    dst = _safe_join_under(get_sound_dir(kind), safe_filename)
    if not src or not dst:
        return
    if not os.path.exists(src):
        return
    if os.path.exists(dst):
        return
    try:
        shutil.move(src, dst)
    except Exception:
        pass


def migrate_sounds_to_subdirs():
    _ensure_sound_dirs()
    items = set()

    for data in TIMEFRAMES.values():
        items.add(("main", data.get("file")))

    for filename in SOUND_TICK_BY_TF.values():
        items.add(("tick", filename))

    for filename in SOUND_TRANSITION_BY_TF.values():
        items.add(("transition", filename))

    items.add(("tick", SOUND_TICK))
    items.add(("transition", SOUND_TICK_LONG))

    # Migrate alert files with any extension
    for base_name in ["funding_alert", "listing_alert", "session_alert"]:
        if base_name.startswith("funding"):
            kind = "funding"
        elif base_name.startswith("listing"):
            kind = "listing"
        else:
            kind = "session"
        for ext in [".wav", ".mp3", ".ogg"]:
            items.add((kind, f"{base_name}{ext}"))

    # Also migrate any TTS pre-recorded files from Voice folder
    try:
        voice_files = os.listdir(SOUND_DIR_VOICE)
        for filename in voice_files:
            if "funding" in filename.lower():
                items.add(("funding", filename))
    except Exception:
        pass

    for kind, filename in items:
        _migrate_sound_file(kind, filename)


# Список таймфреймов
TIMEFRAMES = {
    "1m": {"file": "1m_voice.wav", "seconds": 60, "label": "1 Минута"},
    "5m": {"file": "5m_voice.wav", "seconds": 300, "label": "5 Минут"},
    "15m": {"file": "15m_voice.wav", "seconds": 900, "label": "15 Минут"},
    "30m": {"file": "30m_voice.wav", "seconds": 1800, "label": "30 Минут"},
    "1h": {"file": "1h_voice.wav", "seconds": 3600, "label": "1 Час"},
    "4h": {"file": "4h_voice.wav", "seconds": 14400, "label": "4 Часа"},
    "1d": {"file": "1d_voice.wav", "seconds": 86400, "label": "1 День"},
    "1w": {"file": "1w_voice.wav", "seconds": 604800, "label": "1 Неделя"},
    "1M": {"file": "1Mo_voice.wav", "seconds": 2592000, "label": "1 Месяц"},
}

# Переводы для таймфреймов
TIMEFRAME_LABELS = {
    "RU": {
        "1m": "1 Минута",
        "5m": "5 Минут",
        "15m": "15 Минут",
        "30m": "30 Минут",
        "1h": "1 Час",
        "4h": "4 Часа",
        "1d": "1 День",
        "1w": "1 Неделя",
        "1M": "1 Месяц",
    },
    "EN": {
        "1m": "1 Minute",
        "5m": "5 Minutes",
        "15m": "15 Minutes",
        "30m": "30 Minutes",
        "1h": "1 Hour",
        "4h": "4 Hours",
        "1d": "1 Day",
        "1w": "1 Week",
        "1M": "1 Month",
    },
}


def get_timeframe_label(tf_key, lang="RU"):
    """Получить переведённое название таймфрейма"""
    return TIMEFRAME_LABELS.get(lang, {}).get(tf_key, TIMEFRAMES[tf_key]["label"])


# Персональные звуки для каждого ТФ (уникальные для каждого таймфрейма)
# Для 1M (месяца) используем префикс 1Mo вместо 1M

# VOICE звуки (колонка 1 - основной голосовой алерт)
for tf_key in TIMEFRAMES.keys():
    if tf_key == "1M":
        TIMEFRAMES[tf_key]["file"] = "1Mo_voice.wav"
    else:
        TIMEFRAMES[tf_key]["file"] = f"{tf_key}_voice.wav"

# TICK звуки (колонка 2 - отсчет последних 5 секунд)
SOUND_TICK_BY_TF = {}
for tf_key in TIMEFRAMES.keys():
    if tf_key == "1M":
        SOUND_TICK_BY_TF[tf_key] = "1Mo_tick.wav"
    else:
        SOUND_TICK_BY_TF[tf_key] = f"{tf_key}_tick.wav"

# TRANSITION звуки (колонка 3 - переход на 59-ю секунду)
SOUND_TRANSITION_BY_TF = {}
for tf_key in TIMEFRAMES.keys():
    if tf_key == "1M":
        SOUND_TRANSITION_BY_TF[tf_key] = "1Mo_transition.wav"
    else:
        SOUND_TRANSITION_BY_TF[tf_key] = f"{tf_key}_transition.wav"
# Конфигурация overlay часов
OVERLAY_SHOW_MODE = "custom"  # "always" или "custom" (только для указанных приложений)
OVERLAY_WINDOWS = [
    "Profit Forge",
    "TF-Alerter",
]  # Список приложений для отображения overlay
