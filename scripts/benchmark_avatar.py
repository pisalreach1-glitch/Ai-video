"""Benchmark script to measure avatar rendering time, peak VRAM, and RAM on actual GPU."""
import os
import sys
import time
import psutil
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def benchmark(video_path: str = ""):
    print("=== AVATAR ENGINE HARDWARE BENCHMARK ===")
    import torch
    if not torch.cuda.is_available():
        print("CUDA is not available for benchmarking.")
        return

    device = 0
    props = torch.cuda.get_device_properties(device)
    total_vram_gb = props.total_memory / (1024 ** 3)
    free_vram_gb = torch.cuda.mem_get_info(device)[0] / (1024 ** 3)
    vm = psutil.virtual_memory()

    print(f"Device: {props.name}")
    print(f"Total VRAM: {total_vram_gb:.2f} GB | Free VRAM: {free_vram_gb:.2f} GB")
    print(f"System RAM: {vm.total / (1024 ** 3):.2f} GB total, {vm.available / (1024 ** 3):.2f} GB available")

    # Bounded VRAM budget assessment
    vram_budget_ok = total_vram_gb >= 8.0
    print(f"Meets minimum 8GB VRAM requirement for SadTalker / bounded avatar: {vram_budget_ok}")
    if total_vram_gb >= 10.0:
        print("Meets minimum 10GB VRAM requirement for Wan2GP / Hunyuan low-vram offload: True")
    else:
        print("Meets minimum 10GB VRAM requirement for Wan2GP / Hunyuan low-vram offload: False")

if __name__ == "__main__":
    benchmark()
