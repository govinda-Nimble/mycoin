from django.apps import AppConfig


class ChainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # unused: every model has a UUID pk
    name = "chain"
    verbose_name = "MyCoin chain"
