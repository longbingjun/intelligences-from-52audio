"""视频 enrich：yt-dlp 字幕优先，否则 faster-whisper ASR（解耦子流程）。

用法：
  python scripts/enrich_video.py --id 281250
  python scripts/enrich_video.py --pending              # 处理所有 asr_status=pending 的视频
  python scripts/enrich_video.py --pending --limit 20   # 只处理前 20 条 pending
  python scripts/enrich_video.py --retry-empty          # 重试 ASR 为 empty/failed 的视频
  python scripts/enrich_video.py --retry-empty --cookies-from-browser edge
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records, save_record_in_place  # noqa: E402

ENRICH_DIR = ROOT / "data" / "enrich" / "videos"
VIDEOS_DIR = ROOT / "data" / "videos"

_BVID_RE = re.compile(r"[?&]bvid=([^&]+)", re.I)
_VTT_TS_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}\s*$"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _default_cookies_browser() -> str:
    if platform.system() == "Windows":
        return "edge"
    return "chrome"


def _yt_dlp_cmd(
    *args: str,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> list[str]:
    """用当前 Python 解释器调用 yt-dlp 模块，避免 PATH 未配置 Scripts。"""
    cmd = [sys.executable, "-m", "yt_dlp"]
    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    elif cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    cmd.extend(args)
    return cmd


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _has_binary(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def _has_yt_dlp_module() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("yt_dlp") is not None
    except Exception:
        return False


def _resolve_video_url(url: str, embed_url: str) -> str:
    """将 52audio embed / 文章页 URL 解析为 yt-dlp 可识别的播放地址。"""
    for candidate in (embed_url, url):
        if not candidate:
            continue
        m = _BVID_RE.search(candidate)
        if m:
            return f"https://www.bilibili.com/video/{m.group(1)}"
        if "bilibili.com/video/" in candidate:
            return candidate.split("?")[0]
    return embed_url or url


def _vtt_to_text(vtt: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.startswith("WEBVTT") or line.isdigit():
            continue
        if _VTT_TS_RE.match(line):
            continue
        if line.startswith("NOTE") or line.startswith("STYLE"):
            continue
        line = _VTT_TAG_RE.sub("", line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def _load_empty_asr_video_ids(*, include_ids: list[str] | None = None) -> list[str]:
    ids: list[str] = []
    if not ENRICH_DIR.exists():
        return include_ids or []
    for path in sorted(ENRICH_DIR.glob("*.asr.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("status") in ("empty", "failed"):
            ids.append(path.stem.replace(".asr", ""))
    if include_ids:
        for vid in include_ids:
            if vid not in ids:
                ids.append(vid)
    return ids


def _should_skip_retry(video_id: str, *, force: bool) -> bool:
    if force:
        return False
    asr_path = ENRICH_DIR / f"{video_id}.asr.json"
    if not asr_path.exists():
        return False
    try:
        payload = json.loads(asr_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return payload.get("status") == "done" and bool((payload.get("transcript") or "").strip())


def enrich_one(
    video_id: str,
    url: str,
    embed_url: str,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> dict:
    target = _resolve_video_url(url, embed_url)
    transcript = ""
    method = "none"
    degraded_reason = ""

    if not _has_binary("yt-dlp") and not _has_yt_dlp_module():
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
        rc, _ = _run(
            _yt_dlp_cmd(
                "--skip-download",
                "--write-auto-sub",
                "--write-sub",
                "--sub-lang",
                "zh-Hans,zh,en",
                "--sub-format",
                "vtt/best",
                "-o",
                str(tmp_path / "sub"),
                target,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
            )
        )
        vtt_files = sorted(tmp_path.glob("*.vtt"), key=lambda p: p.stat().st_size, reverse=True)
        if vtt_files:
            transcript = _vtt_to_text(vtt_files[0].read_text(encoding="utf-8", errors="ignore"))
            method = "yt-dlp-subtitle"
        else:
            audio = tmp_path / "audio.m4a"
            rc2, err2 = _run(
                _yt_dlp_cmd(
                    "-f",
                    "bestaudio/best",
                    "-o",
                    str(tmp_path / "audio.%(ext)s"),
                    target,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                )
            )
            audio_files = list(tmp_path.glob("audio.*"))
            audio_file = audio_files[0] if audio_files else audio
            if rc2 == 0 and audio_file.exists():
                try:
                    from faster_whisper import WhisperModel  # type: ignore

                    model = WhisperModel("base", device="cpu", compute_type="int8")
                    segments, _ = model.transcribe(str(audio_file), language="zh")
                    transcript = "\n".join(s.text.strip() for s in segments if s.text.strip())
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
                degraded_reason = f"yt-dlp audio/subtitle failed: {err2[:500]}"

    summary = transcript[:500] + ("…" if len(transcript) > 500 else "")
    result = {
        "video_id": video_id,
        "status": "done" if transcript else "empty",
        "method": method,
        "transcript": transcript,
        "transcript_chars": len(transcript),
        "summary": summary,
        "resolved_url": target,
        "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if cookies_from_browser:
        result["cookies_from_browser"] = cookies_from_browser
    if degraded_reason:
        result["degraded_reason"] = degraded_reason
    return result


def _load_video_by_id(video_id: str) -> dict | None:
    p = VIDEOS_DIR / f"{video_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="指定视频 ID")
    parser.add_argument("--pending", action="store_true", help="处理全部 pending")
    parser.add_argument(
        "--retry-empty",
        "--only-empty",
        dest="retry_empty",
        action="store_true",
        help="仅重试 ASR 状态为 empty/failed 的视频",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="配合 --pending / --retry-empty：只处理前 N 条（0=不限）",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=_default_cookies_browser(),
        help="从浏览器读取 B 站 cookies（默认 Windows=edge，其他=chrome；传 none 禁用）",
    )
    parser.add_argument(
        "--cookies",
        dest="cookies_file",
        default="",
        help="Netscape cookies.txt 文件路径（优先于 --cookies-from-browser）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="重试时覆盖已有 done 且含 transcript 的 ASR 结果",
    )
        type=float,
        default=45.0,
        help="批量处理时，每条视频之间的等待秒数（默认 45，0=不等待）",
    )
    parser.add_argument(
        "--delay-jitter",
        type=float,
        default=15.0,
        help="在 --delay 基础上随机增加的秒数上限（默认 0–15s）",
    )
    args = parser.parse_args()
    ENRICH_DIR.mkdir(parents=True, exist_ok=True)

    cookies_browser = (args.cookies_from_browser or "").strip()
    if cookies_browser.lower() in ("none", "off", "false", "0"):
        cookies_browser = ""
    cookies_file = (args.cookies_file or "").strip()
    if cookies_file and not Path(cookies_file).exists():
        parser.error(f"cookies 文件不存在: {cookies_file}")

    targets: list[dict] = []
    if args.id:
        v = _load_video_by_id(args.id)
        if v:
            targets.append(v)
    elif args.pending:
        pending = [v for v in load_all_records("video") if v.get("asr_status") == "pending"]
        if args.limit and args.limit > 0:
            pending = pending[: args.limit]
        targets = pending
    elif args.retry_empty:
        empty_ids = _load_empty_asr_video_ids()
        if args.limit and args.limit > 0:
            empty_ids = empty_ids[: args.limit]
        for vid in empty_ids:
            if _should_skip_retry(vid, force=args.force):
                print(f"Skipping {vid} (already done)")
                continue
            v = _load_video_by_id(vid)
            if v:
                targets.append(v)
    else:
        parser.error("需要 --id、--pending 或 --retry-empty")

    print(f"[enrich_video] 待处理：{len(targets)} 条")
    if cookies_file:
        print(f"[enrich_video] cookies file: {cookies_file}")
    elif cookies_browser:
        print(f"[enrich_video] cookies-from-browser: {cookies_browser}")
    summary_stats = {"done": 0, "empty": 0, "pending": 0, "failed": 0}
    for i, v in enumerate(targets):
        if i > 0 and args.delay > 0:
            wait = args.delay + random.uniform(0, max(0.0, args.delay_jitter))
            print(f"  等待 {wait:.0f}s 以避免 B 站限流…")
            time.sleep(wait)
        print(f"Enriching {v['id']}...")
        result = enrich_one(
            v["id"],
            v["url"],
            v.get("video_embed_url", ""),
            cookies_from_browser=cookies_browser or None,
            cookies_file=cookies_file or None,
        )
        asr_path = ENRICH_DIR / f"{v['id']}.asr.json"
        asr_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.get("status") == "done":
            v["asr_status"] = "done"
            save_record_in_place("video", v)
        elif result.get("status") == "failed":
            v["asr_status"] = "failed"
            save_record_in_place("video", v)
        status = result.get("status", "unknown")
        summary_stats[status] = summary_stats.get(status, 0) + 1
        reason = result.get("degraded_reason") or result.get("error", "")
        chars = result.get("transcript_chars", len(result.get("transcript") or ""))
        print(f"  -> {status} chars={chars}" + (f" ({reason})" if reason else ""))

    print(json.dumps({"processed": len(targets), **summary_stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
