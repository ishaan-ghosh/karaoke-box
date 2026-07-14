# Vendored from python-audio-separator 0.44.3, commit ee1fcee90963919fe13a146fe71f57f29c2e9bbc.
# Upstream license: MIT; see LICENSE and PROVENANCE.md.

import torch
from torch import nn
import torch.nn.functional as F

# main class


class Attend(nn.Module):
    def __init__(self, dropout=0.0, flash=False):
        super().__init__()
        self.dropout = dropout
        self.attn_dropout = nn.Dropout(dropout)
        # ``flash`` remains part of the vendored constructor contract, but the
        # application is permanently CPU-only. Always use PyTorch's CPU SDPA
        # implementation rather than probing or selecting another backend.
        self.flash = flash

    def flash_attn(self, q, k, v):
        if q.device.type != "cpu" or k.device.type != "cpu" or v.device.type != "cpu":
            raise RuntimeError("MelBand attention is CPU-only.")
        if q.device != k.device or q.device != v.device:
            raise RuntimeError("MelBand attention tensors must share the CPU device.")
        return F.scaled_dot_product_attention(
            q,
            k,
            v,
            dropout_p=self.dropout if self.training else 0.0,
        )

    def forward(self, q, k, v):
        """
        einstein notation
        b - batch
        h - heads
        n, i, j - sequence length (base sequence length, source, target)
        d - feature dimension
        """

        if q.device.type != "cpu" or k.device.type != "cpu" or v.device.type != "cpu":
            raise RuntimeError("MelBand attention is CPU-only.")
        if q.device != k.device or q.device != v.device:
            raise RuntimeError("MelBand attention tensors must share the CPU device.")

        return self.flash_attn(q, k, v)
