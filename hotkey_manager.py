import ctypes
import threading
import os
from ctypes import wintypes
from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyManager(QObject):
    """Менеджер глобальных горячих клавиш для Windows"""

    hotkey_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_hotkey = None
        self._target_vks = None
        self._pressed_vks = set()
        self._fired = False
        self.is_running = False

        self._hook_handle = None
        self._hook_proc = None
        self._thread = None
        self._thread_id = None

        # Карта нормализации модификаторов (левый/правый -> общий)
        self._vk_normalize_map = {
            0xA0: 0x10,  # VK_LSHIFT -> VK_SHIFT
            0xA1: 0x10,  # VK_RSHIFT -> VK_SHIFT
            0xA2: 0x11,  # VK_LCONTROL -> VK_CONTROL
            0xA3: 0x11,  # VK_RCONTROL -> VK_CONTROL
            0xA4: 0x12,  # VK_LMENU -> VK_MENU (Alt)
            0xA5: 0x12,  # VK_RMENU -> VK_MENU (Alt)
        }

        # use_last_error=True чтобы можно было корректно читать GetLastError
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._WH_KEYBOARD_LL = 13
        self._HC_ACTION = 0
        self._WM_KEYDOWN = 0x0100
        self._WM_KEYUP = 0x0101
        self._WM_SYSKEYDOWN = 0x0104
        self._WM_SYSKEYUP = 0x0105
        self._WM_QUIT = 0x0012

        ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)
        LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
        INT = getattr(wintypes, "INT", ctypes.c_int)
        WPARAM = getattr(wintypes, "WPARAM", ctypes.c_size_t)
        LPARAM = getattr(wintypes, "LPARAM", ctypes.c_ssize_t)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        self._KBDLLHOOKSTRUCT = KBDLLHOOKSTRUCT
        self._LowLevelKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, INT, WPARAM, LPARAM)

        # Диагностика и синхронизация старта hook thread
        self._debug = os.environ.get("TF_DEBUG_HOOK", "0") == "1"
        self._ready_event = threading.Event()
        self._install_ok = False
        self._install_error = 0

        # Прототипы WinAPI (важно: иначе SetWindowsHookEx может тихо не работать)
        HHOOK = wintypes.HANDLE
        HINSTANCE = wintypes.HANDLE

        self._user32.SetWindowsHookExW.argtypes = [
            wintypes.INT,
            self._LowLevelKeyboardProc,
            HINSTANCE,
            wintypes.DWORD,
        ]
        self._user32.SetWindowsHookExW.restype = HHOOK

        self._user32.UnhookWindowsHookEx.argtypes = [HHOOK]
        self._user32.UnhookWindowsHookEx.restype = wintypes.BOOL

        self._user32.CallNextHookEx.argtypes = [HHOOK, wintypes.INT, WPARAM, LPARAM]
        self._user32.CallNextHookEx.restype = LRESULT

        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.GetMessageW.restype = wintypes.BOOL

        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.TranslateMessage.restype = wintypes.BOOL

        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.DispatchMessageW.restype = LRESULT

        self._user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            WPARAM,
            LPARAM,
        ]
        self._user32.PostThreadMessageW.restype = wintypes.BOOL

        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = HINSTANCE

        self._kernel32.GetCurrentThreadId.argtypes = []
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def _clear_hotkey(self):
        self._target_vks = None
        self._pressed_vks.clear()
        self._fired = False

    def _emit_hotkey(self):
        # Signal-safe из другого потока: PyQt сам сделает queued connection
        self.hotkey_pressed.emit()

    def _hook_callback(self, nCode, wParam, lParam):
        try:
            if nCode == self._HC_ACTION and self._target_vks is not None:
                kb = ctypes.cast(lParam, ctypes.POINTER(self._KBDLLHOOKSTRUCT)).contents
                vk = int(kb.vkCode)

                is_down = wParam in (self._WM_KEYDOWN, self._WM_SYSKEYDOWN)
                is_up = wParam in (self._WM_KEYUP, self._WM_SYSKEYUP)

                if is_down:
                    self._pressed_vks.add(vk)
                    # Добавляем также нормализованный код модификатора
                    if vk in self._vk_normalize_map:
                        self._pressed_vks.add(self._vk_normalize_map[vk])
                elif is_up:
                    self._pressed_vks.discard(vk)
                    # Удаляем также нормализованный код
                    if vk in self._vk_normalize_map:
                        self._pressed_vks.discard(self._vk_normalize_map[vk])

                # Проверяем если все нужные клавиши нажаты
                if self._target_vks and self._target_vks.issubset(self._pressed_vks):
                    if not self._fired:
                        self._fired = True
                        self._emit_hotkey()
                else:
                    self._fired = False
        except Exception:
            # Никогда не падаем из hook callback
            pass

        try:
            return self._user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)
        except Exception:
            return 0

    def _install_hook(self):
        if self._hook_proc is None:
            self._hook_proc = self._LowLevelKeyboardProc(self._hook_callback)

        ctypes.set_last_error(0)
        h_instance = self._kernel32.GetModuleHandleW(None)
        self._hook_handle = self._user32.SetWindowsHookExW(
            self._WH_KEYBOARD_LL, self._hook_proc, h_instance, 0
        )
        if not self._hook_handle:
            self._install_error = ctypes.get_last_error()
            return False
        return True

    def _uninstall_hook(self):
        if self._hook_handle:
            try:
                self._user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                pass
        self._hook_handle = None

    def _message_loop(self):
        self._thread_id = int(self._kernel32.GetCurrentThreadId())

        self._install_ok = self._install_hook()
        self._ready_event.set()

        if self._debug:
            print(
                f"[HotkeyManager] install_ok={self._install_ok} last_error={self._install_error}"
            )

        if not self._install_ok:
            # Если hook не поставился, просто выходим
            return

        msg = wintypes.MSG()
        while True:
            res = self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res == 0 or res == -1:
                break
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

        self._uninstall_hook()

    def register_hotkey_codes(self, scan_codes, hotkey_str=""):
        """Регистрирует горячую клавишу по VK-кодам (работает без admin)."""
        self._clear_hotkey()
        if not scan_codes:
            self.current_hotkey = None
            return False
        self.current_hotkey = hotkey_str

        # Нормализуем VK коды: конвертируем специфичные модификаторы (Left/Right) в общие
        normalized_vks = set()
        for code in scan_codes:
            vk = int(code)
            # Если это специфичный модификатор (Left/Right), заменяем на общий
            if vk in self._vk_normalize_map:
                normalized_vks.add(self._vk_normalize_map[vk])
            else:
                # Обычная клавиша или уже общий модификатор
                normalized_vks.add(vk)

        self._target_vks = normalized_vks
        # Гарантируем что thread/hook запущены
        if not self.is_running:
            self.start()
        return True

    def register_hotkey(self, hotkey_str):
        """Stub: регистрация по строке больше не поддерживается. Всегда False."""
        self._clear_hotkey()
        self.current_hotkey = None
        return False

    def _on_hotkey_pressed(self):
        """Вызывается при нажатии горячей клавиши"""
        self.hotkey_pressed.emit()

    def update_hotkey(self, hotkey_str):
        """Обновляет горячую клавишу"""
        self.register_hotkey(hotkey_str)

    def start(self):
        """Запускает менеджер (ничего не делает, keyboard работает в фоне)"""
        if self.is_running:
            return

        self.is_running = True
        if self._thread is None or not self._thread.is_alive():
            self._ready_event.clear()
            self._install_ok = False
            self._install_error = 0
            self._thread = threading.Thread(target=self._message_loop, daemon=True)
            self._thread.start()
            self._ready_event.wait(timeout=1.0)

    def stop(self):
        """Останавливает менеджер горячих клавиш"""
        self.is_running = False
        self._clear_hotkey()

        if self._thread_id:
            try:
                self._user32.PostThreadMessageW(self._thread_id, self._WM_QUIT, 0, 0)
            except Exception:
                pass

        if self._thread is not None:
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
        self._thread = None
        self._thread_id = None

    def wait(self, timeout):
        """Заглушка для совместимости с QThread"""
        pass
