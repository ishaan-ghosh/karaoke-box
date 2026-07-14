# Vendored MelBand RoFormer provenance

The RoFormer implementation in `attend.py` and `mel_band_roformer.py` is vendored
from `python-audio-separator` 0.44.3 at commit
`ee1fcee90963919fe13a146fe71f57f29c2e9bbc`:

- <https://github.com/nomadkaraoke/python-audio-separator/tree/ee1fcee90963919fe13a146fe71f57f29c2e9bbc/audio_separator/separator/uvr_lib_v5/roformer>
- Upstream license: MIT (see `LICENSE`)

The vendored runtime makes the selected device path intrinsically CPU-only:
CUDA probing/backend selection and the retained MPS transfer branches were
removed. CPU scaled-dot-product attention and the CPU tensor/model operations
remain aligned with the proven source. The `librosa.filters.mel` call was also
replaced with the fixed pinned Slaney filter helper in `mel_filter.py`.
