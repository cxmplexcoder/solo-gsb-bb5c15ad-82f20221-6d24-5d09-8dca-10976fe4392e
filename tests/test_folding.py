"""核心展开逻辑测试。"""
import pytest

from app.folding import (
    FoldError,
    fold_point,
    fold_point_layer,
    fold_regions,
    plan_punches,
    unfold_board,
)


def test_unfold_left_down_known_coordinates():
    # 8x4 板材：右半向左折 -> 上半向下折；折叠面为 x∈[0,4), y∈[2,4)
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    assert res["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert res["stack_layers"] == 4
    assert res["total_holes"] == 4
    assert res["unique_holes"] == 4
    coords = {(h["x"], h["y"]) for h in res["holes"]}
    assert coords == {(1, 1), (1, 2), (6, 1), (6, 2)}
    for hole in res["holes"]:
        assert hole["layers"] == 1
        assert len(hole["paths"]) == 1
        path = hole["paths"][0]
        assert path["punch"] == 0
        assert path["punch_point"] == {"x": 1, "y": 0}
        # 步骤按折叠原始顺序排列
        assert [s["fold"] for s in path["steps"]] == [0, 1]


def test_path_branches_recorded():
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    by_coord = {(h["x"], h["y"]): h for h in res["holes"]}
    # (6, 1) 是两次都取镜像分支的孔位
    steps = by_coord[(6, 1)]["paths"][0]["steps"]
    assert [s["branch"] for s in steps] == ["mirror", "mirror"]
    assert [s["direction"] for s in steps] == ["left", "down"]
    # (1, 2) 是两次都留在原层的孔位
    steps = by_coord[(1, 2)]["paths"][0]["steps"]
    assert [s["branch"] for s in steps] == ["stay", "stay"]


def test_fold_right_semantics():
    # 4x1：左半向右折，折叠面为 x∈[2,4)
    res = unfold_board(4, 1, ["right"], [(0, 0)])
    assert res["final_face"] == {"x": 2, "y": 0, "width": 2, "height": 1}
    coords = {(h["x"], h["y"]) for h in res["holes"]}
    assert coords == {(1, 0), (2, 0)}


def test_fold_up_semantics():
    # 1x4：下半向上折，折叠面为 y∈[0,2)
    res = unfold_board(1, 4, ["up"], [(0, 1)])
    assert res["final_face"] == {"x": 0, "y": 0, "width": 1, "height": 2}
    coords = {(h["x"], h["y"]) for h in res["holes"]}
    assert coords == {(0, 1), (0, 2)}


def test_no_folds_passthrough():
    res = unfold_board(3, 3, [], [(2, 1)])
    assert res["stack_layers"] == 1
    assert res["unique_holes"] == 1
    hole = res["holes"][0]
    assert (hole["x"], hole["y"], hole["layers"]) == (2, 1, 1)
    assert hole["paths"][0]["steps"] == []


def test_odd_axis_rejected_at_first_step():
    with pytest.raises(FoldError) as exc_info:
        unfold_board(8, 5, ["up"], [(0, 0)])
    err = exc_info.value
    assert err.code == "odd_fold_axis"
    assert err.context["step"] == 0
    assert err.context["axis"] == "height"
    assert err.context["axis_length"] == 5


def test_odd_axis_rejected_at_later_step():
    # 6 -> 3 之后宽度为奇数，第二步应被拒绝
    with pytest.raises(FoldError) as exc_info:
        unfold_board(6, 2, ["left", "left"], [(0, 0)])
    err = exc_info.value
    assert err.code == "odd_fold_axis"
    assert err.context["step"] == 1
    assert err.context["axis_length"] == 3


def test_punch_out_of_bounds():
    with pytest.raises(FoldError) as exc_info:
        unfold_board(4, 4, ["left"], [(2, 0)])  # 折叠面宽 2，x=2 越界
    assert exc_info.value.code == "punch_out_of_bounds"
    assert exc_info.value.context["punch"] == 0


def test_duplicate_punches_merge_but_keep_paths():
    res = unfold_board(4, 2, ["left"], [(1, 0), (1, 0)])
    assert res["total_holes"] == 4
    assert res["unique_holes"] == 2
    for hole in res["holes"]:
        assert hole["layers"] == 2
        assert len(hole["paths"]) == 2
        assert {p["punch"] for p in hole["paths"]} == {0, 1}


def test_multiple_distinct_punches():
    res = unfold_board(4, 4, ["left", "down"], [(0, 0), (1, 1)])
    assert res["stack_layers"] == 4
    assert res["total_holes"] == 8
    assert res["unique_holes"] == 8


def test_layer_numbers_top_to_bottom():
    # 8x4，["left", "down"]：折叠面 (1,0) 的叠层自上而下为 (1,1) (6,1) (6,2) (1,2)
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    layers = {(h["x"], h["y"]): h["paths"][0]["layer"] for h in res["holes"]}
    assert layers == {(1, 1): 1, (6, 1): 2, (6, 2): 3, (1, 2): 4}


def test_layer_order_matches_fold_construction():
    # 8x1 两次 left：折叠面 cell 0 的叠层自上而下为 x=3, 4, 7, 0
    # （第一步 x=4..7 翻面叠上，第二步整体右半再翻面叠上）
    res = unfold_board(8, 1, ["left", "left"], [(0, 0)])
    order = [None] * 4
    for h in res["holes"]:
        order[h["paths"][0]["layer"] - 1] = h["x"]
    assert order == [3, 4, 7, 0]


def test_depth_limits_to_top_layers():
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)], [2])
    assert res["total_holes"] == 2
    assert res["unique_holes"] == 2
    coords = {(h["x"], h["y"]): h["paths"][0]["layer"] for h in res["holes"]}
    assert coords == {(1, 1): 1, (6, 1): 2}


def test_depth_one_keeps_top_layer_only():
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)], [1])
    assert res["total_holes"] == 1
    hole = res["holes"][0]
    assert (hole["x"], hole["y"]) == (1, 1)
    assert hole["paths"][0]["layer"] == 1


def test_depth_equal_to_stack_matches_full_penetration():
    full = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    limited = unfold_board(8, 4, ["left", "down"], [(1, 0)], [4])
    assert limited["total_holes"] == full["total_holes"] == 4
    assert {(h["x"], h["y"]) for h in limited["holes"]} == {
        (h["x"], h["y"]) for h in full["holes"]
    }


def test_mixed_depths_per_punch():
    # 打孔点 (0,1) 的叠层自上而下为 (0,0) (7,0) (7,3) (0,3)，depth=3 截掉最底层
    res = unfold_board(8, 4, ["left", "down"], [(1, 0), (0, 1)], [1, 3])
    assert res["total_holes"] == 4
    assert res["unique_holes"] == 4
    coords = {(h["x"], h["y"]): h["paths"][0]["layer"] for h in res["holes"]}
    assert coords == {(1, 1): 1, (0, 0): 1, (7, 0): 2, (7, 3): 3}
    by_coord = {(h["x"], h["y"]): h for h in res["holes"]}
    assert by_coord[(1, 1)]["paths"][0]["punch"] == 0
    assert by_coord[(0, 0)]["paths"][0]["punch"] == 1


def test_duplicate_points_different_depths_accumulate():
    res = unfold_board(8, 4, ["left", "down"], [(1, 0), (1, 0)], [1, 2])
    assert res["total_holes"] == 3
    assert res["unique_holes"] == 2
    by_coord = {(h["x"], h["y"]): h for h in res["holes"]}
    top = by_coord[(1, 1)]  # 两个打孔点的第 1 层在此重合
    assert top["layers"] == 2
    assert {p["punch"] for p in top["paths"]} == {0, 1}
    assert {p["layer"] for p in top["paths"]} == {1}
    second = by_coord[(6, 1)]  # 仅 depth=2 的打孔点到达第 2 层
    assert second["layers"] == 1
    assert second["paths"][0]["punch"] == 1
    assert second["paths"][0]["layer"] == 2


def test_no_folds_depth_must_be_one():
    res = unfold_board(3, 3, [], [(2, 1)], [1])
    assert res["holes"][0]["paths"][0]["layer"] == 1
    with pytest.raises(FoldError) as exc_info:
        unfold_board(3, 3, [], [(2, 1)], [2])
    assert exc_info.value.code == "invalid_depth"


def test_invalid_depth_rejected():
    with pytest.raises(FoldError) as exc_info:
        unfold_board(8, 4, ["left", "down"], [(1, 0)], [0])
    assert exc_info.value.code == "invalid_depth"

    with pytest.raises(FoldError) as exc_info:
        unfold_board(8, 4, ["left", "down"], [(1, 0)], [5])  # 2 次折叠最多 4 层
    err = exc_info.value
    assert err.code == "invalid_depth"
    assert err.context["punch"] == 0
    assert err.context["depth"] == 5
    assert err.context["max_depth"] == 4

    with pytest.raises(FoldError) as exc_info:
        unfold_board(8, 4, ["left", "down"], [(1, 0)], [1, 2])  # 数量不一致
    assert exc_info.value.code == "invalid_depth"


def test_fold_regions_sequence():
    regions = fold_regions(8, 4, ["left", "down"])
    assert [(r.x, r.y, r.width, r.height) for r in regions] == [
        (0, 0, 8, 4),
        (0, 0, 4, 4),
        (0, 2, 4, 2),
    ]


def test_fold_point_matches_unfold_paths():
    # 展开结果中的每个孔位，正向折叠后必须回到原打孔点
    regions = fold_regions(8, 4, ["left", "down"])
    res = unfold_board(8, 4, ["left", "down"], [(1, 0)])
    for hole in res["holes"]:
        assert fold_point(regions, ["left", "down"], hole["x"], hole["y"]) == (1, 2)


def test_fold_point_layer_matches_unfold_layers():
    # 正向模拟得到的层号必须与展开路径上的 layer 完全一致
    regions = fold_regions(8, 4, ["left", "down"])
    res = unfold_board(8, 4, ["left", "down"], [(1, 0), (0, 1)])
    for hole in res["holes"]:
        _, layer = fold_point_layer(regions, ["left", "down"], hole["x"], hole["y"])
        assert layer == hole["paths"][0]["layer"]


def test_plan_punches_round_trip_single_orbit():
    # 与 test_unfold_left_down_known_coordinates 互逆
    res = plan_punches(8, 4, ["left", "down"], [(1, 1), (1, 2), (6, 1), (6, 2)])
    assert res["final_face"] == {"x": 0, "y": 2, "width": 4, "height": 2}
    assert res["stack_layers"] == 4
    assert res["target_count"] == 4
    assert res["punch_count"] == 1
    assert res["punches"] == [{"x": 1, "y": 0}]


def test_plan_punches_multiple_orbits_sorted():
    targets = [
        (1, 0), (1, 3), (2, 0), (2, 3),  # 等价组 (1, 1)
        (0, 1), (0, 2), (3, 1), (3, 2),  # 等价组 (0, 0)
    ]
    res = plan_punches(4, 4, ["left", "down"], targets)
    assert res["target_count"] == 8
    assert res["punch_count"] == 2
    assert res["punches"] == [{"x": 0, "y": 0}, {"x": 1, "y": 1}]


def test_plan_punches_no_folds_dedup_and_sort():
    res = plan_punches(3, 3, [], [(2, 1), (0, 0), (2, 1)])
    assert res["stack_layers"] == 1
    assert res["target_count"] == 2
    assert res["punches"] == [{"x": 0, "y": 0}, {"x": 2, "y": 1}]


def test_plan_punches_result_feeds_unfold_board():
    targets = [(1, 1), (1, 2), (6, 1), (6, 2)]
    res = plan_punches(8, 4, ["left", "down"], targets)
    punches = [(p["x"], p["y"]) for p in res["punches"]]
    unfolded = unfold_board(8, 4, ["left", "down"], punches)
    assert {(h["x"], h["y"]) for h in unfolded["holes"]} == set(targets)


def test_plan_punches_target_out_of_bounds():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, ["left"], [(1, 1), (9, 0), (0, 4)])
    err = exc_info.value
    assert err.code == "target_out_of_bounds"
    # 越界坐标去重后按 (x, y) 排序全部列出
    assert err.context["out_of_bounds"] == [{"x": 0, "y": 4}, {"x": 9, "y": 0}]
    assert err.context["board_width"] == 4
    assert err.context["board_height"] == 4


def test_plan_punches_prefix_group_derives_depth():
    # (1, 1) 恰好是组 (1, 0) 叠层的最上层 -> 限深打孔 depth=1
    res = plan_punches(8, 4, ["left", "down"], [(1, 1)])
    assert res["target_count"] == 1
    assert res["punch_count"] == 1
    assert res["punches"] == [{"x": 1, "y": 0, "depth": 1}]


def test_plan_punches_full_orbit_omits_depth():
    # 完整镜像轨道贯穿全部 4 层 -> 省略 depth，与旧行为一致
    res = plan_punches(8, 4, ["left", "down"], [(1, 1), (1, 2), (6, 1), (6, 2)])
    assert res["punches"] == [{"x": 1, "y": 0}]


def test_plan_punches_partial_prefix_round_trip():
    # 组 (1, 0) 的前两层 (1, 1)、(6, 1) -> depth=2，复算孔位与目标完全一致
    targets = [(1, 1), (6, 1)]
    res = plan_punches(8, 4, ["left", "down"], targets)
    assert res["punches"] == [{"x": 1, "y": 0, "depth": 2}]
    punches = [(p["x"], p["y"]) for p in res["punches"]]
    depths = [p.get("depth") for p in res["punches"]]
    unfolded = unfold_board(8, 4, ["left", "down"], punches, depths)
    assert {(h["x"], h["y"]) for h in unfolded["holes"]} == set(targets)


def test_plan_punches_dedupes_targets_with_depth():
    res = plan_punches(8, 4, ["left", "down"], [(1, 1), (1, 1)])
    assert res["target_count"] == 1
    assert res["punches"] == [{"x": 1, "y": 0, "depth": 1}]


def test_plan_punches_multiple_groups_mixed_depths_sorted():
    # 组 (0, 0) 为完整轨道（省略 depth），组 (1, 0) 仅最上层（depth=1），按 (x, y) 排序
    targets = [(0, 1), (7, 1), (7, 2), (0, 2), (1, 1)]
    res = plan_punches(8, 4, ["left", "down"], targets)
    assert res["punch_count"] == 2
    assert res["punches"] == [{"x": 0, "y": 0}, {"x": 1, "y": 0, "depth": 1}]
    punches = [(p["x"], p["y"]) for p in res["punches"]]
    depths = [p.get("depth") for p in res["punches"]]
    unfolded = unfold_board(8, 4, ["left", "down"], punches, depths)
    assert {(h["x"], h["y"]) for h in unfolded["holes"]} == set(targets)


def test_plan_punches_missing_upper_layer_rejected():
    # (6, 1) 是组 (1, 0) 的第 2 层，缺少更上层（第 1 层）
    with pytest.raises(FoldError) as exc_info:
        plan_punches(8, 4, ["left", "down"], [(6, 1)])
    err = exc_info.value
    assert err.code == "non_prefix_depth_group"
    assert err.context["group"] == {"x": 1, "y": 0}
    assert err.context["present_layers"] == [2]
    assert err.context["missing_prefix_layers"] == [1]


def test_plan_punches_skipped_layer_rejected():
    # (1, 1) 第 1 层、(6, 2) 第 3 层：跳过第 2 层
    with pytest.raises(FoldError) as exc_info:
        plan_punches(8, 4, ["left", "down"], [(1, 1), (6, 2)])
    err = exc_info.value
    assert err.code == "non_prefix_depth_group"
    assert err.context["group"] == {"x": 1, "y": 0}
    assert err.context["present_layers"] == [1, 3]
    assert err.context["missing_prefix_layers"] == [2]


def test_plan_punches_reports_first_non_prefix_group_sorted():
    # (6, 1) 归并到组 (1, 0) 的第 2 层，(0, 3) 归并到组 (0, 1) 的第 4 层；
    # 两组都非连续前缀时报告 (x, y) 最小者
    with pytest.raises(FoldError) as exc_info:
        plan_punches(8, 4, ["left", "down"], [(6, 1), (0, 3)])
    err = exc_info.value
    assert err.code == "non_prefix_depth_group"
    assert err.context["group"] == {"x": 0, "y": 1}
    assert err.context["present_layers"] == [4]
    assert err.context["missing_prefix_layers"] == [1, 2, 3]


def test_plan_punches_odd_axis_propagates():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(3, 2, ["left"], [(0, 0)])
    assert exc_info.value.code == "odd_fold_axis"


def test_plan_punches_limit_exceeded():
    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, [], [(0, 0), (1, 1)], max_punches=1)
    assert exc_info.value.code == "limit_exceeded"

    with pytest.raises(FoldError) as exc_info:
        plan_punches(4, 4, ["left"], [(0, 0), (1, 0)], max_total_holes=3)
    assert exc_info.value.code == "limit_exceeded"
