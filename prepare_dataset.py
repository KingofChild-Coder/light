#!/usr/bin/env python3
"""
简化版数据准备脚本 - 只需要改日期即可
用法: python prepare_dataset.py --date 2025_9_1
"""

import sys
from pathlib import Path
from prepare_infer_inputs import find_videos, find_labels, place_file

def prepare_dataset(date_str: str, mode: str = "symlink", limit: int = 0, target_dir: str = None):
    """
    根据日期准备数据集
    
    Args:
        date_str: 日期字符串，如 "2025_9_1"
        mode: "symlink" 或 "copy"
        limit: 限制配对数量，0表示全部
        target_dir: 目标目录路径，默认为 /home/zekai/light/light/orgin-video
    """
    # 构建路径
    video_root = Path(f'/media/zekai/Expansion/Experiment data CHAO_MAI/{date_str}/DJI')
    label_root = Path(f'/home/zekai/Data/traffic_light/Label_prepare_traffic/Label_prepare/{date_str}/DJI')
    if target_dir is None:
        target_dir = Path('/home/zekai/light/light/orgin-video_0915')
    else:
        target_dir = Path(target_dir)
    
    # 验证路径
    if not video_root.exists():
        print(f"❌ 视频目录不存在: {video_root}")
        return False
    if not label_root.exists():
        print(f"❌ 标签目录不存在: {label_root}")
        return False
    
    # 创建目标目录
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 清理现有文件
    VIDEO_EXTS = {".mp4", ".MP4"}
    for p in target_dir.iterdir():
        if p.is_file() and (p.suffix in VIDEO_EXTS or p.suffix == ".json"):
            p.unlink()
    
    print(f"📁 正在处理: {date_str}")
    print(f"   视频源: {video_root}")
    print(f"   标签源: {label_root}")
    print(f"   目标:   {target_dir}")
    print()
    
    # 查找和配对
    videos = find_videos(video_root)
    label_map = find_labels(label_root)
    
    paired = 0
    missing_label = []
    
    for video_path in videos:
        stem = video_path.stem
        label_path = label_map.get(stem)
        
        if label_path is None:
            missing_label.append(stem)
            continue
        
        out_video = target_dir / video_path.name
        out_json = target_dir / label_path.name
        
        place_file(video_path.resolve(), out_video, mode)
        place_file(label_path.resolve(), out_json, mode)
        
        paired += 1
        if limit > 0 and paired >= limit:
            break
    
    # 打印结果
    print(f"✅ 配对完成!")
    print(f"   配对数: {paired}")
    print(f"   视频总数: {len(videos)}")
    print(f"   标签总数: {len(label_map)}")
    print(f"   缺失标签: {len(missing_label)}")
    
    if missing_label:
        print(f"   缺失标签列表 (前10个):")
        for stem in missing_label[:10]:
            print(f"     - {stem}")
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="简化版数据准备脚本")
    parser.add_argument("--date", required=True, help="日期 (如: 2025_9_1)")
    parser.add_argument("--target", default="/home/zekai/light/light/orgin-video", help="目标目录 (默认: /home/zekai/light/light/orgin-video)")
    parser.add_argument("--mode", choices=["symlink", "copy"], default="symlink", help="symlink或copy")
    parser.add_argument("--limit", type=int, default=0, help="限制配对数量 (0=全部)")
    
    args = parser.parse_args()
    success = prepare_dataset(args.date, args.mode, args.limit, args.target)
    sys.exit(0 if success else 1)
