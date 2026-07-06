"""视频 enrich：yt-dlp 字幕优先，否则 faster-whisper ASR（解耦子流程）。

用法：
  python scripts/enrich_video.py --id 281250
  python scripts/enrich_video.py --pending              # 处理所有 asr_status=pending 的视频
  python scripts/enrich_video.py --pending --limit 20   # 只处理前 20 条 pending
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


def _has_binary(name: str) -> bool:
    """检测本机是否安装了某个命令行工具（yt-dlp / ffmpeg 等）。"""
    from shutil import which

    return which(name) is not None


def enrich_one(video_id: str, url: str, embed_url: str) -> dict:
    target = embed_url or url
    transcript = ""
    method = "none"
    degraded_reason = ""

    # 本机无 yt-dlp：直接降级标记 pending，不抛错（CI 环境会安装）
    if not _has_binary("yt-dlp"):
        return {
            "video_id": video_id,
            "status": "pending",
            "method": "none",
            "transcript": "",
            "summary": "",
            "degraded_reason": "yt-dlp not installed on host",
            "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

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
            # 下载音频 + faster-whisper（若未安装则标记 pending/failed）
            audio = tmp_path / "audio.m4a"
            rc2, _ = _run(["yt-dlp", "-x", "--audio-format", "m4a", "-o", str(audio), target])
            if rc2 == 0 and audio.exists():
                try:
                    from faster_whisper import WhisperModel  # type: ignore

                    model = WhisperModel("base", device="cpu", compute_type="int8")
                    segments, _ = model.transcribe(str(audio), language="zh")
                    transcript = "\n".join(s.text for s in segments)
                    method = "faster-whisper-base"
                except ImportError as e:
                    return {
                        "video_id": video_id,
                        "status": "pending",
                        "method": "faster-whisper",
                        "transcript": "",
                        "summary": "",
                        "degraded_reason": f"faster-whisper not installed: {e}",
                        "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
                except Exception as e:
                    return {
                        "video_id": video_id,
                        "status": "failed",
                        "method": "faster-whisper",
                        "transcript": "",
                        "summary": "",
                        "error": str(e),
                        "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
            else:
                degraded_reason = "yt-dlp audio download failed"

    summary = transcript[:500] + ("…" if len(transcript) > 500 else "")
    result = {
        "video_id": video_id,
        "status": "done" if transcript else "empty",
        "method": method,
        "transcript": transcript,
        "summary": summary,
        "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if degraded_reason:
        result["degraded_reason"] = degraded_reason
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="指定视频 ID")
    parser.add_argument("--pending", action="store_true", help="处理全部 pending")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="配合 --pending 使用：只处理前 N 条 pending（0=不限）",
    )
    args = parser.parse_args()
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)

    targets: list[dict] = []
    if args.id:
        p = VIDEOS_DIR / f"{args.id}.json"
        if p.exists():
            targets.append(json.loads(p.read_text(encoding="utf-8")))
    elif args.pending:
        pending = [v for v in load_all_records("video") if v.get("asr_status") == "pending"]
        if args.limit and args.limit > 0:
            pending = pending[: args.limit]
        targets = pending
    else:
        parser.error("需要 --id 或 --pending")

    print(f"[enrich_video] 待处理：{len(targets)} 条")
    for v in targets:
        print(f"Enriching {v['id']}...")
        result = enrich_one(v["id"], v["url"], v.get("video_embed_url", ""))
        (ENRICH_DIR / f"{v['id']}.asr.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if result.get("status") == "done":
            v["asr_status"] = "done"
            (VIDEOS_DIR / f"{v['id']}.json").write_text(
                json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        status = result.get("status", "unknown")
        reason = result.get("degraded_reason") or result.get("error", "")
        print(f"  -> {status}" + (f" ({reason})" if reason else ""))


if __name__ == "__main__":
    main()
