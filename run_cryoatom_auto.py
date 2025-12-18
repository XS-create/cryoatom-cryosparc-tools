#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
run_cryoatom_auto.py

在现有 run_cryoatom.py 的基础上：
1. 自动选择空闲 GPU（如未指定 --gpu）
2. 调用 run_cryoatom.py 运行 CryoAtom
3. 自动将 out.cif 拷回 CryoSPARC 原 job 目录，并写日志
"""

import argparse
import sys
import subprocess
from pathlib import Path
import shutil
import os
import logging

from cryosparc.tools import CryoSPARC


# ----------------------------
# 日志配置
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ----------------------------
# CryoSPARC 连接配置（和 run_cryoatom.py 保持一致）
# ----------------------------
def get_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


CS = dict(
    host=os.getenv("CS_HOST", "10.210.21.48"),
    base_port=int(os.getenv("CS_BASE_PORT", "39000")),
    email=get_env("CS_EMAIL"),
    password=get_env("CS_PASSWORD"),
    license=get_env("CS_LICENSE_ID"),
)


# ----------------------------
# 工具函数
# ----------------------------
SCRIPT_DIR = Path(__file__).resolve().parent


def safe_dir(obj):
    """兼容 .dir 既可能是属性也可能是方法。"""
    d = obj.dir() if callable(obj.dir) else obj.dir
    return Path(d)


def pick_free_gpu():
    """
    使用 nvidia-smi，按 (显存占用比例, GPU 利用率) 最小 选一个 GPU。
    若设置了 CUDA_VISIBLE_DEVICES，则只在该列表内挑选。
    出错时退回 GPU 0。
    """
    visible = os.getenv("CUDA_VISIBLE_DEVICES")
    if visible:
        try:
            allowed = {int(x) for x in visible.split(",") if x.strip().isdigit()}
        except Exception:
            allowed = None
            logger.warning(
                "解析 CUDA_VISIBLE_DEVICES=%s 失败，将忽略该限制", visible
            )
    else:
        allowed = None

    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("无法调用 nvidia-smi，退回使用 GPU 0 (%s)", e)
        return 0

    best_idx = 0
    best_score = None  # (mem_ratio, util)

    for line in out.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            idx = int(parts[0])
            mem_used = float(parts[1])
            mem_total = float(parts[2])
            util = float(parts[3])
        except ValueError:
            continue

        if allowed is not None and idx not in allowed:
            continue

        mem_ratio = mem_used / max(mem_total, 1.0)
        score = (mem_ratio, util)

        if best_score is None or score < best_score:
            best_score = score
            best_idx = idx

    if best_score is None:
        logger.warning(
            "nvidia-smi 未返回合法 GPU 信息（或不在 CUDA_VISIBLE_DEVICES 中），退回使用 GPU 0"
        )
        return 0

    logger.info("自动选择 GPU: %d (score=%s)", best_idx, best_score)
    return best_idx


# ----------------------------
# 参数解析
# ----------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="自动选 GPU + 调用 CryoAtom + 结果回填 CryoSPARC"
    )
    p.add_argument("--project", "-p", required=True, help="Project UID, 如 P164")
    p.add_argument("--job", "-j", required=True, help="Job UID, 如 J44")
    p.add_argument("--fasta", "-f", required=True, help="FASTA 文件路径")

    p.add_argument(
        "--volume-output",
        "-o",
        default="volume",
        help="源 job 的 volume 输出名称 (默认: volume)",
    )
    p.add_argument(
        "--map-field",
        default=None,
        help="可选: 数据集中 map 字段名，如 map_sharp/path；不填则自动选择",
    )
    p.add_argument(
        "--row-index",
        type=int,
        default=0,
        help="当输出 dataset 有多行时，选用的行索引 (默认: 0)",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="可选: CryoAtom 工作目录；不填则默认: <project_dir>/cryoatom_<project>_<job>",
    )
    p.add_argument(
        "--no-copy-map",
        action="store_true",
        help="不拷贝 map 文件，直接使用 CryoSPARC 原始 map 路径",
    )
    p.add_argument(
        "--gpu",
        type=int,
        default=None,
        help="指定 GPU；不指定时自动选择最空闲 GPU",
    )
    return p.parse_args()


# ----------------------------
# 主逻辑
# ----------------------------
def main():
    args = parse_args()

    # 1. 选择 GPU
    if args.gpu is None:
        gpu = pick_free_gpu()
    else:
        gpu = args.gpu
        logger.info("使用用户指定 GPU: %d", gpu)

    # 2. 调用 run_cryoatom.py
    rc_script = SCRIPT_DIR / "run_cryoatom.py"
    if not rc_script.exists():
        logger.error("找不到 run_cryoatom.py: %s", rc_script)
        sys.exit(1)

    cmd = [
        sys.executable,
        str(rc_script),
        "--project",
        args.project,
        "--job",
        args.job,
        "--volume-output",
        args.volume_output,
        "--fasta",
        args.fasta,
        "--gpu",
        str(gpu),
    ]

    if args.map_field:
        cmd += ["--map-field", args.map_field]
    if args.row_index is not None:
        cmd += ["--row-index", str(args.row_index)]
    if args.out_dir:
        cmd += ["--out-dir", args.out_dir]
    if args.no_copy_map:
        cmd += ["--no-copy-map"]

    logger.info("调用 run_cryoatom.py：%s", " ".join(cmd))

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logger.error("run_cryoatom.py 运行失败，退出码 %s", e.returncode)
        sys.exit(e.returncode)

    # 3. 连接 CryoSPARC，定位 project / job
    try:
        cs = CryoSPARC(**CS)
    except Exception as e:
        logger.exception("结果已生成，但无法连接 CryoSPARC 做注册: %s", e)
        sys.exit(1)

    project = cs.find_project(args.project)
    if project is None:
        logger.error("找不到 Project: %s", args.project)
        sys.exit(1)

    job = cs.find_job(args.project, args.job)
    if job is None:
        logger.error("找不到 Job: project=%s, job=%s", args.project, args.job)
        sys.exit(1)

    # 4. 推断 CryoAtom 工作目录 & out.cif 路径（规则与 run_cryoatom.py 保持一致）
    if args.out_dir:
        work_dir = Path(args.out_dir)
    else:
        project_dir = safe_dir(project)
        work_dir = project_dir / f"cryoatom_{project.uid}_{job.uid}"

    out_dir = work_dir / "out"
    out_cif = out_dir / "out.cif"

    if not out_cif.exists():
        logger.error("没找到 CryoAtom 输出文件: %s", out_cif)
        sys.exit(1)

    logger.info("找到 CryoAtom 输出模型: %s", out_cif)

    # 5. 拷贝到原 CryoSPARC job 目录下，形成 cryoatom 结果
    job_dir = safe_dir(job)
    target_dir = job_dir / "cryoatom"
    target_dir.mkdir(parents=True, exist_ok=True)

    dest_file = target_dir / f"{project.uid}_{job.uid}_cryoatom.cif"
    shutil.copy2(out_cif, dest_file)

    logger.info("已将模型拷贝回 Job 目录: %s", dest_file)

    # 6. 在原 job 的日志中记录一条信息
    try:
        job.log(
            f"CryoAtom model generated on GPU {gpu} and copied to {dest_file}",
            level="info",
        )
        logger.info("已在 CryoSPARC Job 日志中记录 CryoAtom 结果位置。")
    except Exception as e:
        logger.warning("写 Job 日志失败（不影响文件本身）: %s", e)

    logger.info("----------------------------------------------------------------------")
    logger.info("[DONE] 全流程完成：自动选 GPU + CryoAtom + 结果回填 CryoSPARC")
    logger.info("       最终模型位置：%s", dest_file)
    logger.info("       你可以在 CryoSPARC 的 Job 文件浏览器中看到 cryoatom/ 目录")
    logger.info("----------------------------------------------------------------------")


if __name__ == "__main__":
    main()
