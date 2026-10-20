#!/bin/bash
# UniRig step 2+3: skinning (input = the skeleton FBX of step 1) and merge back onto the textured original.
# Usage: run_skin_merge.sh <name>
name="${1:-model}"
cd "/d/My projects/SF3D/unirig-src" || exit 1
bash launch/inference/generate_skin.sh \
    --input "/d/conda/rig/out/${name}_skel.fbx" \
    --output "/d/conda/rig/out/${name}_skin.fbx" \
    --output_dir "/d/conda/rig/out"
echo "SKIN_EXIT=$?"
bash launch/inference/merge.sh \
    --source "/d/conda/rig/out/${name}_skin.fbx" \
    --target "/d/conda/rig/in/${name}.glb" \
    --output "/d/conda/rig/out/${name}_rigged.glb"
echo "MERGE_EXIT=$?"
