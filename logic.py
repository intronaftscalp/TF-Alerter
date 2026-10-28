import os
import datetime
import ctypes
import math
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QUrl, QSettings, Qt
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
import config
from overlay import OverlayClock


class AlerterLogic(QObject):
    time_signal = pyqtSignal(str)
    play_tts_audio_signal = pyqtSignal(str, float)  # (file_path, volume)

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.is_selecting_color = False
        self.overlay = OverlayClock()

        # Звук (раздельные плееры для чистого воспроизведения)
        self.voice_player = QMediaPlayer()
        self.voice_output = QAudioOutput()
        self.voice_player.setAudioOutput(self.voice_output)

        self.tick_player = QMediaPlayer()
        self.tick_output = QAudioOutput()
        self.tick_player.setAudioOutput(self.tick_output)

        self.transition_player = QMediaPlayer()
        self.transition_output = QAudioOutput()
        self.transition_player.setAudioOutput(self.transition_output)
        self._apply_default_audio_output()
        self.media_devices = QMediaDevices()
        self.media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

        # Кеш звуков для мгновенного воспроизведения (без задержки загрузки)
        self.sound_cache = {}
        self.preload_sounds()

        # Основной таймер для логики алертов (каждую секунду)
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.check_time)
        self.last_played_second = -1
        self.last_tick_second = (
            -1
        )  # Отдельный трекер для синхронизации тиков в последних 5 сек

        # Отдельный быстрый таймер для обновления часов (каждые 100мс)
        # Это позволяет часам обновляться более плавно без нагрузки на основную логику
        self.overlay_update_timer = QTimer()
        self.overlay_update_timer.setInterval(100)  # Обновление каждые 100мс
        self.overlay_update_timer.timeout.connect(self.update_overlay_time)

        self.terminal_title = "Profit Forge"
        self.ui.ov_size_slider.valueChanged.connect(self.update_overlay_style)

        # Подключаем сигнал для воспроизведения TTS из потоков
        self.play_tts_audio_signal.connect(self._play_tts_audio_slot)

    def _apply_default_audio_output(self):
        try:
            default_device = QMediaDevices.defaultAudioOutput()
            self.voice_output.setDevice(default_device)
            self.tick_output.setDevice(default_device)
            self.transition_output.setDevice(default_device)
        except Exception:
            pass

    def preload_sounds(self):
        """Предварительная загрузка всех звуков в кеш для мгновенного воспроизведения"""
        print("[SOUND] Preloading sounds...")

        # Загружаем основные голосовые звуки (закрытие таймфреймов)
        for tf_key, tf_data in config.TIMEFRAMES.items():
            filename = tf_data["file"]
            path = config.get_sound_path("main", filename)
            if path and os.path.exists(path):
                self.sound_cache[f"main_{filename}"] = path
                print(f"  + {filename}")
            else:
                print(f"  - {filename} not found")

        # Загружаем звуки тиков
        for tf_key, tick_sound in config.SOUND_TICK_BY_TF.items():
            if tick_sound:
                path = config.get_sound_path("tick", tick_sound)
                if path and os.path.exists(path):
                    self.sound_cache[f"tick_{tick_sound}"] = path

        # Загружаем звуки переходов
        for tf_key, trans_sound in config.SOUND_TRANSITION_BY_TF.items():
            if trans_sound:
                path = config.get_sound_path("transition", trans_sound)
                if path and os.path.exists(path):
                    self.sound_cache[f"transition_{trans_sound}"] = path

        # Загружаем звук "длинный переход" (для последней секунды)
        if hasattr(config, "SOUND_TICK_LONG"):
            path = config.get_sound_path("transition", config.SOUND_TICK_LONG)
            if path and os.path.exists(path):
                self.sound_cache[f"transition_{config.SOUND_TICK_LONG}"] = path

        print(f"[SOUND] Cache loaded: {len(self.sound_cache)} sounds")

    def _get_player_output(self, kind: str):
        if kind == "tick":
            return self.tick_player, self.tick_output
        if kind == "transition":
            return self.transition_player, self.transition_output
        return self.voice_player, self.voice_output

    def _safe_audio_volume(self, slider_percent):
        return config.slider_to_audio_volume(slider_percent)

    def _start_player_clean(self, player, output, path, target_volume):
        safe_volume = config.clamp_audio_volume(target_volume)
        output.setVolume(0.0)
        player.stop()
        player.setSource(QUrl())
        player.setSource(QUrl.fromLocalFile(path))
        player.play()
        QTimer.singleShot(20, lambda out=output, vol=safe_volume: out.setVolume(vol))

    def _on_audio_outputs_changed(self):
        self._apply_default_audio_output()

    def update_overlay_style(self):
        accent_color = config.COLORS.get("accent", "#ffffff")
        accent_alpha = config.COLORS.get("accent_alpha", 255)
        new_size = self.ui.ov_size_slider.value()
        settings = QSettings("MyTradeTools", "TF-Alerter")
        font_family = settings.value("overlay_font_family", "Arial")
        if not isinstance(font_family, str) or not font_family.strip():
            font_family = "Arial"
        bg_enabled = settings.value("overlay_bg_enabled", False, type=bool)
        bg_color = settings.value("overlay_bg_color", "#000000")
        if not isinstance(bg_color, str) or not bg_color.strip():
            bg_color = "#000000"
        self.overlay.update_style(
            accent_color,
            new_size,
            accent_alpha,
            font_family,
            bg_enabled,
            bg_color,
        )

    def update_overlay_time(self):
        """Обновляет время в overlay каждые 100мс (оптимизировано)"""
        now_local = datetime.datetime.now()
        self.overlay.set_time(now_local.strftime("%H:%M:%S"))

    def get_active_window_title_fast(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            return buff.value
        except Exception:
            return ""

    def check_time(self):
        # 1. Время UTC для логики свечей
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        # 2. Локальное время для отображения
        now_local = datetime.datetime.now()

        # Текущая секунда (абсолютная) для защиты от повторов в одном цикле
        current_second_total = (
            now_utc.hour * 3600 + now_utc.minute * 60 + now_utc.second
        )

        if current_second_total != self.last_played_second:
            self.last_played_second = current_second_total
            sec = now_utc.second

            # --- ЛОГИКА АЛЕРТОВ И ТИКАНЬЯ ---

            # Определяем, какой "следующий" момент времени мы ждем (конец минуты)
            # Привязываем к точной границе секунды, чтобы звуки не спешили.
            next_minute_dt = now_utc.replace(
                second=0, microsecond=0
            ) + datetime.timedelta(minutes=1)
            remaining_seconds = int(
                math.ceil((next_minute_dt - now_utc).total_seconds())
            )

            # Проверяем, есть ли активные таймфреймы, которые закроются в конце этой минуты
            closing_tf, closing_msg = self.get_closing_tf(next_minute_dt)

            if closing_tf:
                # 1. ГОЛОСОВОЙ АЛЕРТ (за 10 секунд)
                if remaining_seconds == config.VOICE_LEAD_TIME:
                    # Проверяем, включены ли голосовые звуки
                    settings = QSettings("MyTradeTools", "TF-Alerter")
                    if settings.value("sounds_voice_enabled", True, type=bool):
                        # Проверяем, нужно ли использовать TTS для этого таймфрейма
                        tf_key_prefixed = f"{closing_tf}_use_tts"
                        use_tts = settings.value(tf_key_prefixed, False, type=bool)
                        tf_tts_enabled = settings.value(
                            "tf_tts_enabled", False, type=bool
                        )

                        print(
                            f"[TTS DEBUG] TF: {closing_tf}, use_tts={use_tts}, tf_tts_enabled={tf_tts_enabled}"
                        )

                        if use_tts and tf_tts_enabled:
                            # Используем TTS озвучку
                            print(f"[TTS] Playing TTS for {closing_tf}")
                            self.play_tts_for_timeframe(closing_tf)
                        else:
                            # Используем обычный звук
                            print(f"[SOUND] Playing sound for {closing_tf}")
                            self.play_voice(
                                config.TIMEFRAMES[closing_tf]["file"], "main"
                            )
                    self.time_signal.emit(f"{closing_msg} (через 10с)")

                # 2. ТИКАНЬЕ (5, 4, 3, 2 сек) - синхронизировано по абсолютной секунде
                elif 2 <= remaining_seconds <= 5:
                    # Используем last_tick_second для точной синхронизации тиков
                    # Это гарантирует, что каждый тик играет ровно в момент прихода на эту секунду
                    tick_sound = config.SOUND_TICK_BY_TF.get(closing_tf, "")
                    if tick_sound and current_second_total != self.last_tick_second:
                        self.last_tick_second = current_second_total
                        # Проверяем, включены ли звуки тиков
                        settings = QSettings("MyTradeTools", "TF-Alerter")
                        if settings.value("sounds_tick_enabled", True, type=bool):
                            self.play_voice(tick_sound, "tick")

                # 3. ПОСЛЕДНИЙ ТИК / ПЕРЕХОД (1 сек)
                elif remaining_seconds == 1:
                    settings = QSettings("MyTradeTools", "TF-Alerter")
                    transition_sound = config.SOUND_TRANSITION_BY_TF.get(closing_tf, "")
                    transition_enabled = settings.value(
                        "sounds_transition_enabled", True, type=bool
                    )

                    if transition_sound and transition_enabled:
                        self.play_voice(transition_sound, "transition")
                    else:
                        tick_sound = config.SOUND_TICK_BY_TF.get(closing_tf, "")
                        if tick_sound and current_second_total != self.last_tick_second:
                            self.last_tick_second = current_second_total
                            if settings.value("sounds_tick_enabled", True, type=bool):
                                self.play_voice(tick_sound, "tick")

            # 4. МОМЕНТ ЗАКРЫТИЯ (00 сек) - Только текст, без звука (звук был в 50 сек)
            if sec == 0:
                # Проверяем "текущий" момент (он уже наступил)
                active_tf, msg = self.get_closing_tf(now_utc)
                if active_tf:
                    self.time_signal.emit(msg)

        # --- ЛОГИКА ВИДИМОСТИ (Оптимизированная) ---
        if self.ui.cb_overlay.isChecked():
            # Определяем должно ли окно быть видимым
            if config.OVERLAY_SHOW_MODE == "always":
                # "Всегда показывать" - показываем во всех окнах
                is_visible_context = True
            else:
                # "Только на определённых окнах" - проверяем список
                active_window = self.get_active_window_title_fast()
                is_visible_context = any(
                    app.lower() in active_window.lower()
                    for app in config.OVERLAY_WINDOWS
                )

            # Дополнительные контексты (выбор цвета, перетаскивание)
            if self.is_selecting_color or self.overlay._dragging:
                is_visible_context = True

            if is_visible_context and not self.overlay.isVisible():
                self.overlay.show()
            elif not is_visible_context and self.overlay.isVisible():
                self.overlay.hide()
        else:
            if self.overlay.isVisible():
                self.overlay.hide()

    def get_closing_tf(self, dt):
        """
        Возвращает самый старший активный таймфрейм, который закрывается в момент dt (обычно :00 секунд).
        dt - это объект datetime (UTC).
        Возвращает кортеж (ключ_тф, сообщение) или (None, None).
        """
        # Сначала проверяем, что секунды == 0 (или близко к 0, т.к. dt мы считаем математически)
        # Но так как мы передаем dt выравненный на минуту, проверим условия кратности.

        # Проверяем включен ли чекбокс перед возвратом
        def is_active(key):
            return self.ui.checkboxes.get(key) and self.ui.checkboxes[key].isChecked()

        # 1. Месяц
        if dt.day == 1 and dt.hour == 0 and dt.minute == 0 and is_active("1M"):
            return "1M", "Месячная свеча закрыта!"

        # 2. Неделя
        if dt.weekday() == 0 and dt.hour == 0 and dt.minute == 0 and is_active("1w"):
            return "1w", "НЕДЕЛЬНАЯ свеча закрыта!"

        # 3. День
        if dt.hour == 0 and dt.minute == 0 and is_active("1d"):
            return "1d", "Дневная свеча закрыта!"

        # 4. 4 Часа
        if dt.hour % 4 == 0 and dt.minute == 0 and is_active("4h"):
            return "4h", "Свеча H4 закрыта!"

        # 5. 1 Час
        if dt.minute == 0 and is_active("1h"):
            return "1h", "Часовая свеча закрыта!"

        # 6. 30 Минут
        if dt.minute % 30 == 0 and is_active("30m"):
            return "30m", "Свеча 30м закрыта!"

        # 7. 15 Минут
        if dt.minute % 15 == 0 and is_active("15m"):
            return "15m", "Свеча 15м закрыта!"

        # 8. 5 Минут
        if dt.minute % 5 == 0 and is_active("5m"):
            return "5m", "Свеча 5м закрыта!"

        # 9. 1 Минута
        if is_active("1m"):
            # 1 минута закрывается каждую минуту
            return "1m", "Минутная свеча закрыта!"

        return None, None

    def play_voice(self, filename, kind="main"):
        vol_value = self.ui.volume_slider.value()
        if vol_value <= 0:
            return

        # Пытаемся получить путь из кеша для мгновенного доступа
        cache_key = f"{kind}_{filename}"
        if cache_key in self.sound_cache:
            path = self.sound_cache[cache_key]
        else:
            # Fallback: получаем путь обычным способом
            path = config.get_sound_path(kind, filename)
            if not path or not os.path.exists(path):
                print(f"- [{kind.upper()}] Sound not found: {filename}")
                return

        volume = self._safe_audio_volume(vol_value)
        player, output = self._get_player_output(kind)
        self._start_player_clean(player, output, path, volume)

    def test_timeframe_alert(self, tf_key):
        """Debug-метод для тестирования звука любого таймфрейма"""
        if tf_key in config.TIMEFRAMES:
            filename = config.TIMEFRAMES[tf_key]["file"]
            label = config.TIMEFRAMES[tf_key]["label"]
            print(f"[TEST] Playing sound for {label}: {filename}")
            self.play_voice(filename, "main")
            self.time_signal.emit(f"[ТЕСТ] {label} закрыт!")
        else:
            print(f"! Timeframe '{tf_key}' not found in config.TIMEFRAMES")

    def _format_timeframe_for_tts(self, tf_key, language="ru"):
        """Форматирует название таймфрейма для естественной TTS озвучки"""
        # Словари для озвучки таймфреймов
        ru_names = {
            "1m": "одна минута",
            "5m": "пять минут",
            "15m": "пятнадцать минут",
            "30m": "тридцать минут",
            "1h": "один час",
            "4h": "четыре часа",
            "1d": "один день",
            "1w": "одна неделя",
            "1M": "один месяц",
        }
        en_names = {
            "1m": "one minute",
            "5m": "five minutes",
            "15m": "fifteen minutes",
            "30m": "thirty minutes",
            "1h": "one hour",
            "4h": "four hours",
            "1d": "one day",
            "1w": "one week",
            "1M": "one month",
        }

        if language == "ru":
            return ru_names.get(tf_key, tf_key)
        return en_names.get(tf_key, tf_key)

    def play_tts_for_timeframe(self, tf_key):
        """Воспроизводит TTS озвучку для таймфрейма"""
        import threading

        settings = QSettings("MyTradeTools", "TF-Alerter")
        engine_type = settings.value("tf_tts_engine", "system")
        language = settings.value("tf_tts_language", "ru")
        voice_id = settings.value("tf_tts_voice_id", "")

        message = self._format_timeframe_for_tts(tf_key, language)
        print(f"[TTS] Engine: {engine_type}, Language: {language}, Voice: {voice_id}")
        print(f"[TTS] Message: {message}")

        if engine_type == "edge":
            # Edge TTS в отдельном потоке
            thread = threading.Thread(
                target=self._speak_tf_edge_tts,
                args=(message, voice_id, language),
                daemon=True,
            )
            thread.start()
        else:
            # System TTS в отдельном потоке
            thread = threading.Thread(
                target=self._speak_tf_system_tts, args=(message, voice_id), daemon=True
            )
            thread.start()

    def _speak_tf_system_tts(self, text, voice_id):
        """Воспроизводит TTS через pyttsx3"""
        try:
            print(f"[System TTS] Starting: {text}, voice={voice_id}")
            import pyttsx3

            engine = pyttsx3.init()
            if voice_id:
                engine.setProperty("voice", voice_id)
                print(f"[System TTS] Voice set to: {voice_id}")

            # Используем громкость из основного слайдера
            vol_value = self.ui.volume_slider.value()
            volume = self._safe_audio_volume(vol_value)
            engine.setProperty("volume", volume)
            print(f"[System TTS] Volume: {volume}")

            engine.say(text)
            engine.runAndWait()
            engine.stop()
            print(f"[System TTS] Finished successfully")
        except Exception as e:
            print(f"⚠️ System TTS error for timeframe: {e}")

    def _speak_tf_edge_tts(self, text, voice_id, language):
        """Воспроизводит TTS через Edge TTS"""
        try:
            print(f"[Edge TTS] Starting: {text}, voice={voice_id}, lang={language}")
            import asyncio
            import tempfile
            import edge_tts

            # Fallback на default голоса если voice_id пустой
            if not voice_id:
                voice_id = (
                    "ru-RU-DmitryNeural" if language == "ru" else "en-US-GuyNeural"
                )
                print(f"[Edge TTS] Using fallback voice: {voice_id}")

            async def generate_audio():
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False
                ) as tmp_file:
                    tmp_path = tmp_file.name
                communicate = edge_tts.Communicate(text, voice_id)
                await communicate.save(tmp_path)
                return tmp_path

            # Генерируем аудио
            tmp_path = asyncio.run(generate_audio())
            print(f"[Edge TTS] Audio generated: {tmp_path}")

            # Проигрываем через voice_player (используем сигнал для thread-safety)
            if os.path.exists(tmp_path):
                vol_value = self.ui.volume_slider.value()
                volume = self._safe_audio_volume(vol_value)
                # Испускаем сигнал для воспроизведения в UI потоке
                self.play_tts_audio_signal.emit(tmp_path, volume)
                print(f"[Edge TTS] Emitted playback signal for: {tmp_path}")
            else:
                print(f"[Edge TTS] ERROR: File not found: {tmp_path}")
        except Exception as e:
            print(f"⚠️ Edge TTS error for timeframe: {e}")
            import traceback

            traceback.print_exc()

    def _play_tts_audio_slot(self, file_path, volume):
        """Слот для воспроизведения TTS аудио в UI потоке"""
        try:
            print(
                f"[Edge TTS] Playing audio in UI thread: {file_path}, volume={volume}"
            )
            if os.path.exists(file_path):
                self._start_player_clean(
                    self.voice_player,
                    self.voice_output,
                    file_path,
                    config.clamp_audio_volume(volume),
                )
                print(f"[Edge TTS] Playback started successfully")
            else:
                print(f"[Edge TTS] ERROR: File not found in slot: {file_path}")
        except Exception as e:
            print(f"[Edge TTS] Playback error in slot: {e}")
            import traceback

            traceback.print_exc()

    def start(self):
        self.timer.start(250)  # 4 раза в секунду для стабильного захвата 55-58 сек
