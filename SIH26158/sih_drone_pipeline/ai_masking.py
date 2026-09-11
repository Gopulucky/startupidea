from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


DYNAMIC_CLASSES = {
    "person", "bicycle", "car", "motorcycle", "bus", "train", "truck",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear",
}


def mask_dynamic_objects(images_dir: str | Path, masks_dir: str | Path, model_name: str = "yolov8n-seg.pt") -> dict:
    """Create COLMAP feature masks using a lightweight segmentation model.

    White pixels remain eligible for features; detected people, vehicles and
    animals are blacked out so they cannot distort the static-scene solve.
    """
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError("AI masking requires `pip install ultralytics`") from error

    images_dir, masks_dir = Path(images_dir), Path(masks_dir)
    masks_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(images_dir.glob("*.jpg"))
    model = YOLO(model_name)
    masked_frames, instances = 0, 0
    for image_path, result in zip(
        images,
        model.predict([str(path) for path in images], imgsz=640, device=0, verbose=False, stream=True),
    ):
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        height, width = image.shape[:2]
        keep = np.full((height, width), 255, dtype=np.uint8)
        if result.masks is not None and result.boxes is not None:
            frame_instances = 0
            for class_id, raw_mask in zip(result.boxes.cls.int().tolist(), result.masks.data.cpu().numpy()):
                if result.names[int(class_id)] not in DYNAMIC_CLASSES:
                    continue
                resized = cv2.resize(raw_mask, (width, height), interpolation=cv2.INTER_LINEAR) > 0.35
                keep[resized] = 0
                frame_instances += 1
            if frame_instances:
                keep = cv2.erode(keep, np.ones((9, 9), np.uint8), iterations=1)
                masked_frames += 1
                instances += frame_instances
        cv2.imwrite(str(masks_dir / f"{image_path.name}.png"), keep)
    return {"model": model_name, "frames": len(images), "masked_frames": masked_frames, "dynamic_instances": instances}
