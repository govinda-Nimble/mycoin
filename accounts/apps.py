from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        try:
            from mycoin.containers import container
            container.wire(modules=["accounts.views"])
        except ImportError:
            pass
