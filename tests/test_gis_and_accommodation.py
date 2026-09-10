import unittest

from app.services.accommodation_tools import parse_budget, parse_preferences
from app.services.gis import haversine_km


class GisAndAccommodationTests(unittest.TestCase):
    def test_haversine_distance_is_geodesic(self):
        distance = haversine_km(
            {"lat": -6.8128, "lng": 39.2297},
            {"lat": -6.7833, "lng": 39.2175},
        )
        self.assertGreater(distance, 3)
        self.assertLess(distance, 4)

    def test_budget_and_acceptance_preferences(self):
        message = (
            "Ninasoma Ardhi University, nina budget ya 150k kwa mwezi, "
            "nataka single room yenye WiFi na maji, na sitaki kutumia zaidi "
            "ya dakika 20 kufika chuoni."
        )
        preferences = parse_preferences(message)
        self.assertEqual(parse_budget(message), (None, 150000))
        self.assertEqual(preferences.university["key"], "aru")
        self.assertEqual(preferences.budget_max, 150000)
        self.assertEqual(preferences.room_type, "single room")
        self.assertEqual(preferences.amenities, ["wifi", "water"])
        self.assertEqual(preferences.max_travel_time_minutes, 20)

    def test_swapped_budget_range(self):
        self.assertEqual(parse_budget("100k mpaka 200k"), (100000, 200000))


if __name__ == "__main__":
    unittest.main()
