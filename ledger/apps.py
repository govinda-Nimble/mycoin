from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ledger"

    def ready(self):
        try:
            from ledger.container import LedgerContainer
            container = LedgerContainer()
            container.wire(modules=["ledger.views"])
        except Exception:
            pass
