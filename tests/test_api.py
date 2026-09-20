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


FULL_ORBIT_TARGETS = [
    {"x": 1, "y": 1},
    {"x": 1, "y": 2},
    {"x": 6, "y": 1},
    {"x": 6, "y": 2},
]


def test_fold_selection_picks_fewest_punches():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [[], ["left"], ["left", "down"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # 三个候选都可行：4 / 2 / 1 个打孔点，选中打孔点最少者
    assert body["selected_index"] == 2
    assert body["plan"]["folds"] == ["left", "down"]
    assert body["plan"]["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert body["plan"]["stack_layers"] == 4
    assert body["plan"]["target_count"] == 4
    assert body["plan"]["punch_count"] == 1
    assert body["plan"]["punches"] == [{"x": 1, "y": 0}]
    summaries = body["candidates"]
    assert [s["index"] for s in summaries] == [0, 1, 2]
    assert [s["fold_count"] for s in summaries] == [0, 1, 2]
    assert [s["punch_count"] for s in summaries] == [4, 2, 1]
    assert all(s["feasible"] for s in summaries)
    assert all("reason" not in s for s in summaries)


def test_fold_selection_tie_breaks_by_fold_count():
    # 两个候选都只需 1 个打孔点：折叠步数更少者胜出，与输入顺序无关
    payload = {
        "board": {"width": 8, "height": 4},
        "targets": [{"x": 1, "y": 1}, {"x": 6, "y": 1}],
    }
    resp = client.post(
        "/api/v1/fold-selection",
        json={**payload, "candidates": [["left", "down"], ["left"]]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    assert body["plan"]["folds"] == ["left"]
    assert body["plan"]["punches"] == [{"x": 1, "y": 1}]
    assert [s["punch_count"] for s in body["candidates"]] == [1, 1]

    resp = client.post(
        "/api/v1/fold-selection",
        json={**payload, "candidates": [["left"], ["left", "down"]]},
    )
    assert resp.status_code == 200
    assert resp.json()["selected_index"] == 0


def test_fold_selection_tie_breaks_by_input_order():
    # 打孔点数与折叠步数都相同：按候选输入顺序取前者
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [["left", "down"], ["down", "left"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 0
    assert [s["punch_count"] for s in body["candidates"]] == [1, 1]
    assert [s["fold_count"] for s in body["candidates"]] == [2, 2]


def test_fold_selection_infeasible_candidate_does_not_interrupt():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            # 奇数轴（第 3 步宽度为 1 / 第 2 步高度为 1）不影响其余候选
            "candidates": [
                ["left", "left", "left", "left"],
                ["left", "down"],
                ["up", "up", "up"],
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    summaries = body["candidates"]
    assert summaries[0]["feasible"] is False
    assert summaries[0]["reason"]["error"] == "odd_fold_axis"
    assert summaries[0]["reason"]["step"] == 3
    assert summaries[0]["reason"]["axis"] == "width"
    assert summaries[0]["reason"]["axis_length"] == 1
    assert "punch_count" not in summaries[0]
    assert summaries[1]["feasible"] is True
    assert summaries[1]["punch_count"] == 1
    assert "reason" not in summaries[1]
    assert summaries[2]["feasible"] is False
    assert summaries[2]["reason"]["error"] == "odd_fold_axis"


def test_fold_selection_non_prefix_reason_structured():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": [{"x": 6, "y": 1}],  # 组 (1, 0) 的第 2 层，缺少更上层
            "candidates": [["left", "down"], ["left"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    reason = body["candidates"][0]["reason"]
    assert reason["error"] == "non_prefix_depth_group"
    assert reason["group"] == {"x": 1, "y": 0}
    assert reason["present_layers"] == [2]
    assert reason["missing_prefix_layers"] == [1]


def test_fold_selection_all_infeasible_returns_400_with_reasons():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 3, "height": 2},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [["left"], ["right"], ["left", "up"]],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "no_feasible_candidate"
    assert len(detail["candidates"]) == 3
    for entry, folds in zip(detail["candidates"], [["left"], ["right"], ["left", "up"]]):
        assert entry["folds"] == folds
        assert entry["reason"]["error"] == "odd_fold_axis"
    assert detail["candidates"][0]["reason"]["axis_length"] == 3


def test_fold_selection_duplicate_candidates_share_result():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [["left"], ["left", "down"], ["left"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # 重复候选各自保留评估结果（除 index 外完全一致），择优时先出现者胜出
    assert body["selected_index"] == 1
    first, _, third = body["candidates"]
    assert {k: v for k, v in first.items() if k != "index"} == {
        k: v for k, v in third.items() if k != "index"
    }
    assert first["feasible"] is True
    assert first["punch_count"] == 2


def test_fold_selection_duplicate_infeasible_candidates_share_reason():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 3, "height": 3},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [["left"], ["up"], ["left"]],
        },
    )
    assert resp.status_code == 400
    candidates = resp.json()["detail"]["candidates"]
    assert {k: v for k, v in candidates[0].items() if k != "index"} == {
        k: v for k, v in candidates[2].items() if k != "index"
    }
    assert candidates[0]["reason"]["axis"] == "width"
    assert candidates[1]["reason"]["axis"] == "height"


def test_fold_selection_selected_plan_compatible_with_unfold():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": [{"x": 1, "y": 1}, {"x": 6, "y": 1}],
            "candidates": [["left", "down"], ["left"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # 选中的计划（含推导出的 depth）可直接作为 /api/v1/unfold 的 punches
    unfolded = client.post(
        "/api/v1/unfold",
        json={
            "board": body["board"],
            "folds": body["plan"]["folds"],
            "punches": body["plan"]["punches"],
        },
    )
    assert unfolded.status_code == 200
    coords = {(h["x"], h["y"]) for h in unfolded.json()["holes"]}
    assert coords == {(1, 1), (6, 1)}


def test_fold_selection_limit_exceeded_candidate_marked_infeasible():
    # 空折叠序列归并出 202 个打孔点，超过 MAX_PUNCHES=200，仅该候选不可行；
    # 目标取 ["left"] 的完整镜像轨道，保证另一候选可行
    targets = [{"x": x, "y": 0} for x in range(101)]
    targets += [{"x": 255 - x, "y": 0} for x in range(101)]
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 256, "height": 1},
            "targets": targets,
            "candidates": [[], ["left"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    assert body["plan"]["punch_count"] == 101
    assert body["candidates"][0]["feasible"] is False
    assert body["candidates"][0]["reason"]["error"] == "limit_exceeded"


def test_fold_selection_too_many_candidates_returns_400(monkeypatch):
    monkeypatch.setattr("app.main.MAX_FOLD_CANDIDATES", 2)
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [[], ["left"], ["left", "down"]],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "limit_exceeded"
    assert "MAX_FOLD_CANDIDATES" in detail["message"]


def test_fold_selection_empty_candidates_returns_422():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [],
        },
    )
    assert resp.status_code == 422


def test_fold_selection_empty_targets_returns_422():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": [],
            "candidates": [["left"]],
        },
    )
    assert resp.status_code == 422


def test_fold_selection_invalid_direction_returns_422():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [["sideways"]],
        },
    )
    assert resp.status_code == 422
