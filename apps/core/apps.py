import sys
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "JanSetu Core"

    def ready(self):
        if "runserver" in sys.argv:
            try:
                from apps.authentication.models import User
                if User.objects.count() == 0:
                    from django.core.management import call_command
                    call_command("seed_data", verbosity=0)
            except Exception:
                pass

