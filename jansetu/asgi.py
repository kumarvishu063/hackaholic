"""ASGI config for JanSetu."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jansetu.settings")

application = get_asgi_application()
