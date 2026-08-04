import os
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

# ---------------------------------------------------------
# 1. CoLSR-main 프로젝트 경로를 시스템에 추가
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 현재 파일(services/ai_colsr.py) 기준 최상위 폴더 밖의 CoLSR-main 폴더 지정
COLSR_MAIN_DIR = os.path.abspath(os.path.join(BASE_DIR, '../../CoLSR-main'))

if COLSR_MAIN_DIR not in sys.path:
    sys.path.append(COLSR_MAIN_DIR)

# CoLSR 내부 모듈 Import
try:
    from util.slconfig import SLConfig
    from util.utils import clean_state_dict
    from models.registry import MODULE_BUILD_FUNCS
except ImportError as e:
    print(f"[CoLSR Error] CoLSR 모듈을 불러오지 못했습니다. 경로를 확인하세요: {e}")

# ---------------------------------------------------------
# 2. 경로 및 하이퍼파라미터 설정
# ---------------------------------------------------------
CONFIG_PATH = os.path.join(COLSR_MAIN_DIR, "config/cfg_surgcount_vit_b.py")
WEIGHT_PATH = os.path.join(COLSR_MAIN_DIR, "results/checkpoint_best_regular.pth")
BERT_PATH = os.path.join(COLSR_MAIN_DIR, "checkpoints/bert-base-uncased")

# 탐지할 도구 클래스 정의 (RF-DETR과 동일하게 맞춤)
CLASSES = ["forceps", "hand_instrument", "retractor", "trocar"]
# GroundingDINO 모델의 텍스트 프롬프트 포맷: "class1 . class2 . class3 ."
CAPTION = " . ".join(CLASSES) + " ."

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
            # 1. 설정 파일(SLConfig) 로드 및 BERT 경로 덮어쓰기
            cfg = SLConfig.fromfile(CONFIG_PATH)
            cfg.text_encoder_type = BERT_PATH
            
            # Args 객체 모방 (모델 빌더가 argparse.Namespace 형태를 기대함)
            class Args: pass
            args = Args()
            for k, v in cfg._cfg_dict.to_dict().items():
                setattr(args, k, v)

            args.device = self.device
            args.eval = True
                
            # 2. 모델 구조 빌드
            build_func = MODULE_BUILD_FUNCS.get(args.modelname)
            self.model, self.criterion, self.postprocessors = build_func(args)
            
            # 3. 사전 학습된 가중치 로드
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
            # CoLSR(GroundingDINO)는 보통 RGB 형태의 정규화된 텐서를 입력으로 받습니다.
            image = Image.open(image_path).convert("RGB")
            width, height = image.size
            
            img_tensor = F.to_tensor(image)
            img_tensor = F.normalize(img_tensor, mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            # 배치 차원 추가: (1, C, H, W)
            img_tensor = img_tensor.unsqueeze(0).to(self.device)

            # 2. 모델 추론 입력 인자 준비
            exemplars = [torch.tensor([]).to(self.device)]
            labels_uncropped = [torch.tensor([0]).to(self.device)]
            captions = [CAPTION]

            # 3. 추론 실행
            with torch.no_grad():
                # outputs 딕셔너리에는 'pred_logits'와 'pred_boxes'가 포함됩니다.
                outputs = self.model(img_tensor, exemplars, labels_uncropped, captions=captions)

                logits = outputs['pred_logits'].sigmoid()[0] # Shape: (Num_Queries, 256)
                boxes = outputs['pred_boxes'][0]             # Shape: (Num_Queries, 4) -> [cx, cy, w, h] 정규화됨

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
                    
                    # 클래스 매핑 (BERT 텍스트 프롬프트 인덱스 기준)
                    label_idx = int(label.item())
                    # 인덱스가 범위를 벗어나는 경우 방어 로직
                    class_name = CLASSES[label_idx] if label_idx < len(CLASSES) else "hand_instrument"

                    results.append({
                        "class_name": class_name,
                        "x": x,
                        "y": y,
                        "confidence": float(score.item())
                    })

        except Exception as e:
            print(f"[CoLSR Inference Error] 추론 중 오류 발생: {e}")

        return results


# Singleton 인스턴스 (메모리에 한 번만 상주)
_colsr_instance = None

def get_colsr_predictor():
    global _colsr_instance
    if _colsr_instance is None:
        _colsr_instance = CoLSRPredictor()
    return _colsr_instance