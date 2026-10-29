"""Private subprocess entry point; never contacts remote services."""

import json
from pathlib import Path
import sys


def main():
    import numpy as np
    from PIL import Image
    import rapidocr
    from rapidocr import RapidOCR

    models = Path(rapidocr.__file__).parent / "models"
    names = {"Det": "PP-OCRv6_det_small.onnx", "Rec": "PP-OCRv6_rec_small.onnx",
             "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx"}
    if any(not (models / name).is_file() for name in names.values()):
        raise RuntimeError("Install the complete rapidocr==3.10.0 wheel, including models")
    parameters = {f"{kind}.model_path": str(models / name) for kind, name in names.items()}
    parameters.update({"Global.log_level": "error", "Global.max_side_len": 3508, "Global.use_cls": False,
                       "Det.limit_side_len": 1600, "Det.limit_type": "max",
                       "EngineConfig.onnxruntime.intra_op_num_threads": 4,
                       "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    engine = RapidOCR(params=parameters)
    with Image.open(sys.argv[1]) as image:
        pixels = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    result = engine(pixels, return_word_box=True)
    values = []
    if result.boxes is not None:
        for line_box,line_text,line_score,words in zip(result.boxes,result.txts,result.scores,result.word_results):
            # Keep the detector's complete baseline. Character boxes are only
            # used downstream when a line crosses a detected form control.
            values.append({"text":line_text,"confidence":float(line_score)*100,"box":line_box.tolist(),
                           "words":[{"text":word[0],"confidence":float(word[1])*100,
                                     "box":np.asarray(word[2]).tolist()} for word in words]})
    Path(sys.argv[2]).write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
