"""硬件闸门：测量本机可承载的盘古模型档位。

判定原则：权重必须能被"显存 + 可用物理内存"容纳。若超出，mmap 会退化为
磁盘换页，单 token 耗时升到秒级，管线跑不动。因此体积是硬门槛，先于质量评估。

用法：
    python pangu/probe/hardware.py
    python pangu/probe/hardware.py --json pangu/reports/hardware.json

候选档位体积取自 HuggingFace 仓库的 LFS 元数据实测值（GiB），非估算。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import platform
import shutil
import subprocess
from pathlib import Path

GIB = 1024 ** 3
GIB_TO_GB = GIB / 1e9

# 安全余量：显存只用到 85%（留 KV cache 与计算缓冲），内存只用到 85%（留 OS 与其他进程）。
VRAM_HEADROOM = 0.85
RAM_HEADROOM = 0.85

# (家族, 量化档, 体积 GiB, 来源仓库, 备注)
CANDIDATES: list[tuple[str, str, float, str, str]] = [
    ("openPangu-2.0-Flash (92B-A6B)", "Q3_K_M", 40.7,
     "mrexodia/openPangu-2.0-Flash-GGUF", "MoE，6B 激活；用户指定的首选仓库"),
    ("openPangu-2.0-Flash (92B-A6B)", "Q4_K_M", 51.5,
     "mrexodia/openPangu-2.0-Flash-GGUF", "perplexity 3.46，质量更好"),
    ("openPangu-Ultra-MoE (718B)", "Int8", 718.0,
     "openpangu/openPangu-Ultra-MoE-718B-V1.1-Int8", "仅云端或数据中心"),
    ("openPangu-Embedded-7B-V1.1", "Q8_0", 7.95,
     "mradermacher/openPangu-Embedded-7B-V1.1-GGUF", "dense，近无损"),
    ("openPangu-Embedded-7B-V1.1", "Q5_K_M", 5.34,
     "mradermacher/openPangu-Embedded-7B-V1.1-GGUF", "dense"),
    ("openPangu-Embedded-7B-V1.1", "Q4_K_M", 4.59,
     "mradermacher/openPangu-Embedded-7B-V1.1-GGUF", "dense，本次主力档"),
    ("openPangu-Embedded-7B-V1.1", "Q3_K_M", 3.77,
     "mradermacher/openPangu-Embedded-7B-V1.1-GGUF", "dense，质量下限候选"),
    ("openPangu-Embedded-1B-V1.1", "Q4_K_M", 0.70,
     "mradermacher/openPangu-Embedded-1B-V1.1-GGUF", "dense，最小可用档"),
]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def read_system_memory_gib() -> tuple[float, float]:
    """返回（总物理内存 GiB，当前可用 GiB）。非 Windows 回退解析 /proc/meminfo。"""
    if platform.system() == "Windows":
        stat = _MemoryStatusEx()
        stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        if not ok:
            return 0.0, 0.0
        return stat.ullTotalPhys / GIB, stat.ullAvailPhys / GIB

    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return 0.0, 0.0
    values: dict[str, float] = {}
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = float(parts[0]) / 1024 / 1024  # kB → GiB
    return values.get("MemTotal", 0.0), values.get("MemAvailable", 0.0)


def read_gpus() -> list[dict[str, object]]:
    """通过 nvidia-smi 读取 NVIDIA 显卡名与显存；不可用时返回空列表。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.used,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []

    gpus: list[dict[str, object]] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[1].isdigit():
            continue
        gpus.append({
            "name": parts[0],
            "vram_mib": int(parts[1]),
            "vram_used_mib": int(parts[2]) if parts[2].isdigit() else 0,
            "driver": parts[3],
        })
    return gpus


def judge(size_gib: float, vram_gib: float, ram_gib: float,
          kv_overhead_gib: float = 1.0) -> tuple[str, str]:
    """返回（结论标签, 说明）。结论：GPU / MIXED / NO。

    kv_overhead_gib 为 8K 上下文下的 KV cache 与计算缓冲预留，不计入权重体积，
    但同样要占显存，否则会把"刚好装下"误判为"可以直跑"。
    """
    need_gb = (size_gib + kv_overhead_gib) * GIB_TO_GB
    if need_gb <= vram_gib * VRAM_HEADROOM:
        return "GPU", "权重与 KV cache 可全量驻留显存，单卡直跑"
    budget = vram_gib + ram_gib * RAM_HEADROOM
    if need_gb <= budget * 0.9:
        return "MIXED", "需显存+内存混合 offload，吞吐显著下降，须实测"
    return "NO", f"超出可用容量 {need_gb / (budget * 0.9):.1f} 倍，mmap 退化为磁盘换页"


def collect() -> dict[str, object]:
    total_ram, avail_ram = read_system_memory_gib()
    gpus = read_gpus()
    vram_gib = max((float(g["vram_mib"]) for g in gpus), default=0.0) / 1024

    disk_free = shutil.disk_usage(Path.cwd()).free / GIB

    rows: list[dict[str, object]] = []
    for family, quant, size_gib, repo, note in CANDIDATES:
        label, reason = judge(size_gib, vram_gib, total_ram)
        rows.append({
            "family": family,
            "quant": quant,
            "size_gib": size_gib,
            "size_gb": round(size_gib * GIB_TO_GB, 2),
            "repo": repo,
            "verdict": label,
            "reason": reason,
            "note": note,
        })

    return {
        "host": {
            "platform": platform.platform(),
            "cpu_count": __import__("os").cpu_count(),
            "gpus": gpus,
            "vram_gib": round(vram_gib, 2),
            "ram_total_gib": round(total_ram, 2),
            "ram_available_gib": round(avail_ram, 2),
            "disk_free_gib": round(disk_free, 2),
        },
        "candidates": rows,
    }


def render_markdown(report: dict[str, object]) -> str:
    host = report["host"]  # type: ignore[index]
    rows = report["candidates"]  # type: ignore[index]
    gpu_desc = ", ".join(
        f"{g['name']}（{g['vram_mib'] / 1024:.1f} GiB）" for g in host["gpus"]  # type: ignore[index]
    ) or "未检测到 NVIDIA 显卡"

    lines = [
        "| 项目 | 实测值 |",
        "| --- | --- |",
        f"| 显卡 | {gpu_desc} |",
        f"| 显存 | {host['vram_gib']} GiB |",  # type: ignore[index]
        f"| 总内存 | {host['ram_total_gib']} GiB |",  # type: ignore[index]
        f"| 当前可用内存 | {host['ram_available_gib']} GiB |",  # type: ignore[index]
        f"| 磁盘剩余 | {host['disk_free_gib']} GiB |",  # type: ignore[index]
        "",
        "| 模型家族 | 量化 | 体积 | 结论 | 依据 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:  # type: ignore[union-attr]
        lines.append(
            f"| {row['family']} | {row['quant']} | {row['size_gb']} GB "
            f"| {row['verdict']} | {row['reason']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="盘古模型档位的硬件可行性闸门")
    ap.add_argument("--json", default="", help="将完整结果写入指定 JSON 路径")
    args = ap.parse_args(argv)

    report = collect()
    print(render_markdown(report))

    feasible = [r for r in report["candidates"] if r["verdict"] != "NO"]  # type: ignore[index]
    print()
    if not feasible:
        print("结论：本机无法承载任何候选档位，本地部署不可行。")
        return 1

    # 选型不是"选最大"：能全量驻留显存的档位优先，因为 offload 档吞吐不可控。
    gpu_rows = [r for r in feasible if r["verdict"] == "GPU"]
    mixed_rows = [r for r in feasible if r["verdict"] == "MIXED"]
    best = max(gpu_rows or mixed_rows, key=lambda r: r["size_gb"])  # type: ignore[index]

    print(f"结论：可承载 {len(feasible)} 个档位；其中可全量驻留显存的有 "
          f"{len(gpu_rows)} 个。在可直跑的档位里质量最高的是 "
          f"{best['family']} {best['quant']}（{best['size_gb']} GB，{best['verdict']}）。")
    for row in mixed_rows:  # type: ignore[union-attr]
        print(f"      更大的 {row['family']} {row['quant']}（{row['size_gb']} GB）"
              f"只能混合 offload，吞吐不可控，不列为默认候选。")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
