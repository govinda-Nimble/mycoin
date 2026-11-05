"""Django discovers models through ``<app>.models``; the real code lives in the infrastructure layer."""
from .infrastructure.models import *  # noqa: F401,F403
