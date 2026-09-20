"""FastAPI 应用入口：包装板材折叠打孔模板展开 / 反向打孔规划 API。"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from .folding import FoldError, ensure_targets_in_bounds, plan_punches, unfold_board
from .models import (
    AllInfeasibleResponse,
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
        "fold-selection 可对同一板材与目标的若干候选折叠序列逐个复用规划规则评估，"
        "按打孔点数、折叠步数、输入顺序择优返回。"
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


def _candidate_reason(exc: FoldError) -> dict:
    """把单个候选评估中抛出的领域错误转成结构化原因字典。"""
    return {"error": exc.code, "message": exc.message, **exc.context}


@app.post(
    "/api/v1/fold-selection",
    response_model=FoldSelectionResponse,
    response_model_exclude_none=True,  # 省略可行候选的 reason、不可行候选的 punch_count 等
    responses={
        400: {
            "model": ErrorResponse | AllInfeasibleResponse,
            "description": "全部候选不可行，或请求级领域校验失败（目标越界、候选数超限）",
        }
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
    unique_targets = sorted(set(targets))
    try:
        # 目标孔位为所有候选共享，越界属于请求级错误，提前一次性拒绝
        ensure_targets_in_bounds(req.board.width, req.board.height, unique_targets)
    except FoldError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": exc.code, "message": exc.message, **exc.context},
        ) from exc

    # 复用现有层序与限深规则逐个评估；重复序列只计算一次，结果按首次下标缓存
    results: dict[tuple[str, ...], dict] = {}
    evaluations: list[dict] = []
    feasible: list[tuple[int, dict]] = []

    for index, fold_enums in enumerate(req.candidates):
        key = tuple(f.value for f in fold_enums)
        if key in results:
            cached = results[key]
            summary = {
                "index": index,
                "fold_count": len(key),
                "duplicate_of": cached["index"],
            }
            if cached["feasible"]:
                summary["feasible"] = True
                summary["punch_count"] = cached["result"]["punch_count"]
            else:
                summary["feasible"] = False
                summary["reason"] = cached["reason"]
            evaluations.append(summary)
            continue

        summary: dict = {"index": index, "fold_count": len(key)}
        if len(key) > MAX_FOLDS:
            reason = {
                "error": "limit_exceeded",
                "message": f"折叠步数 {len(key)} 超过上限 MAX_FOLDS={MAX_FOLDS}。",
            }
            summary.update(feasible=False, reason=reason)
            results[key] = {"index": index, "feasible": False, "reason": reason}
        else:
            try:
                result = plan_punches(
                    req.board.width,
                    req.board.height,
                    list(key),
                    targets,
                    max_punches=MAX_PUNCHES,
                    max_total_holes=MAX_TOTAL_HOLES,
                )
            except FoldError as exc:
                reason = _candidate_reason(exc)
                summary.update(feasible=False, reason=reason)
                results[key] = {"index": index, "feasible": False, "reason": reason}
            else:
                summary.update(feasible=True, punch_count=result["punch_count"])
                results[key] = {"index": index, "feasible": True, "result": result}
                feasible.append((index, result))
        evaluations.append(summary)

    if not feasible:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "all_candidates_infeasible",
                "message": (
                    f"全部 {len(req.candidates)} 个候选折叠序列均不可行，"
                    "详见 reasons 中与 candidates 等长的结构化原因列表。"
                ),
                "reasons": [e["reason"] for e in evaluations],
            },
        )

    # 按打孔点数、折叠步数、候选输入顺序依次择优
    selected_index, plan = min(
        feasible,
        key=lambda item: (
            item[1]["punch_count"],
            len(req.candidates[item[0]]),
            item[0],
        ),
    )

    return {
        "board": req.board,
        "targets": req.targets,
        "selected_index": selected_index,
        "folds": req.candidates[selected_index],
        "evaluations": evaluations,
        **plan,
    }
