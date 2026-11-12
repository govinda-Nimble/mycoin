from django.apps import AppConfig


class NetworkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "network"

    def ready(self):
        try:
            from network.container import NetworkContainer
            container = NetworkContainer()
            container.wire(modules=["network.views"])
        except Exception:
            pass
