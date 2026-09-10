import unittest

import httpx

from app.main import app


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_geocode_and_university_layer(self):
        geocode = await self.client.get("/api/geo/geocode", params={"q": "Sinza"})
        self.assertEqual(geocode.status_code, 200)
        self.assertEqual(geocode.json()["name"], "Sinza")
        self.assertEqual(geocode.json()["precision"], "approximate_place_centroid")

        universities = await self.client.get("/geo/universities")
        self.assertEqual(universities.status_code, 200)
        self.assertTrue(any(item["key"] == "aru" for item in universities.json()["universities"]))

    async def test_chat_preserves_legacy_reply_shape(self):
        response = await self.client.post("/chat", json={"message": "Sinza"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["reply"])
        self.assertEqual(payload["reply"], payload["response"])
        self.assertEqual(payload["intent"], "location_search")
        self.assertIn("map", payload)

    async def test_new_ai_contract_and_conversation_memory(self):
        first = await self.client.post(
            "/api/ai/chat",
            json={"message": "Ninasoma Ardhi University.", "conversation_id": "api-memory"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["intent"], "follow_up")

        second = await self.client.post(
            "/api/ai/chat",
            json={"message": "Single room.", "conversation_id": "api-memory"},
        )
        self.assertEqual(second.status_code, 200)
        self.assertIn("budget", second.json()["message"].lower())

        third = await self.client.post(
            "/api/ai/chat",
            json={"message": "150k", "conversation_id": "api-memory"},
        )
        self.assertEqual(third.status_code, 200)
        self.assertTrue(any(word in third.json()["message"].lower() for word in ("minutes", "dakika")))
        self.assertEqual(third.json()["preferences"]["university_key"], "aru")

    async def test_available_filter_does_not_promote_unknown_rows(self):
        response = await self.client.get("/api/accommodations", params={"available_only": "true"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])
        self.assertTrue(any("unknown" in warning.lower() for warning in payload["warnings"]))

    async def test_university_detail_contract(self):
        response = await self.client.get("/api/universities/aru")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["official_name"], "Ardhi University")


if __name__ == "__main__":
    unittest.main()
