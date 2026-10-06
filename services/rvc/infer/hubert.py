import logging
from functools import lru_cache
from pathlib import Path

import torch
from torch import nn
from transformers import AutoFeatureExtractor, HubertModel

try:
    from tools.cuda_graph import run_cuda_graph
except Exception:
    import importlib.util
    _cg_path = Path(__file__).resolve().parent.parent / "tools" / "cuda_graph.py"
    _spec = importlib.util.spec_from_file_location("rvc_cuda_graph", _cg_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    run_cuda_graph = _mod.run_cuda_graph


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent



logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class HubertModelWithFinalProj(HubertModel):
    def __init__(self, config):
        super().__init__(config)
        self.final_proj = nn.Linear(config.hidden_size, config.classifier_proj_size)


def load_hubert_model(device, is_half=False):
    """Load the official ContentVec model for RVC."""
    dtype = torch.float16 if is_half else torch.float32
    model = HubertModel.from_pretrained("lengyue233/content-vec-best", torch_dtype=dtype)
    model = model.to(device)
    return model.eval()


def hubert_audio_requires_normalization():
    return False


def extract_hubert_features(model, source, version, padding_mask=None):
    attention_mask = None
    if padding_mask is not None and bool(torch.any(padding_mask).item()):
        attention_mask = (~padding_mask.bool()).long()

    if version == "v1":
        if attention_mask is None:
            def forward(input_values):
                outputs = model(
                    input_values=input_values,
                    attention_mask=None,
                    output_hidden_states=True,
                    return_dict=True,
                )
                return model.final_proj(outputs.hidden_states[9])

            return run_cuda_graph(model, "hubert-v1-no-mask", forward, source)

        def forward(input_values, mask):
            outputs = model(
                input_values=input_values,
                attention_mask=mask,
                output_hidden_states=True,
                return_dict=True,
            )
            return model.final_proj(outputs.hidden_states[9])

        return run_cuda_graph(
            model, "hubert-v1-mask", forward, source, attention_mask
        )

    if attention_mask is None:
        def forward(input_values):
            return model(
                input_values=input_values,
                attention_mask=None,
                output_hidden_states=False,
                return_dict=True,
            ).last_hidden_state

        return run_cuda_graph(model, "hubert-v2-no-mask", forward, source)

    def forward(input_values, mask):
        return model(
            input_values=input_values,
            attention_mask=mask,
            output_hidden_states=False,
            return_dict=True,
        ).last_hidden_state

    return run_cuda_graph(model, "hubert-v2-mask", forward, source, attention_mask)
