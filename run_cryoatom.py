#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
run_cryoatom.py — 从 CryoSPARC 自动抽取 map 并调用 CryoAtom 进行建模。

示例：

    conda activate CryoAtom
    python run_cryoatom.py \
        --project P164 \
        --job J243 \
        --volume-output volume \
        --fasta /home/spuser/sequences/WT_GLP-1R.fasta \
        --gpu 0
"""

import argparse
import sys
from pathlib import Path
import shutil
import subprocess
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
# CryoSPARC 连接配置
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
# 参数解析
# ----------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="从 CryoSPARC 自动抽 map 并调用 CryoAtom"
    )
    p.add_argument("--project", "-p", required=True, help="Project UID, 如 P164")
    p.add_argument("--job", "-j", required=True, help="Job UID, 如 J243")
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
        help="输出 dataset 有多行时，选用的行索引 (默认: 0)",
    )
    p.add_argument("--fasta", "-f", required=True, help="FASTA 文件路径")
    p.add_argument(
        "--gpu",
        type=int,
        default=0,
        help="使用的 GPU 编号 (默认: 0，对应 cuda:0)",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="可选: CryoAtom 工作目录；不填则默认 <project_dir>/cryoatom_<project>_<job>",
    )
    p.add_argument(
        "--no-copy-map",
        action="store_true",
        help="不拷贝 map 文件，直接使用 CryoSPARC 原始 map 路径",
    )
    return p.parse_args()


# ----------------------------
# 工具函数
# ----------------------------
def safe_dir(obj):
    """兼容 .dir 既可能是属性也可能是方法。"""
    d = obj.dir() if callable(obj.dir) else obj.dir
    return Path(d)


def choose_map_field(row, explicit=None):
    """从 dataset 的一行里自动选择 map 路径字段。"""
    keys = list(row.keys())
    if explicit:
        if explicit in keys:
            return explicit
        raise RuntimeError(f"指定的 map 字段 '{explicit}' 不在 keys 里: {keys}")

    preferred = [
        "map_sharp/path",
        "map/path",
        "map_half_A/path",
        "map_half_B/path",
    ]
    for k in preferred:
        if k in keys:
            return k

    for k in keys:
        if k.endswith("/path"):
            return k

    raise RuntimeError(f"没找到可用的 map path 字段, keys: {keys}")


# ----------------------------
# 主逻辑
# ----------------------------
def main():
    args = parse_args()

    # 1. 连接 CryoSPARC
    logger.info("Connecting to CryoSPARC at %s:%s", CS["host"], CS["base_port"])
    try:
        cs = CryoSPARC(**CS)
    except Exception as e:
        logger.exception("无法连接/登录 CryoSPARC: %s", e)
        sys.exit(1)

    # 2. 获取 Project / Job
    project = cs.find_project(args.project)
    if project is None:
        logger.error("找不到 Project: %s", args.project)
        sys.exit(1)

    job = cs.find_job(args.project, args.job)
    if job is None:
        logger.error("找不到 Job: project=%s, job=%s", args.project, args.job)
        sys.exit(1)

    logger.info("Using %s / %s (%s)", project.uid, job.uid, job.type)

    # 3. 读取 volume dataset
    try:
        ds = job.load_output(args.volume_output)
    except Exception as e:
        logger.exception("读取 Job %s 的输出 '%s' 失败: %s", job.uid, args.volume_output, e)
        sys.exit(1)

    if len(ds) == 0:
        logger.error("Job %s 的输出 '%s' 是空的", job.uid, args.volume_output)
        sys.exit(1)

    logger.info("输出 '%s' 中共有 %d 行", args.volume_output, len(ds))

    # 4. 选择 dataset 行
    if not (0 <= args.row_index < len(ds)):
        logger.error(
            "row-index=%d 超出范围 (共有 %d 行)", args.row_index, len(ds)
        )
        sys.exit(1)

    row = ds[args.row_index]
    logger.info("使用第 %d 行数据", args.row_index)

    # 5. 选择 map 字段
    try:
        map_field = choose_map_field(row, explicit=args.map_field)
    except Exception as e:
        logger.exception("自动选择 map 字段失败: %s", e)
        sys.exit(1)

    map_rel_path = row[map_field]
    logger.info("选择 map 字段: %s = %s", map_field, map_rel_path)

    # 解析 map 的绝对路径
    try:
        # 注意这里用 project_dir，而不是 job_dir
        project_dir = safe_dir(project)
        map_rel_path = Path(map_rel_path)
        if map_rel_path.is_absolute():
            map_path = map_rel_path.resolve()
        else:
            map_path = (project_dir / map_rel_path).resolve()
    except Exception as e:
        logger.exception("解析 map 路径失败: %s", e)
        sys.exit(1)

    if not map_path.exists():
        logger.error("找不到 map 文件: %s", map_path)
        sys.exit(1)

    logger.info("解析后的 map 路径: %s", map_path)

    # 6. 准备 CryoAtom 工作目录
    if args.out_dir:
        work_dir = Path(args.out_dir)
    else:
        work_dir = project_dir / f"cryoatom_{project.uid}_{job.uid}"

    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("CryoAtom 工作目录: %s", work_dir)

    # 7. 准备输入文件
    fasta_path = Path(args.fasta)
    if not fasta_path.exists():
        logger.error("找不到 FASTA 文件: %s", fasta_path)
        sys.exit(1)

    fasta_in = work_dir / "input.fasta"
    shutil.copy2(fasta_path, fasta_in)
    logger.info("已拷贝 FASTA 到: %s", fasta_in)

    if args.no_copy_map:
        map_in = map_path
        logger.info("不拷贝 map 文件，直接使用: %s", map_in)
    else:
        map_in = work_dir / "input_map.mrc"
        shutil.copy2(map_path, map_in)
        logger.info("已拷贝 map 到: %s", map_in)

    out_dir = work_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("输出目录: %s", out_dir)

    # 8. 构建 CryoAtom 命令
    cmd = [
        "cryoatom",
        "build",
        "-s",
        str(fasta_in),
        "-v",
        str(map_in),
        "-o",
        str(out_dir),
    ]
    if args.gpu is not None:
        cmd += ["-d", f"cuda:{args.gpu}"]

    logger.info("将执行 CryoAtom 命令：%s", " ".join(cmd))

    # 9. 运行 CryoAtom —— 这里用 check=True
    subprocess.run(
        cmd,
        cwd=str(work_dir),
        check=True,  # 如果退出码非 0，会抛 CalledProcessError
    )

    # 10. 简单列一下输出
    cif = out_dir / "out.cif"
    cif_raw = out_dir / "out_raw.cif"

    logger.info("----------------------------------------------------------------------")
    logger.info("CryoAtom 运行完成。主要输出：")
    logger.info(
        "  过滤 FASTA 后的模型: %s %s",
        cif,
        "(存在)" if cif.exists() else "(未找到)",
    )
    logger.info(
        "  Raw 模型（包含更多 map 区域）: %s %s",
        cif_raw,
        "(存在)" if cif_raw.exists() else "(未找到)",
    )
    logger.info("----------------------------------------------------------------------")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        # CryoAtom 命令失败时会走到这里
        logger.error(
            "CryoAtom 进程失败 (退出码 %s)。命令: %s",
            e.returncode,
            " ".join(e.cmd) if isinstance(e.cmd, (list, tuple)) else e.cmd,
        )
        sys.exit(e.returncode)
    except Exception:
        # 其他未捕获异常
        logger.exception("程序运行过程中出现未处理异常")
        sys.exit(1)
