# Downloads Hunyuan3D-2 texture models (delight + paint v2-0) into D:\conda\hf. Resumable.
# Symlinks are forced off: this Windows account cannot create them (WinError 1314).
$env:HF_HOME = 'D:\conda\hf'; $env:TMP = 'D:\conda\tmp'; $env:TEMP = 'D:\conda\tmp'
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$py = 'D:\conda\envs\sf3d\python.exe'
& $py -c @"
import huggingface_hub.file_download as fd
fd.are_symlinks_supported = lambda *a, **k: False
from huggingface_hub import snapshot_download
p = snapshot_download('tencent/Hunyuan3D-2', max_workers=3,
    allow_patterns=['hunyuan3d-delight-v2-0/*', 'hunyuan3d-paint-v2-0/*'],
    # fp16 safetensors only where a .bin duplicate exists; keep the text encoder (.bin only)
    ignore_patterns=['*/unet/diffusion_pytorch_model.bin', '*/vae/diffusion_pytorch_model.bin', '*.ckpt', '*.onnx', '*.msgpack'])
print('TEXWEIGHTS_DONE', p)
"@
