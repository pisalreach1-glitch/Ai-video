"""Probe system hardware, GPU, VRAM, RAM, and Python CUDA environment."""
import sys
import os
import platform
import psutil

def probe():
    print("=== SYSTEM & HARDWARE PROBE ===")
    print(f"OS: {platform.system()} {platform.release()} ({platform.version()})")
    print(f"Architecture: {platform.machine()}")
    print(f"Python: {sys.version}")

    # System Memory (RAM)
    vm = psutil.virtual_memory()
    total_ram_gb = vm.total / (1024 ** 3)
    avail_ram_gb = vm.available / (1024 ** 3)
    print(f"System RAM: Total {total_ram_gb:.2f} GB | Available {avail_ram_gb:.2f} GB ({vm.percent}% used)")

    # PyTorch and CUDA in current environment
    try:
        import torch
        print(f"\nPyTorch Version: {torch.__version__}")
        print(f"CUDA Available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            print(f"CUDA Device Count: {device_count}")
            for i in range(device_count):
                props = torch.cuda.get_device_properties(i)
                total_vram_gb = props.total_memory / (1024 ** 3)
                free_vram_gb = torch.cuda.mem_get_info(i)[0] / (1024 ** 3)
                print(f"  GPU {i}: {props.name}")
                print(f"    Compute Capability: {props.major}.{props.minor}")
                print(f"    Total VRAM: {total_vram_gb:.2f} GB")
                print(f"    Free VRAM: {free_vram_gb:.2f} GB")
                print(f"    Multi-processor count: {props.multi_processor_count}")
        else:
            print("  No CUDA device detected in this Python environment.")
    except ImportError:
        print("PyTorch is not installed in this environment.")

    # Check nvidia-smi if available
    print("\n=== NVIDIA-SMI OUTPUT ===")
    import subprocess
    try:
        smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=5)
        if smi.returncode == 0:
            print(smi.stdout.strip())
        else:
            print(f"nvidia-smi exited with code {smi.returncode}: {smi.stderr}")
    except Exception as e:
        print(f"Could not run nvidia-smi: {e}")

if __name__ == "__main__":
    probe()
