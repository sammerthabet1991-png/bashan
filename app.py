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

        async function checkLiveState() {
            try {
                const response = await fetch('/api/live_state');
                const state = await response.json();
                const serverTime = state.server_time || (Date.now() / 1000);
                
                if (lastTickerSpeeds.top !== state.sweida_speed) {
                    document.getElementById('top-ticker-content').style.animation = `ticker ${state.sweida_speed}s linear infinite`;
                    lastTickerSpeeds.top = state.sweida_speed;
                }
                if (lastTickerSpeeds.bottom !== state.world_speed) {
                    document.getElementById('ticker-content').style.animation = `ticker ${state.world_speed}s linear infinite`;
                    lastTickerSpeeds.bottom = state.world_speed;
                }
                
                const banner = document.getElementById('breaking-banner');
                if(state.breaking_banner) { document.getElementById('breaking-text').innerText = state.breaking_banner; banner.style.display = 'flex'; } else { banner.style.display = 'none'; }
                
                const stage = document.getElementById('stage-container');
                
                if(state.media_type === 'youtube' && state.youtube_url) {
                    let embedUrl = getYoutubeEmbedUrl(state.youtube_url);
                    if(embedUrl && (lastMediaType !== 'youtube' || lastYoutubeUrl !== state.youtube_url)) {
                        stage.innerHTML = `<iframe id="youtube-frame" class="youtube-card" src="${embedUrl}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
                        lastMediaType = 'youtube';
                        lastYoutubeUrl = state.youtube_url;
                    }
                    audioPlayer.pause();
                    currentSongPath = "";
                } 
                else if(state.media_type === 'video') {
