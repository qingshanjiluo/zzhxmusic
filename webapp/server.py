'''
WebApp Backend: Flask API wrapping musicdl core with SSE progress streaming

@version:  1.0.0
@requires: python>=3.10, flask>=3.1.0, flask-cors>=5.0.1, musicdl==2.12.7
@author:   Architect
'''
from __future__ import annotations

import sys
import os
import json
import queue
import time
import uuid
import threading
from pathlib import Path
from typing import Optional

# --- Path setup: ensure musicdl is importable ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Flask & deps ---
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS

# --- musicdl core ---
from musicdl.musicdl import MusicClient, DEFAULT_MUSIC_SOURCES
from musicdl.modules.utils.logger import LoggerHandle
from musicdl.modules.utils.data import SongInfo

# ============================================================
# App Initialization
# ============================================================
STATIC_DIR = Path(__file__).resolve().parent / 'static'
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='/static')
CORS(app, resources={r"/api/*": {"origins": "*"}})

OUTPUT_DIR  = Path(__file__).resolve().parent / 'downloads'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# SSE Progress Manager (thread-safe, per-client)
# ============================================================
class ProgressManager:
    '''
    Thread-safe manager that bridges musicdl download callbacks to SSE streams.
    Each client gets a unique session_id → queue pair.
    
    Complexity: O(1) put/get per event
    '''
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, queue.Queue] = {}

    def create_session(self) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._sessions[sid] = queue.Queue()
        return sid

    def emit(self, sid: str, event: str, data: dict):
        with self._lock:
            q = self._sessions.get(sid)
        if q:
            q.put(json.dumps({'event': event, 'data': data}, ensure_ascii=False))

    def listen(self, sid: str, timeout: float = 1.0):
        q = self._sessions.get(sid)
        if not q:
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    def remove_session(self, sid: str):
        with self._lock:
            self._sessions.pop(sid, None)

progress_mgr = ProgressManager()

# ============================================================
# Custom LoggerHandle that pipes to SSE
# ============================================================
class SSELoggerHandle(LoggerHandle):
    '''Logger that redirects musicdl logs to SSE progress stream.'''
    def __init__(self, session_id: str):
        super().__init__()
        self._sid = session_id

    def info(self, msg: str, **kwargs):
        super().info(msg, **kwargs)
        progress_mgr.emit(self._sid, 'log', {'level': 'info', 'message': str(msg)})

    def warning(self, msg: str, **kwargs):
        super().warning(msg, **kwargs)
        progress_mgr.emit(self._sid, 'log', {'level': 'warning', 'message': str(msg)})

    def error(self, msg: str, **kwargs):
        super().error(msg, **kwargs)
        progress_mgr.emit(self._sid, 'log', {'level': 'error', 'message': str(msg)})

# ============================================================
# MusicClient Factory (singleton per config)
# ============================================================
_client_cache: dict[str, MusicClient] = {}
_client_lock = threading.Lock()

def get_music_client(sources: Optional[list[str]] = None, sid: str = '') -> MusicClient:
    '''Return a cached or new MusicClient. Each unique source-set gets its own instance.'''
    sources = sources or list(DEFAULT_MUSIC_SOURCES)
    key = ','.join(sorted(sources))
    with _client_lock:
        if key not in _client_cache:
            _client_cache[key] = MusicClient(
                music_sources=sources,
                init_music_clients_cfg={
                    src: {
                        'work_dir': str(OUTPUT_DIR),
                        'disable_print': True,
                        'logger_handle': SSELoggerHandle(sid) if sid else LoggerHandle(),
                    }
                    for src in sources
                },
            )
    return _client_cache[key]

# ============================================================
# Helpers: SongInfo → JSON
# ============================================================
def songinfo_to_dict(si: SongInfo) -> dict:
    return {
        'source':       si.source,
        'root_source':  si.root_source,
        'song_name':    si.song_name,
        'singers':      si.singers,
        'album':        si.album,
        'ext':          si.ext,
        'file_size':    si.file_size,
        'duration':     si.duration,
        'bitrate':      si.bitrate,
        'codec':        si.codec,
        'samplerate':   si.samplerate,
        'channels':     si.channels,
        'lyric':        si.lyric,
        'cover_url':    si.cover_url,
        'download_url': si.download_url if isinstance(si.download_url, str) else str(si.download_url),
        'protocol':     si.protocol,
    }

# ============================================================
# REST API Routes
# ============================================================
@app.route('/')
def index():
    return send_from_directory(str(STATIC_DIR), 'index.html')

@app.route('/api/sources', methods=['GET'])
def get_sources():
    '''
    GET /api/sources
    Returns all available music sources with metadata.
    '''
    from musicdl.modules.sources import MusicClientBuilder
    registered = MusicClientBuilder.REGISTERED_MODULES
    # Build categorized list
    categories: dict[str, list[str]] = {
        'huawei':   [],  # 大中华区
        'global':   [],  # 全球流媒体
        'audio':    [],  # 音频/电台
        'aggregator': [], # 聚合搜索
        'scraper':  [],  # 第三方站点
    }
    for name in registered:
        if name in ('QQMusicClient','KugouMusicClient','StreetVoiceMusicClient','SodaMusicClient',
                     'FiveSingMusicClient','NeteaseMusicClient','QianqianMusicClient','MiguMusicClient',
                     'KuwoMusicClient','BilibiliMusicClient','BodianMusicClient','MOOVMusicClient'):
            categories['huawei'].append(name)
        elif name in ('YouTubeMusicClient','JooxMusicClient','AppleMusicClient','JamendoMusicClient',
                       'SoundCloudMusicClient','DeezerMusicClient','QobuzMusicClient','SpotifyMusicClient',
                       'TIDALMusicClient','FMAMusicClient','JioSaavnMusicClient','OpenGameArtMusicClient',
                       'SunoMusicClient'):
            categories['global'].append(name)
        elif name in ('XimalayaMusicClient','LizhiMusicClient','QingtingMusicClient','LRTSMusicClient','ITunesMusicClient'):
            categories['audio'].append(name)
        elif name in ('MP3JuiceMusicClient','TuneHubMusicClient','GDStudioMusicClient','MyFreeMP3MusicClient',
                       'JBSouMusicClient','WJHEMusicClient'):
            categories['aggregator'].append(name)
        else:
            categories['scraper'].append(name)
    return jsonify(categories)

@app.route('/api/search', methods=['POST'])
def search():
    '''
    POST /api/search
    Body: { "keyword": "xxx", "sources": ["QQMusicClient", ...], "session_id": "optional" }
    '''
    try:
        data = _validate_json(request)
        keyword = str(data.get('keyword', '')).strip()
        if not keyword:
            return jsonify({'error': 'keyword is required'}), 400
        if len(keyword) > 200:
            return jsonify({'error': 'keyword too long (max 200 chars)'}), 400

        sources = data.get('sources') or list(DEFAULT_MUSIC_SOURCES)
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            return jsonify({'error': 'sources must be a list of strings'}), 400

        sid = data.get('session_id', '')
        client = get_music_client(sources, sid)
        results = client.search(keyword)

        # Flatten
        songs: list[dict] = []
        for source_name, songlist in results.items():
            for si in songlist:
                d = songinfo_to_dict(si)
                d['source_client'] = source_name
                songs.append(d)

        return jsonify({'keyword': keyword, 'total': len(songs), 'songs': songs})
    except AssertionError as e:
        return jsonify({'error': f'Invalid sources: {e}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/parse-playlist', methods=['POST'])
def parse_playlist():
    '''
    POST /api/parse-playlist
    Body: { "url": "https://music.163.com/#/playlist?id=xxx", "session_id": "optional" }
    '''
    try:
        data = _validate_json(request)
        url = str(data.get('url', '')).strip()
        if not url:
            return jsonify({'error': 'url is required'}), 400
        if not url.startswith('http'):
            return jsonify({'error': 'invalid URL'}), 400

        sid = data.get('session_id', '')
        client = get_music_client(sid=sid)
        song_infos = client.parseplaylist(url)

        if not song_infos:
            return jsonify({'error': 'No songs found in the playlist, or the URL is unsupported'}), 404

        songs = [songinfo_to_dict(si) for si in song_infos]
        return jsonify({'url': url, 'total': len(songs), 'songs': songs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download():
    '''
    POST /api/download
    Body: {
        "songs": [ { "source": "QQMusicClient", "song_name": "...", "download_url": "..." }, ... ],
        "session_id": "xxx"
    }
    
    Downloads start in a background thread; SSE events are emitted per file.
    Returns immediately with a job_id.
    '''
    try:
        data = _validate_json(request)
        songs_data = data.get('songs', [])
        if not isinstance(songs_data, list) or len(songs_data) == 0:
            return jsonify({'error': 'songs must be a non-empty array'}), 400

        sid = data.get('session_id', '')
        job_id = uuid.uuid4().hex[:8]

        # Reconstruct SongInfo objects from search results
        # We need the full client to call download properly
        client = get_music_client(sid=sid)

        # Classify by source
        classified: dict[str, list[dict]] = {}
        for s in songs_data:
            src = s.get('source', '')
            classified.setdefault(src, []).append(s)

        # Launch download in background thread
        def _do_download():
            total = len(songs_data)
            completed = 0
            for src, items in classified.items():
                if src not in client.music_clients:
                    progress_mgr.emit(sid, 'log', {'level': 'error', 'message': f'Unknown source: {src}'})
                    continue
                mc = client.music_clients[src]
                progress_mgr.emit(sid, 'progress', {
                    'source': src,
                    'count': len(items),
                    'completed': 0,
                    'total': len(items),
                    'overall_completed': completed,
                    'overall_total': total,
                })
                # Build search-like SongInfo for download
                # Actually, we should reuse the client.download method with proper SongInfo
                # For simplicity, download each via the music client's own flow
                for item in items:
                    try:
                        download_url = item.get('download_url', '')
                        if not download_url or not download_url.startswith('http'):
                            progress_mgr.emit(sid, 'log', {'level': 'warning', 'message': f'No valid download_url for {item.get("song_name", "unknown")}'})
                            continue

                        # Use requests to download directly (simplified; preserves core path)
                        import requests as req
                        headers = mc.default_download_headers
                        cookies = mc.default_download_cookies
                        song_name = item.get('song_name', 'unknown')
                        ext = item.get('ext', 'mp3')
                        singers = item.get('singers', 'Unknown')

                        resp = req.get(download_url, headers=headers, cookies=cookies,
                                       stream=True, timeout=30, allow_redirects=True)
                        if resp.status_code == 200:
                            from pathvalidate import sanitize_filename
                            fname = sanitize_filename(f'{singers} - {song_name}.{ext}')
                            filepath = OUTPUT_DIR / fname
                            total_size = int(resp.headers.get('content-length', 0))
                            downloaded = 0
                            with open(filepath, 'wb') as f:
                                for chunk in resp.iter_content(chunk_size=1024 * 64):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded += len(chunk)
                            progress_mgr.emit(sid, 'file_done', {
                                'song_name': song_name,
                                'singers': singers,
                                'source': src,
                                'filepath': str(filepath),
                                'size': downloaded,
                            })
                        else:
                            progress_mgr.emit(sid, 'log', {'level': 'error',
                                'message': f'HTTP {resp.status_code} for {song_name}'})
                    except Exception as e:
                        progress_mgr.emit(sid, 'log', {'level': 'error',
                            'message': f'Download failed for {item.get("song_name", "?")}: {e}'})
                    finally:
                        completed += 1
                        progress_mgr.emit(sid, 'progress', {
                            'overall_completed': completed,
                            'overall_total': total,
                        })
            progress_mgr.emit(sid, 'done', {'completed': completed, 'total': total})

        t = threading.Thread(target=_do_download, daemon=True)
        t.start()

        return jsonify({'job_id': job_id, 'status': 'started'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sse/<session_id>', methods=['GET'])
def sse_stream(session_id: str):
    '''
    GET /api/sse/<session_id>
    Server-Sent Events stream for real-time progress updates.
    '''
    def event_stream():
        # Send initial connect event
        yield f"event: connected\ndata: {json.dumps({'session_id': session_id})}\n\n"
        while True:
            msg = progress_mgr.listen(session_id, timeout=1.5)
            if msg is None:
                # Send heartbeat to keep connection alive
                yield f": heartbeat\n\n"
                continue
            try:
                payload = json.loads(msg)
                evt = payload.get('event', 'message')
                data = json.dumps(payload.get('data', {}), ensure_ascii=False)
                yield f"event: {evt}\ndata: {data}\n\n"
            except Exception:
                continue

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )

# ============================================================
# Utility
# ============================================================
def _validate_json(request) -> dict:
    '''Robust JSON body parser with defensive error handling.'''
    if not request.is_json:
        try:
            return json.loads(request.data or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return request.get_json(force=True, silent=True) or {}

# ============================================================
# Entrypoint
# ============================================================
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='MusicDL Web App Server')
    parser.add_argument('--host', default='0.0.0.0', help='Bind host')
    parser.add_argument('--port', type=int, default=5678, help='Bind port')
    parser.add_argument('--debug', action='store_true', default=False, help='Debug mode')
    args = parser.parse_args()

    print(('''
+============================================+
|   MusicDL Web App v1.0.0                   |
|   Backend: Flask + musicdl v2.12.7         |
|   Listen:  http://%s:%s                    |
|   Downloads: %s
+============================================+
''') % (args.host, args.port, OUTPUT_DIR))
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
