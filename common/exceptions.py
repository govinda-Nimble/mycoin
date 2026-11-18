import logging
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common.models import ImmutableRecordError
from common.utils import format_database_constraint_error

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django REST Framework.
    Intercepts unhandled database IntegrityError, Django ValidationError,
    and ImmutableRecordError, returning clean, standardized HTTP 400 responses
    to prevent raw database constraint errors or tracebacks from leaking to the frontend.
    """
    # 1. Let DRF handle standard APIExceptions first
    response = exception_handler(exc, context)

    if response is not None:
        return response

    # 2. Intercept database constraint violations and Django validation errors
    if isinstance(exc, (IntegrityError, DjangoValidationError, ImmutableRecordError)):
        friendly_message = format_database_constraint_error(exc)
        view_obj = context.get("view") if isinstance(context, dict) else None
        view_name = getattr(view_obj, "__name__", None) or getattr(getattr(view_obj, "__class__", None), "__name__", str(view_obj))
        logger.warning(
            "Intercepted database/model constraint violation in view %s: %s (Raw: %s)",
            view_name,
            friendly_message,
            str(exc),
        )
        return Response(
            {
                "success": False,
                "reason": friendly_message,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 3. Return None for other unhandled exceptions so Django's standard 500 handler works
    return None
