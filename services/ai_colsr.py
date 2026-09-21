import os
import json
import sys
import torch
import cv2
import numpy as np
from PIL import Image
import torchvision.transforms.functional as F

from transformers.modeling_utils import ModuleUtilsMixin

if not hasattr(ModuleUtilsMixin, 'get_head_mask'):
    if hasattr(ModuleUtilsMixin, '_get_head_mask'):
        ModuleUtilsMixin.get_head_mask = ModuleUtilsMixin._get_head_mask
    else:
        def dummy_get_head_mask(self, head_mask, num_hidden_layers, is_attention_chunked=False):
            if head_mask is not None:
                return [head_mask] * num_hidden_layers
            return [None] * num_hidden_layers
        ModuleUtilsMixin.get_head_mask = dummy_get_head_mask

if hasattr(ModuleUtilsMixin, 'get_extended_attention_mask'):
    _original_ext_mask = ModuleUtilsMixin.get_extended_attention_mask
    def patched_ext_mask(self, attention_mask, input_shape, *args, **kwargs):
        if len(args) > 0 and (isinstance(args[0], torch.device) or isinstance(args[0], str)):
            args = () 
        
        if 'dtype' in kwargs and (isinstance(kwargs['dtype'], torch.device) or isinstance(kwargs['dtype'], str)):
            kwargs['dtype'] = None
            
        kwargs.pop('device', None)
        
        return _original_ext_mask(self, attention_mask, input_shape, *args, **kwargs)
        
    ModuleUtilsMixin.get_extended_attention_mask = patched_ext_mask

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COLSR_MAIN_DIR = os.path.abspath(os.path.join(BASE_DIR, '../../CoLSR_main'))

if COLSR_MAIN_DIR not in sys.path:
    sys.path.append(COLSR_MAIN_DIR)

# CoLSR 내부 모듈 Import
try:
    from util.slconfig import SLConfig
    from util.utils import clean_state_dict
    from models.registry import MODULE_BUILD_FUNCS
except ImportError as e:
    print(f"[CoLSR Error] CoLSR 모듈을 불러오지 못했습니다. 경로를 확인하세요: {e}")

CONFIG_PATH = os.path.join(COLSR_MAIN_DIR, "results/config_args_all.json")
WEIGHT_PATH = os.path.join(COLSR_MAIN_DIR, "results/checkpoint_best_regular.pth")
BERT_PATH = os.path.join(COLSR_MAIN_DIR, "checkpoints/bert-base-uncased")
CLASSES = ["circular scissor handle"]
CAPTION = "circular scissor handle ."

class CoLSRPredictor:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.score_threshold = 0.5
        self._load_model()

    def _load_model(self):
        if not os.path.exists(WEIGHT_PATH):
            print(f"[CoLSR Warning] 가중치 파일이 없습니다: {WEIGHT_PATH}")
            return
            
        print(f"[CoLSR] {self.device} 환경에서 모델을 불러오는 중입니다...")
        
        try:
            with open(CONFIG_PATH, 'r') as f:
                args_dict = json.load(f)

            class Args: pass
            args = Args()
            for k, v in args_dict.items():
                setattr(args, k, v)

            args.text_encoder_type = BERT_PATH
            args.device = self.device
            args.eval = True
                
            build_func = MODULE_BUILD_FUNCS.get(args.modelname)
            self.model, self.criterion, self.postprocessors = build_func(args)
            
            checkpoint = torch.load(WEIGHT_PATH, map_location="cpu", weights_only=False)
            self.model.load_state_dict(clean_state_dict(checkpoint['model']), strict=False)
            
            self.model.to(self.device)
            self.model.eval()
            print("[CoLSR] 모델 로드 완료.")
            
        except Exception as e:
            print(f"[CoLSR Error] 모델 로드 중 오류 발생: {e}")

    def predict(self, image_path: str) -> list:
        if self.model is None:
            return []

        results = []
        try:
            # 1. 이미지 로드 및 Tensor 변환
            image = Image.open(image_path).convert("RGB")
            width, height = image.size
            
            img_tensor = F.to_tensor(image)
            img_tensor = F.normalize(img_tensor, mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            # 배치 차원 추가: (1, C, H, W)
            img_tensor = img_tensor.unsqueeze(0).to(self.device)

            # 2. 모델 추론 입력 인자 준비
            exemplars = [torch.empty((0, 4), dtype=torch.float32, device=self.device)]
            labels_uncropped = [torch.empty((0,), dtype=torch.int64, device=self.device)]
            captions = [CAPTION]

            # 3. 추론 실행
            with torch.no_grad():
                outputs = self.model(img_tensor, exemplars, labels_uncropped, captions=captions)

                logits = outputs['pred_logits'].sigmoid()[0] 
                boxes = outputs['pred_boxes'][0]             

                # 4. 결과 후처리 (Threshold 필터링)
                scores, labels = logits.max(dim=-1)
                mask = scores >= self.score_threshold
                
                kept_boxes = boxes[mask]
                kept_scores = scores[mask]
                kept_labels = labels[mask]

                # 5. 좌표 복원 및 JSON 직렬화 포맷 구성
                for box, score, label in zip(kept_boxes, kept_scores, kept_labels):
                    cx_norm, cy_norm, w_norm, h_norm = box.tolist()
                    
                    # 정규화된(0~1) 중심점 좌표를 원본 이미지 스케일로 복원
                    x = int(cx_norm * width)
                    y = int(cy_norm * height)
                    
                    label_idx = int(label.item())
                    class_name = "Hemostat"

                    results.append({
                        "class_name": class_name,
                        "x": x,
                        "y": y,
                        "confidence": float(score.item())
                    })

        except Exception as e:
            print(f"[CoLSR Inference Error] 추론 중 오류 발생: {e}")

        return results

_colsr_instance = None

def get_colsr_predictor():
    global _colsr_instance
    if _colsr_instance is None:
        _colsr_instance = CoLSRPredictor()
    return _colsr_instance