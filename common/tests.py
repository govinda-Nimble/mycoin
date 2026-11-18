from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase
from rest_framework import exceptions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from common.exceptions import custom_exception_handler
from common.models import ImmutableRecordError
from common.utils import (
    CONSTRAINT_MESSAGES,
    format_database_constraint_error,
    get_single_error,
)


class DatabaseConstraintErrorFormattingTests(SimpleTestCase):
    """Tests for format_database_constraint_error utility."""

    def test_known_named_check_constraint(self):
        exc = IntegrityError('new row for relation "ledger_transaction" violates check constraint "chain_tx_amount_positive"')
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "Transaction amount must be greater than zero.")

    def test_known_named_unique_constraint(self):
        exc = IntegrityError('duplicate key value violates unique constraint "chain_block_unique_hash"\nDETAIL: Key (hash)=(abc) already exists.')
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "A block with this hash already exists on the blockchain.")

    def test_postgres_generic_unique_constraint_detail(self):
        exc = IntegrityError('duplicate key value violates unique constraint "custom_table_field_key"\nDETAIL: Key (custom_field)=(123) already exists.')
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "A record with this custom field already exists.")

    def test_sqlite_generic_unique_constraint(self):
        exc = IntegrityError('UNIQUE constraint failed: accounts_user.email')
        formatted = format_database_constraint_error(exc)
        self.assertIn("already exists", formatted)

    def test_not_null_constraint(self):
        exc = IntegrityError('null value in column "hash" of relation "ledger_transaction" violates not-null constraint')
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "Field 'hash' is required and cannot be empty.")

    def test_immutable_record_error(self):
        exc = ImmutableRecordError("Cannot modify block after finalization.")
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "This record is finalized and cannot be modified or deleted.")

    def test_django_validation_error_dict(self):
        exc = DjangoValidationError({"amount": ["Ensure this value is greater than or equal to 0."]})
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "Ensure this value is greater than or equal to 0.")

    def test_django_validation_error_list(self):
        exc = DjangoValidationError(["Invalid transaction state."])
        formatted = format_database_constraint_error(exc)
        self.assertEqual(formatted, "Invalid transaction state.")


class CustomExceptionHandlerTests(SimpleTestCase):
    """Tests for DRF custom_exception_handler."""

    def test_handles_integrity_error(self):
        exc = IntegrityError('new row violates check constraint "chain_tx_gas_limit_positive"')
        context = {"view": "MockView"}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "success": False,
                "reason": "Gas limit must be greater than zero.",
            },
        )

    def test_handles_django_validation_error(self):
        exc = DjangoValidationError({"sender": ["Sender account does not exist."]})
        context = {"view": "MockView"}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "success": False,
                "reason": "Sender account does not exist.",
            },
        )

    def test_handles_immutable_record_error(self):
        exc = ImmutableRecordError("Record is frozen.")
        context = {"view": "MockView"}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "success": False,
                "reason": "This record is finalized and cannot be modified or deleted.",
            },
        )

    def test_passes_through_drf_validation_error(self):
        exc = exceptions.ValidationError({"detail": "Field is required."})
        context = {"view": "MockView"}
        response = custom_exception_handler(exc, context)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_returns_none_for_standard_unexpected_exception(self):
        exc = RuntimeError("Unexpected system error")
        context = {"view": "MockView"}
        response = custom_exception_handler(exc, context)

        self.assertIsNone(response)
