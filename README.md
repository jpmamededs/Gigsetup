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
4. organize_metadata
5. organize_directory_by_genre

### Notes about metadata correction

- `suggest_verified_metadata` agora aceita `fixExistingMetadata` (default `true`) para sugerir correcoes mesmo quando os campos ja estao preenchidos.
- Isso ajuda a corrigir genero preenchido incorretamente e limpar `title`/`artist` quando vierem misturados.

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

## Launcher desktop (React + Tailwind + Python)

O projeto agora inclui um launcher desktop para:

- Iniciar/parar o servidor MCP
- Selecionar modo `streamable-http` ou `stdio`
- Configurar conexao automatica para VS Code, Cursor e Claude Code

Stack da interface:

- Shell desktop: `pywebview` (Python)
- Frontend: `React` + `Tailwind CSS` (Vite)

Rodar launcher em desenvolvimento:

```bash
cd ui
npm install
npm run build
cd ..
python launcher.py
```

Observacao:

- Se o launcher for executavel (`.exe`), ele tambem funciona como processo do servidor via `--server`.

## Gerar executavel (Windows)

Use o script (compila frontend e empacota exe):

```bat
build_exe.bat
```

Resultado esperado:

```text
dist/DJMetadataLauncher.exe
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

Opcao recomendada: use o launcher e clique em `Conectar automaticamente` com `Agente = VS Code`.

## Connect (local and remote)

### 1. Local (recommended for personal use)

Run:

```bash
python server.py
```

Then configure your MCP client with stdio command.

### 2. Remote/public (HTTP + API key)

Create an `.env` file from `.env.example` and set `MCP_API_KEY`.

Run:

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 python server.py
```

Your endpoint will be:

```text
https://your-domain.com/mcp
```

### Cursor (remote)

`mcp.json`:

```json
{
  "mcpServers": {
    "dj-metadata": {
      "url": "https://your-domain.com/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

Opcao recomendada: use o launcher e clique em `Conectar automaticamente` com `Agente = Cursor`.

### Claude Code (remote)

```bash
claude mcp add --transport http dj-metadata https://your-domain.com/mcp --header "Authorization: Bearer <your-api-key>"
```

Opcao recomendada: use o launcher e clique em `Conectar automaticamente` com `Agente = Claude Code`.

### Notes

- This server modifies local files; if you host it remotely, ensure each user is isolated to their own folder.
- Keep `dryRun=true` as the default workflow before writing metadata.

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
