"""核心折叠 / 展开 / 反向打孔规划逻辑（纯 Python，不依赖 Web 框架）。

坐标约定：
- 板材为整数网格，单元格坐标 (x, y)，x 向右、y 向下，左上角为 (0, 0)。
- 打孔点使用最终折叠面的局部坐标，(0, 0) 为折叠面左上角。
- 展开结果中的孔位与规划接口的目标孔位均使用原始板材坐标。

折叠方向语义（被移动的一半朝该方向折）：
- left  ：右半部分向左折，折叠面落在左半区；
- right ：左半部分向右折，折叠面落在右半区；
- up    ：下半部分向上折，折叠面落在上半区；
- down  ：上半部分向下折，折叠面落在下半区。

叠层约定（限深打孔）：
- 每一步折叠先将被移动半区的叠层翻面（层序反转），再叠到固定半区之上；
- 最终折叠面的叠层自上而下编号为 1..2^len(folds)；
- 打孔点可携带 depth，只传播到前 depth 层对应的原板坐标，省略时贯穿全部层。
"""
from __future__ import annotations

from dataclasses import dataclass

HORIZONTAL_FOLDS = {"left", "right"}  # 沿竖直轴对折，改变宽度
VERTICAL_FOLDS = {"up", "down"}       # 沿水平轴对折，改变高度


class FoldError(ValueError):
    """折叠序列校验或展开过程中抛出的领域错误。"""

    def __init__(self, code: str, message: str, **context):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class Region:
    """原始板材上的轴对齐网格区域。"""

    x: int
    y: int
    width: int
    height: int


def fold_regions(width: int, height: int, folds: list[str]) -> list[Region]:
    """计算每一次对折后板材占据的区域。

    返回长度为 len(folds) + 1 的列表：regions[0] 为整张板材，
    regions[i + 1] 为应用 folds[i] 之后的区域。

    当某一步的折叠轴长度为奇数时抛出 FoldError("odd_fold_axis")。
    """
    regions = [Region(0, 0, width, height)]
    for i, direction in enumerate(folds):
        cur = regions[-1]
        if direction in HORIZONTAL_FOLDS:
            if cur.width % 2:
                raise FoldError(
                    "odd_fold_axis",
                    f"第 {i} 步折叠（'{direction}'）要求当前宽度为偶数，实际为 {cur.width}。",
                    step=i,
                    direction=direction,
                    axis="width",
                    axis_length=cur.width,
                )
            half = cur.width // 2
            x = cur.x if direction == "left" else cur.x + half
            regions.append(Region(x, cur.y, half, cur.height))
        else:
            if cur.height % 2:
                raise FoldError(
                    "odd_fold_axis",
                    f"第 {i} 步折叠（'{direction}'）要求当前高度为偶数，实际为 {cur.height}。",
                    step=i,
                    direction=direction,
                    axis="height",
                    axis_length=cur.height,
                )
            half = cur.height // 2
            y = cur.y if direction == "up" else cur.y + half
            regions.append(Region(cur.x, y, cur.width, half))
    return regions


def layer_number(steps: list[dict]) -> int:
    """由按折叠原始顺序排列的分支记录计算该路径的最终层号（1 = 最上层）。

    第 k 步折叠前叠层高度为 2^k：被移动半区翻面（层序反转）后叠到固定半区
    之上，因此 stay 分支落在下半叠（位置 +2^k），mirror 分支落在上半叠且
    位置反转（2^k - 1 - pos）。
    """
    pos = 0
    for k, step in enumerate(steps):
        if step["branch"] == "stay":
            pos = (1 << k) + pos
        else:
            pos = (1 << k) - 1 - pos
    return pos + 1


def unfold_board(
    width: int,
    height: int,
    folds: list[str],
    punches: list[tuple[int, int]],
    depths: list[int | None] | None = None,
) -> dict:
    """逆序展开折叠序列，通过镜像传播孔位。

    参数：
        width/height：原始板材的整数网格尺寸。
        folds：按执行顺序给出的折叠方向序列。
        punches：最终折叠面上的打孔点（折叠面局部坐标）。
        depths：与 punches 等长的可选限深序列；depths[i] 为 None 时该点贯穿
            全部 2^len(folds) 层，否则只传播到自上而下前 depths[i] 层。

    返回：
        包含 final_face、stack_layers、total_holes、unique_holes、holes 的字典。
        重合坐标被合并为一个 hole，其 paths 保留每一条传播路径，path["layer"]
        为该分支在最终叠层中的层号（1 = 最上层）。
    """
    regions = fold_regions(width, height, folds)
    final = regions[-1]

    if depths is None:
        depths = [None] * len(punches)
    elif len(depths) != len(punches):
        raise FoldError(
            "invalid_depth",
            f"depths 数量 {len(depths)} 与打孔点数量 {len(punches)} 不一致。",
        )
    max_depth = 1 << len(folds)
    for idx, depth in enumerate(depths):
        if depth is not None and not 1 <= depth <= max_depth:
            raise FoldError(
                "invalid_depth",
                f"打孔点 #{idx} 的 depth={depth} 非法："
                f"取值范围为 1..2^{len(folds)}={max_depth}。",
                punch=idx,
                depth=depth,
                max_depth=max_depth,
            )

    for idx, (px, py) in enumerate(punches):
        if not (0 <= px < final.width and 0 <= py < final.height):
            raise FoldError(
                "punch_out_of_bounds",
                f"打孔点 #{idx} ({px}, {py}) 超出最终折叠面范围 "
                f"（{final.width}x{final.height}，局部坐标从 0 开始）。",
                punch=idx,
                x=px,
                y=py,
                face_width=final.width,
                face_height=final.height,
            )

    # 状态项：(x, y, 打孔点索引, 传播步骤)。步骤按展开顺序（最后一次折叠在前）追加。
    states: list[tuple[int, int, int, list[dict]]] = [
        (final.x + px, final.y + py, idx, []) for idx, (px, py) in enumerate(punches)
    ]

    for i in range(len(folds) - 1, -1, -1):
        direction = folds[i]
        before = regions[i]  # 该次折叠之前（即展开之后）的区域
        nxt: list[tuple[int, int, int, list[dict]]] = []
        for x, y, idx, steps in states:
            stay = {"fold": i, "direction": direction, "branch": "stay"}
            mirror = {"fold": i, "direction": direction, "branch": "mirror"}
            # 未移动的那一层：坐标不变
            nxt.append((x, y, idx, steps + [stay]))
            # 被折过来的那一层：关于折叠轴镜像
            if direction in HORIZONTAL_FOLDS:
                mx = 2 * before.x + before.width - 1 - x
                nxt.append((mx, y, idx, steps + [mirror]))
            else:
                my = 2 * before.y + before.height - 1 - y
                nxt.append((x, my, idx, steps + [mirror]))
        states = nxt

    # 合并重合坐标，保留各自传播路径；限深打孔只保留前 depth 层
    merged: dict[tuple[int, int], list[dict]] = {}
    total_holes = 0
    for x, y, idx, steps in states:
        # 反转为请求中折叠的原始顺序，便于阅读
        ordered = list(reversed(steps))
        layer = layer_number(ordered)
        depth = depths[idx]
        if depth is not None and layer > depth:
            continue
        total_holes += 1
        path = {
            "punch": idx,
            "punch_point": {"x": punches[idx][0], "y": punches[idx][1]},
            "layer": layer,
            "steps": ordered,
        }
        merged.setdefault((x, y), []).append(path)

    holes = [
        {"x": x, "y": y, "layers": len(paths), "paths": paths}
        for (x, y), paths in sorted(merged.items())
    ]
    return {
        "final_face": {
            "x": final.x,
            "y": final.y,
            "width": final.width,
            "height": final.height,
        },
        "stack_layers": 1 << len(folds),
        "total_holes": total_holes,
        "unique_holes": len(holes),
        "holes": holes,
    }


def fold_point_layer(
    regions: list[Region], folds: list[str], x: int, y: int
) -> tuple[tuple[int, int], int]:
    """正向折叠原始板材坐标 (x, y)，返回（最终折叠面坐标, 最终叠层中的层号）。

    每步折叠中，位于被移动半区的点关于折叠轴镜像（mirror 分支），其余点
    保持不动（stay 分支）；分支序列经 layer_number 换算为最终叠层自上而下
    的层号（1 = 最上层），与 unfold_board 展开路径上的 layer 完全一致。
    """
    steps: list[dict] = []
    for i, direction in enumerate(folds):
        before = regions[i]
        if direction in HORIZONTAL_FOLDS:
            half = before.width // 2
            moved = x >= before.x + half if direction == "left" else x < before.x + half
            if moved:
                x = 2 * before.x + before.width - 1 - x
                steps.append({"branch": "mirror"})
            else:
                steps.append({"branch": "stay"})
        else:
            half = before.height // 2
            moved = y >= before.y + half if direction == "up" else y < before.y + half
            if moved:
                y = 2 * before.y + before.height - 1 - y
                steps.append({"branch": "mirror"})
            else:
                steps.append({"branch": "stay"})
    return (x, y), layer_number(steps)


def fold_point(regions: list[Region], folds: list[str], x: int, y: int) -> tuple[int, int]:
    """将原始板材坐标 (x, y) 沿折叠序列正向映射到最终折叠面（仍为板材坐标）。

    每步折叠中，位于被移动半区的点关于折叠轴镜像，其余点保持不动；
    与 unfold_board 的逆序镜像传播互为逆过程。
    """
    return fold_point_layer(regions, folds, x, y)[0]


def plan_punches(
    width: int,
    height: int,
    folds: list[str],
    targets: list[tuple[int, int]],
    *,
    max_punches: int | None = None,
    max_total_holes: int | None = None,
) -> dict:
    """反向打孔规划：由期望的展开孔位反推最终折叠面上的（限深）打孔点集合。

    流程：
    1. 目标孔位去重并做板材边界校验；
    2. 沿折叠序列把每个目标孔位正向归并到最终折叠面的等价位置（相同位置
       构成一个等价组，组代表即候选打孔点），同时算出它在该组最终叠层中
       的层号（自上而下，1 = 最上层）；
    3. 每个等价组的层号集合必须恰好是连续前缀 1..d：该组用一个限深打孔点
       覆盖（depth=d），d 等于总层数 2^len(folds) 时省略 depth（贯穿全部层）；
    4. 复用 unfold_board 按推导出的 depth 复算展开结果，仅当复算孔位集合
       与去重后的目标集合完全一致时，返回按 (x, y) 稳定排序的打孔点列表。

    异常：
        FoldError("target_out_of_bounds")：目标含越界坐标，
            context 的 out_of_bounds 列出全部越界点。
        FoldError("non_prefix_depth_group")：首个层号非连续前缀的等价组
            （目标跳层或缺少更上层），context 列出该组的 present_layers 与
            missing_prefix_layers，绝不默默补孔。
        FoldError("limit_exceeded")：归并后的打孔点数或展开孔位总数超限。
    """
    regions = fold_regions(width, height, folds)
    final = regions[-1]
    total_layers = 1 << len(folds)

    # 目标孔位去重，统一按 (x, y) 排序保证后续处理顺序稳定
    unique_targets = sorted(set(targets))

    out_of_bounds = [
        (x, y) for x, y in unique_targets if not (0 <= x < width and 0 <= y < height)
    ]
    if out_of_bounds:
        raise FoldError(
            "target_out_of_bounds",
            f"目标孔位包含 {len(out_of_bounds)} 个越界坐标"
            f"（板材 {width}x{height}，坐标从 0 开始）。",
            out_of_bounds=[{"x": x, "y": y} for x, y in out_of_bounds],
            board_width=width,
            board_height=height,
        )

    # 沿折叠过程正向归并：等价组（折叠面局部坐标）-> 组内目标占有的层号集合
    layers_by_punch: dict[tuple[int, int], set[int]] = {}
    for tx, ty in unique_targets:
        (fx, fy), layer = fold_point_layer(regions, folds, tx, ty)
        layers_by_punch.setdefault((fx - final.x, fy - final.y), set()).add(layer)
    punches = sorted(layers_by_punch)

    if max_punches is not None and len(punches) > max_punches:
        raise FoldError(
            "limit_exceeded",
            f"归并后打孔点数 {len(punches)} 超过上限 MAX_PUNCHES={max_punches}。",
        )
    if max_total_holes is not None:
        total = len(punches) << len(folds)
        if total > max_total_holes:
            raise FoldError(
                "limit_exceeded",
                f"展开后将产生 {total} 个孔位，超过上限 "
                f"MAX_TOTAL_HOLES={max_total_holes}，请减少折叠步数或目标孔位。",
            )

    # 逐组校验层号为连续前缀 1..d，并推导限深（d 等于总层数时省略 depth）
    depths: list[int | None] = []
    for punch in punches:
        present = sorted(layers_by_punch[punch])
        d = len(present)
        if present != list(range(1, d + 1)):
            missing = [
                layer
                for layer in range(1, present[-1] + 1)
                if layer not in layers_by_punch[punch]
            ]
            raise FoldError(
                "non_prefix_depth_group",
                f"等价组 ({punch[0]}, {punch[1]}) 的目标层号 {present} 不是"
                f"自上而下的连续前缀：缺失前缀层 {missing}；限深打孔只能打穿"
                "前 depth 层，请补全缺失层对应的目标或移除跳层目标后重试，"
                "服务端不会自动补孔。",
                group={"x": punch[0], "y": punch[1]},
                present_layers=present,
                missing_prefix_layers=missing,
            )
        depths.append(None if d == total_layers else d)

    # 用现有展开逻辑按推导出的 depth 复算，验证复算孔位与目标集合完全一致
    recomputed = unfold_board(width, height, folds, punches, depths)
    target_set = set(unique_targets)
    recomputed_set = {(h["x"], h["y"]) for h in recomputed["holes"]}
    if recomputed_set != target_set:
        raise FoldError(
            "target_mismatch",
            "复算结果与目标集合不一致。",
            missing=[{"x": x, "y": y} for x, y in sorted(target_set - recomputed_set)],
            extra=[{"x": x, "y": y} for x, y in sorted(recomputed_set - target_set)],
        )

    return {
        "final_face": {
            "x": final.x,
            "y": final.y,
            "width": final.width,
            "height": final.height,
        },
        "stack_layers": total_layers,
        "target_count": len(unique_targets),
        "punch_count": len(punches),
        "punches": [
            {"x": x, "y": y, **({"depth": d} if d is not None else {})}
            for (x, y), d in zip(punches, depths)
        ],
    }
