# Third-party software in UbiClipper

UbiClipper itself is licensed under the GNU General Public License v3.0
(see `LICENSE`). The Windows installer and portable version also contain:

| Software | Licence | Where |
|---|---|---|
| Python 3.12 (python.org build) | PSF License | `python/` |
| FFmpeg (gyan.dev "essentials" build) | GPL-3.0 | `ffmpeg/` (licence and source info in that folder) |
| faster-whisper | MIT | `python/Lib/site-packages` |
| CTranslate2 | MIT | 〃 |
| ONNX Runtime | MIT | 〃 |
| NumPy | BSD-3-Clause | 〃 |
| tokenizers, huggingface_hub | Apache-2.0 | 〃 |
| yt-dlp | Unlicense | 〃 |
| curl_cffi | MIT | 〃 |
| tkinterdnd2 | MIT | 〃 |

Downloaded on first start (not part of the download itself):

| Model / files | Licence |
|---|---|
| Whisper large-v3-turbo (CTranslate2 conversion) | MIT |
| CED audio tagging model (sherpa-onnx release) | Apache-2.0 |
| WeSpeaker ResNet34 voice model | Apache-2.0 |
| Qwen3-4B-Instruct (CTranslate2 int8 conversion) | Apache-2.0 |
| NVIDIA CUDA runtime, cuBLAS, cuDNN (NVIDIA PCs only, optional) | NVIDIA software licence |

Each package's own licence file is included next to it in `site-packages`.
