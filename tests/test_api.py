"""HTTP API 测试。"""
import pytest
from fastapi.testclient import TestClient

from app import main as main_module
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


# --------------------------------------------------------------------------- #
# POST /api/v1/fold-selection
# --------------------------------------------------------------------------- #

FULL_ORBIT_TARGETS = [
    {"x": 1, "y": 1},
    {"x": 1, "y": 2},
    {"x": 6, "y": 1},
    {"x": 6, "y": 2},
]


def test_fold_selection_picks_punch_count_then_folds_then_order():
    # 1x8 纵向全轨道 4 孔：
    # - []：4 打孔点、0 折
    # - ['up','up']：1 打孔点、2 折（全轨道贯穿，省略 depth）
    # - ['left', ...] 类横向折叠在此目标上不可行，不中断其余候选
    targets = [{"x": 0, "y": y} for y in (1, 2, 5, 6)]
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 1, "height": 8},
            "targets": targets,
            "candidates": [[], ["up", "up"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # 打孔点数优先：1 打的 2 折候选胜过 4 打的 0 折候选
    assert body["selected_index"] == 1
    assert body["folds"] == ["up", "up"]
    assert body["punch_count"] == 1
    assert body["punches"] == [{"x": 0, "y": 1}]
    evals = body["evaluations"]
    assert evals[0] == {"index": 0, "feasible": True, "fold_count": 0, "punch_count": 4}
    assert evals[1] == {"index": 1, "feasible": True, "fold_count": 2, "punch_count": 1}


def test_fold_selection_fold_count_breaks_equal_punch_tie():
    # 单目标在 [] 与 ['up','up']（限深 depth）下都只需 1 打孔点 -> 折叠步数更少者胜
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 1, "height": 8},
            "targets": [{"x": 0, "y": 1}],
            "candidates": [["up", "up"], []],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    assert body["folds"] == []
    assert body["punch_count"] == 1


def test_fold_selection_two_fold_candidates_input_order_breaks_tie():
    # 两个打孔点数与折叠步数完全相同的可行候选，取下标更小者
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [["down", "left"], ["left", "down"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 0
    assert body["punch_count"] == 1
    assert body["folds"] == ["down", "left"]
    assert body["evaluations"] == [
        {"index": 0, "feasible": True, "fold_count": 2, "punch_count": 1},
        {"index": 1, "feasible": True, "fold_count": 2, "punch_count": 1},
    ]


def test_fold_selection_selected_plan_matches_punch_plan():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [["left", "down"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 0
    assert body["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert body["stack_layers"] == 4
    assert body["target_count"] == 4
    assert body["punches"] == [{"x": 1, "y": 0}]
    # 选中计划可直接喂给 /api/v1/unfold
    unfolded = client.post(
        "/api/v1/unfold",
        json={
            "board": body["board"],
            "folds": body["folds"],
            "punches": body["punches"],
        },
    )
    assert unfolded.status_code == 200
    coords = {(h["x"], h["y"]) for h in unfolded.json()["holes"]}
    assert coords == {(1, 1), (1, 2), (6, 1), (6, 2)}


def test_fold_selection_depth_plan_propagates_depth():
    # 仅最上层目标：两候选均 1 打孔点，0 折候选折叠步数更少而入选
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": [{"x": 1, "y": 1}],
            "candidates": [["left", "down"], []],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    assert body["folds"] == []
    assert body["punches"] == [{"x": 1, "y": 1}]
    # 2 折候选同样可行，其计划携带 depth=1
    assert body["evaluations"][0]["feasible"] is True
    assert body["evaluations"][0]["punch_count"] == 1


def test_fold_selection_duplicate_evaluated_once_but_reported_per_index():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": FULL_ORBIT_TARGETS,
            "candidates": [["left", "down"], ["left"], ["left", "down"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 0  # 重复候选不产生新的最优下标
    evals = body["evaluations"]
    assert len(evals) == 3
    assert evals[0] == {"index": 0, "feasible": True, "fold_count": 2, "punch_count": 1}
    assert "duplicate_of" not in evals[0]
    assert evals[2] == {
        "index": 2,
        "feasible": True,
        "fold_count": 2,
        "punch_count": 1,
        "duplicate_of": 0,
    }


def test_fold_selection_duplicate_infeasible_repeats_reason():
    # 4x4 三折 left：4->2->1，第 3 步轴长为奇数；重复候选各自保留原因
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 4, "height": 4},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [["left", "left", "left"], ["left", "left", "left"]],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "all_candidates_infeasible"
    assert len(detail["reasons"]) == 2
    for reason in detail["reasons"]:
        assert reason["error"] == "odd_fold_axis"
        assert reason["step"] == 2
        assert reason["axis"] == "width"
        assert reason["axis_length"] == 1


def test_fold_selection_infeasible_candidate_does_not_abort_others():
    # 候选 0 奇数轴不可行，候选 1 可行 -> 正常 200 选中候选 1
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 4, "height": 4},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [["left", "left", "left"], ["left", "down"]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    assert body["folds"] == ["left", "down"]
    evals = body["evaluations"]
    assert evals[0]["feasible"] is False
    assert evals[0]["reason"]["error"] == "odd_fold_axis"
    assert "punch_count" not in evals[0]
    assert evals[1]["feasible"] is True
    assert evals[1]["punch_count"] == 1
    assert "reason" not in evals[1]


def test_fold_selection_non_prefix_reason_is_structured():
    # (6,1) 是组 (1,0) 第 2 层，缺第 1 层 -> 全部不可行时完整列出原因
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 4},
            "targets": [{"x": 6, "y": 1}],
            "candidates": [["left", "down"]],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "all_candidates_infeasible"
    (reason,) = detail["reasons"]
    assert reason["error"] == "non_prefix_depth_group"
    assert reason["group"] == {"x": 1, "y": 0}
    assert reason["present_layers"] == [2]
    assert reason["missing_prefix_layers"] == [1]
    assert reason["message"]


def test_fold_selection_all_infeasible_returns_400_with_full_reasons():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 4, "height": 4},
            "targets": [{"x": 3, "y": 0}],
            "candidates": [
                ["left", "left", "left"],   # odd_fold_axis
                ["left", "down"],            # non_prefix_depth_group
            ],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "all_candidates_infeasible"
    assert len(detail["reasons"]) == 2
    assert [r["error"] for r in detail["reasons"]] == [
        "odd_fold_axis",
        "non_prefix_depth_group",
    ]
    assert detail["message"]


def test_fold_selection_candidate_over_max_folds_is_infeasible():
    # 单候选折叠步数超过 MAX_FOLDS 记为资源超限，不影响同请求中其它候选
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 524288, "height": 1},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [["left"] * 21, []],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 1
    assert body["evaluations"][0]["feasible"] is False
    assert body["evaluations"][0]["reason"]["error"] == "limit_exceeded"
    assert body["evaluations"][1]["feasible"] is True


def test_fold_selection_resource_limit_candidate_is_infeasible():
    # 归并后打孔点数超过 MAX_PUNCHES：记为资源超限而非请求级失败
    # 8x1：(0,0) 与 (7,0) 互为镜像，['left'] 归并为 1 个打孔点；[] 为 2 个
    targets = [{"x": 0, "y": 0}, {"x": 7, "y": 0}]

    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 1},
            "targets": targets,
            "candidates": [["left"], []],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 0
    assert body["punch_count"] == 1
    assert body["evaluations"][1]["punch_count"] == 2

    main_module.MAX_PUNCHES = 1
    limited = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 1},
            "targets": targets,
            "candidates": [["left"], []],
        },
    )
    # ['left'] 1 打仍可行；[] 2 打超限但不中断其它候选，仍返回 200
    assert limited.status_code == 200
    evals = limited.json()["evaluations"]
    assert evals[0]["feasible"] is True
    assert evals[0]["punch_count"] == 1
    assert evals[1]["feasible"] is False
    assert evals[1]["reason"]["error"] == "limit_exceeded"
    assert evals[1]["reason"]["message"]


def test_fold_selection_all_resource_limited_returns_400():
    main_module.MAX_PUNCHES = 1
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 8, "height": 1},
            "targets": [{"x": 0, "y": 0}, {"x": 1, "y": 0}],
            "candidates": [[], ["left"]],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "all_candidates_infeasible"
    assert [r["error"] for r in detail["reasons"]] == [
        "limit_exceeded",
        "limit_exceeded",
    ]


def test_fold_selection_too_many_candidates_returns_400():
    original = main_module.MAX_FOLD_CANDIDATES
    main_module.MAX_FOLD_CANDIDATES = 2
    try:
        resp = client.post(
            "/api/v1/fold-selection",
            json={
                "board": {"width": 4, "height": 4},
                "targets": [{"x": 0, "y": 0}],
                "candidates": [[], ["left"], ["down"]],
            },
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["error"] == "limit_exceeded"
        assert "MAX_FOLD_CANDIDATES" in detail["message"]
    finally:
        main_module.MAX_FOLD_CANDIDATES = original


def test_fold_selection_target_out_of_bounds_is_request_error():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 4, "height": 4},
            "targets": [{"x": 0, "y": 0}, {"x": 4, "y": 0}],
            "candidates": [["left"], []],
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "target_out_of_bounds"
    assert detail["out_of_bounds"] == [{"x": 4, "y": 0}]


def test_fold_selection_empty_candidates_returns_422():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 4, "height": 4},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [],
        },
    )
    assert resp.status_code == 422


def test_fold_selection_empty_targets_returns_422():
    resp = client.post(
        "/api/v1/fold-selection",
        json={"board": {"width": 4, "height": 4}, "targets": [], "candidates": [[]]},
    )
    assert resp.status_code == 422


def test_fold_selection_invalid_direction_returns_422():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 4, "height": 4},
            "targets": [{"x": 0, "y": 0}],
            "candidates": [["sideways"]],
        },
    )
    assert resp.status_code == 422


def test_fold_selection_no_folds_candidate_plans_directly():
    resp = client.post(
        "/api/v1/fold-selection",
        json={
            "board": {"width": 3, "height": 3},
            "targets": [{"x": 2, "y": 1}, {"x": 2, "y": 1}],
            "candidates": [[]],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_index"] == 0
    assert body["folds"] == []
    assert body["final_face"] == {"x": 0, "y": 0, "width": 3, "height": 3}
    assert body["stack_layers"] == 1
    assert body["target_count"] == 1
    assert body["punches"] == [{"x": 2, "y": 1}]


def test_fold_selection_existing_endpoints_unchanged():
    # 兼容性回归：旧接口行为不受影响
    assert client.get("/health").json() == {"status": "ok"}
    unfold = client.post(
        "/api/v1/unfold",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "punches": [{"x": 1, "y": 0}],
        },
    )
    assert unfold.status_code == 200
    plan = client.post(
        "/api/v1/punch-plan",
        json={
            "board": {"width": 8, "height": 4},
            "folds": ["left", "down"],
            "targets": FULL_ORBIT_TARGETS,
        },
    )
    assert plan.status_code == 200
    assert plan.json()["punches"] == [{"x": 1, "y": 0}]


@pytest.fixture(autouse=True)
def _restore_limits():
    """确保修改过的防护上限在测试间恢复默认值。"""
    candidates = main_module.MAX_FOLD_CANDIDATES
    punches = main_module.MAX_PUNCHES
    yield
    main_module.MAX_FOLD_CANDIDATES = candidates
    main_module.MAX_PUNCHES = punches
