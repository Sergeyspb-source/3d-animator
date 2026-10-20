#!/bin/bash
# UniRig step 1: skeleton prediction. Staged files live in space-free paths under /d/conda/rig.
# Uses the "lowmem" task (5 beams, fewer surface samples): the original needs more than 6 GB of VRAM on a 8 GB card
# and runs out of memory next to the Windows desktop; this one needs about 3.5 GB and gave the same skeleton.
# Usage: run_skel.sh <name> [faces_target_count] [seed]
name="${1:-model}"
faces="${2:-50000}"
seed="${3:-12345}"
cd "/d/My projects/SF3D/unirig-src" || exit 1
bash launch/inference/generate_skeleton.sh \
    --input "/d/conda/rig/in/${name}.glb" \
    --output "/d/conda/rig/out/${name}_skel.fbx" \
    --output_dir "/d/conda/rig/out" \
    --faces_target_count "${faces}" \
    --seed "${seed}" \
    --skeleton_task configs/task/quick_inference_skeleton_articulationxl_ar_256_lowmem.yaml
echo "SKEL_EXIT=$?"
