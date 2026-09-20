"""FastAPI 应用入口：包装板材折叠打孔模板展开 / 反向打孔规划 API。"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from .folding import FoldError, plan_punches, unfold_board
from .models import (
    ErrorResponse,
    FoldSelectionRequest,
    FoldSelectionResponse,
    PunchPlanRequest,
    PunchPlanResponse,
    UnfoldRequest,
    UnfoldResponse,
)

# 可通过环境变量调整的防护上限
MAX_FOLDS = int(os.environ.get("MAX_FOLDS", "20"))
MAX_PUNCHES = int(os.environ.get("MAX_PUNCHES", "200"))
MAX_TOTAL_HOLES = int(os.environ.get("MAX_TOTAL_HOLES", "200000"))
MAX_FOLD_CANDIDATES = int(os.environ.get("MAX_FOLD_CANDIDATES", "50"))

app = FastAPI(
    title="包装板材折叠打孔模板展开 API",
    version="1.3.0",
    description=(
        "提交整数网格矩形板材、依次执行的对折方向序列以及最终折叠面上的打孔点，"
        "服务端逆序展开折叠并镜像传播孔位，返回展开后的唯一孔位、覆盖层数与来源路径。"
        "另提供反向打孔规划：由期望的展开孔位反推最终折叠面上的最小打孔点集合，"
        "目标只覆盖叠层连续前缀时自动推导限深 depth。"
        "折叠序列择优接口对同一组目标孔位逐个评估候选折叠序列，"
        "按打孔点数、折叠步数、输入顺序选出最优方案。"
    ),
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/v1/unfold",
    response_model=UnfoldResponse,
    responses={400: {"model": ErrorResponse, "description": "领域校验失败"}},
)
def unfold(req: UnfoldRequest) -> dict:
    if len(req.folds) > MAX_FOLDS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "limit_exceeded",
                "message": f"折叠步数 {len(req.folds)} 超过上限 MAX_FOLDS={MAX_FOLDS}。",
            },
        )
    if len(req.punches) > MAX_PUNCHES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "limit_exceeded",
                "message": f"打孔点数 {len(req.punches)} 超过上限 MAX_PUNCHES={MAX_PUNCHES}。",
            },
        )
    total = len(req.punches) << len(req.folds)
    if total > MAX_TOTAL_HOLES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "limit_exceeded",
                "message": (
                    f"展开后将产生 {total} 个孔位，超过上限 "
                    f"MAX_TOTAL_HOLES={MAX_TOTAL_HOLES}，请减少折叠步数或打孔点。"
                ),
            },
        )

    folds = [f.value for f in req.folds]
    punches = [(p.x, p.y) for p in req.punches]
    depths = [p.depth for p in req.punches]
    try:
        result = unfold_board(req.board.width, req.board.height, folds, punches, depths)
    except FoldError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": exc.code, "message": exc.message, **exc.context},
        ) from exc

    return {"board": req.board, "folds": req.folds, **result}


@app.post(
    "/api/v1/punch-plan",
    response_model=PunchPlanResponse,
    response_model_exclude_none=True,  # 贯穿全部层的打孔点省略 depth 字段
    responses={400: {"model": ErrorResponse, "description": "领域校验失败"}},
)
def punch_plan(req: PunchPlanRequest) -> dict:
    if len(req.folds) > MAX_FOLDS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "limit_exceeded",
                "message": f"折叠步数 {len(req.folds)} 超过上限 MAX_FOLDS={MAX_FOLDS}。",
            },
        )

    folds = [f.value for f in req.folds]
    targets = [(t.x, t.y) for t in req.targets]
    try:
        result = plan_punches(
            req.board.width,
            req.board.height,
            folds,
            targets,
            max_punches=MAX_PUNCHES,
            max_total_holes=MAX_TOTAL_HOLES,
        )
    except FoldError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": exc.code, "message": exc.message, **exc.context},
        ) from exc

    return {"board": req.board, "folds": req.folds, **result}


def _evaluate_candidate(
    width: int, height: int, folds: tuple[str, ...], targets: list[tuple[int, int]]
) -> dict:
    """评估单个候选折叠序列：可行返回打孔计划，不可行返回结构化原因。

    复用 plan_punches 的层序与限深规则；奇数轴、非连续前缀、资源超限等
    FoldError 一律转为该候选的不可行原因，不向其余候选传播。
    """
    if len(folds) > MAX_FOLDS:
        return {
            "feasible": False,
            "reason": {
                "error": "limit_exceeded",
                "message": f"折叠步数 {len(folds)} 超过上限 MAX_FOLDS={MAX_FOLDS}。",
            },
        }
    try:
        plan = plan_punches(
            width,
            height,
            list(folds),
            targets,
            max_punches=MAX_PUNCHES,
            max_total_holes=MAX_TOTAL_HOLES,
        )
    except FoldError as exc:
        return {
            "feasible": False,
            "reason": {"error": exc.code, "message": exc.message, **exc.context},
        }
    return {"feasible": True, "plan": plan}


@app.post(
    "/api/v1/fold-selection",
    response_model=FoldSelectionResponse,
    response_model_exclude_none=True,  # 可行候选省略 reason，不可行候选省略 punch_count
    responses={
        400: {"model": ErrorResponse, "description": "全部候选不可行或超出候选数量上限"}
    },
)
def fold_selection(req: FoldSelectionRequest) -> dict:
    if len(req.candidates) > MAX_FOLD_CANDIDATES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "limit_exceeded",
                "message": (
                    f"候选折叠序列数 {len(req.candidates)} 超过上限 "
                    f"MAX_FOLD_CANDIDATES={MAX_FOLD_CANDIDATES}。"
                ),
            },
        )

    targets = [(t.x, t.y) for t in req.targets]

    # 相同折叠序列只评估一次，结果映射回全部下标
    evaluated: dict[tuple[str, ...], dict] = {}
    for candidate in req.candidates:
        key = tuple(f.value for f in candidate)
        if key not in evaluated:
            evaluated[key] = _evaluate_candidate(
                req.board.width, req.board.height, key, targets
            )

    evaluations = []
    for idx, candidate in enumerate(req.candidates):
        key = tuple(f.value for f in candidate)
        outcome = evaluated[key]
        entry = {
            "index": idx,
            "folds": list(key),
            "fold_count": len(key),
            "feasible": outcome["feasible"],
        }
        if outcome["feasible"]:
            entry["punch_count"] = outcome["plan"]["punch_count"]
        else:
            entry["reason"] = outcome["reason"]
        evaluations.append(entry)

    feasible = [e for e in evaluations if e["feasible"]]
    if not feasible:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_feasible_candidate",
                "message": f"全部 {len(evaluations)} 个候选折叠序列均不可行。",
                "candidates": [
                    {"index": e["index"], "folds": e["folds"], "reason": e["reason"]}
                    for e in evaluations
                ],
            },
        )

    # 依次按打孔点数、折叠步数、输入顺序择优
    best = min(feasible, key=lambda e: (e["punch_count"], e["fold_count"], e["index"]))
    plan = evaluated[tuple(best["folds"])]["plan"]
    return {
        "board": req.board,
        "selected_index": best["index"],
        "plan": {"folds": best["folds"], **plan},
        "candidates": evaluations,
    }
