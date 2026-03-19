"""Unit tests for market_client — HTTP calls mocked with respx."""
import pytest
import respx
import httpx

from app.services import market_client
from app.services.market_client import MarketClientError


BASE = "https://api.partner.market.yandex.ru"
CAMPAIGN = "12345"


class TestGetOrder:
    @respx.mock
    def test_returns_order_dict(self):
        order_data = {"id": 42, "status": "PROCESSING", "items": []}
        respx.get(f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/42").mock(
            return_value=httpx.Response(200, json={"order": order_data})
        )

        result = market_client.get_order("42")
        assert result["id"] == 42
        assert result["status"] == "PROCESSING"

    @respx.mock
    def test_raises_on_403(self):
        respx.get(f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/42").mock(
            return_value=httpx.Response(403, json={"message": "OAuth token is invalid"})
        )

        with pytest.raises(MarketClientError) as exc_info:
            market_client.get_order("42")
        assert exc_info.value.status_code == 403

    @respx.mock
    def test_uses_api_key_header(self):
        """Verify Api-Key header is sent, not Authorization: Bearer."""
        route = respx.get(f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/99").mock(
            return_value=httpx.Response(200, json={"order": {"id": 99}})
        )
        market_client.get_order("99")

        request = route.calls.last.request
        assert "Api-Key" in request.headers
        assert request.headers["Api-Key"] == "ACMA:test_token"
        assert "Authorization" not in request.headers

    @respx.mock
    def test_raises_on_500(self):
        respx.get(f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/1").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(MarketClientError):
            market_client.get_order("1")


class TestSendDigitalGoods:
    @respx.mock
    def test_sends_correct_payload_single_item(self):
        route = respx.post(
            f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/100/deliverDigitalGoods"
        ).mock(return_value=httpx.Response(200, json={"status": "OK"}))

        result = market_client.send_digital_goods("100", [
            {"id": 501, "count": 1, "payloads": ["KEY-ABCD-1234"]}
        ])

        assert result == {"status": "OK"}
        sent_body = route.calls.last.request.content
        import json
        body = json.loads(sent_body)
        assert body["items"][0]["id"] == 501
        assert body["items"][0]["codes"] == ["KEY-ABCD-1234"]

    @respx.mock
    def test_sends_multiple_codes_for_count_2(self):
        """Critical: codes length must match item.count."""
        route = respx.post(
            f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/200/deliverDigitalGoods"
        ).mock(return_value=httpx.Response(200, json={}))

        market_client.send_digital_goods("200", [
            {"id": 601, "count": 2, "payloads": ["CODE-A", "CODE-B"]}
        ])

        import json
        body = json.loads(route.calls.last.request.content)
        codes = body["items"][0]["codes"]
        assert len(codes) == 2
        assert "CODE-A" in codes
        assert "CODE-B" in codes

    def test_raises_on_payload_count_mismatch(self):
        """Mismatched payloads vs count should raise before hitting API."""
        with pytest.raises(ValueError, match="expected 2 payloads, got 1"):
            market_client.send_digital_goods("300", [
                {"id": 701, "count": 2, "payloads": ["ONLY-ONE"]}
            ])

    @respx.mock
    def test_long_payload_goes_to_slip(self):
        """Payloads longer than threshold → placeholder in codes, full in slip."""
        long_payload = "login: user@example.com\n" + "password: " + "x" * 60
        route = respx.post(
            f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/400/deliverDigitalGoods"
        ).mock(return_value=httpx.Response(200, json={}))

        market_client.send_digital_goods("400", [
            {"id": 801, "count": 1, "payloads": [long_payload]}
        ])

        import json
        body = json.loads(route.calls.last.request.content)
        item = body["items"][0]
        assert len(item["codes"]) == 1
        assert len(item["codes"][0]) <= 64  # Short token, not the full payload
        assert "slip" in item
        assert long_payload in item["slip"]

    @respx.mock
    def test_raises_on_bad_request(self):
        respx.post(
            f"{BASE}/v2/campaigns/{CAMPAIGN}/orders/500/deliverDigitalGoods"
        ).mock(return_value=httpx.Response(
            400, json={"message": "Required=2 digital items, found=1"}
        ))

        with pytest.raises(MarketClientError) as exc_info:
            market_client.send_digital_goods("500", [
                {"id": 901, "count": 1, "payloads": ["CODE"]}
            ])
        assert exc_info.value.status_code == 400
