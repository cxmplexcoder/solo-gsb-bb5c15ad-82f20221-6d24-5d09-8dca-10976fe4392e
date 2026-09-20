"""HTTP API 测试。"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_unfold_ok():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert body["stack_layers"] == 4
    assert body["total_holes"] == 4
    assert body["unique_holes"] == 4
    coords = {(h["x"], h["y"]) for h in body["holes"]}
    assert coords == {(1, 1), (1, 2), (6, 1), (6, 2)}
    sample = body["holes"][0]
    assert sample["layers"] == 1
    assert sample["paths"][0]["punch"] == 0
    assert len(sample["paths"][0]["steps"]) == 2


def test_unfold_odd_axis_returns_400():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 3, "height": 2},
            "folds": ["left"],
            "punches": [{"x": 0, "y": 0}],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "odd_fold_axis"
    assert detail["axis"] == "width"
    assert detail["axis_length"] == 3
    assert detail["step"] == 0


def test_unfold_punch_out_of_bounds_returns_400():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 4, "height": 4},
            "folds": ["left"],
            "punches": [{"x": 2, "y": 0}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "punch_out_of_bounds"


def test_invalid_direction_returns_422():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 4, "height": 4},
            "folds": ["sideways"],
            "punches": [{"x": 0, "y": 0}],
        },
    )
    assert resp.status_code == 422


def test_empty_punches_returns_422():
    resp = client.post(
        "/api/v1/unfold",
        json={"board": {"width": 4, "height": 4}, "folds": [], "punches": []},
    )
    assert resp.status_code == 422


def test_negative_coordinate_returns_422():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 4, "height": 4},
            "folds": [],
            "punches": [{"x": -1, "y": 0}],
        },
    )
    assert resp.status_code == 422


def test_duplicate_punches_merged_with_paths():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 4, "height": 2},
            "folds": ["left"],
            "punches": [{"x": 1, "y": 0}, {"x": 1, "y": 0}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["unique_holes"] == 2
    for hole in body["holes"]:
        assert hole["layers"] == 2
        assert {p["punch"] for p in hole["paths"]} == {0, 1}


def test_unfold_with_depth_limits_layers():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0, "depth": 2}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stack_layers"] == 4
    assert body["total_holes"] == 2
    assert body["unique_holes"] == 2
    coords = {(h["x"], h["y"]): h["paths"][0]["layer"] for h in body["holes"]}
    assert coords == {(1, 1): 1, (6, 1): 2}


def test_unfold_without_depth_keeps_full_penetration():
    # 未带 depth 的旧请求行为不变，路径附带 layer 层号
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_holes"] == 4
    layers = {(h["x"], h["y"]): h["paths"][0]["layer"] for h in body["holes"]}
    assert layers == {(1, 1): 1, (6, 1): 2, (6, 2): 3, (1, 2): 4}


def test_unfold_mixed_depths_accumulate_layers():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0, "depth": 1}, {"x": 1, "y": 0, "depth": 2}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_holes"] == 3
    assert body["unique_holes"] == 2
    by_coord = {(h["x"], h["y"]): h for h in body["holes"]}
    assert by_coord[(1, 1)]["layers"] == 2
    assert {p["punch"] for p in by_coord[(1, 1)]["paths"]} == {0, 1}
    assert by_coord[(6, 1)]["layers"] == 1
    assert by_coord[(6, 1)]["paths"][0]["layer"] == 2


def test_unfold_depth_zero_returns_422():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0, "depth": 0}],
        },
    )
    assert resp.status_code == 422


def test_unfold_depth_above_stack_returns_422():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0, "depth": 5}],  # 2 次折叠最多 4 层
        },
    )
    assert resp.status_code == 422


def test_unfold_depth_without_folds_must_be_one():
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 3, "height": 3},
            "folds": [],
            "punches": [{"x": 1, "y": 1, "depth": 2}],
        },
    )
    assert resp.status_code == 422


def test_punch_plan_ok():
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [
                {"x": 1, "y": 1},
                {"x": 1, "y": 2},
                {"x": 6, "y": 1},
                {"x": 6, "y": 2},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert body["stack_layers"] == 4
    assert body["target_count"] == 4
    assert body["punch_count"] == 1
    assert body["punches"] == [{"x": 1, "y": 0}]


def test_punch_plan_dedupes_and_sorts_targets():
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 4, "height": 4},
            "folds": [],
            "targets": [{"x": 2, "y": 1}, {"x": 0, "y": 0}, {"x": 2, "y": 1}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_count"] == 2
    assert body["punch_count"] == 2
    assert body["punches"] == [{"x": 0, "y": 0}, {"x": 2, "y": 1}]


def test_punch_plan_result_compatible_with_unfold():
    plan = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [
                {"x": 1, "y": 1},
                {"x": 1, "y": 2},
                {"x": 6, "y": 1},
                {"x": 6, "y": 2},
            ],
        },
    ).json()
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": plan["punches"],
        },
    )
    assert resp.status_code == 200
    coords = {(h["x"], h["y"]) for h in resp.json()["holes"]}
    assert coords == {(1, 1), (1, 2), (6, 1), (6, 2)}


def test_punch_plan_target_out_of_bounds_returns_400():
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 4, "height": 4},
            "folds": [],
            "targets": [{"x": 1, "y": 1}, {"x": 4, "y": 0}],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "target_out_of_bounds"
    assert detail["out_of_bounds"] == [{"x": 4, "y": 0}]


def test_punch_plan_prefix_group_returns_depth():
    # (1, 1) 是组 (1, 0) 叠层的最上层 -> 限深打孔 depth=1
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [{"x": 1, "y": 1}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_count"] == 1
    assert body["punch_count"] == 1
    assert body["punches"] == [{"x": 1, "y": 0, "depth": 1}]


def test_punch_plan_full_orbit_omits_depth_key():
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [
                {"x": 1, "y": 1},
                {"x": 1, "y": 2},
                {"x": 6, "y": 1},
                {"x": 6, "y": 2},
            ],
        },
    )
    assert resp.status_code == 200
    # 贯穿全部层时响应里不出现 depth 字段
    assert resp.json()["punches"] == [{"x": 1, "y": 0}]


def test_punch_plan_non_prefix_group_returns_400():
    # (6, 1) 是组 (1, 0) 的第 2 层，缺少更上层（第 1 层）
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [{"x": 6, "y": 1}],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "non_prefix_depth_group"
    assert detail["group"] == {"x": 1, "y": 0}
    assert detail["present_layers"] == [2]
    assert detail["missing_prefix_layers"] == [1]


def test_punch_plan_skipped_layer_returns_400():
    # 第 1、3 层存在但跳过第 2 层
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [{"x": 1, "y": 1}, {"x": 6, "y": 2}],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "non_prefix_depth_group"
    assert detail["group"] == {"x": 1, "y": 0}
    assert detail["present_layers"] == [1, 3]
    assert detail["missing_prefix_layers"] == [2]


def test_punch_plan_depth_result_compatible_with_unfold():
    # 带 depth 的规划结果可直接作为 /api/v1/unfold 的 punches，
    # 复算孔位与去重后的 targets 完全一致
    plan = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": [{"x": 1, "y": 1}, {"x": 6, "y": 1}, {"x": 1, "y": 1}],
        },
    )
    assert plan.status_code == 200
    punches = plan.json()["punches"]
    assert punches == [{"x": 1, "y": 0, "depth": 2}]
    resp = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": punches,
        },
    )
    assert resp.status_code == 200
    coords = {(h["x"], h["y"]) for h in resp.json()["holes"]}
    assert coords == {(1, 1), (6, 1)}


def test_punch_plan_odd_axis_returns_400():
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 3, "height": 2},
            "folds": ["left"],
            "targets": [{"x": 0, "y": 0}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "odd_fold_axis"


def test_punch_plan_empty_targets_returns_422():
    resp = client.post(
        "/api/v1/punch-plan",
        json={"board": {"width": 4, "height": 4}, "folds": [], "targets": []},
    )
    assert resp.status_code == 422


def test_punch_plan_negative_coordinate_returns_422():
    resp = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 4, "height": 4},
            "folds": [],
            "targets": [{"x": -1, "y": 0}],
        },
    )
    assert resp.status_code == 422
