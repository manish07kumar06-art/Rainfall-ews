"""Optional: estimate water depth from a still frame using geometry priors.

This is the computer-vision *contract*, not a fake YOLOv8 weight file.

Production path:
  1. Label traffic-cam frames (tyre bbox, waterline, streetlight).
  2. Train YOLOv8n on that set (`yolo detect train data=cctv.yaml model=yolov8n.pt`).
  3. depth_m = tyre_submerged_frac * typical_tyre_m  (Mumbai cars ~0.65 m).
  4. POST the observation; impact_engine treats it as a virtual gauge.

Until (2) exists, impact snapshots already emit the same JSON from the
inundation field at each camera pose (see backend/impact_engine.py).

If ultralytics is installed and models/yolov8n_flood.pt exists, this script
will run a detector. Otherwise it prints the labelled-data recipe.
"""
from pathlib import Path

MODEL = Path(__file__).resolve().parent.parent / "models" / "yolov8n_flood.pt"
TYRE_M = 0.65


def depth_from_tyre_fraction(frac: float) -> float:
    return round(max(0.0, frac) * TYRE_M, 2)


def main():
    print("CCTV virtual-sensor contract")
    print("  depth_m = tyre_submerged_frac * 0.65")
    print("  payload: {id, water_depth_m, tyre_submerged_frac, status}")
    if MODEL.exists():
        try:
            from ultralytics import YOLO  # type: ignore
            print("  weights found:", MODEL)
            YOLO(str(MODEL))
            print("  ultralytics loaded — run detect on a frame directory next.")
        except ImportError:
            print("  weights present but ultralytics is not installed.")
    else:
        print("  no", MODEL.name, "yet — dashboard uses fused inundation at camera pose.")
        print("  collect 300–500 monsoon frames, label tyres, then train yolov8n.")


if __name__ == "__main__":
    main()
