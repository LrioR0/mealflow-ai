from fastapi.testclient import TestClient

from app.main import app


def test_create_and_revise_agent_run() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/runs",
            json={
                "workspace_id": "demo-workspace",
                "site_id": "demo-site",
                "meal_service_id": "demo-lunch",
                "request_text": "明天午餐 120 人，预算 900 元，清淡，优先临期番茄，不能含花生",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "WAITING_APPROVAL"
        assert len(body["tool_trace"]) >= 5
        assert len(body["options"]) == 3

        revised = client.post(
            f"/api/v1/agent/runs/{body['id']}/revise",
            json={"expected_diners": 150},
        )

    assert revised.status_code == 200
    revised_body = revised.json()
    assert revised_body["constraints"]["expected_diners"] == 150
    assert revised_body["options"][0]["estimated_cost_cents"] > body["options"][0][
        "estimated_cost_cents"
    ]
