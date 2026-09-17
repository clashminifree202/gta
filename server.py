import os
import sys
import asyncio
import argparse
import hashlib
import json
from typing import Optional
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import additions.saves as saves
from additions.auth import BasicAuthMiddleware
from additions.cache import proxy_and_cache, get_local_file
from additions.packed import init_packed_archive, get_packed_file, is_initialized as packed_is_initialized
from fastapi import Depends

# Add utils path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils'))

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--custom_saves", action="store_true")
parser.add_argument("--login", type=str)
parser.add_argument("--password", type=str)
parser.add_argument("--vcsky_local", type=str, nargs='?', const='vcsky', default=None,
                    help="Serve vcsky from local directory instead of proxy. Optionally specify path (default: vcsky/)")
parser.add_argument("--vcbr_local", type=str, nargs='?', const='vcbr', default=None,
                    help="Serve vcbr from local directory instead of proxy. Optionally specify path (default: vcbr/)")
parser.add_argument("--vcsky_url", type=str, default="https://cdn.dos.zone/vcsky/", help="Custom vcsky proxy URL")
parser.add_argument("--vcbr_url", type=str, default="https://br.cdn.dos.zone/vcsky/", help="Custom vcbr proxy URL")
parser.add_argument("--vcsky_cache", action="store_true", help="Cache vcsky files locally. If files are not found in the local directory, they will be downloaded from the specified URL and saved to the local directory.")
parser.add_argument("--vcbr_cache", action="store_true", help="Cache vcbr files locally. If files are not found in the local directory, they will be downloaded from the specified URL and saved to the local directory.")
parser.add_argument("--packed", type=str, nargs='?', const='revcdos.bin', default=None,
                    help="Serve vcsky/ and vcbr/ from packed archive. Can be a local file path or URL. "
                         "If URL, downloads to local file if not present. If no value specified, uses 'revcdos.bin'. "
                         "Supports brotli passthrough.")
parser.add_argument("--unpacked", type=str, default=None,
                    help="Unpack archive to local folders and serve from there. Can be a local .bin file or URL. "
                         "Unpacks to unpacked/{md5_hash}/ and sets vcsky_local/vcbr_local automatically. "
                         "If already unpacked, uses existing files without re-unpacking. "
                         "If URL, streams and unpacks during download using downloader_brotli.")
parser.add_argument("--pack", type=str, default=None,
                    help="Pack a folder to {hash}.bin archive. Can be a folder path or MD5 hash from unpacked/ "
                         "Packs all subfolders (vcsky/, vcbr/, etc.) into a single archive. "
                         "After packing, uses the archive with --packed mode to serve files.")
args = parser.parse_args()


def _md5_hash(text: str) -> str:
    """Get MD5 hash of text."""
    return hashlib.md5(text.encode()).hexdigest()


def _is_url(path: str) -> bool:
    """Check if path is a URL."""
    return path.startswith("http://") or path.startswith("https://")


def _is_md5_hash(text: str) -> bool:
    """Check if text is a valid MD5 hash (32 hex characters)."""
    if len(text) != 32:
        return False
    try:
        int(text, 16)
        return True
    except ValueError:
        return False


def _get_unpacked_dir(source: str) -> str:
    """
    Get unpacked directory path for a source.
    
    If source IS a valid MD5 hash (32 hex chars), uses it directly.
    Otherwise computes MD5 hash from the source string.
    """
    # Check if source itself is a valid MD5 hash
    if _is_md5_hash(source):
        return os.path.join("unpacked", source.lower())
    
    # Compute hash from source
    source_hash = _md5_hash(source)
    return os.path.join("unpacked", source_hash)


def _check_unpacked_exists(unpacked_dir: str) -> bool:
    """Check if unpacked directory exists and has content."""
    if not os.path.isdir(unpacked_dir):
        return False
    
    # Check if vcsky or vcbr subdirectory exists with files
    for subdir in ["vcsky", "vcbr"]:
        subdir_path = os.path.join(unpacked_dir, subdir)
        if os.path.isdir(subdir_path):
            # Check if there are any files in subdirectories
            for root, dirs, files in os.walk(subdir_path):
                if files:
                    return True
    
    return False


async def _unpack_from_url(url: str, output_dir: str) -> bool:
    """
    Unpack archive directly from URL using streaming download.
    Uses downloader_brotli for efficient stream unpacking.
    """
    try:
        from utils.downloader_brotli import download_and_unpack_async
        print(f"Streaming and unpacking from URL: {url}")
        print(f"Output directory: {output_dir}")
        await download_and_unpack_async(url, output_dir)
        return True
    except Exception as e:
        print(f"Error unpacking from URL: {e}")
        return False


async def _unpack_from_file(file_path: str, output_dir: str) -> bool:
    """
    Unpack archive from local file.
    Uses packer_brotli.unpack_file for unpacking.
    """
    try:
        from utils.packer_brotli import unpack_file
        print(f"Unpacking local file: {file_path}")
        print(f"Output directory: {output_dir}")
        
        # Run sync unpack in executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, unpack_file, file_path, output_dir)
        return True
    except Exception as e:
        print(f"Error unpacking file: {e}")
        return False


def pack_source(source: str) -> Optional[str]:
    """
    Pack folder contents into {hash}.bin archive.
    
    If source is an MD5 hash, uses unpacked/{hash}/ folder.
    Otherwise uses the folder path directly.
    
    Packs all subfolders (vcsky/, vcbr/, etc.) by:
    1. Creating archive from first subfolder using pack_folder()
    2. Adding remaining subfolders using add_folder()
    
    Args:
        source: Folder path or MD5 hash
        
    Returns:
        Output filename (e.g., "abc123...def.bin") or None if failed
    """
    from utils.packer_brotli import pack_folder, add_folder
    
    # Resolve source to folder path and output hash
    if _is_md5_hash(source):
        folder_path = os.path.join("unpacked", source.lower())
        output_hash = source.lower()
    else:
        folder_path = source.rstrip('/\\')
        output_hash = _md5_hash(os.path.basename(folder_path))
    
    if not os.path.isdir(folder_path):
        print(f"Error: Folder not found: {folder_path}")
        return None
    
    output_file = f"{output_hash}.bin"
    
    # Get immediate subdirectories (vcsky, vcbr, etc.)
    subdirs = sorted([d for d in os.listdir(folder_path)
                     if os.path.isdir(os.path.join(folder_path, d)) and not d.startswith('.')])
    
    if not subdirs:
        print(f"Error: No subdirectories found in {folder_path}")
        return None
    
    print(f"Packing {len(subdirs)} subfolders from {folder_path} to {output_file}")
    print(f"Subfolders: {', '.join(subdirs)}")
    print()
    
    # Pack first subfolder (creates new archive)
    first_subdir = os.path.join(folder_path, subdirs[0])
    print(f"=== Creating archive from {subdirs[0]} ===")
    pack_folder(first_subdir, output_file)
    
    # Add remaining subfolders
    for subdir_name in subdirs[1:]:
        subdir_path = os.path.join(folder_path, subdir_name)
        print(f"\n=== Adding {subdir_name} ===")
        add_folder(output_file, subdir_path)
    
    final_size = os.path.getsize(output_file)
    print(f"\n=== Packing complete ===")
    print(f"Output: {output_file} ({final_size:,} bytes)")
    
    return output_file


async def setup_unpacked(source: str) -> tuple:
    """
    Setup unpacked mode - unpack archive if needed and return local paths.
    
    Args:
        source: Local file path, URL to packed archive, or MD5 hash of existing unpacked folder
        
    Returns:
        Tuple of (vcsky_local_path, vcbr_local_path) or (None, None) if failed
    """
    unpacked_dir = _get_unpacked_dir(source)
    
    # Check if source is just an MD5 hash (use existing folder only)
    is_hash_only = _is_md5_hash(source)
    
    # Check if already unpacked
    if _check_unpacked_exists(unpacked_dir):
        print(f"Using existing unpacked directory: {unpacked_dir}")
    elif is_hash_only:
        # Source is MD5 hash but folder doesn't exist - error
        print(f"Error: Unpacked folder not found for hash: {source}")
        print(f"Expected directory: {unpacked_dir}")
        return None, None
    else:
        # Need to unpack
        print(f"Unpacking to: {unpacked_dir}")
        os.makedirs(unpacked_dir, exist_ok=True)
        
        if _is_url(source):
            # Stream unpack from URL
            success = await _unpack_from_url(source, unpacked_dir)
        else:
            # Unpack from local file
            if not os.path.isfile(source):
                print(f"Error: Archive file not found: {source}")
                return None, None
            success = await _unpack_from_file(source, unpacked_dir)
        
        if not success:
            print(f"Failed to unpack from: {source}")
            return None, None
    
    # Determine vcsky and vcbr paths
    vcsky_path = None
    vcbr_path = None
    
    # Check for vcsky folder
    vcsky_candidate = os.path.join(unpacked_dir, "vcsky")
    if os.path.isdir(vcsky_candidate):
        vcsky_path = vcsky_candidate
        print(f"  vcsky: {vcsky_path}")
    
    # Check for vcbr folder
    vcbr_candidate = os.path.join(unpacked_dir, "vcbr")
    if os.path.isdir(vcbr_candidate):
        vcbr_path = vcbr_candidate
        print(f"  vcbr: {vcbr_path}")
    
    if not vcsky_path and not vcbr_path:
        print(f"Warning: No vcsky or vcbr folders found in {unpacked_dir}")
        # Maybe the folders are directly in unpacked_dir without vcsky/vcbr prefix
        # Check if there's a subfolder that looks like the archive name
        for item in os.listdir(unpacked_dir):
            item_path = os.path.join(unpacked_dir, item)
            if os.path.isdir(item_path):
                vcsky_sub = os.path.join(item_path, "vcsky")
                vcbr_sub = os.path.join(item_path, "vcbr")
                if os.path.isdir(vcsky_sub):
                    vcsky_path = vcsky_sub
                if os.path.isdir(vcbr_sub):
                    vcbr_path = vcbr_sub
    
    return vcsky_path, vcbr_path


# Read password from environment variable (set in Render dashboard)
# If set, use it as the secret. If not, use default for backward compatibility.
SECRET_PASSWORD = os.environ.get("REVCDOS_PASSWORD", "revcdos2024")

# Track access - will be set to True at startup if env var is configured properly
VALID_PASSWORD = SECRET_PASSWORD
# Global flag: if REVCDOS_PASSWORD env var is set at startup, grant access automatically
ALLOW_ACCESS = bool(os.environ.get("REVCDOS_PASSWORD"))

app = FastAPI()

# Handle login/password as basic auth if provided
if args.login and args.password:
    app.add_middleware(BasicAuthMiddleware, username=args.login, password=args.password)

if args.custom_saves:
    app.include_router(saves.router)


# Global state for access tracking (simple in-memory)
# In production, use cookies or sessions
access_granted = False


@app.middleware("http")
async def access_middleware(request: Request, call_next):
    """
    Middleware to check for password authorization.
    Logic:
    - If REVCDOS_PASSWORD env var is set at startup (ALLOW_ACCESS=True), grant access automatically
    - Otherwise, check cookie or query parameter as before
    """
    global access_granted
    
    # If access is allowed via environment variable, grant access automatically
    if ALLOW_ACCESS:
        access_granted = True
        # Set cookie so frontend knows access is granted
        response = await call_next(request)
        response.headers["Set-Cookie"] = "revcdos_access=granted; path=/; max-age=86400"
        return response
    
    # Check cookie first
    cookies = request.cookies.get("revcdos_access")
    if cookies == "granted":
        access_granted = True
    
    # Check query parameter
    query_password = request.query_params.get("password")
    if query_password and query_password == SECRET_PASSWORD:
        # Set cookie for future requests
        response = Response("", status_code=200, headers={"Set-Cookie": "revcdos_access=granted; path=/; max-age=86400"})
        access_granted = True
        # Run next middleware/route
        response.body = await call_next(request).body
        return response
    
    # If password is wrong or missing, ensure access_granted stays False
    if query_password and query_password != SECRET_PASSWORD:
        access_granted = False
    
    response = await call_next(request)
    return response


# --- RUTA PRINCIPAL: YouTube Tapadera o Juego ---

# Lista de términos para búsquedas aleatorias en YouTube
YOUTUBE_SEARCH_TERMS = [
    "musica clásica relajante",
    "game soundtrack retro", 
    "anime opening 90s",
    "retro gaming music",
    "GTA Vice City soundtrack",
    "8-bit music",
    "chiptune",
    "videogame music nostalgic"
]

# HTML de la interfaz tipo YouTube (incrustado en Python)
YOUTUBE_HTML = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube - Videos de música</title>
    <style>
        :root {
            --youtube-red: #ff0000;
            --dark-gray: #202124;
            --medium-gray: #5f6368;
            --light-gray: #e8eaed;
            --white: #ffffff;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Roboto', Arial, sans-serif;
            background: var(--dark-gray);
            color: var(--light-gray);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        .yt-header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 56px;
            background: var(--dark-gray);
            border-bottom: 1px solid var(--medium-gray);
            display: flex;
            align-items: center;
            padding: 0 24px;
            z-index: 9999;
        }

        .yt-logo {
            height: 40px;
            width: 40px;
            background: url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' fill='%23ff000'/><path d='M0 0h64v64H0z' fill='none'/><path d='M2 58h60v6L2 2zM8 32h48v16L8 16V32zM24 40h16v8h-16v-8zM40 40h8v8h-8v-8z'/></svg>") no-repeat center;
            margin-right: 12px;
        }

        .yt-logo-text {
            font-size: 28px;
            font-weight: bold;
            color: var(--youtube-red);
        }

        .yt-search {
            flex: 1;
            margin: 0 16px;
            display: flex;
        }

        .yt-search-input {
            flex: 1;
            height: 40px;
            padding: 0 16px;
            font-size: 18px;
            border: 1px solid var(--medium-gray);
            border-radius: 24px;
            background: var(--medium-gray);
            color: var(--white);
            outline: none;
        }

        .yt-search-input::placeholder {
            color: var(--medium-gray);
        }

        .yt-search-btn {
            height: 40px;
            width: 40px;
            border: none;
            background: var(--youtube-red);
            color: var(--white);
            font-size: 24px;
            cursor: pointer;
        }

        .yt-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 120px 24px 24px;
        }

        .yt-title {
            font-size: 32px;
            margin-bottom: 8px;
            color: var(--white);
        }

        .yt-subtitle {
            font-size: 18px;
            color: var(--medium-gray);
            margin-bottom: 32px;
            text-align: center;
        }

        .yt-access-instructions {
            background: var(--medium-gray);
            border: 1px solid var(--light-gray);
            border-radius: 8px;
            padding: 24px;
            max-width: 500px;
            margin-bottom: 32px;
        }

        .yt-access-instructions p {
            margin: 8px 0;
            font-size: 16px;
        }

        .yt-access-instructions strong {
            color: var(--youtube-red);
        }

        .yt-button {
            background: var(--youtube-red);
            border: none;
            color: var(--white);
            padding: 12px 24px;
            font-size: 18px;
            border-radius: 24px;
            cursor: pointer;
            font-weight: bold;
            width: 100%;
            margin: 8px 0;
            transition: background 0.2s;
        }

        .yt-button:hover {
            background: #cc0000;
        }

        .yt-random-action {
            background: var(--medium-gray);
            border: none;
            color: var(--white);
            padding: 12px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
            margin: 4px;
        }

        .yt-random-action:hover {
            background: #3a3d41;
        }

        .footer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            height: 40px;
            background: var(--dark-gray);
            border-top: 1px solid var(--medium-gray);
            display: flex;
            justify-content: center;
            align-items: center;
            font-size: 12px;
            color: var(--medium-gray);
            width: 100%;
        }

        .game-info {
            margin-top: 32px;
            padding: 20px;
            background: var(--medium-gray);
            border-radius: 8px;
            max-width: 500px;
            color: var(--white);
            display: none;
        }

        .game-info.visible {
            display: block;
        }
    </style>
</head>
<body>
    <!-- Header tipo YouTube -->
    <div class="yt-header">
        <div class="yt-logo"></div>
        <div class="yt-logo-text">YouTube</div>
        <div class="yt-search">
            <input type="text" class="yt-search-input" id="searchInput" placeholder="Buscar">
            <button class="yt-search-btn" onclick="searchYouTube()">✕</button>
        </div>
    </div>

    <!-- Contenido principal -->
    <div class="yt-main">
        <div class="yt-title">Disfruta de tus videos favoritos</div>
        
        <div class="yt-access-instructions">
            <p>Para acceder al <strong>juego secreto de GTA Vice City</strong>, escribe la contraseña:</p>
            <input type="text" id="passwordInput" style="
                width: 100%; 
                padding: 12px; 
                margin: 12px 0; 
                font-size: 18px;
                border: 1px solid var(--medium-gray);
                border-radius: 24px;
                background: var(--dark-gray);
                color: var(--white);
                outline: none;
            " onkeydown="if(event.key=== 'Enter') verifyPassword()">
            
            <div style="margin-top: 12px;">
                <button class="yt-button" onclick="verifyPassword()">Acceder al Juego</button>
            </div>
            
            <p style="margin-top: 16; font-size: 14px; color: var(--medium-gray);">
                Si no sabes la contraseña, abajo encontrarás videos aleatorios.<br>
                La contraseña actual es: <code>revcdos2024</code>
            </p>
        </div>

        <!-- Botones de acción -->
        <div style="display: flex; gap: 8px; margin-top: 32px; flex-wrap: wrap; justify-content: center;">
            <button class="yt-random-action" onclick="playRandomVideo()">
                ▶️ Video Aleatorio
            </button>
            <button class="yt-random-action" onclick="goYouTubeSearch('GTA Vice City')">
                🔍 Buscar GTA en YouTube
            </button>
        </div>

        <!-- Información del juego (oculta/muestra con JS) -->
        <div id="game-info" class="game-info">
            <h3>🎮 reVCDOS - GTA Vice City en el navegador</h3>
            <p>Juego completo de GTA Vice City corriendo en WebAssembly.</p>
            <p>Características: controles táctiles, motor de trampas (F3), guardados locales, idiomas EN/RU.</p>
            <p>Haz clic abajo para jugar ahora o escribe la contraseña.</p>
            <button class="yt-button" onclick="startGameNow()">Jugar Ahora</button>
        </div>
    </div>

    <!-- Footer -->
    <div class="footer">
        © 2026 reVCDOS - Para fines educativos y de desarrollo
    </div>

    <script>
        // Verificar si tiene acceso granted via cookie
        (function() {
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var cookie = cookies[i].trim();
                if (cookie.startsWith('revcdos_access=')) {
                    var hasAccess = (cookie.split('=')[1] === 'granted');
                    var gameInfo = document.getElementById('game-info');
                    if (hasAccess) {
                        gameInfo.classList.add('visible');
                    }
                }
            }
        })();

        function verifyPassword() {
            var pwd = document.getElementById('passwordInput').value.trim();
            // Enviar contraseña al servidor vía fetch
            fetch('?password=' + encodeURIComponent(pwd))
                .then(function(response) {
                    // Recargar página para que el servidor procese la cookie
                    window.location.reload();
                });
        }

        function startGameNow() {
            // Ir directamente al juego (simular que puso la contraseña correcta)
            fetch('?password=' + encodeURIComponent('revcdos2024'))
                .then(function() {
                    window.location.reload();
                });
        }

        function searchYouTube() {
            var term = document.getElementById('searchInput').value;
            if (term.trim()) {
                window.location = 'https://www.youtube.com/results?q=' + encodeURIComponent(term);
            }
        }

        function playRandomVideo() {
            var randomTerm = '<?php echo $YOUTUBE_SEARCH_TERMS[array_rand($YOUTUBE_SEARCH_TERMS)] ?>';
            // Actually this is Python, not PHP - we'll handle differently
            var terms = ['musica clásica relajante', 'game soundtrack retro', 'anime opening 90s', 'retro gaming music'];
            var randomIndex = Math.floor(Math.random() * terms.length);
            var randomTerm = terms[randomIndex];
            window.location = 'https://www.youtube.com/results?q=' + encodeURIComponent(randomTerm);
        }

        function goYouTubeSearch(term) {
            window.location = 'https://www.youtube.com/results?q=' + encodeURIComponent(term);
        }

        // Auto-foco en el input de contraseña
        setTimeout(function() {
            document.getElementById('passwordInput').focus();
        }, 500);
    </script>
</body>
</html>'''

# Reemplazamos los términos de YouTube con la lista Python
YOUTUBE_HTML = YOUTUBE_HTML.replace("<?php echo $YOUTUBE_SEARCH_TERMS[array_rand($YOUTUBE_SEARCH_TERMS)] ?>", 
    YOUTUBE_SEARCH_TERMS[0] if YOUTUBE_SEARCH_TERMS else "musica")

# Lista global para alternar búsquedas aleatorias
youtube_term_index = 0

@app.get("/")
async def root(request: Request):
    """
    Ruta principal: Sirve la interfaz tipo YouTube o el juego según acceso.
    """
    global access_granted
    
    # Verificar cookie de acceso
    cookies = request.cookies.get("revcdos_access")
    if cookies == "granted":
        access_granted = True
    
    # Si tiene acceso grantado (por cookie o env var), servir el juego
    if access_granted:
        # Servir el juego desde dist/
        if os.path.exists("dist/index.html"):
            with open("dist/index.html", "r", encoding="utf-8") as f:
                content = f.read()
            
            # Inyectar estado de custom_saves
            custom_saves_val = "1" if args.custom_saves else "0"
            content = content.replace(
                'new URLSearchParams(window.location.search).get("custom_saves") === "1"',
                f'"{custom_saves_val}" === "1"'
            )
            
            return HTMLResponse(
                content=content,
                headers={
                    "Cross-Origin-Opener-Policy": "same-origin",
                    "Cross-Origin-Embedder-Policy": "require-corp"
                }
            )
        return HTMLResponse("Juego no encontrado", status_code=404)
    
    # Si no tiene acceso, servir la interfaz tipo YouTube SIN input de contraseña
    # Alternar el término de búsqueda aleatorio cada vez que se carga la página
    global youtube_term_index
    current_term = YOUTUBE_SEARCH_TERMS[youtube_term_index]
    youtube_term_index = (youtube_term_index + 1) % len(YOUTUBE_SEARCH_TERMS)
    
    # Modificar el HTML: remover el input de contraseña y las instrucciones
    html = YOUTUBE_HTML
    # Remover el div de accesoInstructions que tiene el input de contraseña
    html = html.replace('''<div class="yt-access-instructions">
            <p>Para acceder al <strong>juego secreto de GTA Vice City</strong>, escribe la contraseña:</p>
            <input type="text" id="passwordInput" style="
                width: 100%; 
                padding: 12px; 
                margin: 12px 0; 
                font-size: 18px;
                border: 1px solid var(--medium-gray);
                border-radius: 24px;
                background: var(--dark-gray);
                color: var(--white);
                outline: none;
            " onkeydown="if(event.key=== 'Enter') verifyPassword()">
            
            <div style="margin-top: 12px;">
                <button class="yt-button" onclick="verifyPassword()">Acceder al Juego</button>
            </div>
            
            <p style="margin-top: 16; font-size: 14px; color: var(--medium-gray);">
                Si no sabes la contraseña, abajo encontrarás videos aleatorios.<br>
                La contraseña actual es: <code>revcdos2024</code>
            </p>
        </div>''', '')
    
    # Asegurarse de que el input de password no tenga focus auto
    html = html.replace('''setTimeout(function() {
            document.getElementById('passwordInput').focus();
        }, 500);''', '''setTimeout(function() {
            document.getElementById('searchInput').focus();
        }, 500);''')
    
    # Remover la función verifyPassword del script
    html = html.replace('''function verifyPassword() {
            var pwd = document.getElementById('passwordInput').value.trim();
            // Enviar contraseña al servidor vía fetch
            fetch('?password=' + encodeURIComponent(pwd))
                .then(function() {
                    // Después de setcookie, recargar la página
                    window.location.reload();
                });
        }''', '')
    
    # Remover startGameNow que fetch para password
    html = html.replace('''function startGameNow() {
            // Ir directamente al juego (simular que puso la contraseña correcta)
            fetch('?password=' + encodeURIComponent('revcdos2024'))
                .then(function() {
                    window.location.reload();
                });
        }''', '')
    
    # Actualizar el título y subtítulo
    html = html.replace('<div class="yt-title">Disfruta de tus videos favoritos</div>', '<div class="yt-title">YouTube</div>')
    html = html.replace('<div class="yt-subtitle">Para acceder al <strong>juego secreto de GTA Vice City</strong>, escribe la contraseña:</div>', '<div class="yt-subtitle">Busca tus videos favoritos</div>')
    
    # Remover el div game-info o hacerlo siempre visible si hay access granted planeado
    # Por ahora, mantenerlo oculto por defecto
    
    return HTMLResponse(content=html, media_type="text/html")


# Rutas de proxy para archivos del juego (vcsky y vcbr)
# Estas rutas ya están definidas más abajo en el archivo
async def vc_sky_proxy(request: Request, path: str):
    # Try packed archive first if enabled
    if args.packed and packed_is_initialized():
        packed_path = f"vcsky/{path}"
        if response := await get_packed_file(packed_path, request):
            return response
    
    # Try local directory
    if args.vcsky_local:
        local_path = os.path.join(args.vcsky_local, path)
        if response := get_local_file(local_path, request):
            return response
        # If local mode is explicitly set, don't fall through to proxy
        if args.vcsky_local is not None:
            raise HTTPException(status_code=404, detail="File not found")
    
    # Proxy mode
    url = f"{args.vcsky_url}{path}"
    if args.vcsky_cache:
        cache_path = os.path.join("vcsky", path)
        return await proxy_and_cache(request, url, cache_path)
    return await proxy_and_cache(request, url, disable_cache=True)


@app.api_route("/vcbr/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def vc_br_proxy(request: Request, path: str):
    # Try packed archive first if enabled
    if args.packed and packed_is_initialized():
        packed_path = f"vcbr/{path}"
        if response := await get_packed_file(packed_path, request):
            return response
    
    # Try local directory
    if args.vcbr_local:
        local_path = os.path.join(args.vcbr_local, path)
        if response := get_local_file(local_path, request):
            return response
        # If local mode is explicitly set, don't fall through to proxy
        if args.vcbr_local is not None:
            raise HTTPException(status_code=404, detail="File not found")
    
    # Proxy mode
    url = f"{args.vcbr_url}{path}"
    if args.vcbr_cache:
        cache_path = os.path.join("vcbr", path)
        return await proxy_and_cache(request, url, cache_path)
    return await proxy_and_cache(request, url, disable_cache=True)


# Ruta para servir archivos estáticos desde dist/
app.mount("/", StaticFiles(directory="dist"), name="root")


async def init_server():
    """Initialize server components that need async init."""
    global VCSKY_LOCAL_PATH, VCBR_LOCAL_PATH
    
    # Handle --unpacked mode first (takes precedence)
    if args.unpacked:
        vcsky_path, vcbr_path = await setup_unpacked(args.unpacked)
        if vcsky_path:
            VCSKY_LOCAL_PATH = vcsky_path
        if vcbr_path:
            VCBR_LOCAL_PATH = vcbr_path
    
    # Handle --packed mode
    if args.packed:
        # init_packed_archive handles both local paths and URLs
        # If URL is provided, it will download the file if not present locally
        result = await init_packed_archive(args.packed)
        if result is None:
            print(f"Warning: Failed to initialize packed archive from: {args.packed}")


def start_server(app=app, host="0.0.0.0", port=args.port):
    import uvicorn
    
    # Initialize server components
    if args.packed or args.unpacked:
        asyncio.run(init_server())
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    # Handle --pack first (pack folder then use packed mode)
    if args.pack:
        print(f"Pack mode: {args.pack}")
        packed_file = pack_source(args.pack)
        if packed_file:
            print(f"\nUsing packed archive: {packed_file}")
            args.packed = packed_file
        else:
            print("Packing failed, exiting.")
            sys.exit(1)
    
    print(f"Starting server on http://localhost:{args.port}")
    
    if args.unpacked:
        print(f"unpacked mode: {args.unpacked}")
    elif args.packed:
        print(f"packed: {args.packed}")
    else:
        vcsky_mode = 'local' if args.vcsky_local else 'proxy'
        vcbr_mode = 'local' if args.vcbr_local else 'proxy'
        vcsky_info = args.vcsky_local or args.vcsky_url
        vcbr_info = args.vcbr_local or args.vcbr_url
        print(f"vcsky: {vcsky_mode} ({vcsky_info})")
        print(f"vcbr: {vcbr_mode} ({vcbr_info})")
    
    start_server()