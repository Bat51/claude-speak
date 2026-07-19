#!/usr/bin/env python3
"""
claude-speak configuration server.

Provides a web UI for testing voices and configuring settings.
Run this, and it opens a browser with the settings page.

Usage:
    python configure.py              # Opens browser to settings page
    python configure.py --port 8910  # Custom port
    python configure.py --no-browser # Don't auto-open browser
"""

import asyncio
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Import the v2 engine (speak.py lives next to this file)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speak

CLAUDE_PROJECTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "projects")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "claude_speak_previews")


def encode_cwd_to_dirname(cwd):
    """Encode a working directory path to Claude's project directory name."""
    path = os.path.normpath(cwd)
    return path.replace(":", "-").replace("\\", "-").replace("/", "-")


def decode_dirname(dirname):
    """Best-effort decode of dirname back to a readable path.

    Supports two encoding formats:
      1. Legacy dash-separated: C--Projects-MyApp (from replace-based encoding)
      2. Base64 URL-safe: encoded with base64.urlsafe_b64encode (in case
         Claude Code's own encoding scheme changes)
    """
    # Try base64 decoding first — base64url uses [A-Za-z0-9_-] and optional '=' padding.
    # Legacy dirnames always contain '--' (from drive letter colon) on Windows or start
    # with a dash on Unix, so a valid base64 dirname is distinguishable.
    if not dirname.startswith('-') and '--' not in dirname:
        try:
            # Add padding if needed (base64 requires length divisible by 4)
            padded = dirname + '=' * (-len(dirname) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode('utf-8')
            # Sanity check: decoded path should look like an absolute path
            if decoded.startswith('/') or (len(decoded) >= 3 and decoded[1] == ':'):
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass  # Not base64, fall through to legacy decoding

    # Legacy dash-separated decoding
    if os.name == 'nt':
        parts = dirname.split('-')
        # Find drive letter pattern: single letter followed by empty string (from ::)
        if len(parts) >= 3 and len(parts[0]) == 1 and parts[0].isalpha() and parts[1] == '':
            drive = parts[0] + ':\\'
            rest = '\\'.join(p for p in parts[2:] if p)
            return drive + rest
    return '/' + '/'.join(p for p in dirname.split('-') if p)


class ConfigHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the settings UI and API."""

    # CSRF token shared across all handler instances (set by the server)
    csrf_token = None

    def _check_origin(self):
        """Validate Origin header on POST requests to prevent CSRF attacks.

        Accepts requests from localhost origins (any port) or requests with
        no Origin header (same-origin requests from older browsers).
        Returns True if the request is allowed, False otherwise.
        """
        origin = self.headers.get('Origin')
        if origin is None:
            # No Origin header — same-origin request (e.g., from same page fetch)
            return True
        parsed_origin = urlparse(origin)
        # Allow localhost variants only
        if parsed_origin.hostname in ('localhost', '127.0.0.1', '::1'):
            return True
        return False

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/settings.html':
            self._serve_html()
        elif parsed.path == '/api/voices':
            self._api_list_voices()
        elif parsed.path == '/api/projects':
            self._api_list_projects()
        elif parsed.path == '/api/settings':
            params = parse_qs(parsed.query)
            project = params.get('project', [None])[0]
            self._api_get_settings(project)
        elif parsed.path == '/api/csrf-token':
            self._api_csrf_token()
        elif parsed.path.startswith('/audio/'):
            self._serve_audio(parsed.path)
        else:
            self.send_error(404)

    def do_POST(self):
        # CSRF protection: validate Origin header
        if not self._check_origin():
            self._json_response({'error': 'Forbidden: invalid Origin header'}, 403)
            return

        # CSRF protection: validate token (if client sends one)
        csrf_header = self.headers.get('X-CSRF-Token')
        if csrf_header is not None and csrf_header != self.csrf_token:
            self._json_response({'error': 'Forbidden: invalid CSRF token'}, 403)
            return

        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length else b'{}'

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json_response({'error': 'Invalid JSON'}, 400)
            return

        if parsed.path == '/api/preview':
            self._api_preview(data)
        elif parsed.path == '/api/settings':
            self._api_save_settings(data)
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-CSRF-Token')
        self.end_headers()

    # ─── Page Serving ────────────────────────────────────────────────────────

    def _serve_html(self):
        """Serve the settings.html page."""
        html_path = os.path.join(SCRIPT_DIR, 'settings.html')
        try:
            with open(html_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, 'settings.html not found')

    def _serve_audio(self, path):
        """Serve a generated audio preview file."""
        # Decode URL-encoded characters FIRST to prevent %2f/%5c bypass
        filename = unquote(path.split('/')[-1])
        # Strip any directory components regardless of encoding tricks
        filename = os.path.basename(filename)
        # Reject directory traversal patterns and empty filenames
        if not filename or '..' in filename:
            self.send_error(403)
            return
        # Verify the resolved path is within PREVIEW_DIR
        audio_path = os.path.realpath(os.path.join(PREVIEW_DIR, filename))
        if not audio_path.startswith(os.path.realpath(PREVIEW_DIR) + os.sep):
            self.send_error(403)
            return

        if os.path.exists(audio_path):
            with open(audio_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', len(content))
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    # ─── API Endpoints ───────────────────────────────────────────────────────

    def _api_csrf_token(self):
        """GET /api/csrf-token - Return the current CSRF token for POST requests."""
        self._json_response({'token': self.csrf_token})

    def _api_list_voices(self):
        """GET /api/voices - List all available edge-tts voices."""
        try:
            import edge_tts
            voices = asyncio.run(edge_tts.list_voices())
            self._json_response(voices)
        except ImportError:
            self._json_response({'error': 'edge-tts not installed. Run: pip install edge-tts'}, 500)
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _api_list_projects(self):
        """GET /api/projects - List recently active projects (last 24h)."""
        import time as _time
        now = _time.time()
        cutoff = now - 86400  # 24 hours ago

        projects = []
        if os.path.exists(CLAUDE_PROJECTS_DIR):
            for dirname in os.listdir(CLAUDE_PROJECTS_DIR):
                dirpath = os.path.join(CLAUDE_PROJECTS_DIR, dirname)
                if not os.path.isdir(dirpath):
                    continue

                # Find the most recently modified JSONL file
                jsonl_files = [
                    os.path.join(dirpath, f) for f in os.listdir(dirpath)
                    if f.endswith('.jsonl')
                ]
                if not jsonl_files:
                    continue

                last_active = max(os.path.getmtime(f) for f in jsonl_files)

                # Only include projects active in the last 24 hours
                if last_active < cutoff:
                    continue

                decoded_path = decode_dirname(dirname)
                is_paused = os.path.exists(os.path.join(dirpath, 'speech-paused'))

                voice = None
                voice_file = os.path.join(dirpath, 'speech-voice')
                if os.path.exists(voice_file):
                    try:
                        with open(voice_file, 'r') as f:
                            voice = f.read().strip()
                    except OSError:
                        pass

                projects.append({
                    'dirname': dirname,
                    'path': decoded_path,
                    'name': os.path.basename(decoded_path.rstrip('/\\')),
                    'voice': voice,
                    'paused': is_paused,
                    'last_active': last_active,
                })

        # Sort by most recently active first
        projects.sort(key=lambda p: p['last_active'], reverse=True)
        self._json_response(projects)

    def _api_get_settings(self, project_path):
        """GET /api/settings?project=<path> - Get settings for a project."""
        settings = {
            'paused': False,
            'voice': None,
            'global_voice': None,
        }

        if project_path:
            dirname = encode_cwd_to_dirname(project_path)
            project_dir = os.path.join(CLAUDE_PROJECTS_DIR, dirname)

            pause_file = os.path.join(project_dir, 'speech-paused')
            settings['paused'] = os.path.exists(pause_file)

            voice_file = os.path.join(project_dir, 'speech-voice')
            if os.path.exists(voice_file):
                try:
                    with open(voice_file, 'r') as f:
                        v = f.read().strip()
                    if v:
                        settings['voice'] = v
                except OSError:
                    pass

        # Check global voice
        global_voice_file = os.path.join(os.path.expanduser("~"), ".claude", "speech-voice")
        if os.path.exists(global_voice_file):
            try:
                with open(global_voice_file, 'r') as f:
                    v = f.read().strip()
                if v:
                    settings['global_voice'] = v
            except OSError:
                pass

        self._json_response(settings)

    def _api_save_settings(self, data):
        """POST /api/settings - Save settings for a project."""
        # Validate POST data types
        if not isinstance(data, dict):
            self._json_response({'error': 'Request body must be a JSON object'}, 400)
            return

        project_path = data.get('project')
        voice = data.get('voice')
        paused = data.get('paused')

        # Type validation: project must be a string (or absent/null for global)
        if project_path is not None and not isinstance(project_path, str):
            self._json_response({'error': "'project' must be a string"}, 400)
            return
        # Type validation: voice must be a string (or absent/null)
        if voice is not None and not isinstance(voice, str):
            self._json_response({'error': "'voice' must be a string"}, 400)
            return
        # Type validation: paused must be a boolean (or absent/null)
        if paused is not None and not isinstance(paused, bool):
            self._json_response({'error': "'paused' must be a boolean"}, 400)
            return

        if project_path:
            dirname = encode_cwd_to_dirname(project_path)
            config_dir = os.path.join(CLAUDE_PROJECTS_DIR, dirname)
        else:
            # Global settings
            config_dir = os.path.join(os.path.expanduser("~"), ".claude")

        os.makedirs(config_dir, exist_ok=True)

        # Save voice
        if voice is not None:
            voice_file = os.path.join(config_dir, 'speech-voice')
            if voice == '' or voice == 'default':
                if os.path.exists(voice_file):
                    os.remove(voice_file)
            else:
                with open(voice_file, 'w') as f:
                    f.write(voice)

        # Save paused state
        if paused is not None:
            pause_file = os.path.join(config_dir, 'speech-paused')
            if paused:
                Path(pause_file).touch()
            elif os.path.exists(pause_file):
                os.remove(pause_file)

        self._json_response({'ok': True})

    def _api_preview(self, data):
        """POST /api/preview - Generate and return preview audio URL."""
        text = data.get('text', 'Hello! I am your Claude Code assistant. Let me help you write better code today.')
        voice = data.get('voice', 'en-US-GuyNeural')
        rate = data.get('rate', '+0%')

        os.makedirs(PREVIEW_DIR, exist_ok=True)

        # Cache by content hash
        cache_key = hashlib.md5(f"{text}|{voice}|{rate}".encode()).hexdigest()[:16]
        filename = f"preview_{cache_key}.mp3"
        output_path = os.path.join(PREVIEW_DIR, filename)

        if not os.path.exists(output_path):
            if not speak.synthesize(text, voice, rate, output_path):
                self._json_response({'error': 'TTS generation failed'}, 500)
                return

        if not os.path.exists(output_path):
            self._json_response({'error': 'Audio file was not generated'}, 500)
            return

        self._json_response({'url': f'/audio/{filename}'})

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _json_response(self, data, status=200):
        """Send a JSON response."""
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        """Suppress default request logging (too noisy)."""
        pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Allow concurrent requests (preview generation can be slow)."""
    allow_reuse_address = True
    daemon_threads = True


def cleanup_previews(max_age_seconds=None):
    """Clean up preview audio files.

    Args:
        max_age_seconds: If provided, only delete files older than this many seconds.
                         If None, delete all preview files (used on startup/shutdown).
    """
    if not os.path.exists(PREVIEW_DIR):
        return
    if max_age_seconds is None:
        # Full cleanup — remove entire directory
        try:
            shutil.rmtree(PREVIEW_DIR, ignore_errors=True)
        except Exception:
            pass
    else:
        # Selective cleanup — only remove files older than max_age_seconds
        now = time.time()
        try:
            for filename in os.listdir(PREVIEW_DIR):
                filepath = os.path.join(PREVIEW_DIR, filename)
                try:
                    if os.path.isfile(filepath) and (now - os.path.getmtime(filepath)) > max_age_seconds:
                        os.remove(filepath)
                except OSError:
                    pass
        except OSError:
            pass


def _periodic_preview_cleanup(stop_event, interval_seconds=600, max_age_seconds=3600):
    """Background thread that periodically cleans up stale preview files.

    Args:
        stop_event: threading.Event to signal the thread to stop.
        interval_seconds: How often to run cleanup (default: 600 = 10 minutes).
        max_age_seconds: Delete files older than this (default: 3600 = 1 hour).
    """
    while not stop_event.wait(timeout=interval_seconds):
        cleanup_previews(max_age_seconds=max_age_seconds)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="claude-speak configuration server")
    parser.add_argument('--port', '-p', type=int, default=8910, help='Port (default: 8910)')
    parser.add_argument('--no-browser', action='store_true', help="Don't auto-open browser")
    args = parser.parse_args()

    # Clean up old previews on start
    cleanup_previews()

    # Generate CSRF token for this server session
    csrf_token = secrets.token_hex(32)
    ConfigHandler.csrf_token = csrf_token

    try:
        server = ThreadedTCPServer(("127.0.0.1", args.port), ConfigHandler)
    except OSError as e:
        if "Address already in use" in str(e) or "10048" in str(e):
            print(f"Port {args.port} is already in use. Try: python configure.py --port {args.port + 1}")
            sys.exit(1)
        raise

    # Start background thread for periodic preview cleanup (every 10 min, files > 1 hour)
    cleanup_stop = threading.Event()
    cleanup_thread = threading.Thread(
        target=_periodic_preview_cleanup,
        args=(cleanup_stop,),
        daemon=True,
        name='preview-cleanup',
    )
    cleanup_thread.start()

    url = f"http://localhost:{args.port}"
    print(f"claude-speak settings: {url}")
    print("Press Ctrl+C to stop\n")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        cleanup_stop.set()
        server.shutdown()
        cleanup_previews()


if __name__ == "__main__":
    main()
