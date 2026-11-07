"""LATE_AT is read in OFFICE_TIMEZONE, not in the server's UTC clock."""
import os
import unittest
from unittest.mock import patch

from backend import attendance, database as db


class OfficeTimezoneTests(unittest.TestCase):
    def test_default_is_unchanged_without_a_timezone(self):
        with patch.dict(os.environ, {"OFFICE_TIMEZONE": ""}):
            self.assertEqual(db.office_time_str("09:00:00"), "09:00:00")

    def test_utc_clock_is_converted_to_office_time(self):
        with patch.dict(os.environ, {"OFFICE_TIMEZONE": "Asia/Kolkata"}):
            self.assertEqual(db.office_time_str("04:00:00"), "09:30:00")
            self.assertFalse(attendance._is_late(db.office_time_str("04:00:00")))
            self.assertTrue(attendance._is_late(db.office_time_str("04:01:00")))

    def test_unknown_zone_falls_back_safely(self):
        with patch.dict(os.environ, {"OFFICE_TIMEZONE": "Not/AZone"}):
            self.assertEqual(db.office_time_str("09:00:00"), "09:00:00")


if __name__ == "__main__":
    unittest.main()
