import unittest
from datetime import datetime, timezone

from token_store import _utc_expiry


class TokenStoreTests(unittest.TestCase):
    def test_naive_google_expiry_is_normalized_to_utc(self):
        value = datetime(2026, 8, 23, 12, 0, 0)
        normalized = _utc_expiry(value, datetime.now(timezone.utc))
        self.assertEqual(normalized.tzinfo, timezone.utc)
        self.assertEqual(normalized.hour, 12)


if __name__ == "__main__":
    unittest.main()
