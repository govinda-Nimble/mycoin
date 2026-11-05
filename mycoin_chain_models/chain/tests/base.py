from django.db import IntegrityError, transaction


class DBConstraintMixin:
    """Assert that the DATABASE (not just Python) rejects a write, without breaking the test transaction."""

    def assertDBRejects(self, func, *args, **kwargs):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                func(*args, **kwargs)
