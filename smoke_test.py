from __future__ import annotations

import argparse
import json
from pathlib import Path

from server import apply_verified_metadata, scan_tracks, suggest_verified_metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test for the metadata MCP server")
    parser.add_argument("folder", type=str, help="Music folder to test")
    parser.add_argument("--min-confidence", type=float, default=0.78)
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        raise SystemExit("Invalid folder")

    print("\n[1/3] scan_tracks")
    scan_result = scan_tracks(str(folder), recursive=True)
    print(json.dumps({
        "totalFiles": scan_result["totalFiles"],
        "missingAnyCount": scan_result["missingAnyCount"]
    }, ensure_ascii=False, indent=2))

    print("\n[2/3] suggest_verified_metadata")
    suggestions = suggest_verified_metadata(
        folderPath=str(folder),
        recursive=True,
        minConfidence=args.min_confidence,
        onlyMissing=True,
    )
    print(json.dumps({
        "totalSuggestions": suggestions["totalSuggestions"],
        "verifiedCount": suggestions["verifiedCount"],
        "blockedCount": suggestions["blockedCount"]
    }, ensure_ascii=False, indent=2))

    print("\n[3/3] apply_verified_metadata (strict dry-run)")
    dry_updates = [
        {
            "filePath": item["filePath"],
            "metadata": item["suggested"],
            "confidence": item["confidence"],
            "evidence": item["evidence"],
        }
        for item in suggestions["suggestions"]
    ]

    apply_result = apply_verified_metadata(
        updates=dry_updates,
        dryRun=True,
        strict=True,
        minConfidence=args.min_confidence,
    )
    print(json.dumps({
        "total": apply_result["total"],
        "blocked": apply_result["blocked"],
        "failed": apply_result["failed"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
