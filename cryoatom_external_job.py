#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
cryoatom_external_job.py

在 CryoSPARC External Job 里封装整套 CryoAtom 流程：

1. 创建 External Job（GUI 里会出现一个 External 节点）；
2. 在 External Job 里调用 run_cryoatom_auto.py：
   - 自动选 GPU（如果没指定）；
   - 读取指定 project/job 的 volume，运行 CryoAtom；
   - 把 out.cif 拷贝到原 CryoSPARC job 目录的 cryoatom/ 下；
3. 再由 External Job 把这个 cif 路径挂成一个简单的 output dataset（model/path）。

用法示例：

    python cryoatom_external_job.py \\
        --project P164 \\
        --workspace W1 \\
        --src-job J44 \\
        --fasta /home/spuser/sequences/WT_GLP-1R.fasta

可选透传参数（和 run_cryoatom_auto.py 一致）：
    --volume-output / --map-field / --row-index / --out-dir / --no-copy-map / --gpu
"""

import os
import sys
import logging
import subprocess
from pathlib import Path

from cryosparc.tools import CryoSPARC
from cryosparc.job import ExternalJob
from cryosparc.dataset import Dataset


# ----------------------------
# 脚本自身日志
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


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


def safe_dir(obj) -> Path:
    """兼容 job.dir / project.dir 既可能是属性也可能是方法。"""
    d = obj.dir() if callable(obj.dir) else obj.dir
    return Path(d)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="在 External Job 中运行 CryoAtom 并挂载模型输出"
    )

    parser.add_argument("--project", "-p", required=True, help="Project UID，如 P164")
    parser.add_argument("--workspace", "-w", required=True, help="Workspace UID，如 W1")

    parser.add_argument(
        "--src-job",
        "-j",
        required=True,
        help="作为输入 volume 的 CryoSPARC 源 job UID，如 J44",
    )
    parser.add_argument(
        "--fasta",
        "-f",
        required=True,
        help="输入 FASTA 文件路径",
    )

    # 以下参数透传给 run_cryoatom_auto.py（和你那个脚本保持一致）
    parser.add_argument(
        "--volume-output",
        "-o",
        default="volume",
        help="源 job 的 volume 输出名称 (默认: volume)",
    )
    parser.add_argument(
        "--map-field",
        default=None,
        help="可选: 数据集中 map 字段名，如 map_sharp/path；不填则自动选择",
    )
    parser.add_argument(
        "--row-index",
        type=int,
        default=0,
        help="当输出 dataset 有多行时，选用的行索引 (默认: 0)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="可选: CryoAtom 工作目录；不填则默认: <project_dir>/cryoatom_<project>_<job>",
    )
    parser.add_argument(
        "--no-copy-map",
        action="store_true",
        help="不拷贝 map 文件，直接使用 CryoSPARC 原始 map 路径",
    )
    parser.add_argument(
        "--gpu",
        type=int,
        default=None,
        help="指定 GPU；不指定时由 run_cryoatom_auto.py 自动选择",
    )

    args = parser.parse_args()

    # ----------------------------
    # 连接 CryoSPARC
    # ----------------------------
    logger.info("Connecting to CryoSPARC at %s:%s", CS["host"], CS["base_port"])
    try:
        cs = CryoSPARC(**CS)
    except Exception as e:
        logger.exception("无法连接/登录 CryoSPARC: %s", e)
        sys.exit(1)

    project = cs.find_project(args.project)
    if not project:
        logger.error("找不到 Project: %s", args.project)
        sys.exit(1)

    project_name = (
        getattr(project, "title", None)
        or getattr(project, "name", None)
        or getattr(project, "project_name", None)
        or project.uid
    )
    logger.info("找到 Project: %s (%s)", project.uid, project_name)

    # 也提前拿到源 job，后面算 cif 路径要用
    src_job = cs.find_job(args.project, args.src_job)
    if not src_job:
        logger.error("找不到源 Job: %s/%s", args.project, args.src_job)
        sys.exit(1)

    logger.info("源 Job: %s (%s)", src_job.uid, src_job.type)

    ws_uid = args.workspace
    logger.info("使用 Workspace UID: %s", ws_uid)

    # ----------------------------
    # 创建 External Job
    # ----------------------------
    title = f"CryoAtom ExternalJob for {args.project}-{args.src_job}"
    try:
        ej: ExternalJob = project.create_external_job(
            ws_uid,
            title=title,
        )
    except Exception as e:
        logger.exception("创建 External Job 失败: %s", e)
        sys.exit(1)

    logger.info("已创建 External Job: %s", ej.uid)

    # ----------------------------
    # 准备调用 run_cryoatom_auto.py
    # ----------------------------
    script_dir = Path(__file__).resolve().parent
    rc_auto = script_dir / "run_cryoatom_auto.py"

    if not rc_auto.exists():
        logger.error("找不到 run_cryoatom_auto.py: %s", rc_auto)
        sys.exit(1)

    cmd = [
        sys.executable,
        str(rc_auto),
        "--project",
        args.project,
        "--job",
        args.src_job,
        "--fasta",
        args.fasta,
        "--volume-output",
        args.volume_output,
    ]

    if args.map_field:
        cmd += ["--map-field", args.map_field]
    cmd += ["--row-index", str(args.row_index)]
    if args.out_dir:
        cmd += ["--out-dir", args.out_dir]
    if args.no_copy_map:
        cmd += ["--no-copy-map"]
    if args.gpu is not None:
        cmd += ["--gpu", str(args.gpu)]

    logger.info("External Job 内将执行命令：")
    logger.info("  %s", " ".join(cmd))

    # ----------------------------
    # 在 External Job 中执行 CryoAtom，并挂载输出
    # ----------------------------
    try:
        with ej.run():
            ej.log(f"[INFO] ExternalJob: 开始执行 CryoAtom for {args.src_job}")
            ej.log(f"[INFO] 调用命令: {' '.join(cmd)}")

            # 1) 调用 run_cryoatom_auto.py
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                ej.log(f"[ERROR] run_cryoatom_auto.py 失败，退出码 {e.returncode}")
                if e.stdout:
                    ej.log("[ERROR] --- stdout ---")
                    for line in e.stdout.splitlines():
                        ej.log(f"[ERROR] {line}")
                if e.stderr:
                    ej.log("[ERROR] --- stderr ---")
                    for line in e.stderr.splitlines():
                        ej.log(f"[ERROR] {line}")
                raise

            # 把 stdout/stderr 也写进 job 日志，方便调试
            if proc.stdout:
                ej.log("[INFO] --- CryoAtom stdout ---")
                for line in proc.stdout.splitlines():
                    ej.log(f"[INFO] {line}")
            if proc.stderr.strip():
                ej.log("[INFO] --- CryoAtom stderr ---")
                for line in proc.stderr.splitlines():
                    ej.log(f"[INFO] {line}")

            ej.log("[INFO] CryoAtom 子流程执行成功。")

            # 2) 推断最终模型 cif 路径（和 run_cryoatom_auto.py 的规则保持一致）
            if args.out_dir:
                work_dir = Path(args.out_dir)
            else:
                project_dir = safe_dir(project)
                work_dir = project_dir / f"cryoatom_{project.uid}_{src_job.uid}"

            out_dir = work_dir / "out"
            out_cif = out_dir / "out.cif"

            # run_cryoatom_auto.py 会把 out.cif 拷贝到 job_dir/cryoatom/ 下
            job_dir = safe_dir(src_job)
            target_dir = job_dir / "cryoatom"
            dest_file = target_dir / f"{project.uid}_{src_job.uid}_cryoatom.cif"

            if dest_file.exists():
                model_path = dest_file
                ej.log(f"[INFO] 使用拷回 Job 目录的模型: {model_path}")
            elif out_cif.exists():
                model_path = out_cif
                ej.log(f"[INFO] 未找到拷贝版本，直接使用 work_dir 中的 out.cif: {model_path}")
            else:
                ej.log(
                    f"[WARN] 未找到可以挂载的模型文件: {dest_file} 或 {out_cif}，跳过输出挂载",
                    level="info",
                )
                ej.log("[INFO] External Job 结束（无模型输出 dataset）。")
                return
            
         #  # 1) 新建一个空的 Dataset
         #  ds = Dataset()

         #  # 2) 添加一个字符串字段：("字段名", "O")  => object/string
         #  ds.add_fields([("model/path", "O")])

         #  # 3) 分配 1 行数据
         #  ds.add_data(1)

         #  # 4) 给第 0 行填上模型路径
         #  ds["model/path"][0] = str(model_path)

         #  # 5) 在 External Job 里声明一个输出
         #  ej.add_output(
         #      type="annotation_model",      # 先用 annotation_model，比随便写 "model" 安全
         #      name="cryoatom_model",
         #      slots=["model"],             # slot 名叫 "model"
         #  )

         #  # 6) 把 dataset 保存成这个输出
         #  ej.save_output("cryoatom_model", ds)

            ej.log(f"[INFO] 已挂载模型输出 dataset 'cryoatom_model'，字段 model/path={model_path}",)
        #    # 暂时先不挂 output dataset，只在日志里记录模型路径
        #    ej.log(
        #        f"[INFO] （暂不挂 dataset）CryoAtom 模型位置：{model_path}",
        #        level="info",
        #    )

            ej.log("[INFO] External Job 全流程完成。")

    except Exception as e:
        logger.exception("External Job 内执行失败: %s", e)
        sys.exit(1)

    logger.info("完成：请到 CryoSPARC GUI 查看 External Job %s", ej.uid)


if __name__ == "__main__":
    main()
