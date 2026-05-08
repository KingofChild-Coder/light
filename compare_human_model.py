"""
Compare model detections in infer_results_0901.db with hand-labeled CSV tags.

Hand-labeled CSV format is expected to look like:
  relative_time_ms,relative_time_text,absolute_time_text,tag_type,note

This script matches each hand-labeled timestamp to the nearest model snapshot
for the same video, then reports label agreement, time gap, and an optional
per-event detail table.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Optional


DB_PATH = Path("infer_results_0901.db")

HAND_TO_MODEL = {
    "red": "R",
    "r": "R",
    "green": "G",
    "g": "G",
}


@dataclass(frozen=True)
class HumanEvent:
    time_s: float
    label: str
    note: str = ""


@dataclass(frozen=True)
class ModelRow:
    time_s: float
    region_idx: int
    label: str
    confidence: float


@dataclass(frozen=True)
class ComparisonRow:
    video: str
    event_index: int
    human_time_s: float
    human_label: str
    model_time_s: Optional[float]
    delta_s: Optional[float]
    model_label: str
    model_region_idx: Optional[int]
    model_confidence: Optional[float]
    matched: bool
    note: str


def canonical_label(label: str | None) -> str:
    if label is None:
        return "None"
    text = str(label).strip()
    if not text:
        return "None"
    upper = text.upper()
    if upper in {"R", "G"}:
        return upper
    lower = text.lower()
    return HAND_TO_MODEL.get(lower, text)


def derive_video_name(csv_path: Path) -> str:
    stem = csv_path.stem
    if stem.endswith("_tag"):
        return stem[:-4]
    return stem


def iter_tag_csvs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*_tag.csv"))


def index_tag_csvs(path: Path) -> dict[str, Path]:
    if path.is_file():
        return {derive_video_name(path): path}

    indexed: dict[str, Path] = {}
    for csv_path in path.rglob("*_tag.csv"):
        indexed[derive_video_name(csv_path)] = csv_path
    return indexed


def load_human_events(csv_path: Path) -> list[HumanEvent]:
    events: list[HumanEvent] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                time_s = float(row["relative_time_ms"]) / 1000.0
            except (KeyError, TypeError, ValueError):
                continue
            label = canonical_label(row.get("tag_type"))
            if label not in {"R", "G"}:
                continue
            events.append(HumanEvent(time_s=time_s, label=label, note=(row.get("note") or "").strip()))
    return events


def load_model_rows(db_path: Path, video: str) -> list[ModelRow]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT time_s, region_idx, label, confidence, id
            FROM detections
            WHERE video = ?
            ORDER BY time_s ASC, region_idx ASC, confidence DESC, id ASC
            """,
            (video,),
        ).fetchall()
    finally:
        conn.close()

    best_per_time_region: dict[tuple[float, int], ModelRow] = {}
    for time_s, region_idx, label, confidence, _row_id in rows:
        key = (float(time_s), int(region_idx))
        candidate = ModelRow(
            time_s=float(time_s),
            region_idx=int(region_idx),
            label=canonical_label(label),
            confidence=float(confidence) if confidence is not None else -1.0,
        )
        current = best_per_time_region.get(key)
        if current is None or candidate.confidence > current.confidence:
            best_per_time_region[key] = candidate

    grouped: dict[float, list[ModelRow]] = {}
    for row in best_per_time_region.values():
        grouped.setdefault(row.time_s, []).append(row)

    snapshots: list[ModelRow] = []
    for time_s in sorted(grouped):
        snapshots.extend(sorted(grouped[time_s], key=lambda r: r.region_idx))
    return snapshots


def load_db_videos(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT video
            FROM detections
            ORDER BY video
            """
        ).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def group_model_by_time(rows: list[ModelRow]) -> tuple[list[float], dict[float, list[ModelRow]]]:
    times: list[float] = []
    grouped: dict[float, list[ModelRow]] = {}
    for row in rows:
        if row.time_s not in grouped:
            times.append(row.time_s)
            grouped[row.time_s] = []
        grouped[row.time_s].append(row)
    times.sort()
    return times, grouped


def select_model_row(
    rows: list[ModelRow],
    region_idx: Optional[int] = None,
) -> Optional[ModelRow]:
    if not rows:
        return None

    if region_idx is not None:
        for row in rows:
            if row.region_idx == region_idx:
                return row
        return None

    best_non_none: Optional[ModelRow] = None
    best_any: Optional[ModelRow] = None
    for row in rows:
        if best_any is None or row.confidence > best_any.confidence:
            best_any = row
        if row.label in {"R", "G"} and (best_non_none is None or row.confidence > best_non_none.confidence):
            best_non_none = row
    return best_non_none or best_any


def nearest_snapshot(
    times: list[float],
    grouped: dict[float, list[ModelRow]],
    target_time: float,
    tolerance_s: float,
) -> tuple[Optional[float], list[ModelRow]]:
    if not times:
        return None, []

    idx = bisect_left(times, target_time)
    candidates = []
    if idx < len(times):
        candidates.append(times[idx])
    if idx > 0:
        candidates.append(times[idx - 1])

    best_time = None
    best_gap = None
    for candidate_time in candidates:
        gap = abs(candidate_time - target_time)
        if best_gap is None or gap < best_gap:
            best_time = candidate_time
            best_gap = gap

    if best_time is None or best_gap is None or best_gap > tolerance_s:
        return None, []
    return best_time, grouped.get(best_time, [])


def compare_video(
    db_path: Path,
    csv_path: Path,
    tolerance_s: float,
    region_idx: Optional[int],
) -> tuple[str, list[ComparisonRow]]:
    video = derive_video_name(csv_path)
    human_events = load_human_events(csv_path)
    model_rows = load_model_rows(db_path, video)
    model_times, grouped = group_model_by_time(model_rows)

    comparisons: list[ComparisonRow] = []
    for event_index, event in enumerate(human_events, start=1):
        model_time_s, snapshot_rows = nearest_snapshot(model_times, grouped, event.time_s, tolerance_s)
        selected = select_model_row(snapshot_rows, region_idx=region_idx)
        if selected is None:
            comparisons.append(
                ComparisonRow(
                    video=video,
                    event_index=event_index,
                    human_time_s=event.time_s,
                    human_label=event.label,
                    model_time_s=model_time_s,
                    delta_s=abs(model_time_s - event.time_s) if model_time_s is not None else None,
                    model_label="None",
                    model_region_idx=None,
                    model_confidence=None,
                    matched=False,
                    note=event.note,
                )
            )
            continue

        comparisons.append(
            ComparisonRow(
                video=video,
                event_index=event_index,
                human_time_s=event.time_s,
                human_label=event.label,
                model_time_s=model_time_s,
                delta_s=abs(model_time_s - event.time_s) if model_time_s is not None else None,
                model_label=selected.label,
                model_region_idx=selected.region_idx,
                model_confidence=selected.confidence,
                matched=(selected.label == event.label),
                note=event.note,
            )
        )
    return video, comparisons


def format_seconds(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def print_summary(csv_path: Path, video: str, comparisons: list[ComparisonRow]) -> None:
    total = len(comparisons)
    compared = sum(1 for row in comparisons if row.model_time_s is not None)
    matched = sum(1 for row in comparisons if row.matched)
    if compared:
        deltas = [row.delta_s for row in comparisons if row.delta_s is not None]
        avg_gap = mean(deltas) if deltas else 0.0
        med_gap = median(deltas) if deltas else 0.0
    else:
        avg_gap = 0.0
        med_gap = 0.0

    accuracy = matched / compared * 100 if compared else 0.0
    coverage = compared / total * 100 if total else 0.0

    print(f"\n{csv_path.name} -> {video}")
    print(f"  human events: {total}")
    print(f"  matched snapshots: {compared} ({coverage:.1f}%)")
    print(f"  label agreement: {matched}/{compared} ({accuracy:.1f}%)")
    print(f"  time gap: mean {avg_gap:.3f}s, median {med_gap:.3f}s")
    print("  event details:")
    print("    idx  human_t   human  model_t   model  region  conf   gap     ok")
    for row in comparisons:
        print(
            "    "
            f"{row.event_index:>3}  "
            f"{row.human_time_s:>7.3f}  "
            f"{row.human_label:^5}  "
            f"{format_seconds(row.model_time_s):>7}  "
            f"{row.model_label:^5}  "
            f"{str(row.model_region_idx) if row.model_region_idx is not None else '-':>6}  "
            f"{row.model_confidence if row.model_confidence is not None else '':>5}  "
            f"{format_seconds(row.delta_s):>6}  "
            f"{'Y' if row.matched else 'N'}"
        )


def write_output_csv(output_path: Path, rows: list[ComparisonRow]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "video",
            "event_index",
            "human_time_s",
            "human_label",
            "model_time_s",
            "delta_s",
            "model_label",
            "model_region_idx",
            "model_confidence",
            "matched",
            "note",
        ])
        for row in rows:
            writer.writerow([
                row.video,
                row.event_index,
                f"{row.human_time_s:.6f}",
                row.human_label,
                format_seconds(row.model_time_s),
                format_seconds(row.delta_s),
                row.model_label,
                "" if row.model_region_idx is None else row.model_region_idx,
                "" if row.model_confidence is None else f"{row.model_confidence:.6f}",
                int(row.matched),
                row.note,
            ])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare model detections with hand-labeled traffic-light tags.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Hand-label CSV file or a directory containing *_tag.csv files")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to the model SQLite database")
    parser.add_argument("--tolerance", type=float, default=1.5, help="Max allowed time gap in seconds when snapping to the nearest model snapshot")
    parser.add_argument("--region-idx", type=int, default=None, help="Only compare a specific region index instead of the best region across all regions")
    parser.add_argument("--all-db", action="store_true", help="Compare every video in the database against matching *_tag.csv files in the given directory")
    parser.add_argument("--output", type=str, default=None, help="Optional CSV file to write combined comparison rows")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    input_path = Path(args.path)

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path.resolve()}")

    all_rows: list[ComparisonRow] = []
    total_events = 0
    total_matched = 0
    total_compared = 0
    missing_videos: list[str] = []
    compared_videos = 0

    if args.all_db:
        tag_root = input_path if input_path.is_dir() else input_path.parent
        csv_index = index_tag_csvs(tag_root)
        db_videos = load_db_videos(db_path)

        if not db_videos:
            raise SystemExit(f"No videos found in database: {db_path.resolve()}")

        for video in db_videos:
            csv_path = csv_index.get(video)
            if csv_path is None:
                missing_videos.append(video)
                continue
            video_name, comparisons = compare_video(db_path, csv_path, args.tolerance, args.region_idx)
            print_summary(csv_path, video_name, comparisons)
            all_rows.extend(comparisons)
            total_events += len(comparisons)
            total_compared += sum(1 for row in comparisons if row.model_time_s is not None)
            total_matched += sum(1 for row in comparisons if row.matched)
            compared_videos += 1
    else:
        csv_files = iter_tag_csvs(input_path)
        if not csv_files:
            raise SystemExit(f"No *_tag.csv files found under: {input_path.resolve()}")

        for csv_path in csv_files:
            video, comparisons = compare_video(db_path, csv_path, args.tolerance, args.region_idx)
            print_summary(csv_path, video, comparisons)
            all_rows.extend(comparisons)
            total_events += len(comparisons)
            total_compared += sum(1 for row in comparisons if row.model_time_s is not None)
            total_matched += sum(1 for row in comparisons if row.matched)
            compared_videos += 1

    if args.output:
        write_output_csv(Path(args.output), all_rows)
        print(f"\nWrote comparison rows to: {Path(args.output).resolve()}")

    if missing_videos:
        preview = ", ".join(missing_videos[:10])
        more = f" ... (+{len(missing_videos) - 10} more)" if len(missing_videos) > 10 else ""
        print(f"\nMissing hand labels for {len(missing_videos)} database videos: {preview}{more}")

    if total_events:
        overall_accuracy = total_matched / total_compared * 100 if total_compared else 0.0
        overall_coverage = total_compared / total_events * 100 if total_events else 0.0
        print("\nOverall")
        print(f"  events: {total_events}")
        print(f"  matched snapshots: {total_compared} ({overall_coverage:.1f}%)")
        print(f"  label agreement: {total_matched}/{total_compared} ({overall_accuracy:.1f}%)")
        if args.all_db:
            print(f"  compared videos: {compared_videos}")


if __name__ == "__main__":
    main()