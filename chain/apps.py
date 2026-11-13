from django.apps import AppConfig


class ChainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "chain"

    def ready(self):
        try:
            from chain.container import ChainContainer
            container = ChainContainer()
            container.wire(modules=["chain.views"])
        except Exception:
            pass
