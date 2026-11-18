# Local fork notes (albertop27/anykit, branch `local`)

Runs AnyKit without fal or an API key. Generation goes to a local ComfyUI. The builder and critic run as a Claude
Code skill (`anykit-local` in the Art Design playground) instead of the Claude Agent SDK app.

| Change | Why |
|---|---|
| `generate/local.py` (`ref`, `3d`) | Replaces `kit/gen.mjs` and `generate/fal.mjs`: Krea 2 / Qwen Image 2.1 references, TRELLIS 2 + Pixal3D meshes, same file layout |
| `kit/tools/compare.py --models` | Model list is configurable (`trellis2,pixal3d`) |

Not used locally: `app.py`, `client.py`, `agent/kit_builder.py`, `agent/llm.py` (fal app, Claude Agent SDK, OpenRouter).

Findings: TRELLIS 2 output already faces -Y and is upright, so `normalize.py --gen trellis2` needs no rotation.
Pixal3D output is in the photo's camera frame (yawed and pitched), so it needs a canonicalize step before
normalize. Not built yet.
