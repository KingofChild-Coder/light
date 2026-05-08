#!/usr/bin/env python3
"""
服务器端批处理脚本：监听 /srv/light_batch/work/{date}/.ready，处理该天数据，创建 .done 标记。

使用流程（后台运行）：
  python3 server_batch_process.py \
    --work-root /srv/light_batch \
    --poll-interval 5 \
    --infer-script /path/to/infer_origin.py

脚本行为：
  1. 扫描 /srv/light_batch/work/ 目录
  2. 找到 .ready 标记的目录，标记为"待处理"
  3. 启动多进程推理任务
  4. 完成后创建 .done 标记
  5. 清理临时视频文件（可选）
  6. 等待下一个 .ready

日志：
  /srv/light_batch/logs/{date}.log
"""

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

class ServerBatchProcessor:
    def __init__(
        self,
        work_root: str,
        db_root: str,
        log_root: str,
        infer_script: str,
        poll_interval: int = 5,
        num_workers: int = 4,
    ):
        self.work_root = Path(work_root)
        self.db_root = Path(db_root)
        self.log_root = Path(log_root)
        self.infer_script = infer_script
        self.poll_interval = poll_interval
        self.num_workers = num_workers
        
        # 确保目录存在
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.db_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)
    
    def log(self, date: str, msg: str):
        """记录日志到文件"""
        log_file = self.log_root / f"{date}.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        print(line.rstrip())
        with open(log_file, "a") as fh:
            fh.write(line)
    
    def scan_ready_dates(self) -> list[str]:
        """扫描 work/ 目录，找出所有有 .ready 标记的日期"""
        ready_dates = []
        if not self.work_root.exists():
            return ready_dates
        
        for date_dir in sorted(self.work_root.iterdir()):
            if not date_dir.is_dir():
                continue
            ready_marker = date_dir / ".ready"
            done_marker = date_dir / ".done"
            
            # 跳过已完成的
            if done_marker.exists():
                continue
            
            # 找到 .ready 标记的目录
            if ready_marker.exists():
                ready_dates.append(date_dir.name)
        
        return ready_dates
    
    def count_videos(self, date: str) -> int:
        """计算某日期目录下的视频文件数"""
        date_dir = self.work_root / date
        count = sum(1 for p in date_dir.glob("*.MP4")) + sum(1 for p in date_dir.glob("*.mp4"))
        return count
    
    def run_inference(self, date: str) -> bool:
        """启动该日期的推理任务"""
        date_dir = self.work_root / date
        db_file = self.db_root / f"infer_results_{date}.db"
        log_file = self.log_root / f"{date}_infer.log"
        
        self.log(date, f"========== BEGIN {date} ==========")
        self.log(date, f"输入目录: {date_dir}")
        self.log(date, f"输出数据库: {db_file}")
        
        video_count = self.count_videos(date)
        if video_count == 0:
            self.log(date, "❌ 未找到视频文件，跳过")
            return False
        
        self.log(date, f"找到 {video_count} 个视频文件")
        
        # 构建推理命令
        # 假设 infer_origin.py 支持 --video-dir 和 --db-path 参数
        # 如果不支持，需要修改或通过环境变量
        cmd = (
            f"python3 {self.infer_script} "
            f"--video-dir {shlex.quote(str(date_dir))} "
            f"--db-path {shlex.quote(str(db_file))} "
            f"> {shlex.quote(str(log_file))} 2>&1"
        )
        
        self.log(date, f"========== INFER START ==========")
        self.log(date, f"命令: {cmd}")
        
        start_time = time.time()
        rc = os.system(cmd)
        elapsed = time.time() - start_time
        
        if rc == 0:
            self.log(date, f"✅ 推理完成 (耗时: {int(elapsed)}s)")
            self.log(date, f"========== INFER DONE ==========")
            return True
        else:
            self.log(date, f"❌ 推理失败 (exit code: {rc})")
            return False
    
    def cleanup_work_dir(self, date: str):
        """清理该日期的临时数据"""
        date_dir = self.work_root / date
        self.log(date, "========== CLEANUP START ==========")
        
        # 删除所有视频和 JSON 文件
        for pattern in ["*.MP4", "*.mp4", "*.json"]:
            for f in date_dir.glob(pattern):
                try:
                    f.unlink()
                    self.log(date, f"  删除: {f.name}")
                except Exception as e:
                    self.log(date, f"  ⚠️  无法删除 {f.name}: {e}")
        
        # 删除 .ready 标记
        ready_marker = date_dir / ".ready"
        if ready_marker.exists():
            ready_marker.unlink()
            self.log(date, "  删除: .ready")
        
        self.log(date, "========== CLEANUP DONE ==========")
    
    def create_done_marker(self, date: str):
        """创建 .done 标记，告诉本地脚本处理完成"""
        date_dir = self.work_root / date
        done_marker = date_dir / ".done"
        done_marker.touch()
        self.log(date, f"✅ 创建 .done 标记")
        self.log(date, f"========== END {date} ==========\n")
    
    def process_one(self, date: str) -> bool:
        """处理单个日期的完整流程"""
        try:
            # 1. 运行推理
            ok = self.run_inference(date)
            if not ok:
                self.log(date, "推理失败，跳过清理和标记")
                return False
            
            # 2. 清理临时数据
            self.cleanup_work_dir(date)
            
            # 3. 创建 .done 标记
            self.create_done_marker(date)
            
            return True
        except Exception as e:
            self.log(date, f"❌ 异常错误: {e}")
            return False
    
    def run_daemon(self):
        """以守护进程方式运行：持续监听新的 .ready 标记"""
        print(f"🚀 服务器批处理守护进程启动")
        print(f"   工作根目录: {self.work_root}")
        print(f"   轮询间隔: {self.poll_interval}s")
        print(f"   监听中...\n")
        
        processed_dates = set()
        
        try:
            while True:
                ready_dates = self.scan_ready_dates()
                
                for date in ready_dates:
                    if date not in processed_dates:
                        print(f"\n🔔 检测到 {date} 待处理")
                        self.process_one(date)
                        processed_dates.add(date)
                
                time.sleep(self.poll_interval)
        
        except KeyboardInterrupt:
            print("\n\n用户中断，守护进程退出")


def main(argv=None):
    p = argparse.ArgumentParser(description="服务器端批处理守护进程")
    p.add_argument("--work-root", default="/srv/light_batch/work", help="工作目录根")
    p.add_argument("--db-root", default="/srv/light_batch/db", help="数据库目录根")
    p.add_argument("--log-root", default="/srv/light_batch/logs", help="日志目录根")
    p.add_argument("--infer-script", default="/home/chmai/Data/light/infer_origin.py", help="推理脚本路径")
    p.add_argument("--poll-interval", type=int, default=5, help="轮询间隔（秒）")
    p.add_argument("--num-workers", type=int, default=4, help="并发工作进程数（预留）")
    p.add_argument("--date", help="仅处理指定日期（不进入守护模式）")
    
    args = p.parse_args(argv)
    
    processor = ServerBatchProcessor(
        args.work_root,
        args.db_root,
        args.log_root,
        args.infer_script,
        poll_interval=args.poll_interval,
        num_workers=args.num_workers,
    )
    
    if args.date:
        # 单次处理
        return 0 if processor.process_one(args.date) else 1
    else:
        # 守护进程
        processor.run_daemon()
        return 0


if __name__ == "__main__":
    sys.exit(main())
