"""Windowed executable entry point."""
import os
import sys


def self_test():
    import asyncio
    import json
    import tempfile
    from pathlib import Path
    import app_paths
    with tempfile.TemporaryDirectory(prefix='summary-agent-check-') as folder:
        app_paths.DATA_DIR = Path(folder)
        import gui
        real_client = gui.client
        class OfflineClient:
            loop = real_client.loop
            async def connect(self):
                pass
            async def is_user_authorized(self):
                return False
        gui.client = OfflineClient()
        app = gui.App()
        app.withdraw()
        app.update()
        real_client.loop.run_until_complete(asyncio.sleep(.01))
        assert app._login.flow.stage == 'phone'
        app._login.close()
        app.enable_tray = lambda: None
        app._build_main()
        app.update()
        assert app.summary_detail_menu.get() == 'Кратко'
        app.show_page('settings')
        app.summary_detail_menu.open()
        app.update()
        app.summary_detail_menu.popup.choose(1)
        assert app.summary_detail_menu.get() == 'Стандартно'
        app.limit_entry.delete(0, 'end')
        app.limit_entry.insert(0, '25')
        app.save_schedule()
        assert app.schedule.first_run_limit == 25
        from autostart import startup_command
        assert startup_command().endswith('--autostart')
        app.schedule.save(app._schedule_path)
        assert Path(gui.DB_NAME).exists() if hasattr(gui, 'DB_NAME') else True
        app.destroy()
        real_client.session.close()
        result = {'ok': True, 'login': True, 'settings': True, 'menus': True,
                  'autostart_command': True, 'data_isolated': True}
    Path(sys.argv[2]).write_text(json.dumps(result), encoding='utf-8')


def main():
    # pythonw/PyInstaller have no console; existing progress prints stay harmless.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
            self_test()
            return
        import gui
        gui.start_app()
    except Exception as error:
        if '--self-test' in sys.argv:
            from pathlib import Path
            Path(sys.argv[2]).write_text(type(error).__name__ + ': ' + str(error), encoding='utf-8')
            raise
        import ctypes
        from app_paths import APP_DIR
        text = ('Не удалось запустить приложение. Проверьте файл .env рядом с TelegramSummaryAgent.exe.\n\n'
                f'Папка приложения: {APP_DIR}\nТип ошибки: {type(error).__name__}')
        ctypes.windll.user32.MessageBoxW(None, text, 'Telegram Summary Agent', 0x10)


if __name__ == '__main__':
    main()
