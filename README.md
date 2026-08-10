# DJ Music Metadata MCP (Python)

MCP server for DJs to organize metadata with API-based validation and batch writing.

## What this server does

- Scans a music folder and finds missing fields.
- Queries external APIs (MusicBrainz and iTunes) to suggest metadata with evidence.
- Computes a confidence score per track and blocks low-confidence writes in strict mode.
- Supports multiple genres per track.
- Writes metadata to MP3, FLAC, and M4A/MP4.

## Exposed MCP tools

1. scan_tracks
2. suggest_verified_metadata
3. apply_verified_metadata

## Requirements

- Python 3.10+

## Optional API credentials

- Spotify (recommended):
  - SPOTIFY_CLIENT_ID
  - SPOTIFY_CLIENT_SECRET
- SoundCloud (optional):
  - SOUNDCLOUD_CLIENT_ID

If these variables are not configured, the server still works with MusicBrainz and iTunes.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python server.py
```

Example (Windows PowerShell):

```powershell
$env:SPOTIFY_CLIENT_ID="your_client_id"
$env:SPOTIFY_CLIENT_SECRET="your_client_secret"
$env:SOUNDCLOUD_CLIENT_ID="your_client_id"
python server.py
```

## MCP setup (VS Code)

Example file: [mcp.server.json](mcp.server.json)

## Recommended workflow

1. Run scan_tracks to map missing fields.
2. Run suggest_verified_metadata with minConfidence between 0.78 and 0.90.
3. Review per-track evidence.
4. Run apply_verified_metadata with dryRun true.
5. If results look correct, run again with dryRun false.

## Example 1: scan

Tool: scan_tracks

```json
{
  "folderPath": "D:/DJ/Setlist",
  "recursive": true
}
```

## Example 2: API-based verified suggestion

Tool: suggest_verified_metadata

```json
{
  "folderPath": "D:/DJ/Setlist",
  "recursive": true,
  "minConfidence": 0.82,
  "onlyMissing": true
}
```

## Example 3: apply in strict mode

Tool: apply_verified_metadata

```json
{
  "dryRun": true,
  "strict": true,
  "minConfidence": 0.82,
  "updates": [
    {
      "filePath": "D:/DJ/Setlist/Artist - Track.mp3",
      "confidence": 0.91,
      "evidence": [
        { "source": "musicbrainz", "recordingId": "..." }
      ],
      "metadata": {
        "title": "Track",
        "artist": "Artist",
        "genre": ["Tech House", "House"],
        "comment": ["Validated by API"]
      }
    }
  ]
}
```

Set dryRun to false to write changes.
