import unittest
from types import SimpleNamespace

import main


class TestTTSFallback(unittest.TestCase):
    def test_funding_edge_tts_falls_back_to_system_tts(self):
        window = main.MainWindow.__new__(main.MainWindow)
        window.ui = SimpleNamespace(
            funding_enable_check=SimpleNamespace(isChecked=lambda: True),
            listing_enable_check=SimpleNamespace(isChecked=lambda: True),
            session_enable_check=SimpleNamespace(isChecked=lambda: True),
        )
        window._is_funding_tts_enabled = lambda: True
        window._is_listing_tts_enabled = lambda: True
        window._is_session_tts_enabled = lambda: True
        window._edge_tts_busy = False
        window._edge_tts_started = False
        window._listing_edge_tts_busy = False
        window._listing_edge_tts_started = False
        window._session_tts_busy = False

        captured = {}

        def fake_system_tts(text, voice_id, language="ru"):
            captured["called"] = (text, voice_id, language)

        window._speak_system_tts = fake_system_tts
        window._speak_listing_system_tts = fake_system_tts
        window._speak_session_system_tts = fake_system_tts

        window._fallback_edge_tts_to_system_tts(
            "test message",
            "ru-RU-SvetlanaNeural",
            "ru",
            kind="funding",
        )

        self.assertEqual(captured["called"], ("test message", "ru-RU-SvetlanaNeural", "ru"))


if __name__ == "__main__":
    unittest.main()
