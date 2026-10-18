"""Command line interface for zhihu-backup."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .auth import login, state_dir_path
from .config import DEFAULT_OUTPUT, DEFAULT_SLEEP, DEFAULT_STATE_DIR
from .errors import AuthError, ZhihuBackupError
from .runner import Runner
from .urls import parse_target, resolve_user

logger = logging.getLogger(__name__)


def _add_common(parser: argparse.ArgumentParser, *, with_pdf: bool = True) -> None:
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="备份输出目录（默认 ./backup）")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help="Cookie/状态目录")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="请求间隔秒数")
    parser.add_argument("--cookie", help="直接传入 Cookie 字符串")
    parser.add_argument("--cookie-file", help="Cookie 文件（JSON 或原始 Cookie 字符串）")
    parser.add_argument("--driver", help="手动指定 msedgedriver 路径")
    parser.add_argument("--force", action="store_true", help="忽略 manifest 强制重下")
    parser.add_argument("--update", action="store_true", help="内容更新时间变新时重下")
    parser.add_argument("--json", action="store_true", help="输出 JSON 汇总（供 GUI 调用）")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    if with_pdf:
        parser.add_argument("--pdf", action="store_true", help="额外生成 PDF")
        parser.add_argument("--no-images", action="store_true", help="不下载图片，保留远程链接")
        parser.add_argument("--limit", type=int, default=0, help="最多处理多少条")
        parser.add_argument(
            "--no-question-body",
            action="store_true",
            help="回答不额外抓取问题描述",
        )
        parser.add_argument(
            "--pdf-only",
            "--pdf_only",
            dest="pdf_only",
            action="store_true",
            help="只生成 PDF，不重新下载内容",
        )
        parser.add_argument(
            "--videos",
            action="store_true",
            help="user 模式：额外备份该用户的 zvideo 列表（内容里的视频默认下载）",
        )
        parser.add_argument(
            "--no-videos",
            action="store_true",
            help="不下载任何视频",
        )
        parser.add_argument(
            "--videos-only",
            "--videos_only",
            dest="videos_only",
            action="store_true",
            help="只补已有内容缺失的视频",
        )
        parser.add_argument(
            "--video-quality",
            choices=["best", "hd", "sd", "ld"],
            default="best",
            help="视频清晰度（默认 best）",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zhihu-backup",
        description="备份知乎用户的回答、文章、想法以及用户资料。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="打开浏览器登录并保存 Cookie")
    login_parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    login_parser.add_argument("--driver")
    login_parser.add_argument("--timeout", type=int, default=600)
    login_parser.add_argument("--json", action="store_true")
    login_parser.add_argument("--verbose", action="store_true")

    profile_parser = subparsers.add_parser("profile", help="只备份用户资料")
    profile_parser.add_argument("target", help="用户主页 URL 或 url_token")
    _add_common(profile_parser, with_pdf=True)

    user_parser = subparsers.add_parser("user", help="备份指定用户的全部内容")
    user_parser.add_argument("target", help="用户主页 URL 或 url_token")
    user_parser.add_argument("--answers", action="store_true", help="备份回答")
    user_parser.add_argument("--articles", action="store_true", help="备份文章")
    user_parser.add_argument("--pins", action="store_true", help="备份想法")
    user_parser.add_argument("--since", help="只备份该日期之后的内容，如 2024-01-01")
    user_parser.add_argument("--dry-run", action="store_true", help="只枚举，不下载")
    _add_common(user_parser, with_pdf=True)

    urls_parser = subparsers.add_parser("urls", help="备份单个或多个知乎内容链接")
    urls_parser.add_argument("urls", nargs="*", help="回答/文章/想法链接")
    urls_parser.add_argument("--file", help="从文本文件读取链接，每行一个")
    _add_common(urls_parser, with_pdf=True)

    return parser


def _setup_logging(args) -> None:
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    output = Path(getattr(args, "output", DEFAULT_OUTPUT))
    try:
        log_dir = output / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError as exc:
        sys.stderr.write(f"无法创建日志文件：{exc}\n")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _parse_since(value: Optional[str]) -> int:
    if not value:
        return 0
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(value, fmt).timestamp())
        except ValueError:
            continue
    raise ZhihuBackupError(f"无法识别的日期：{value}，请使用 YYYY-MM-DD")


def _read_url_file(path: str) -> List[str]:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise ZhihuBackupError(f"URL 文件不存在：{file_path}")
    values = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            values.append(line)
    return values


def _emit(payload: Dict[str, Any], as_json: bool, command: str) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if command == "login":
        user = payload.get("user") or {}
        if user.get("name"):
            print(f"登录成功：{user.get('name')}。Cookie 已保存。")
        else:
            print("登录成功，Cookie 已保存。")
        return

    if payload.get("dry_run"):
        print(f"枚举完成：{payload.get('user', {}).get('name', '')}")
        for kind, count in (payload.get("counts") or {}).items():
            print(f"  {kind}: {count}")
        return

    if command == "profile" and payload.get("profile"):
        profile = payload.get("profile") or {}
        print(
            f"已保存用户资料：{profile.get('name', '')}（{profile.get('url_token', '')}）"
        )
        print(f"输出目录：{payload.get('output')}")
        return

    print(
        f"完成：成功 {payload.get('ok', 0)}，跳过 {payload.get('skipped', 0)}，"
        f"失败 {payload.get('failed', 0)}"
    )
    print(f"输出目录：{payload.get('output')}")
    errors = payload.get("errors") or []
    if errors:
        print("部分失败：")
        for error in errors[:5]:
            print(f"  - {error.get('url', '')}：{error.get('error', '')}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args)

    try:
        if args.command == "login":
            state_dir = state_dir_path(args.state_dir)
            me = login(state_dir, driver_path=args.driver, timeout=args.timeout)
            payload = {
                "status": "ok",
                "state_dir": str(state_dir),
                "user": {
                    "url_token": me.get("url_token") or "",
                    "name": me.get("name") or "",
                },
            }
            _emit(payload, args.json, "login")
            return 0

        if args.command == "user":
            args.since_ts = _parse_since(args.since)

        runner = Runner(args)
        try:
            if args.command == "profile":
                if parse_target(args.target) is not None:
                    logger.info(
                        "检测到内容链接，按 urls 模式处理：%s", args.target
                    )
                    result = runner.backup_urls([args.target])
                else:
                    token = resolve_user(args.target)
                    result = runner.backup_profile(token)
            elif args.command == "user":
                token = resolve_user(args.target)
                kinds = []
                if args.answers:
                    kinds.append("answers")
                if args.articles:
                    kinds.append("articles")
                if args.pins:
                    kinds.append("pins")
                if not kinds:
                    kinds = ["answers", "articles", "pins"]
                if (args.videos or args.videos_only) and not args.no_videos:
                    kinds.append("zvideos")
                result = runner.backup_user(token, kinds, dry_run=args.dry_run)
            else:  # urls
                values = list(args.urls)
                if args.file:
                    values.extend(_read_url_file(args.file))
                if not values:
                    parser.error("请至少提供一个链接，或使用 --file 指定链接文件")
                result = runner.backup_urls(values)
        finally:
            runner.close()

        _emit(result, getattr(args, "json", False), args.command)
        return 0 if result.get("failed", 0) == 0 else 1

    except AuthError as exc:
        logger.error("%s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    except ZhihuBackupError as exc:
        logger.error("%s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    except KeyboardInterrupt:
        logger.warning("已中断，可重新运行继续备份。")
        return 130
    except Exception as exc:  # pragma: no cover - unexpected failures
        logger.exception("未预期的错误：%s", exc)
        return 1
