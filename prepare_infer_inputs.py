import argparse
import os
from pathlib import Path

VIDEO_EXTS = {".mp4", ".MP4"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare infer_origin.py inputs by pairing videos and LabelMe JSON files"
    )
    parser.add_argument("--video_root", type=Path, required=True, help="Root directory containing videos")
    parser.add_argument("--label_root", type=Path, required=True, help="Root directory containing LabelMe JSON files")
    parser.add_argument(
        "--target_dir",
        type=Path,
        default=Path("orgin-video"),
        help="Output directory to hold paired video/json links (default: orgin-video)",
    )
    parser.add_argument(
        "--mode",
        choices=["symlink", "copy"],
        default="symlink",
        help="How to place files into target_dir",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of paired videos to prepare (0 means all)",
    )
    parser.add_argument(
        "--clean-target",
        action="store_true",
        help="Remove existing .mp4/.MP4/.json files in target_dir before preparing",
    )
    return parser.parse_args()


def find_videos(video_root: Path):
    videos = []
    for p in video_root.rglob("*"):
        if p.is_file() and p.suffix in VIDEO_EXTS:
            videos.append(p)
    return sorted(videos)


def find_labels(label_root: Path):
    labels = {}
    for json_path in sorted(label_root.rglob("*.json")):
        stem = json_path.stem
        video_stem = stem.rsplit("_t", 1)[0]
        if video_stem not in labels:
            labels[video_stem] = json_path
    return labels


def remove_existing_inputs(target_dir: Path):
    for p in target_dir.iterdir():
        if p.is_file() and (p.suffix in VIDEO_EXTS or p.suffix == ".json"):
            p.unlink()


def place_file(src: Path, dst: Path, mode: str):
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if mode == "symlink":
        os.symlink(src, dst)
    else:
        dst.write_bytes(src.read_bytes())


def main():
    args = parse_args()

    if not args.video_root.exists():
        raise SystemExit(f"video_root does not exist: {args.video_root}")
    if not args.label_root.exists():
        raise SystemExit(f"label_root does not exist: {args.label_root}")

    args.target_dir.mkdir(parents=True, exist_ok=True)
    if args.clean_target:
        remove_existing_inputs(args.target_dir)

    videos = find_videos(args.video_root)
    label_map = find_labels(args.label_root)

    paired = 0
    missing_label = []
    collision = []

    for video_path in videos:
        stem = video_path.stem
        label_path = label_map.get(stem)
        if label_path is None:
            missing_label.append(stem)
            continue

        out_video = args.target_dir / video_path.name
        out_json = args.target_dir / label_path.name

        if out_video.exists() and out_video.resolve() != video_path.resolve():
            collision.append(str(out_video))
            continue
        if out_json.exists() and out_json.resolve() != label_path.resolve():
            collision.append(str(out_json))
            continue

        place_file(video_path.resolve(), out_video, args.mode)
        place_file(label_path.resolve(), out_json, args.mode)

        paired += 1
        if args.limit > 0 and paired >= args.limit:
            break

    print(f"Prepared pairs: {paired}")
    print(f"Videos scanned: {len(videos)}")
    print(f"JSON scanned: {len(label_map)}")
    print(f"Missing labels: {len(missing_label)}")
    if missing_label:
        print("Missing label stems (first 10):")
        for stem in missing_label[:10]:
            print(f"  - {stem}")
    if collision:
        print(f"Name collisions skipped: {len(collision)}")


if __name__ == "__main__":
    main()
