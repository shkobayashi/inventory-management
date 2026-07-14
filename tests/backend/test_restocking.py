"""
Tests for restocking API endpoints (recommendations, order submission).
"""
import pytest


class TestRestockRecommendationsEndpoint:
    """Test suite for the restock recommendations endpoint."""

    def test_get_recommendations_returns_expected_shape(self, client):
        """Test that the recommendations response has the expected top-level keys."""
        response = client.get("/api/restocking/recommendations?budget=10000")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "budget" in data
        assert "total_allocated_cost" in data
        assert "remaining_budget" in data
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    def test_recommendation_item_structure(self, client):
        """Test that each recommendation has the expected fields."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        assert len(data["recommendations"]) > 0

        item = data["recommendations"][0]
        assert "sku" in item
        assert "name" in item
        assert "category" in item
        assert "quantity_on_hand" in item
        assert "reorder_point" in item
        assert "unit_cost" in item
        assert "demand_gap" in item
        assert "urgency_score" in item
        assert "suggested_quantity" in item
        assert "suggested_cost" in item
        assert "lead_time_days" in item
        assert "reason" in item

    def test_recommendations_respect_budget(self, client):
        """Test that the total allocated cost never exceeds the given budget."""
        budget = 5000
        response = client.get(f"/api/restocking/recommendations?budget={budget}")
        data = response.json()

        total_cost = sum(item["suggested_cost"] for item in data["recommendations"])
        assert total_cost <= budget + 0.01
        assert abs(data["total_allocated_cost"] - total_cost) < 0.01
        assert abs(data["remaining_budget"] - (budget - total_cost)) < 0.01

    def test_recommendations_only_include_flagged_items(self, client):
        """Test that every recommended item is below reorder point or above forecasted demand."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        data = response.json()

        for item in data["recommendations"]:
            below_reorder_point = item["quantity_on_hand"] < item["reorder_point"]
            forecasted_demand = item.get("forecasted_demand")
            exceeds_forecast = (
                forecasted_demand is not None and forecasted_demand > item["quantity_on_hand"]
            )
            assert below_reorder_point or exceeds_forecast, (
                f"Item {item['sku']} was recommended without a demand gap"
            )

    def test_zero_budget_returns_no_allocations(self, client):
        """Test that a zero budget results in no recommended allocations."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert data["recommendations"] == []
        assert data["total_allocated_cost"] == 0

    def test_negative_budget_rejected(self, client):
        """Test that a negative budget is rejected with a 400 error."""
        response = client.get("/api/restocking/recommendations?budget=-100")
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_lead_time_days_always_positive(self, client):
        """Test that every recommendation has a positive lead time."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        data = response.json()

        assert len(data["recommendations"]) > 0
        for item in data["recommendations"]:
            assert isinstance(item["lead_time_days"], int)
            assert item["lead_time_days"] > 0


class TestRestockOrderSubmissionEndpoint:
    """Test suite for submitting restocking orders."""

    def _get_low_stock_sku(self, client):
        """Helper: find a recommended SKU and quantity to use in order tests."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        recommendations = response.json()["recommendations"]
        assert len(recommendations) > 0
        first = recommendations[0]
        return first["sku"], first["suggested_quantity"]

    def test_create_restock_order_success(self, client):
        """Test that submitting a valid restock order succeeds."""
        sku, quantity = self._get_low_stock_sku(client)

        response = client.post(
            "/api/restocking/orders",
            json={"budget": 10000, "items": [{"sku": sku, "quantity": quantity}]},
        )
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_date"] < order["expected_delivery"]
        assert len(order["items"]) == 1
        assert order["items"][0]["sku"] == sku
        assert order["items"][0]["quantity"] == quantity

    def test_created_order_total_value_matches_items(self, client):
        """Test that total_value equals the sum of quantity * unit_price across items."""
        sku, quantity = self._get_low_stock_sku(client)

        response = client.post(
            "/api/restocking/orders",
            json={"budget": 10000, "items": [{"sku": sku, "quantity": quantity}]},
        )
        order = response.json()

        calculated_total = sum(
            item["quantity"] * item["unit_price"] for item in order["items"]
        )
        assert abs(order["total_value"] - calculated_total) < 0.01

    def test_submitted_order_appears_in_orders_list(self, client):
        """Test that a submitted restock order shows up under GET /api/orders?status=Submitted."""
        sku, quantity = self._get_low_stock_sku(client)

        create_response = client.post(
            "/api/restocking/orders",
            json={"budget": 10000, "items": [{"sku": sku, "quantity": quantity}]},
        )
        created_order = create_response.json()

        list_response = client.get("/api/orders?status=Submitted")
        assert list_response.status_code == 200

        submitted_orders = list_response.json()
        submitted_ids = [order["id"] for order in submitted_orders]
        assert created_order["id"] in submitted_ids

    def test_create_order_with_unknown_sku_returns_404(self, client):
        """Test that submitting an order with an unknown SKU returns 404."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 10000, "items": [{"sku": "NOT-A-REAL-SKU", "quantity": 5}]},
        )
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data

    def test_create_order_with_empty_items_returns_400(self, client):
        """Test that submitting an order with no items returns 400."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 10000, "items": []},
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_create_order_with_nonpositive_quantity_returns_400(self, client):
        """Test that submitting an order with a non-positive quantity returns 400."""
        response = client.get("/api/inventory")
        sku = response.json()[0]["sku"]

        response = client.post(
            "/api/restocking/orders",
            json={"budget": 10000, "items": [{"sku": sku, "quantity": 0}]},
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
