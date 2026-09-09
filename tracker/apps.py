import os
import sys
from django.apps import AppConfig
from django.conf import settings


class TrackerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracker'

    def ready(self):
        # Exclude management commands where bot should never auto-start
        excluded_commands = {
            'migrate', 'makemigrations', 'collectstatic', 'test',
            'run_bot', 'showmigrations', 'dumpdata', 'loaddata', 'shell',
            'createsuperuser', 'check'
        }
        args_set = set(sys.argv)
        if args_set.intersection(excluded_commands):
            return

        is_runserver = 'runserver' in sys.argv
        is_reloader_worker = os.environ.get('RUN_MAIN') == 'true'
        is_noreload = '--noreload' in sys.argv

        # Allow auto-start if running with runserver OR if AUTO_START_BOT is True (e.g. in WSGI/PythonAnywhere)
        auto_start_bot = getattr(settings, 'AUTO_START_BOT', False) or (
            os.environ.get('AUTO_START_BOT', '').strip().lower() in ('true', '1', 'yes')
        )

        if (is_runserver and (is_reloader_worker or is_noreload)) or auto_start_bot:
            from tracker.bot.runner import start_bot_background
            start_bot_background()
