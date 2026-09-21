import os
import torch
from rfdetr import RFDETRSmall

PTH_PATH = "static/ai_model/rf-detr.pth"

CLASS_NAMES = ['forceps', 'hand_instrument', 'retractor', 'trocar', 'scalpel', 'frazier', 'Hemostat_bundle']
CONFIDENCE_THRESHOLD = 0.5

class RFDETRPredictor:
    def __init__(self):
        self.class_names = CLASS_NAMES
        self.conf_thresh = CONFIDENCE_THRESHOLD
        
        self._load_model()

    def _load_model(self):
        print("Loading RF-DETR model...")
        if not os.path.exists(PTH_PATH):
            print(f"Warning: Model file not found at {PTH_PATH}")
            self.model = None
            return

        self.model = RFDETRSmall(pretrain_weights=PTH_PATH, num_classes=len(self.class_names))
            
        print("RF-DETR model loaded successfully.")

    def predict(self, image_path: str) -> list:
        if self.model is None:
            print("Model is not loaded. Returning empty detections.")
            return []

        detections = self.model.predict(image_path)
        
        results = []
        if detections is not None and len(detections) > 0:
            for bbox, conf, cls_id in zip(detections.xyxy, detections.confidence, detections.class_id):
                if conf >= self.conf_thresh:
                    results.append({
                        "class_name": self.class_names[int(cls_id)],
                        "confidence": float(conf),
                        "bbox": [float(x) for x in bbox]
                    })
        print(f"Predictions for {image_path}: {results}")
        return results

_predictor_instance = None

def get_predictor():
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = RFDETRPredictor()
    return _predictor_instance