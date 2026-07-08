import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import yaml


class TestDistrictConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(PROJECT_ROOT, "config", "districts.yaml")
        with open(path, encoding="utf-8") as f:
            cls.config = yaml.safe_load(f)
        cls.districts = {d["district_id"]: d for d in cls.config["districts"]}

    def test_all_districts_have_required_fields(self):
        required = {"district_id", "name", "city", "center_lng", "center_lat", "radius_m"}
        for did, d in self.districts.items():
            with self.subTest(district=d["name"]):
                missing = required - set(d.keys())
                self.assertEqual(
                    missing, set(),
                    f"{did} is missing: {missing}",
                )

    def test_verified_districts_have_address_and_source(self):
        for did, d in self.districts.items():
            if d.get("coordinate_verified") is True:
                with self.subTest(district=d["name"]):
                    self.assertIn("address", d, f"{did} verified but missing address")
                    self.assertIn("coordinate_source", d, f"{did} verified but missing coordinate_source")

    def test_districts_with_previous_coords_preserve_them(self):
        for did, d in self.districts.items():
            if "previous_center_lng" in d or "previous_center_lat" in d:
                with self.subTest(district=d["name"]):
                    self.assertIn("previous_center_lng", d)
                    self.assertIn("previous_center_lat", d)

    def test_yangpu_binjiang_has_all_location_fields(self):
        d = self.districts.get("yangpu_binjiang")
        self.assertIsNotNone(d, "yangpu_binjiang not found in config")
        fields = ["address", "coordinate_source", "coordinate_verified",
                   "previous_center_lng", "previous_center_lat"]
        for f in fields:
            with self.subTest(field=f):
                self.assertIn(f, d, f"yangpu_binjiang missing {f}")

    def test_yangpu_binjiang_coord_changed(self):
        d = self.districts.get("yangpu_binjiang")
        self.assertIsNotNone(d)
        self.assertNotEqual(
            d["center_lng"], d["previous_center_lng"],
            "center_lng should differ from previous_center_lng",
        )
        self.assertNotEqual(
            d["center_lat"], d["previous_center_lat"],
            "center_lat should differ from previous_center_lat",
        )
        self.assertEqual(d["previous_center_lng"], 121.514)
        self.assertEqual(d["previous_center_lat"], 31.270)

    def test_yangpu_binjiang_new_coords_not_equal_old(self):
        d = self.districts.get("yangpu_binjiang")
        self.assertIsNotNone(d)
        self.assertNotEqual(d["center_lng"], 121.514)
        self.assertNotEqual(d["center_lat"], 31.270)

    def test_zhihui_fang_has_correct_verified_fields(self):
        d = self.districts.get("zhihui_fang")
        self.assertIsNotNone(d)
        self.assertTrue(d.get("coordinate_verified"))
        self.assertEqual(d.get("coordinate_source"), "amap_geocode")
        self.assertIn("address", d)
        self.assertIn("previous_center_lng", d)
        self.assertIn("previous_center_lat", d)


if __name__ == "__main__":
    unittest.main()
