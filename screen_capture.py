"""
XEON V2 - Screen Capture
Takes screenshots and describes them with OpenAI vision.
"""

import base64
import io
import os
import tempfile

from PIL import ImageGrab


def capture_screen() -> bytes:
    """Capture the entire screen and return PNG bytes."""
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def describe_screen(openai_client, model: str) -> str:
    """Capture screen and describe it using OpenAI vision."""
    png_bytes = capture_screen()
    b64 = base64.b64encode(png_bytes).decode("utf-8")

    response = await openai_client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Beschreibe kurz auf Deutsch was auf diesem Bildschirm zu sehen ist. "
                            "Maximal 2-3 Saetze. Nenne die wichtigsten offenen Programme und Inhalte."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{b64}",
                    },
                ],
            }
        ],
        max_output_tokens=300,
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
    )
    return response.output_text.strip()


async def describe_screen_codex(codex_runner) -> str:
    """Capture screen and describe it using Codex CLI image input."""
    png_bytes = capture_screen()
    tmp = tempfile.NamedTemporaryFile(prefix="xeon_screen_", suffix=".png", delete=False)
    image_path = tmp.name
    try:
        tmp.write(png_bytes)
        tmp.close()
        return await codex_runner(
            (
                "Beschreibe kurz auf Deutsch was auf diesem Bildschirm zu sehen ist. "
                "Maximal 2-3 Saetze. Nenne die wichtigsten offenen Programme und Inhalte. "
                "Fuehre keine Kommandos aus und bearbeite keine Dateien."
            ),
            image_path=image_path,
        )
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.remove(image_path)
        except OSError:
            pass
