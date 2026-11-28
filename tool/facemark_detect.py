"""Face landmarks (MediaPipe Face Landmarker, 478 points, Apache 2.0) on pictures, for model_improve's face fit. Runs in
an environment of its own (mediapipe pins its numpy and protobuf; the app's stays apart): config.json "facemark_python"
(default D:/conda/envs/facemark/Scripts/python.exe), model "facemark_model" (default
D:/conda/models/mediapipe/face_landmarker.task, from storage.googleapis.com/mediapipe-models).
python facemark_detect.py <model.task> <out.json> <image> [<image> ...]
-> {image: [[x, y, z], ...] in the image's pixels (z in the x scale, towards the camera negative) or null}"""
import json
import sys

import mediapipe as mp
import numpy as np
from PIL import Image

opts = mp.tasks.vision.FaceLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path=sys.argv[1]), num_faces=1,
    min_face_detection_confidence=0.2, min_face_presence_confidence=0.2)
out = {}
with mp.tasks.vision.FaceLandmarker.create_from_options(opts) as det:
    for path in sys.argv[3:]:
        im = np.asarray(Image.open(path).convert("RGB"))
        H, W = im.shape[:2]
        r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(im)))
        if r.face_landmarks:
            out[path] = [[p.x * W, p.y * H, p.z * W] for p in r.face_landmarks[0]]
        else:
            out[path] = None
json.dump(out, open(sys.argv[2], "w"))
print({k.split("/")[-1]: (len(v) if v else None) for k, v in out.items()})
