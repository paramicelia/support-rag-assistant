# How to record the demo (30-45 seconds)

## Tool

**ShareX** (free, Windows). Download: https://getsharex.com/

Configure once:
- Region capture → "Screen recording (GIF)"
- FPS: 10–15
- Output: GIF (or MP4 if you also want a higher-quality copy)
- Save to: `support-rag-assistant/demo/demo.gif`

Alternatives:
- **Win + G** (Xbox Game Bar): MP4 only, no GIF. Use if you'll convert later.
- **LICEcap**: GIF-only, smaller download, dead simple. https://www.cockos.com/licecap/
- **ffmpeg** (post-process MP4 → GIF, smallest output):
  ```bash
  ffmpeg -i demo.mp4 -vf "fps=10,scale=1280:-1:flags=lanczos,palettegen" palette.png
  ffmpeg -i demo.mp4 -i palette.png -lavfi "fps=10,scale=1280:-1:flags=lanczos [x]; [x][1:v] paletteuse" demo.gif
  ```

Target size: **≤ 8 MB** (GitHub renders inline up to 10 MB; smaller is faster).

---

## Setup before recording

1. Start the API:
   ```bash
   uvicorn src.api:app --host 127.0.0.1 --port 8000 --log-level warning
   ```
2. Open `http://127.0.0.1:8000/` in a clean browser window.
3. Set window width to ~1280 px so the 6-column pipeline fits without horizontal scroll.
4. Close devtools, hide bookmarks bar — just the page should be visible.
5. **Pre-warm the LLM:** run one preset (any) before recording so the first
   real demo call doesn't catch a cold Groq connection. Then refresh.

---

## The 5-shot script (≈ 35 seconds total)

| # | Action                                      | Why this preset                                                | Approx time |
|---|---------------------------------------------|----------------------------------------------------------------|-------------|
| 1 | Click **EN withdrawal** preset → **Resolve →** | Happy path: all 6 layers green, real answer about Visa cashout | ~8 s        |
| 2 | Clear textarea, click **RG crisis** preset → **Resolve →** | High-risk short-circuit: only Layer 1 fires, operator handoff with GamCare resources | ~6 s |
| 3 | Click **RU пароль** preset → **Resolve →** | Multilingual: question in Russian, LLM answers in Russian, kb_016 cited | ~8 s |
| 4 | Click **Mega Moolah** preset → **Resolve →** | Generator self-refuses (the "better to refuse than invent" rule) → low_confidence escalation | ~6 s |
| 5 | Click **Prompt inj** preset → **Resolve →** | OOD layer catches "ignore previous instructions" → out_of_scope | ~5 s |

**What to highlight visually as you go:**
- Shot 1 — the green border on every layer column, the source chip (`kb_005`), the answer text.
- Shot 2 — only Layer 1 (orange), Layers 2–6 dimmed, orange operator-guidance box at the bottom.
- Shot 3 — same as shot 1 but the answer text is in Cyrillic.
- Shot 4 — Layer 4 orange ("refused"), the operator message "model could not answer with sufficient confidence".
- Shot 5 — Layer 1 green, Layer 2 orange ("off-topic"), the rest dimmed.

**Pro tip:** click a layer's `raw` to expand the JSON trace once during shot 1
and once during shot 2. Shows the auditability story without saying anything.

---

## Common mistakes

- Recording at 30 fps inflates the GIF for no benefit. 10–12 fps is plenty
  for a UI demo and cuts size 2-3×.
- Cropping out the latency / backend badge at the top right hides the
  "real LLM, not mock" signal. Keep it in frame.
- Don't mouse-jitter while waiting for Groq to respond. ShareX records
  it. Pause on the loading state, click once decision lands.

---

## After recording

```bash
# place the file
mv path/to/sharex-output.gif demo/demo.gif

# commit
git add demo/demo.gif README.md
git commit -m "Add UI demo gif"
git push
```

Then add a `![Pipeline viewer demo](demo/demo.gif)` line near the top of
`README.md` so it renders inline on GitHub.
