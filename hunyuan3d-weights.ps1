# Downloads the Hunyuan3D-2mv shape models (multiview: the base one and the turbo one for «Fast shape», ~4.9 GB each)
# into D:\conda\hf. Resumable: just run again.
$env:HF_HOME = 'D:\conda\hf'; $env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$py = 'D:\conda\envs\sf3d\python.exe'   # sf3d env already has huggingface_hub
& $py -c @"
from huggingface_hub import snapshot_download
p = snapshot_download('tencent/Hunyuan3D-2mv',
    allow_patterns=['hunyuan3d-dit-v2-mv/config.yaml', 'hunyuan3d-dit-v2-mv/model.fp16.safetensors',
                    'hunyuan3d-dit-v2-mv-turbo/config.yaml', 'hunyuan3d-dit-v2-mv-turbo/model.fp16.safetensors',
                    '*.md', 'LICENSE*'])
print('WEIGHTS_DONE', p)
"@
