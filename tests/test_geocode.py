import os
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.geocode_districts import geocode_address


class TestGeocode(unittest.TestCase):

    def test_geocode_no_api_key_returns_none(self):
        """geocode_address returns None when no API key is set."""
        key = os.environ.pop("AMAP_API_KEY", None)
        try:
            result = geocode_address("上海市杨浦区平凉路2241号")
            self.assertIsNone(result)
        finally:
            if key is not None:
                os.environ["AMAP_API_KEY"] = key

    def test_geocode_script_runs_without_error_no_key(self):
        """geocode_districts.py runs without crashing regardless of API key."""
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "src", "geocode_districts.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
