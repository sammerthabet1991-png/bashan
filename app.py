        
        .youtube-card { width: 100%; height: 100%; max-width: 1250px; max-height: 700px; border-radius: 12px; border: 2px solid rgba(212, 175, 55, 0.4); background-color: #000; pointer-events: none; }
        .ticker-container { position: absolute; bottom: 0; left: 0; width: 100%; height: 50px; background: rgba(8, 11, 20, 0.98); border-top: 2px solid #d4af37; display: flex; align-items: center; z-index: 1000; pointer-events: none; }
        .ticker-title { background: linear-gradient(135deg, #d4af37, #aa7c11); color: #000; padding: 0 15px; height: 100%; display: flex; align-items: center; font-weight: 900; font-size: 16px; white-space: nowrap; }
        .ticker-wrap { width: 100%; overflow: hidden; white-space: nowrap; position: relative; }
        .ticker-move { display: inline-block; white-space: nowrap; padding-right: 100%; font-size: 17px; color: #ffffff; }
        .ticker-item { display: inline-block; padding: 0 20px; }
        #touch-overlay { position: fixed; bottom: 62px; left: 12px; width: auto; height: auto; z-index: 9999; background: rgba(0,0,0,.72); color: #fff; border: 1px solid #d4af37; border-radius: 8px; padding: 10px 14px; cursor: pointer; font-size: 14px; }
        .breaking-banner { position: absolute; bottom: 50px; left: 0; width: 100%; background: linear-gradient(90deg, #b71c1c, #d32f2f, #b71c1c); color: #ffffff; padding: 6px 15px; box-sizing: border-box; font-size: 16px; font-weight: 900; z-index: 999; display: none; align-items: center; border-top: 2px solid #ffeb3b; pointer-events: none; }
        @keyframes ticker { 0% { transform: translate3d(0, 0, 0); } 100% { transform: translate3d(100%, 0, 0); } }
    </style>
</head>
<body>
    <button id="touch-overlay" onclick="enableAudioAndPlay()">🔊 تفعيل الصوت إذا كان المتصفح يمنع التشغيل التلقائي</button>
    <div class="corner-logo"><img src="/logo.png" alt="Logo"></div>
    <div class="top-ticker-container">
        <div class="top-ticker-title">أخبار السويداء</div>
        <div class="ticker-wrap"><div class="ticker-move" id="top-ticker-content">جاري التحميل...</div></div>
    </div>
    <div class="center-stage" id="stage-container"></div>
    <div class="breaking-banner" id="breaking-banner"><span>🔴 عاجل: </span><span id="breaking-text"></span></div>
    <audio id="audio-player" preload="auto" style="display:none;"></audio>
    <div class="ticker-container">
        <div class="ticker-title">أخبار عالمية</div>
        <div class="ticker-wrap"><div class="ticker-move" id="ticker-content">جاري التحميل...</div></div>
    </div>
    <script>
        let imageList = [], songList = [], videoList = [], currentSongPath = "", lastMediaType = "", lastYoutubeUrl = "", activeVideoUrl = "";
        const audioPlayer = document.getElementById('audio-player');

        function enableAudioAndPlay() {
            document.getElementById('touch-overlay').style.display = 'none';
            const iframe = document.getElementById('youtube-frame');
            if (iframe) { iframe.src = iframe.src; }
            if (audioPlayer.src) { audioPlayer.muted = false; audioPlayer.play().catch(()=>{}); }
            const vid = document.getElementById('live-video');
            if (vid) { vid.muted = false; vid.play().catch(()=>{}); }
        }

        async function loadAssets() {
            try {
                imageList = await (await fetch('/api/get_images')).json();
                songList = await (await fetch('/api/get_songs')).json();
                videoList = await (await fetch('/api/get_videos')).json();
            } catch(e){}
        }

        function getYoutubeEmbedUrl(url) {
            let videoId = "";
            if (url.includes('youtu.be/')) {
                videoId = url.split('youtu.be/')[1]?.split('?')[0];
            } else if (url.includes('youtube.com/embed/')) {
                videoId = url.split('embed/')[1]?.split('?')[0];
            } else if (url.includes('youtube.com/watch')) {
                let urlParams = new URLSearchParams(url.split('?')[1]);
                videoId = urlParams.get('v');
            } else if (url.includes('youtube.com/live/')) {
                videoId = url.split('live/')[1]?.split('?')[0];
            } else {
                videoId = url.trim();
            }
            if (!videoId) return "";
            return `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=0&controls=0&showinfo=0&modestbranding=1&loop=1&playlist=${videoId}&disablekb=1&fs=0&iv_load_policy=3&playsinline=1`;
        }

        let lastTickerSpeeds = {top: null, bottom: null};
        let playlistDurations = {};
        let playlistSignature = "";
        let lastPlaylistItem = "";

        function syncAudio(serverTime, activeSongSetting) {
            if (!songList.length) return;
            let targetSongUrl = "";
            let songOffset = 0;
            if (activeSongSetting === "AUTO_PLAYLIST") {
                const songDuration = 200;
                const totalDuration = songList.length * songDuration;
                const pTime = serverTime % totalDuration;
                targetSongUrl = songList[Math.floor(pTime / songDuration)];
                songOffset = pTime % songDuration;
            } else {
                targetSongUrl = activeSongSetting;
                songOffset = serverTime % (audioPlayer.duration || 200);
            }
            if (!targetSongUrl) return;
            if (currentSongPath !== targetSongUrl) {
                currentSongPath = targetSongUrl;
                audioPlayer.src = targetSongUrl;
                try { audioPlayer.currentTime = songOffset; } catch(e) {}
                audioPlayer.play().catch(() => {});
            } else if (Math.abs(audioPlayer.currentTime - songOffset) > 2) {
                try { audioPlayer.currentTime = songOffset; } catch(e) {}
            }
            if (audioPlayer.paused) audioPlayer.play().catch(() => {});
        }

        async function getPlaylistDurations(items) {
            const signature = JSON.stringify(items);
            if (signature === playlistSignature && Object.keys(playlistDurations).length) return;
            playlistSignature = signature;
            playlistDurations = {};
            await Promise.all(items.map(item => new Promise(resolve => {
                const el = document.createElement(item.kind === 'video' ? 'video' : 'audio');
                el.preload = 'metadata';
                el.src = item.url;
                let done = false;
                const finish = () => {
                    if (done) return; done = true;
                    playlistDurations[item.url] = (Number.isFinite(el.duration) && el.duration > 0) ? el.duration : 180;
                    el.removeAttribute('src'); el.load(); resolve();
                };
                el.onloadedmetadata = finish;
                el.onerror = () => { if (!done) { done = true; playlistDurations[item.url] = 180; resolve(); } };
                setTimeout(() => { if (!done) { done = true; playlistDurations[item.url] = 180; resolve(); } }, 5000);
            })));
        }

        async function syncProgramPlaylist(state, serverTime) {
            const items = state.playlist || [];
            if (!items.length) return;
            await getPlaylistDurations(items);
            const elapsed = Math.max(0, serverTime - (state.playlist_started_at || serverTime));
            const durations = items.map(item => Math.max(1, playlistDurations[item.url] || 180));
            const total = durations.reduce((a,b) => a+b, 0);
            let pos = elapsed % total, idx = 0;
            while (idx < durations.length - 1 && pos >= durations[idx]) { pos -= durations[idx]; idx++; }
            const item = items[idx];
            if (!item) return;
            const stage = document.getElementById('stage-container');
            if (item.kind === 'video') {
                let vid = document.getElementById('live-video');
                if (!vid || lastMediaType !== 'playlist-video' || lastPlaylistItem !== item.url) {
                    stage.innerHTML = `<video id="live-video" class="video-card" playsinline autoplay loop></video>`;
                    vid = document.getElementById('live-video');
                    vid.src = item.url;
                    lastMediaType = 'playlist-video';
                    lastPlaylistItem = item.url;
                }
                vid.muted = false;
                if (Math.abs((vid.currentTime || 0) - pos) > 2) { try { vid.currentTime = pos; } catch(e) {} }
                if (vid.paused) vid.play().catch(() => { vid.muted = true; vid.play().catch(()=>{}); });
                audioPlayer.pause(); currentSongPath = "";
            } else {
                if (lastMediaType !== 'playlist-audio') {
                    stage.innerHTML = `<div class="image-card" id="main-image"></div>`;
                    lastMediaType = 'playlist-audio';
                    lastPlaylistItem = "";
                }
                if (imageList.length) {
                    const imgIdx = Math.floor(serverTime / 6) % imageList.length;
                    document.getElementById('main-image').style.backgroundImage = `url('${imageList[imgIdx]}')`;
                }
                if (currentSongPath !== item.url) {
                    currentSongPath = item.url;
                    audioPlayer.src = item.url;
                }
                if (Math.abs((audioPlayer.currentTime || 0) - pos) > 2) { try { audioPlayer.currentTime = pos; } catch(e) {} }
                if (audioPlayer.paused) audioPlayer.play().catch(()=>{});
            }
        }
