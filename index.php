<!DOCTYPE html>
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
            text-align: center;
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
        <div class="yt-title">YouTube</div>
        
        <div class="yt-access-instructions">
            <p>Bienvenido a reVCDOS - GTA Vice City en el navegador</p>
            <p>Usa el buscador para encontrar videos o haz clic abajo</p>
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

        <!-- Información del juego (muestra si tiene acceso) -->
        <div id="game-info" class="game-info">
            <h3>🎮 reVCDOS - GTA Vice City en el navegador</h3>
            <p>Juego completo de GTA Vice City corriendo en WebAssembly.</p>
            <p>Características: controles táctiles, motor de trampas (F3), guardados locales, idiomas EN/RU.</p>
            <p>Haz clic en "Jugar Ahora" para comenzar.</p>
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

        function searchYouTube() {
            var term = document.getElementById('searchInput').value;
            if (term.trim()) {
                window.location = 'https://www.youtube.com/results?q=' + encodeURIComponent(term);
            }
        }

        function playRandomVideo() {
            var terms = ['musica clásica relajante', 'game soundtrack retro', 'anime opening 90s', 'retro gaming music'];
            var randomTerm = terms[Math.floor(Math.random() * terms.length)];
            window.location = 'https://www.youtube.com/results?q=' + encodeURIComponent(randomTerm);
        }

        function goYouTubeSearch(term) {
            window.location = 'https://www.youtube.com/results?q=' + encodeURIComponent(term);
        }

        // Auto-foco en el input de búsqueda
        setTimeout(function() {
            document.getElementById('searchInput').focus();
        }, 500);

        function startGameNow() {
            // Marcar acceso como concedido y recargar
            fetch('?password=revcdos2024')
                .then(function() {
                    window.location.reload();
                });
        }
    </script>
</body>
</html>