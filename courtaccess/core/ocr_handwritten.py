"""
courtaccess/core/ocr_handwritten.py

Handwritten text extraction from low-confidence OCR regions.
Uses Qwen2.5-VL (vision-language model) for regions where PaddleOCR
confidence falls below threshold.

STUB/REAL HYBRID:
  - Stub: returns empty result (no handwriting detected). Safe default.
  - Real: calls Qwen2.5-VL via HuggingFace transformers. GPU required.

PRODUCTION NOTES:
  - Only called for regions where ocr_printed confidence < 0.6.
  - Results are MERGED with printed OCR output by the pretranslation DAG.
  - Enable with USE_REAL_HANDWRITING_OCR=true + GPU container.

OUTPUT CONTRACT (per region):
  {
      "text":       str,
      "bbox":       [x0, y0, x1, y1],
      "confidence": float,   # 0.0-1.0
      "page":       int,
      "source":     "qwen2.5-vl" | "stub",
  }
"""

import os

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

_USE_REAL = str(os.getenv("USE_REAL_HANDWRITING_OCR")).lower() == "true"
_CONFIDENCE_THRESHOLD = 0.6  # Only process regions below this confidence


def extract_handwritten(
    image_path: str,
    low_confidence_regions: list[dict],
    page_num: int = 0,
) -> list[dict]:
    """
    Extract handwritten text from low-confidence OCR regions in a page image.

    Args:
        image_path:             Path to the rendered page PNG.
        low_confidence_regions: List of region dicts from ocr_printed with
                                confidence < CONFIDENCE_THRESHOLD.
        page_num:               Page index (0-based) for output metadata.

    Returns:
        List of region dicts matching OUTPUT CONTRACT above.
        Empty list if no regions provided or none processed.
    """
    if not low_confidence_regions:
        logger.debug("[HANDWRITING OCR] No low-confidence regions on page %d — skipping.", page_num)
        return []

    if _USE_REAL:
        return _real_extract(image_path, low_confidence_regions, page_num)
    return _stub_extract(low_confidence_regions, page_num)


def _stub_extract(regions: list[dict], page_num: int) -> list[dict]:
    """
    Stub: returns empty results. Handwriting OCR skipped in stub mode.
    All court forms from mass.gov are digital PDFs — no handwriting expected
    in the scraper pipeline. This stub is sufficient for Phase 2.
    """
    logger.debug(
        "[STUB HANDWRITING OCR] %d region(s) on page %d — returning empty (stub).",
        len(regions),
        page_num,
    )
    return []


def _real_extract(
    image_path: str,
    regions: list[dict],
    page_num: int,
) -> list[dict]:
    """
    Production handwriting extraction via Qwen2.5-VL.
    Crops each low-confidence region from the page image and runs VLM inference.

    REQUIRES:
        - GPU with >= 16GB VRAM
        - USE_REAL_HANDWRITING_OCR=true
        - Model weights at QWEN_VL_MODEL_PATH

    NOTE: NOT active in stub mode.
    """
    try:
        import torch
        from PIL import Image
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

        model_path = os.getenv("QWEN_VL_MODEL_PATH")
        processor = AutoProcessor.from_pretrained(model_path)
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        model.eval()

        full_image = Image.open(image_path).convert("RGB")
        results = []

        for region in regions:
            bbox = region.get("bbox", [0, 0, 100, 20])
            x0, y0, x1, y1 = [int(v) for v in bbox]
            cropped = full_image.crop((x0, y0, x1, y1))

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": cropped},
                        {"type": "text", "text": "Transcribe the handwritten text exactly as written."},
                    ],
                }
            ]
            text_input = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = processor(text=[text_input], images=[cropped], return_tensors="pt").to(model.device)

            with torch.no_grad():
                output_ids = model.generate(**inputs, max_new_tokens=128)
            generated = processor.batch_decode(output_ids, skip_special_tokens=True)[0]
            transcribed = generated.split("assistant")[-1].strip()

            results.append(
                {
                    "text": transcribed,
                    "bbox": bbox,
                    "confidence": 0.85,
                    "page": page_num,
                    "source": "qwen2.5-vl",
                }
            )
            logger.debug(
                "[REAL HANDWRITING OCR] Page %d region %s → '%s…'",
                page_num,
                bbox,
                transcribed[:30],
            )

        return results

    except Exception as exc:
        logger.error("[REAL HANDWRITING OCR] Failed: %s — returning empty.", exc)
        return []
