from django.apps import AppConfig


class StakingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "staking"

    def ready(self):
        try:
            from staking.container import StakingContainer
            container = StakingContainer()
            container.wire(modules=["staking.views"])
        except Exception:
            pass
