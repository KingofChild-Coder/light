#!/usr/bin/env python3
"""
本地推送脚本：按日期批量推送数据到服务器，并等待每天处理完成后再推送下一天。

使用流程：
1. 准备 manifest.csv（包含要推送的视频文件路径）
2. 运行此脚本
3. 脚本自动：
   - 按日期分组
   - 每日 rsync 推送到服务器 /srv/light_batch/work/{date}/
   - 创建 .ready 标记告诉服务器可以开始处理
   - 轮询等待 .done 标记（服务器处理完成）
   - 继续下一天

示例：
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai \
  --server-root /srv/light_batch \
  --local-user zekai \
  --poll-interval 10 \
  --poll-timeout 3600
"""

import argparse
import csv
import os
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime

DATE_RE = __import__("re").compile(r"(\d{4}_\d{1,2}_\d{1,2})")


def parse_manifest(manifest_path: str) -> dict[str, list[str]]:
    """读取 manifest.csv，按日期分组"""
    groups: dict[str, list[str]] = defaultdict(list)
    with open(manifest_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            v = row.get("video") or row.get("path") or ""
            if not v:
                continue
            m = DATE_RE.search(v)
            if not m:
                print(f"⚠️  无法从路径提取日期：{v}")
                continue
            date = m.group(1)
            groups[date].append(v)
    return groups


def run_cmd(cmd: str, check=True) -> int:
    """运行命令"""
    print(f"  $ {cmd}")
    rc = os.system(cmd)
    if check and rc != 0:
        raise RuntimeError(f"命令失败：{cmd} (exit code: {rc})")
    return rc


def rsync_day_to_server(
    date: str,
    files: list[str],
    server: str,
    server_user: str,
    server_root: str,
    local_user: str,
    dry_run: bool = False,
) -> bool:
    """将一天的文件 rsync 到服务器"""
    print(f"\n📤 [{datetime.now().strftime('%H:%M:%S')}] 推送 {date} ({len(files)} 个文件)...")
    
    work_dir = f"{server_root}/work/{date}"
    failed_count = 0
    
    for src_file in files:
        # 确保 rsync 能处理空格和特殊字符
        src_quoted = shlex.quote(src_file)
        dst = f"{server_user}@{server}:{work_dir}/"
        
        cmd = f"rsync -avz --partial {src_quoted} {dst}"
        if dry_run:
            cmd = f"{cmd} --dry-run"
        
        rc = run_cmd(cmd, check=False)
        if rc != 0:
            print(f"  ❌ 推送失败：{src_file}")
            failed_count += 1
    
    if failed_count > 0:
        print(f"  ⚠️  {failed_count}/{len(files)} 个文件推送失败")
        return False
    
    print(f"  ✅ {date} 所有文件推送完成")
    return True


def create_ready_marker(
    date: str,
    server: str,
    server_user: str,
    server_root: str,
) -> bool:
    """在服务器上创建 .ready 标记"""
    work_dir = f"{server_root}/work/{date}"
    cmd = f'ssh {server_user}@{server} "touch {work_dir}/.ready && echo .ready已创建"'
    print(f"  创建 .ready 标记...")
    rc = run_cmd(cmd, check=False)
    return rc == 0


def wait_for_done_marker(
    date: str,
    server: str,
    server_user: str,
    server_root: str,
    poll_interval: int = 10,
    poll_timeout: int = 3600,
) -> bool:
    """轮询等待服务器完成处理（.done 标记）"""
    work_dir = f"{server_root}/work/{date}"
    start_time = time.time()
    poll_count = 0
    
    print(f"  ⏳ 等待服务器处理 {date}...")
    print(f"     (轮询间隔：{poll_interval}s，超时：{poll_timeout}s)")
    
    while True:
        elapsed = time.time() - start_time
        poll_count += 1
        
        # 检查 .done 文件
        cmd = f'ssh {server_user}@{server} "[ -f {work_dir}/.done ] && echo 1 || echo 0"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.stdout.strip() == "1":
            print(f"  ✅ {date} 处理完成！(耗时：{int(elapsed)}s)")
            return True
        
        if elapsed > poll_timeout:
            print(f"  ❌ 等待超时（{poll_timeout}s），{date} 可能处理失败")
            return False
        
        # 定期打印进度
        if poll_count % max(1, (poll_timeout // poll_interval // 10)) == 0:
            print(f"     [{datetime.now().strftime('%H:%M:%S')}] 已等待 {int(elapsed)}s...")
        
        time.sleep(poll_interval)


def cleanup_work_dir(
    date: str,
    server: str,
    server_user: str,
    server_root: str,
) -> bool:
    """清理服务器上的临时数据（完成后）"""
    work_dir = f"{server_root}/work/{date}"
    cmd = f'ssh {server_user}@{server} "rm -rf {work_dir}/* && echo 临时数据已清理"'
    print(f"  清理 {date} 临时数据...")
    rc = run_cmd(cmd, check=False)
    return rc == 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="本地按日期推送数据到服务器，等待处理完成后推送下一天"
    )
    p.add_argument("--manifest", required=True, help="manifest.csv 路径")
    p.add_argument("--server", required=True, help="服务器地址（如 venus3.ihpc.uts.edu.au）")
    p.add_argument("--server-user", required=True, help="服务器 SSH 用户（如 chmai）")
    p.add_argument("--server-root", default="/srv/light_batch", help="服务器工作根目录")
    p.add_argument("--local-user", required=True, help="本地 SSH 用户（如 zekai）")
    p.add_argument("--poll-interval", type=int, default=10, help="轮询间隔（秒）")
    p.add_argument("--poll-timeout", type=int, default=3600, help="单日处理超时（秒）")
    p.add_argument("--dry-run", action="store_true", help="仅模拟，不真正执行")
    p.add_argument("--date", help="仅推送指定日期（YYYY_M_D）")
    p.add_argument("--skip-cleanup", action="store_true", help="完成后不清理临时数据")
    
    args = p.parse_args(argv)
    
    # 解析 manifest
    groups = parse_manifest(args.manifest)
    if args.date:
        groups = {k: v for k, v in groups.items() if k == args.date}
    
    if not groups:
        print("❌ manifest.csv 中未找到任何视频")
        return 1
    
    print(f"📋 共 {len(groups)} 天数据待处理")
    for date in sorted(groups.keys()):
        print(f"   {date}: {len(groups[date])} 个文件")
    
    print("\n" + "="*60)
    
    # 逐日处理
    for i, date in enumerate(sorted(groups.keys()), 1):
        files = groups[date]
        print(f"\n[{i}/{len(groups)}] 处理日期 {date}")
        print("="*60)
        
        # 1. 推送数据
        ok = rsync_day_to_server(
            date, files,
            args.server, args.server_user, args.server_root,
            args.local_user,
            dry_run=args.dry_run
        )
        if not ok:
            print(f"❌ {date} 推送失败，跳过此日期")
            continue
        
        if args.dry_run:
            print("  (模拟模式，跳过后续步骤)")
            continue
        
        # 2. 创建 .ready 标记
        ok = create_ready_marker(date, args.server, args.server_user, args.server_root)
        if not ok:
            print(f"❌ 无法创建 .ready 标记，跳过此日期")
            continue
        
        # 3. 等待 .done 标记
        ok = wait_for_done_marker(
            date, args.server, args.server_user, args.server_root,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout
        )
        if not ok:
            print(f"⚠️  {date} 处理超时或失败，请手动检查服务器")
            continue
        
        # 4. 清理临时数据
        if not args.skip_cleanup:
            cleanup_work_dir(date, args.server, args.server_user, args.server_root)
        
        print()
    
    print("\n" + "="*60)
    print("✅ 所有日期处理完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
