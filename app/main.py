"""FastAPI 应用入口：包装板材折叠打孔模板展开 / 反向打孔规划 API。"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from .folding import FoldError, plan_punches, unfold_board
from .models import (
    ErrorResponse,
    PunchPlanRequest,
    PunchPlanResponse,
    UnfoldRequest,
    UnfoldResponse,
)

# 可通过环境变量调整的防护上限
MAX_FOLDS = int(os.environ.get("MAX_FOLDS", "20"))
MAX_PUNCHES = int(os.environ.get("MAX_PUNCHES", "200"))
MAX_TOTAL_HOLES = int(os.environ.get("MAX_TOTAL_HOLES", "200000"))

app = FastAPI(
    title="包装板材折叠打孔模板展开 API",
    version="1.2.0",
    description=(
        "提交整数网格矩形板材、依次执行的对折方向序列以及最终折叠面上的打孔点，"
        "服务端逆序展开折叠并镜像传播孔位，返回展开后的唯一孔位、覆盖层数与来源路径。"
        "另提供反向打孔规划：由期望的展开孔位反推最终折叠面上的最小打孔点集合，"
        "目标只覆盖叠层连续前缀时自动推导限深 depth。"
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
