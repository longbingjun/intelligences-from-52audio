"""视频 enrich：yt-dlp 字幕优先，否则 faster-whisper ASR（解耦子流程）。

用法：
  python scripts/enrich_video.py --id 281250
  python scripts/enrich_video.py --pending   # 处理所有 asr_status=pending 的视频
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records  # noqa: E402

ENRICH_DIR = ROOT / "data" / "enrich" / "videos"
VIDEOS_DIR = ROOT / "data" / "videos"


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def enrich_one(video_id: str, url: str, embed_url: str) -> dict:
    target = embed_url or url
    transcript = ""
    method = "none"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # 尝试 yt-dlp 拉字幕
        rc, out = _run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-auto-sub",
                "--sub-lang",
                "zh-Hans,zh,en",
                "--sub-format",
                "vtt",
                "-o",
                str(tmp_path / "sub"),
                target,
            ]
        )
        vtt_files = list(tmp_path.glob("*.vtt"))
        if vtt_files:
            transcript = vtt_files[0].read_text(encoding="utf-8", errors="ignore")
            method = "yt-dlp-subtitle"
        else:
            # 下载音频 + faster-whisper（若未安装则标记 failed）
            audio = tmp_path / "audio.m4a"
            rc2, _ = _run(["yt-dlp", "-x", "--audio-format", "m4a", "-o", str(audio), target])
            if rc2 == 0 and audio.exists():
                try:
                    from faster_whisper import WhisperModel  # type: ignore

                    model = WhisperModel("base", device="cpu", compute_type="int8")
                    segments, _ = model.transcribe(str(audio), language="zh")
                    transcript = "\n".join(s.text for s in segments)
                    method = "faster-whisper-base"
                except Exception as e:
                    return {"status": "failed", "error": str(e), "method": "faster-whisper"}

    summary = transcript[:500] + ("…" if len(transcript) > 500 else "")
    return {
        "video_id": video_id,
        "status": "done" if transcript else "empty",
        "method": method,
        "transcript": transcript,
        "summary": summary,
        "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="指定视频 ID")
    parser.add_argument("--pending", action="store_true", help="处理全部 pending")
    args = parser.parse_args()
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)

    targets: list[dict] = []
    if args.id:
        p = VIDEOS_DIR / f"{args.id}.json"
        if p.exists():
            targets.append(json.loads(p.read_text(encoding="utf-8")))
    elif args.pending:
        targets = [v for v in load_all_records("video") if v.get("asr_status") == "pending"]
    else:
        parser.error("需要 --id 或 --pending")

    for v in targets:
        print(f"Enriching {v['id']}...")
        result = enrich_one(v["id"], v["url"], v.get("video_embed_url", ""))
        (ENRICH_DIR / f"{v['id']}.asr.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.get("status") == "done":
            v["asr_status"] = "done"
            (VIDEOS_DIR / f"{v['id']}.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
