"""Export Whisper (large-v3-turbo) to ONNX for UbiClipper's DirectML engine.

Runs on a GitHub Linux machine (packaging/models workflow), not on users' PCs.

encoder.onnx   mel (B, n_mels, 3000) -> cross_k, cross_v (L, B, 1500, D)
decoder.onnx   tokens (B, T), self_k, self_v (L, B0, 448, D), cross_k, cross_v
               (L, 1, 1500, D), offset (1,), beam (B,) -> logits (B, T, V), self_k, self_v (updated),
               qk (B, A, T, 1500): raw cross-attention scores of the
               alignment heads, for word timestamps (the same signal
               openai-whisper and CTranslate2 use)

Weights, inputs and outputs are float16 (the files are about 1.3 GB + 0.4 GB);
--fp32 makes a float32 copy for checking.

    python export_whisper_onnx.py --model turbo --out whisper-turbo-onnx
"""

from __future__ import annotations

import argparse
import json
import os

import torch
import torch.nn as nn
import torch.nn.functional as F
import whisper


def attend(q, k, v, n_head, mask=None):
    """Whisper's attention, written out so the scores can be returned. k and v
    may have batch 1 (the audio, shared by all beams): it broadcasts."""
    b, t, d = q.shape
    kb, s = k.shape[0], k.shape[1]
    scale = (d // n_head) ** -0.25
    q = q.view(b, t, n_head, -1).permute(0, 2, 1, 3) * scale
    k = k.view(kb, s, n_head, -1).permute(0, 2, 3, 1) * scale
    v = v.view(kb, s, n_head, -1).permute(0, 2, 1, 3)
    qk = q @ k                                  # (B, H, T, S)
    if mask is not None:
        qk = qk + mask
    w = F.softmax(qk.float(), dim=-1).to(q.dtype)
    out = (w @ v).permute(0, 2, 1, 3).reshape(b, t, d)
    return out, qk


class Encoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.encoder = model.encoder
        self.blocks = model.decoder.blocks

    def forward(self, mel):
        x = self.encoder(mel)
        ks = [blk.cross_attn.key(x) for blk in self.blocks]
        vs = [blk.cross_attn.value(x) for blk in self.blocks]
        return torch.stack(ks), torch.stack(vs)


class Decoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.dec = model.decoder
        self.n_head = model.dims.n_text_head
        heads = model.alignment_heads.to_dense().nonzero().tolist()
        self.heads = [(int(l), int(h)) for l, h in heads]

    def forward(self, tokens, self_k, self_v, cross_k, cross_v, offset, beam):
        # Only tensor ops on `offset` (no Python ints), so the exported graph
        # works for any offset: new keys/values are scattered into the fixed
        # 448-slot cache and attention masks out the slots not written yet.
        # `beam` picks (and repeats) cache rows for beam search, so the caches
        # can stay on the graphics card between steps.
        dec = self.dec
        self_k = self_k.index_select(1, beam)
        self_v = self_v.index_select(1, beam)
        b, t = tokens.shape[0], tokens.shape[1]
        n_ctx = self_k.shape[2]
        idx = torch.arange(t, device=tokens.device) + offset          # (T,)
        x = dec.token_embedding(tokens) + dec.positional_embedding.index_select(0, idx)
        cols = torch.arange(n_ctx, device=tokens.device).unsqueeze(0)  # (1, 448)
        mask = torch.where(cols > idx.unsqueeze(1), torch.tensor(float("-inf")),
                           torch.tensor(0.0))                          # (T, 448)
        new_k, new_v, qks = [], [], []
        for i, blk in enumerate(dec.blocks):
            h = blk.attn_ln(x)
            q, k, v = blk.attn.query(h), blk.attn.key(h), blk.attn.value(h)
            where = idx.view(1, -1, 1).expand(b, t, k.shape[-1])
            kc = self_k[i].scatter(1, where, k)
            vc = self_v[i].scatter(1, where, v)
            new_k.append(kc)
            new_v.append(vc)
            out, _ = attend(q, kc, vc, self.n_head, mask)
            x = x + blk.attn.out(out)
            h = blk.cross_attn_ln(x)
            out, qk = attend(blk.cross_attn.query(h), cross_k[i], cross_v[i], self.n_head)
            x = x + blk.cross_attn.out(out)
            for layer, head in self.heads:
                if layer == i:
                    qks.append(qk[:, head])
            x = x + blk.mlp(blk.mlp_ln(x))
        x = dec.ln(x)
        logits = (x @ dec.token_embedding.weight.t()).float()
        return logits, torch.stack(new_k), torch.stack(new_v), torch.stack(qks, dim=1)


def to_fp16(src: str, dst: str) -> None:
    import onnx
    from onnxconverter_common import float16
    m = onnx.load(src, load_external_data=True)
    # inputs/outputs float16 too: caches stay float16 on the graphics card
    m16 = float16.convert_float_to_float16(m, keep_io_types=False, disable_shape_infer=True)
    onnx.save(m16, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="turbo")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fp32", action="store_true", help="keep float32 weights")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tmp = os.path.join(a.out, "_fp32")
    os.makedirs(tmp, exist_ok=True)

    model = whisper.load_model(a.model, device="cpu").eval()
    d = model.dims
    enc, dec = Encoder(model).eval(), Decoder(model).eval()
    L, D = d.n_text_layer, d.n_text_state

    mel = torch.zeros(1, d.n_mels, 3000)
    with torch.no_grad():
        ck, cv = enc(mel)
        torch.onnx.export(enc, (mel,), os.path.join(tmp, "encoder.onnx"),
                          input_names=["mel"], output_names=["cross_k", "cross_v"],
                          dynamic_axes={"mel": {0: "b"}, "cross_k": {1: "b"}, "cross_v": {1: "b"}},
                          opset_version=17, dynamo=False)
        tokens = torch.tensor([[50258, 50259, 50360]], dtype=torch.long)
        sk = torch.zeros(L, 1, d.n_text_ctx, D)
        sv = torch.zeros(L, 1, d.n_text_ctx, D)
        off = torch.tensor([0], dtype=torch.long)
        beam = torch.tensor([0], dtype=torch.long)
        torch.onnx.export(dec, (tokens, sk, sv, ck, cv, off, beam), os.path.join(tmp, "decoder.onnx"),
                          input_names=["tokens", "self_k", "self_v", "cross_k", "cross_v",
                                       "offset", "beam"],
                          output_names=["logits", "self_k_out", "self_v_out", "qk"],
                          dynamic_axes={"tokens": {0: "b", 1: "t"}, "self_k": {1: "pb"},
                                        "self_v": {1: "pb"}, "cross_k": {1: "ab"},
                                        "cross_v": {1: "ab"}, "beam": {0: "b"},
                                        "logits": {0: "b", 1: "t"},
                                        "self_k_out": {1: "b"}, "self_v_out": {1: "b"},
                                        "qk": {0: "b", 2: "t"}},
                          opset_version=17, dynamo=False)

    for name in ("encoder.onnx", "decoder.onnx"):
        if a.fp32:      # > 2 GB: weights go into a side file
            import onnx
            m = onnx.load(os.path.join(tmp, name), load_external_data=True)
            onnx.save(m, os.path.join(a.out, name), save_as_external_data=True,
                      all_tensors_to_one_file=True, location=name + ".data")
        else:
            to_fp16(os.path.join(tmp, name), os.path.join(a.out, name))

    cfg = dict(n_mels=d.n_mels, n_text_ctx=d.n_text_ctx, n_text_state=D,
               n_text_layer=L, n_text_head=d.n_text_head, n_audio_ctx=d.n_audio_ctx,
               n_vocab=d.n_vocab, is_multilingual=bool(model.is_multilingual),
               num_languages=int(getattr(model, "num_languages", 99)),
               alignment_heads=Decoder(model).heads, source=f"openai-whisper {a.model}",
               precision="fp32" if a.fp32 else "fp16")
    with open(os.path.join(a.out, "config.json"), "w") as f:
        json.dump(cfg, f, indent=1)
    import shutil
    shutil.rmtree(tmp)
    print(json.dumps(cfg))


if __name__ == "__main__":
    main()
