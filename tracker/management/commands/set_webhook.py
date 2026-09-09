import json
import urllib.request
import urllib.parse
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Sets, checks, or removes Telegram Bot Webhook for 24/7 automated hosting on PythonAnywhere'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            type=str,
            help='Your domain or PythonAnywhere base URL (e.g. https://nikhilravula.pythonanywhere.com)',
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Delete the current webhook and switch back to long-polling mode',
        )
        parser.add_argument(
            '--info',
            action='store_true',
            help='Check current webhook status from Telegram API',
        )
        parser.add_argument(
            '--no-proxy',
            action='store_true',
            help='Bypass proxy when contacting Telegram API',
        )

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '').strip()

        if not token or token == 'your_api' or 'your_token' in token.lower():
            self.stdout.write(self.style.ERROR("[!] Error: Telegram Bot Token not configured in .env."))
            return

        no_proxy = options.get('no_proxy', False)
        proxy_url = getattr(settings, 'TELEGRAM_PROXY_URL', '')
        if not proxy_url and not no_proxy:
            import os
            if 'PYTHONANYWHERE_DOMAIN' in os.environ or os.path.exists('/etc/pythonanywhere'):
                proxy_url = 'http://proxy.server:3128'

        opener = urllib.request.build_opener()
        if proxy_url and str(proxy_url).lower() not in ('none', 'direct', 'false', '0'):
            self.stdout.write(f"[*] Using proxy: {proxy_url}")
            proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
            opener = urllib.request.build_opener(proxy_handler)

        def api_call(endpoint, params=None):
            url = f"https://api.telegram.org/bot{token}/{endpoint}"
            if params:
                url += "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={'User-Agent': 'SmartExpenseTracker/1.0'})
            with opener.open(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))

        # 1. Delete Webhook
        if options.get('delete'):
            try:
                res = api_call('deleteWebhook')
                if res.get('ok'):
                    self.stdout.write(self.style.SUCCESS("[+] Webhook successfully removed! You can now use polling mode."))
                else:
                    self.stdout.write(self.style.ERROR(f"[!] Telegram response: {res}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[!] Failed to delete webhook: {e}"))
            return

        # 2. Check Webhook Info
        if options.get('info'):
            try:
                res = api_call('getWebhookInfo')
                self.stdout.write(self.style.SUCCESS(f"[+] Webhook Info:\n{json.dumps(res, indent=2)}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[!] Failed to fetch webhook info: {e}"))
            return

        # 3. Set Webhook
        raw_url = options.get('url')
        if not raw_url:
            self.stdout.write(self.style.WARNING(
                "\nUsage:\n"
                "  python manage.py set_webhook --url https://<your-domain>.pythonanywhere.com\n"
                "  python manage.py set_webhook --info\n"
                "  python manage.py set_webhook --delete\n"
            ))
            return

        clean_url = raw_url.strip().rstrip('/')
        if not clean_url.startswith('https://'):
            self.stdout.write(self.style.ERROR("[!] Error: Telegram Webhook URL must use HTTPS (e.g. https://nikhilravula.pythonanywhere.com)"))
            return

        webhook_endpoint = f"{clean_url}/telegram/webhook/"

        try:
            self.stdout.write(f"[*] Setting webhook to: {webhook_endpoint} ...")
            res = api_call('setWebhook', {'url': webhook_endpoint, 'drop_pending_updates': 'false'})
            if res.get('ok'):
                self.stdout.write(self.style.SUCCESS(
                    "\n" + "=" * 65 + "\n"
                    "  TELEGRAM WEBHOOK ACTIVATED SUCCESSFULLY!\n"
                    "=" * 65 + "\n"
                    f"[+] Webhook URL: {webhook_endpoint}\n"
                    "[+] Your bot is now running automatically 24/7 on PythonAnywhere!\n"
                    "    - No terminal commands needed.\n"
                    "    - No background processes needed.\n"
                    "    - Whenever a user messages the bot, Telegram sends updates directly to Django.\n"
                    "=" * 65 + "\n"
                ))
            else:
                self.stdout.write(self.style.ERROR(f"[!] Telegram rejected webhook: {res}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[!] Error setting webhook: {e}"))
