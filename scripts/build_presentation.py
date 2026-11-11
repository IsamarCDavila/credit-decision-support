"""Build silent bilingual MP4 walkthroughs from retained, real application screenshots."""

import argparse
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT, FPS = 1280, 720, 12
SCENES = [
    (
        5,
        "01-entry",
        "Evidence before decisions",
        "Evidencia antes de decidir",
        "Synthetic credit analysis. Guided roles. No real credit authorization.",
        "Análisis crediticio sintético. Roles guiados. Sin autorización de créditos reales.",
    ),
    (
        7,
        "02-analysis",
        "01  Understand the analysis",
        "01  Comprende el análisis",
        "150,000 / 100,000 = DSCR 1.5000. Policy outcome and human review stay separate.",
        "150.000 / 100.000 = DSCR 1.5000. La política y la revisión son estados separados.",
    ),
    (
        8,
        "03-evidence",
        "02  Follow the evidence",
        "02  Consulta la evidencia",
        "Each verified amount links to a retained source and an exact row/column locator.",
        "Cada importe verificado conduce a una fuente conservada y su fila/columna exacta.",
    ),
    (
        9,
        "04-review",
        "03  Record a reasoned assessment",
        "03  Registra una evaluación con motivo",
        "A different simulated actor requests more information. The reason is retained verbatim.",
        "Otro actor simulado solicita información. El motivo se conserva sin reescritura.",
    ),
    (
        9,
        "05-audit",
        "04  Trace and export",
        "04  Consulta y exporta",
        "The event chain retains the review. PDF/JSON exports preserve the verified snapshot.",
        "La auditoría conserva la revisión. PDF/JSON retienen la instantánea verificada.",
    ),
    (
        7,
        "architecture",
        "How the system works",
        "Cómo funciona el sistema",
        "Models propose; code validates and calculates. A separate human endpoint records review.",
        "El modelo propone; el código valida y calcula. La revisión humana es separada.",
    ),
    (
        5,
        "evidence",
        "Measured scope",
        "Alcance medido",
        "Small mock cohort. No production reliability or model-superiority claim.",
        "Muestra sintética pequeña. Sin garantía de producción ni superioridad del modelo.",
    ),
]


def font(size, bold=False):
    import reportlab

    name = "VeraBd.ttf" if bold else "Vera.ttf"
    return ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / name), size)


def text(draw, xy, value, size=20, fill="#d8e6ef", bold=False, wrap=96):
    draw.multiline_text(
        xy, "\n".join(textwrap.wrap(value, wrap)), font=font(size, bold), fill=fill, spacing=7
    )


def frame(scene_index, progress, locale, screenshots):
    es = locale == "es"
    _, key, title_en, title_es, caption_en, caption_es = SCENES[scene_index]
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#10283d")
    draw = ImageDraw.Draw(canvas)
    text(draw, (48, 25), "CREDIT DECISION SUPPORT", 17, "#7ed0c4", True)
    text(draw, (48, 67), title_es if es else title_en, 32, "#ffffff", True, 66)
    text(draw, (1065, 30), f"{scene_index + 1:02} / 07  |  {locale.upper()}", 16)
    if key in screenshots:
        image = screenshots[key]
        max_top = max(0, image.height - 450)
        if key in {"03-evidence", "04-review", "05-audit"}:
            position = 0.55 + 0.45 * progress
        elif key == "02-analysis":
            position = 0.38 * progress
        else:
            position = 0.6 * progress
        top = int(max_top * position)
        canvas.paste(image.crop((0, top, 1184, top + 450)), (48, 149))
        draw.rectangle((47, 148, 1232, 599), outline="#7590a6", width=1)
    elif key == "architecture":
        boxes = [
            (
                "Roles guiados" if es else "Guided roles",
                "Analista / Revisor / Auditor" if es else "Analyst / Reviewer / Auditor",
            ),
            (
                "API y acceso" if es else "API and access",
                "FastAPI / autorización" if es else "FastAPI / authorization",
            ),
            (
                "Worker persistente" if es else "Persistent worker",
                "Concesiones / pasos validados" if es else "Leases / validated steps",
            ),
            (
                "Reglas + modelo" if es else "Rules + model",
                "DSCR decimal / simulado u OpenAI" if es else "Decimal DSCR / mock or OpenAI",
            ),
            (
                "Persistencia y auditoría" if es else "Persistence and audit",
                "PostgreSQL / PDF / JSON",
            ),
        ]
        for n, (title, detail) in enumerate(boxes):
            y = 155 + n * 87
            draw.rounded_rectangle((75, y, 1205, y + 70), 12, fill="#203e56")
            text(draw, (98, y + 18), title, 21, "#ffffff", True, 50)
            text(draw, (650, y + 20), detail, 18, wrap=50)
    else:
        metrics = [
            ("40 / 40", "Recorridos completos" if es else "Completed workflows"),
            ("240 / 240", "Campos coincidentes" if es else "Matching fields"),
            ("186", "Pruebas en Linux CI" if es else "Tests in Linux CI"),
        ]
        for n, (value, label) in enumerate(metrics):
            x = 48 + n * 404
            draw.rounded_rectangle((x, 174, x + 376, 373), 16, fill="#203e56")
            text(draw, (x + 26, 213), value, 43, "#ffffff", True)
            text(draw, (x + 26, 302), label, 18, wrap=29)
        detail = (
            "40 casos sintéticos; concurrencias 1, 2, 4 y 8. IC Wilson del 95%: 91,24–100%."
            if es
            else "40 synthetic cases; concurrency 1, 2, 4, and 8. Wilson 95% CI: 91.24–100%."
        )
        text(draw, (64, 420), detail, 22, wrap=85)
        text(
            draw,
            (64, 499),
            "SIMULACIÓN / modelo simulado" if es else "SIMULATION / mock provider",
            24,
            "#7ed0c4",
            True,
        )
    text(draw, (48, 626), caption_es if es else caption_en, 20, "#ffffff", wrap=96)
    draw.rectangle((48, 704, 1232, 708), fill="#35536a")
    draw.rectangle((48, 704, 48 + int(1184 * (scene_index + progress) / 7), 708), fill="#7ed0c4")
    return canvas


def build(ffmpeg, media, output):
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "edited_screenshot_walkthrough",
        "duration_seconds": 50,
        "fps": FPS,
        "resolution": [WIDTH, HEIGHT],
        "audio": False,
        "languages": [],
    }
    for locale in ("en", "es"):
        screenshots = {}
        for _, key, *_ in SCENES:
            source = media / f"{key}.{locale}.webp"
            if source.exists():
                image = Image.open(source).convert("RGB")
                screenshots[key] = image.resize((1184, round(image.height * 1184 / image.width)))
        if len(screenshots) != 5:
            raise ValueError("Five retained screenshots are required for each language")
        target = output / f"walkthrough.{locale}.mp4"
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target),
        ]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert encoder.stdin
        transcript = []
        elapsed = 0
        for index, (seconds, key, title_en, title_es, caption_en, caption_es) in enumerate(SCENES):
            for n in range(seconds * FPS):
                image = frame(index, n / max(1, seconds * FPS - 1), locale, screenshots)
                encoder.stdin.write(image.tobytes())
                if index == 1 and n == seconds * FPS // 2:
                    image.save(output / f"poster.{locale}.png")
            transcript.append(
                {
                    "start_seconds": elapsed,
                    "end_seconds": elapsed + seconds,
                    "scene": key,
                    "title": title_es if locale == "es" else title_en,
                    "caption": caption_es if locale == "es" else caption_en,
                }
            )
            elapsed += seconds
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("FFmpeg could not encode the walkthrough")
        subprocess.run([ffmpeg, "-v", "error", "-i", str(target), "-f", "null", "-"], check=True)
        (output / f"transcript.{locale}.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest["languages"].append(
            {
                "locale": locale,
                "file": target.name,
                "bytes": target.stat().st_size,
                "decoded_without_errors": True,
            }
        )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--media-dir", type=Path, default=Path("docs/media"))
    parser.add_argument("--output-dir", type=Path, default=Path("storage/presentation"))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("Provide a local FFmpeg executable with --ffmpeg")
    build(args.ffmpeg, args.media_dir, args.output_dir)
