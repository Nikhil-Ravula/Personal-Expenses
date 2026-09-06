import os
import sys
from django.apps import AppConfig


class TrackerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracker'

    def ready(self):
        # Auto-start Telegram Bot only when runserver is running
        is_runserver = 'runserver' in sys.argv
        # Django's autoreloader runs the process twice.
        # RUN_MAIN == 'true' indicates the child/worker process actually running the web server.
        # If --noreload was specified, RUN_MAIN might not be set.
        is_reloader_worker = os.environ.get('RUN_MAIN') == 'true'
        is_noreload = '--noreload' in sys.argv

        if is_runserver and (is_reloader_worker or is_noreload):
            from tracker.bot.runner import start_bot_background
            start_bot_background()
