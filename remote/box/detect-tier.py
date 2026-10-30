#!/usr/bin/env python3
"""
Pick the AI settings for the hardware this runs on, so nobody has to edit ai.env.

    python3 -I box/detect-tier.py            print the tier and write ../ai.box.env
    python3 -I box/detect-tier.py --dry-run  print only

ai.sh loads ai.box.env after ai.env, so these values win; `./ai.sh up auto` also takes
the profile (gpu or cpu) from it. Delete ai.box.env to go back to ai.env alone.

The tiers follow the measurements in README.md ("Simulating laptop tiers"): Gemma 4 E4B
is the batch model everywhere (bigger models gained nothing on KPI's short tasks), so
what changes is GPU vs CPU, the Whisper model, threads and the memory cap. The agent
model (agents/agents.env) is only reported here: gpt-oss-120b needs ~63 GB.
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'ai.box.env')

KOBO_RESERVE_GB = 8      # Kobo stack ~4-6 GB, plus the OS
MIN_AI_RAM_GB = 16       # below this, run Kobo without AI
NVIDIA_MIN_VRAM_GB = 7   # E4B Q4_0 + whisper turbo measured at 6.3 GB
AGENT_MODEL_GB = 70      # gpt-oss-120b, 62.8 GB measured, plus context


def ram_gb():
    with open('/proc/meminfo') as f:
        for line in f:
            if line.startswith('MemTotal:'):
                return int(line.split()[1]) / 1024 / 1024
    return 0


def physical_cores():
    """Cores, not hyperthreads: llama.cpp and whisper.cpp run best with one thread per core."""
    cores = set()
    for path in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/topology/core_id'):
        cpu = os.path.dirname(os.path.dirname(path))
        try:
            with open(path) as f:
                core = f.read().strip()
            with open(os.path.join(cpu, 'topology', 'physical_package_id')) as f:
                pkg = f.read().strip()
        except OSError:
            continue
        cores.add((pkg, core))
    return len(cores) or os.cpu_count() or 1


def nvidia_vram_gb():
    if not shutil.which('nvidia-smi'):
        return 0
    try:
        out = subprocess.run(['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    return max((int(x) for x in out.split() if x.isdigit()), default=0) / 1024


def amd_gpu():
    for path in glob.glob('/sys/class/drm/card*/device/vendor'):
        with open(path) as f:
            if f.read().strip() == '0x1002':
                return True
    return False


def detect():
    ram, cores, vram, amd = ram_gb(), physical_cores(), nvidia_vram_gb(), amd_gpu()
    found = f'{ram:.0f} GB RAM, {cores} cores, ' + (
        f'NVIDIA GPU {vram:.0f} GB' if vram else 'AMD GPU' if amd else 'no GPU')
    notes = []
    env = {'LLM_MODEL': 'gemma-4-E4B-it-Q4_0.gguf', 'LLM_MMPROJ': '',
           'LLM_THREADS': cores, 'WHISPER_THREADS': cores}

    if ram < MIN_AI_RAM_GB:
        return found, 'kobo-only', {'AI_PROFILE': 'none'}, [
            f'Under {MIN_AI_RAM_GB} GB RAM: KoboToolbox runs, the AI features stay off.']

    mem_cap = int(ram - KOBO_RESERVE_GB)
    if vram >= NVIDIA_MIN_VRAM_GB:
        tier = 'gpu'
        env.update(AI_PROFILE='gpu', LLM_NGL=99, WHISPER_MODEL='ggml-large-v3-turbo-q8_0.bin')
    else:
        tier = 'cpu'
        if vram:
            notes.append(f'The NVIDIA GPU has {vram:.0f} GB, under the {NVIDIA_MIN_VRAM_GB} GB '
                         'the models need together: running on the CPU.')
        if amd:
            # Strix Halo is the recommended box; its llama.cpp Vulkan/ROCm build is a W5
            # item. Until then the CPU profile works on it, slower.
            notes.append('AMD GPU found, but the Vulkan/ROCm profile is not built yet (PLAN W5): '
                         'running on the CPU.')
        env.update(AI_PROFILE='cpu',
                   # Turbo on fewer than 8 cores is slower than real time on long clips
                   WHISPER_MODEL='ggml-large-v3-turbo-q8_0.bin' if cores >= 8 else 'ggml-medium-q5_0.bin')
        if cores < 8:
            notes.append('Under 8 cores: Whisper medium (faster, a little less accurate).')
    env.update(AI_MEM_LIMIT=f'{mem_cap}g', AI_CPUS=os.cpu_count() or cores)

    agent_mem = vram if vram else (ram - KOBO_RESERVE_GB if amd else 0)
    notes.append('Agent model: gpt-oss-120b fits.' if agent_mem >= AGENT_MODEL_GB else
                 'Agent model: too small for gpt-oss-120b; agents need the recommended box '
                 '(or Gemma 4 26B-A4B for questions only, PLAN 3e).')
    return found, tier, env, notes


def main():
    found, tier, env, notes = detect()
    print(f'Found: {found}\nTier: {tier}')
    for note in notes:
        print(f'  - {note}')
    lines = ['# Written by box/detect-tier.py for this machine; overrides ai.env.',
             f'# {found} -> {tier}']
    lines += [f'{k}={v}' for k, v in env.items()]
    if '--dry-run' in sys.argv:
        print('\n'.join(lines[2:]))
        return
    with open(OUT, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'Wrote {os.path.normpath(OUT)}')


if __name__ == '__main__':
    main()
