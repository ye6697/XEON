// XEON V2 - Frontend
const orb = document.getElementById('orb');
const status = document.getElementById('status');
const transcript = document.getElementById('transcript');
const mode = document.getElementById('mode');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const speakOutput = document.getElementById('speak-output');
const usageTotal = document.getElementById('usage-total');
const usageModels = document.getElementById('usage-models');
const attachFilesButton = document.getElementById('attach-files-button');
const attachFolderButton = document.getElementById('attach-folder-button');
const clearAttachmentsButton = document.getElementById('clear-attachments-button');
const fileInput = document.getElementById('file-input');
const folderInput = document.getElementById('folder-input');
const attachmentList = document.getElementById('attachment-list');
const todoList = document.getElementById('todo-list');
const todoToast = document.getElementById('todo-toast');
const todoToastText = document.getElementById('todo-toast-text');
const newsHud = document.getElementById('news-hud');
const hudCountryList = document.getElementById('hud-country-list');
const worldMonitorView = document.getElementById('world-monitor-view');
const worldMonitorBanner = document.getElementById('world-monitor-banner');
const mapFocus = document.getElementById('map-focus');
const mapStage = document.getElementById('map-stage');
const tileMap = document.getElementById('tile-map');
const focusGuardOverlay = document.getElementById('focus-guard-overlay');
const focusGuardTask = document.getElementById('focus-guard-task');
const windowMinimize = document.getElementById('window-minimize');
const windowTray = document.getElementById('window-tray');
const windowClose = document.getElementById('window-close');

let ws;
let audioQueue = [];
let isPlaying = false;
let audioUnlocked = false;
let appBusy = false;
let busyMode = 'Nachdenken';
let pendingAudio = null;
let currentAudio = null;
let currentAudioUrl = null;
let suppressAudioEnded = false;
let selectedAttachments = [];
let reconnectTimer = null;
let bgMusicContext = null;
let bgMusicGain = null;
let bgMusicStarted = false;
let newsReportRunning = false;
let hueNewsPulseActive = false;
const voiceWakeWordRequired = false;
const bootParams = new URLSearchParams(window.location.search);
const introCompleted = bootParams.get('intro') === 'complete';
const focusGuardBoot = bootParams.get('focus_guard') === '1';
const introPrewarmId = bootParams.get('prewarm') || sessionStorage.getItem('xeonIntroPrewarmId') || '';
let startupGreetingDelivered = false;

async function windowCommand(command) {
    try {
        await fetch(`/api/window/${command}`, { method: 'POST' });
    } catch (_error) {
        if (command === 'close') window.close();
    }
}

if (windowMinimize) windowMinimize.addEventListener('click', () => windowCommand('minimize'));
if (windowTray) windowTray.addEventListener('click', () => windowCommand('tray'));
if (windowClose) windowClose.addEventListener('click', () => windowCommand('close'));

if (introCompleted) {
    document.body.classList.add('booting');
    window.setTimeout(() => document.body.classList.remove('booting'), 2350);
}

const worldMonitorCountries = {
    germany: { name: 'Deutschland', lat: 51.2, lon: 10.4, zoom: 6 },
    turkey: { name: 'Tuerkei', lat: 39.0, lon: 35.2, zoom: 6 },
    china: { name: 'China', lat: 35.9, lon: 104.2, zoom: 5 },
    usa: { name: 'USA', lat: 39.8, lon: -98.6, zoom: 5 },
    russia: { name: 'Russland', lat: 61.5, lon: 105.3, zoom: 4 },
    ukraine: { name: 'Ukraine', lat: 49.0, lon: 31.4, zoom: 6 },
    israel: { name: 'Israel', lat: 31.0, lon: 34.8, zoom: 7 },
    iran: { name: 'Tehran', lat: 35.7, lon: 51.4, zoom: 7 },
    india: { name: 'Indien', lat: 20.6, lon: 78.9, zoom: 6 },
    brazil: { name: 'Brasilien', lat: -14.2, lon: -51.9, zoom: 5 },
    'saudi-arabia': { name: 'Saudi-Arabien', lat: 23.9, lon: 45.1, zoom: 6 },
    egypt: { name: 'Aegypten', lat: 26.8, lon: 30.8, zoom: 6 },
    france: { name: 'Frankreich', lat: 46.2, lon: 2.2, zoom: 6 },
    'united-kingdom': { name: 'Grossbritannien', lat: 55.4, lon: -3.4, zoom: 6 },
    netherlands: { name: 'Niederlande', lat: 52.1, lon: 5.3, zoom: 7 },
    italy: { name: 'Italien', lat: 42.8, lon: 12.5, zoom: 6 },
    poland: { name: 'Polen', lat: 52.0, lon: 19.1, zoom: 6 },
    vietnam: { name: 'Vietnam', lat: 15.9, lon: 108.3, zoom: 6 },
    taiwan: { name: 'Taiwan', lat: 23.8, lon: 121.0, zoom: 7 },
    japan: { name: 'Japan', lat: 36.2, lon: 138.3, zoom: 5 },
    'south-korea': { name: 'Suedkorea', lat: 36.4, lon: 127.8, zoom: 7 },
    uae: { name: 'VAE', lat: 24.4, lon: 54.4, zoom: 7 },
    singapore: { name: 'Singapur', lat: 1.35, lon: 103.82, zoom: 9 },
    mexico: { name: 'Mexiko', lat: 23.6, lon: -102.5, zoom: 5 },
};

function lonToTileX(lon, zoom) {
    return ((lon + 180) / 360) * (2 ** zoom);
}

function latToTileY(lat, zoom) {
    const rad = lat * Math.PI / 180;
    return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * (2 ** zoom);
}

function renderTileMap(lat = 25, lon = 20, zoom = 2) {
    if (!tileMap) return;
    const tileSize = 256;
    const rect = tileMap.getBoundingClientRect();
    const width = Math.max(800, rect.width || window.innerWidth);
    const height = Math.max(520, rect.height || window.innerHeight);
    const centerX = lonToTileX(lon, zoom);
    const centerY = latToTileY(lat, zoom);
    const centerPxX = centerX * tileSize;
    const centerPxY = centerY * tileSize;
    const startTileX = Math.floor((centerPxX - width / 2) / tileSize) - 1;
    const endTileX = Math.floor((centerPxX + width / 2) / tileSize) + 1;
    const startTileY = Math.floor((centerPxY - height / 2) / tileSize) - 1;
    const endTileY = Math.floor((centerPxY + height / 2) / tileSize) + 1;
    const maxTile = 2 ** zoom;
    tileMap.innerHTML = '';
    tileMap.style.setProperty('--tile-fade', '0');
    for (let x = startTileX; x <= endTileX; x += 1) {
        for (let y = startTileY; y <= endTileY; y += 1) {
            if (y < 0 || y >= maxTile) continue;
            const wrappedX = ((x % maxTile) + maxTile) % maxTile;
            const img = document.createElement('img');
            img.className = 'map-tile';
            const subdomain = ['a', 'b', 'c'][Math.abs(wrappedX + y) % 3];
            img.src = `https://${subdomain}.basemaps.cartocdn.com/dark_all/${zoom}/${wrappedX}/${y}@2x.png`;
            img.onerror = () => {
                img.src = `https://tile.openstreetmap.org/${zoom}/${wrappedX}/${y}.png`;
                img.classList.add('fallback-tile');
            };
            img.alt = '';
            img.draggable = false;
            img.style.left = `${(x * tileSize - centerPxX) + width / 2}px`;
            img.style.top = `${(y * tileSize - centerPxY) + height / 2}px`;
            tileMap.appendChild(img);
        }
    }
    window.requestAnimationFrame(() => tileMap.style.setProperty('--tile-fade', '1'));
}

function showNewsHud(items = []) {
    if (!newsHud) return;
    newsHud.hidden = false;
    if (worldMonitorView) worldMonitorView.hidden = true;
    startHueNewsPulse();
    const labels = Array.isArray(items) && items.length ? items : ['Tuerkei', 'China', 'EU', 'USA', 'Suez', 'Hormus'];
    if (hudCountryList) {
        hudCountryList.textContent = labels.map(item => `Analysiere ${item}`).join('  |  ');
    }
}

function hideNewsHud() {
    if (newsHud) newsHud.hidden = true;
    stopHueNewsPulse();
}

function startHueNewsPulse() {
    if (hueNewsPulseActive) return;
    hueNewsPulseActive = true;
    fetch('/api/hue/news/start', { method: 'POST' }).catch(() => {});
}

function stopHueNewsPulse() {
    if (!hueNewsPulseActive) return;
    hueNewsPulseActive = false;
    fetch('/api/hue/news/stop', { method: 'POST' }).catch(() => {});
}

function showWorldMonitor(countryCode, title) {
    if (!worldMonitorView) return;
    hideNewsHud();
    worldMonitorView.hidden = false;
    const country = worldMonitorCountries[countryCode] || { name: 'Global', lat: 25, lon: 20, zoom: 2 };
    renderTileMap(country.lat, country.lon, country.zoom);
    if (mapFocus) {
        mapFocus.style.left = '50%';
        mapFocus.style.top = '50%';
        mapFocus.setAttribute('data-label', country.name);
    }
    if (mapStage) {
        mapStage.classList.remove('map-zooming');
        void mapStage.offsetWidth;
        mapStage.classList.add('map-zooming');
    }
    if (worldMonitorBanner) worldMonitorBanner.textContent = `XEON Fokus: ${title || (worldMonitorCountries[countryCode]?.name || 'World Monitor')}`;
}

async function focusWorldMonitorCountry(countryCode, title) {
    if (!worldMonitorView) return;
    hideNewsHud();
    worldMonitorView.hidden = false;
    if (worldMonitorBanner) worldMonitorBanner.textContent = 'Globaler Reset: Lagebild wird neu ausgerichtet';
    renderTileMap(25, 20, 2);
    if (mapFocus) {
        mapFocus.style.left = '50%';
        mapFocus.style.top = '50%';
        mapFocus.setAttribute('data-label', 'Global');
    }
    if (mapStage) {
        mapStage.classList.remove('map-zooming');
        mapStage.classList.add('map-resetting');
    }
    await sleep(880);
    if (mapStage) {
        mapStage.classList.remove('map-resetting');
    }
    showWorldMonitor(countryCode, title);
    await sleep(980);
}

function hideWorldMonitor() {
    if (worldMonitorView) worldMonitorView.hidden = true;
    if (mapStage) {
        mapStage.classList.remove('map-zooming');
    }
}

function sleep(ms) {
    return new Promise(resolve => window.setTimeout(resolve, ms));
}

function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char]));
}

function formatAge(createdAt) {
    const created = Date.parse(createdAt || '');
    if (!created) return 'neu';
    const minutes = Math.max(0, Math.floor((Date.now() - created) / 60000));
    if (minutes < 90) return `${minutes || 1} min offen`;
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return `${hours} h offen`;
    return `${Math.floor(hours / 24)} Tage offen`;
}

function renderTodos(items = []) {
    if (!todoList) return;
    if (!items.length) {
        todoList.textContent = 'Keine offenen Aufgaben';
        return;
    }
    todoList.innerHTML = items.slice(0, 8).map(item => {
        const severity = item.severity || severityFromCreated(item.created_at);
        const evidence = item.awaiting_evidence ? ' · Nachweis offen' : '';
        const duplicate = item.duplicate ? ' · Duplikat erkannt' : '';
        const badge = item.badge || severity;
        const due = item.due_at ? ` · ${item.due_at}` : '';
        return `
            <div class="accountability-item accountability-severity-${escapeHtml(severity)}">
                <div class="accountability-main">${escapeHtml(item.text || 'Offene Aufgabe')}</div>
                <div class="accountability-meta">${escapeHtml(formatAge(item.created_at))} · ${escapeHtml(badge)}${escapeHtml(due)}${escapeHtml(evidence)}${escapeHtml(duplicate)}</div>
            </div>
        `;
    }).join('');
}

function severityFromCreated(createdAt) {
    const created = Date.parse(createdAt || '');
    if (!created) return 'normal';
    const days = (Date.now() - created) / 86400000;
    if (days >= 4) return 'hard';
    if (days >= 2) return 'strict';
    return 'normal';
}

async function refreshAccountability() {
    try {
        const todoResponse = await fetch('/api/todos', { cache: 'no-store' });
        if (todoResponse.ok) {
            const data = await todoResponse.json();
            renderTodos(data.items || []);
        }
    } catch (error) {
        console.warn('[xeon] accountability refresh failed:', error);
    }
}

function showTodoToast(text) {
    if (!todoToast || !todoToastText) return;
    todoToastText.textContent = text || '';
    todoToast.hidden = false;
    window.clearTimeout(showTodoToast.hideTimer);
    showTodoToast.hideTimer = window.setTimeout(() => {
        todoToast.hidden = true;
    }, 16000);
}

function playPreparedAudio(base64Audio) {
    return new Promise(resolve => {
        if (!base64Audio) {
            resolve();
            return;
        }
        const bytes = Uint8Array.from(atob(base64Audio), c => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: 'audio/mpeg' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudio = audio;
        currentAudioUrl = url;
        isPlaying = true;
        setOrbState('speaking');
        setMode('Spricht');
        audio.onended = () => {
            URL.revokeObjectURL(url);
            currentAudio = null;
            currentAudioUrl = null;
            isPlaying = false;
            resolve();
        };
        audio.onerror = () => {
            URL.revokeObjectURL(url);
            currentAudio = null;
            currentAudioUrl = null;
            isPlaying = false;
            resolve();
        };
        audio.play().catch(() => {
            pendingAudio = audio;
            resolve();
        });
    });
}

async function runNewsReport(data) {
    if (newsReportRunning) return;
    newsReportRunning = true;
    appBusy = true;
    stopListening();
    hideNewsHud();
    const meta = data.meta || null;
    updateUsagePanel(meta);
    for (const item of data.items || []) {
        status.textContent = `Fokus: ${item.title || item.country}`;
        setMode('Lagebericht');
        await focusWorldMonitorCountry(item.country, item.title);
        addTranscript('xeon', item.text, meta);
        await playPreparedAudio(item.audio || '');
        await sleep(180);
    }
    if (data.conclusion && data.conclusion.text) {
        status.textContent = 'XEON zieht Fazit...';
        addTranscript('xeon', data.conclusion.text, meta);
        await playPreparedAudio(data.conclusion.audio || '');
    }
    hideWorldMonitor();
    hideNewsHud();
    appBusy = false;
    newsReportRunning = false;
    status.textContent = '';
    setMode('Zuhoeren');
    setOrbState('listening');
    setTimeout(startListening, 400);
}

function extractWakeCommand(text) {
    const normalized = (text || '').trim();
    if (!voiceWakeWordRequired) return normalized;
    const match = normalized.match(/\b(xeon|seeon|see-on|x eon)\b[:,\s-]*(.*)$/i);
    if (!match) return '';
    return (match[2] || normalized).trim();
}

function startBackgroundMusic() {
    if (bgMusicStarted) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    bgMusicStarted = true;
    bgMusicContext = new AudioCtx();
    bgMusicGain = bgMusicContext.createGain();
    bgMusicGain.gain.value = 0.32;
    bgMusicGain.connect(bgMusicContext.destination);
    bgMusicContext.resume().catch(() => {});

    const masterFilter = bgMusicContext.createBiquadFilter();
    masterFilter.type = 'lowpass';
    masterFilter.frequency.value = 1800;
    masterFilter.Q.value = 0.6;
    masterFilter.connect(bgMusicGain);

    const notes = [110, 164.81, 220, 293.66];
    notes.forEach((freq, index) => {
        const osc = bgMusicContext.createOscillator();
        const gain = bgMusicContext.createGain();
        osc.type = index === 0 ? 'sine' : 'triangle';
        osc.frequency.value = freq;
        gain.gain.value = index === 0 ? 0.16 : 0.075;
        osc.connect(gain);
        gain.connect(masterFilter);
        osc.start();
    });

    const pulse = bgMusicContext.createOscillator();
    const pulseGain = bgMusicContext.createGain();
    pulse.type = 'sine';
    pulse.frequency.value = 0.055;
    pulseGain.gain.value = 0.045;
    pulse.connect(pulseGain);
    pulseGain.connect(masterFilter);
    pulse.start();

    let step = 0;
    const motif = [329.63, 392, 440, 493.88, 440, 392];
    window.setInterval(() => {
        if (!bgMusicContext || !bgMusicGain) return;
        const now = bgMusicContext.currentTime;
        const osc = bgMusicContext.createOscillator();
        const gain = bgMusicContext.createGain();
        osc.type = 'triangle';
        osc.frequency.value = motif[step % motif.length];
        gain.gain.setValueAtTime(0.0, now);
        gain.gain.linearRampToValueAtTime(0.12, now + 0.08);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 1.6);
        osc.connect(gain);
        gain.connect(masterFilter);
        osc.start(now);
        osc.stop(now + 1.7);
        step += 1;
    }, 2200);
}

function setBackgroundMusicDucked(ducked) {
    if (!bgMusicGain || !bgMusicContext) return;
    bgMusicContext.resume().catch(() => {});
    const target = ducked ? 0.09 : 0.32;
    bgMusicGain.gain.cancelScheduledValues(bgMusicContext.currentTime);
    bgMusicGain.gain.linearRampToValueAtTime(target, bgMusicContext.currentTime + 0.45);
}

// Unlock audio on ANY user interaction
function unlockAudio() {
    if (!audioUnlocked) {
        const silent = new Audio('data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA');
        silent.play().then(() => {
            audioUnlocked = true;
            startBackgroundMusic();
            console.log('[xeon] Audio unlocked');
        }).catch(() => {});
    }
}
document.addEventListener('click', unlockAudio, { once: false });
document.addEventListener('pointerdown', unlockAudio, { once: false });
document.addEventListener('touchstart', unlockAudio, { once: false });
document.addEventListener('keydown', unlockAudio, { once: false });

function retryPendingAudio() {
    if (!pendingAudio) return;
    const audio = pendingAudio;
    pendingAudio = null;
    audio.play().then(() => {
        setOrbState('speaking');
        setMode('Spricht');
        status.textContent = '';
    }).catch(() => {
        pendingAudio = audio;
        status.textContent = 'Audio ist blockiert. Klicken oder Taste druecken, Sir.';
        setMode('Wartet auf Audio');
    });
}
document.addEventListener('click', retryPendingAudio, { once: false });
document.addEventListener('touchstart', retryPendingAudio, { once: false });
document.addEventListener('keydown', retryPendingAudio, { once: false });

async function consumeIntroPrewarm() {
    if (!introCompleted || !introPrewarmId || startupGreetingDelivered) return false;
    for (let attempt = 0; attempt < 12; attempt += 1) {
        try {
            const response = await fetch(`/api/intro-prewarm/${encodeURIComponent(introPrewarmId)}?t=${Date.now()}`, { cache: 'no-store' });
            if (response.ok) {
                const data = await response.json();
                if (data.status === 'ready' && data.text) {
                    startupGreetingDelivered = true;
                    sessionStorage.removeItem('xeonIntroPrewarmId');
                    addTranscript('xeon', data.text, data.meta);
                    updateUsagePanel(data.meta);
                    if (data.audio) {
                        queueAudio(data.audio);
                    } else {
                        setOrbState('idle');
                        setTimeout(startListening, 350);
                    }
                    appBusy = false;
                    status.textContent = '';
                    setMode(data.audio ? 'Spricht' : 'Wartet auf Befehl');
                    return true;
                }
                if (data.status === 'error' || data.status === 'missing') break;
            }
        } catch (_) {}
        await sleep(250);
    }
    return false;
}

function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => {
        console.log('[xeon] WebSocket connected');
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        window.setTimeout(startBackgroundMusic, 600);
        setBusy('Nachdenken', 'XEON startet...');
        if (focusGuardBoot) {
            showFocusGuardOverlay('Focus Guard wird vorbereitet...');
            appBusy = true;
            setMode('FOCUS GUARD');
            status.textContent = 'Intervention aktiv...';
        } else if (introCompleted) {
            consumeIntroPrewarm().then(delivered => {
                if (!delivered && ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ text: 'XEON activate', speak: true }));
                }
            });
        } else {
            ws.send(JSON.stringify({ text: 'XEON activate', speak: true }));
        }
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'response') {
            addTranscript('xeon', data.text, data.meta);
            updateUsagePanel(data.meta);
            if (data.audio && data.audio.length > 0) {
                queueAudio(data.audio);
            } else {
                if (appBusy) {
                    setOrbState('thinking');
                    setMode(busyMode);
                } else {
                    setOrbState('idle');
                    setTimeout(startListening, 500);
                }
            }
        } else if (data.type === 'status') {
            if (newsReportRunning && data.busy === false) {
                return;
            }
            if (data.busy === true) appBusy = true;
            if (data.busy === false) appBusy = false;
            status.textContent = data.text;
            if (data.mode && !(data.busy === false && isPlaying)) {
                setMode(data.mode);
                if (appBusy) busyMode = data.mode;
            }
            if (appBusy && !isPlaying) {
                setOrbState('thinking');
            }
            if (!appBusy) {
                setTimeout(startListening, 300);
            }
        } else if (data.type === 'news_hud') {
            if (data.visible === false) {
                hideNewsHud();
            } else {
                showNewsHud(data.items || []);
            }
        } else if (data.type === 'world_monitor') {
            if (data.visible === false) {
                hideWorldMonitor();
            } else {
                showWorldMonitor(data.country, data.title);
            }
        } else if (data.type === 'news_report') {
            runNewsReport(data);
        } else if (data.type === 'todos') {
            renderTodos(data.items || []);
        } else if (data.type === 'todo_toast') {
            showTodoToast(data.text || '');
        } else if (data.type === 'focus_guard') {
            showFocusGuardOverlay(data.text || data.task || 'Eine ueberfaellige Aufgabe blockiert den Spielmodus.');
        }
    };
    ws.onclose = () => {
        status.textContent = 'Verbindung wird neu aufgebaut...';
        if (!reconnectTimer) {
            reconnectTimer = setTimeout(() => {
                reconnectTimer = null;
                connect();
            }, 1500);
        }
    };
}

function showFocusGuardOverlay(text) {
    if (!focusGuardOverlay) return;
    focusGuardTask.textContent = text || 'Ueberfaellige Aufgabe erkannt.';
    focusGuardOverlay.hidden = false;
    focusGuardOverlay.classList.remove('soften');
    document.body.classList.add('focus-guard-active');
    setMode('FOCUS GUARD');
    status.textContent = 'Intervention aktiv';
    window.clearTimeout(showFocusGuardOverlay.timer);
    showFocusGuardOverlay.timer = window.setTimeout(() => {
        focusGuardOverlay.classList.add('soften');
    }, 2200);
}

function hideFocusGuardOverlay() {
    if (!focusGuardOverlay) return;
    focusGuardOverlay.classList.remove('soften');
    focusGuardOverlay.hidden = true;
    document.body.classList.remove('focus-guard-active');
}

function queueAudio(base64Audio) {
    audioQueue.push(base64Audio);
    if (!isPlaying) playNext();
}

function stopCurrentAudioForUserSpeech() {
    suppressAudioEnded = true;
    audioQueue = [];
    if (currentAudio) {
        try {
            currentAudio.pause();
            currentAudio.currentTime = 0;
        } catch (_) {}
    }
    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
    }
    currentAudio = null;
    currentAudioUrl = null;
    pendingAudio = null;
    isPlaying = false;
    suppressAudioEnded = false;
}

function submitVoiceCommand(text) {
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    if (isSpeechStopCommand(text)) {
        if (isPlaying) {
            stopCurrentAudioForUserSpeech();
            status.textContent = 'Gestoppt, Sir.';
        } else {
            status.textContent = 'Stop erkannt.';
        }
        setMode('Zuhoeren');
        setOrbState('listening');
        return;
    }
    if (isPlaying) {
        return;
    }
    addTranscript('user', text);
    setBusy('Nachdenken', 'XEON denkt nach...');
    ws.send(JSON.stringify({ text, speak: true }));
}

function playNext() {
    if (audioQueue.length === 0) {
        if (focusGuardOverlay && !focusGuardOverlay.hidden) {
            hideFocusGuardOverlay();
        }
        isPlaying = false;
        if (appBusy) {
            setOrbState('thinking');
            setMode(busyMode);
        } else {
            setOrbState('listening');
            setMode('Zuhoeren');
            status.textContent = '';
            setTimeout(startListening, 500);
        }
        return;
    }
    isPlaying = true;
    setOrbState('speaking');
    setMode('Spricht');
    status.textContent = '';
    const b64 = audioQueue.shift();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    currentAudioUrl = url;
    currentAudioStartedAt = Date.now();
    audio.preload = 'auto';
    audio.volume = 1;
    audio.onended = () => {
        URL.revokeObjectURL(url);
        currentAudio = null;
        currentAudioUrl = null;
        if (!suppressAudioEnded) playNext();
    };
    audio.onerror = () => {
        URL.revokeObjectURL(url);
        currentAudio = null;
        currentAudioUrl = null;
        if (!suppressAudioEnded) playNext();
    };
    audio.play().then(() => {
        startBackgroundMusic();
        setTimeout(startListening, 150);
    }).catch(err => {
        console.warn('[xeon] Audio playback blocked or failed:', err);
        pendingAudio = audio;
        status.textContent = 'Audio ist blockiert. Klicken oder Taste druecken, Sir.';
        setOrbState('idle');
        setMode('Wartet auf Audio');
    });
}

// Local Faster-Whisper STT: browser records audio, server transcribes locally.
let micStream = null;
let audioContext = null;
let analyser = null;
let vadTimer = null;
let recorder = null;
let recordedChunks = [];
let isListening = false;
let sttMonitoring = false;
let speechActive = false;
let speechStartedAt = 0;
let utteranceStartedWhileSpeaking = false;
let lastVoiceAt = 0;
let currentAudioStartedAt = 0;
const vadThreshold = 0.022;
const minSpeechMs = 750;
const silenceStopMs = 900;
const bargeInGuardMs = 450;

function isSpeechStopCommand(text) {
    const normalized = (text || '')
        .toLowerCase()
        .replace(/[.,!?;:()[\]{}"']/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    if (!normalized) return false;
    const stopPhrases = [
        'stop',
        'stopp',
        'xeon stop',
        'xeon stopp',
        'halt',
        'pause',
        'pausieren',
        'sei still',
        'ruhe',
        'hoer auf',
        'hör auf',
        'aufhoeren',
        'aufhören',
        'nicht weiter',
        'abbrechen',
        'brich ab',
    ];
    const padded = ` ${normalized} `;
    return stopPhrases.some(phrase => normalized === phrase || padded.includes(` ${phrase} `));
}

function getRecorderMimeType() {
    if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) return 'audio/webm;codecs=opus';
    if (MediaRecorder.isTypeSupported('audio/webm')) return 'audio/webm';
    if (MediaRecorder.isTypeSupported('audio/mp4')) return 'audio/mp4';
    return '';
}

async function ensureMic() {
    if (micStream) return;
    micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
        },
    });
    audioContext = new AudioContext();
    if (audioContext.state === 'suspended') {
        await audioContext.resume();
    }
    const source = audioContext.createMediaStreamSource(micStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
}

function rmsLevel() {
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const value of data) {
        const normalized = (value - 128) / 128;
        sum += normalized * normalized;
    }
    return Math.sqrt(sum / data.length);
}

function beginUtterance() {
    if (speechActive) return;
    recordedChunks = [];
    utteranceStartedWhileSpeaking = isPlaying;
    const mimeType = getRecorderMimeType();
    recorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined);
    recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) recordedChunks.push(event.data);
    };
    recorder.onstop = submitRecordedAudio;
    recorder.start(180);
    speechActive = true;
    speechStartedAt = Date.now();
    lastVoiceAt = Date.now();
    if (!isPlaying) {
        setOrbState('listening');
        setMode('Zuhoeren');
        status.textContent = 'Ich hoere zu...';
    }
}

function endUtterance() {
    if (!recorder || recorder.state === 'inactive') return;
    speechActive = false;
    recorder.stop();
    if (!isPlaying) {
        status.textContent = 'Transkribiere lokal...';
        setMode('Verstehen');
    }
}

async function submitRecordedAudio() {
    const duration = Date.now() - speechStartedAt;
    const wasSpeakingWhenHeard = utteranceStartedWhileSpeaking;
    utteranceStartedWhileSpeaking = false;
    if (duration < minSpeechMs || recordedChunks.length === 0) {
        status.textContent = '';
        return;
    }

    const type = recorder?.mimeType || 'audio/webm';
    const blob = new Blob(recordedChunks, { type });
    recordedChunks = [];
    try {
        const response = await fetch('/api/transcribe', {
            method: 'POST',
            headers: { 'Content-Type': type },
            body: blob,
        });
        if (!response.ok) {
            throw new Error(`STT HTTP ${response.status}`);
        }
        const data = await response.json();
        if (data.error) {
            throw new Error(data.error);
        }
        const text = (data.text || '').trim();
        if (text) {
            const command = extractWakeCommand(text);
            if (isSpeechStopCommand(command || text)) {
                if (isPlaying) {
                    stopCurrentAudioForUserSpeech();
                    status.textContent = 'Gestoppt, Sir.';
                } else {
                    status.textContent = 'Stop erkannt.';
                }
                setMode('Zuhoeren');
                setOrbState('listening');
                return;
            }
            if (wasSpeakingWhenHeard) {
                return;
            }
            submitVoiceCommand(command || text);
        } else if (!appBusy) {
            status.textContent = '';
            setMode('Zuhoeren');
        }
    } catch (error) {
        console.warn('[xeon] local STT failed:', error);
        status.textContent = 'Spracherkennung startet neu...';
        if (!appBusy) setTimeout(startListening, 1200);
    }
}

function monitorVoiceActivity() {
    if (!sttMonitoring || !analyser) return;
    const level = rmsLevel();
    const now = Date.now();
    if (isPlaying && now - currentAudioStartedAt < bargeInGuardMs) {
        vadTimer = window.setTimeout(monitorVoiceActivity, 80);
        return;
    }
    if (level > vadThreshold) {
        lastVoiceAt = now;
        if (!speechActive && (!appBusy || isPlaying)) beginUtterance();
    }
    if (speechActive && now - lastVoiceAt > silenceStopMs) {
        endUtterance();
    }
    vadTimer = window.setTimeout(monitorVoiceActivity, 80);
}

function startListening() {
    if ((appBusy && !isPlaying) || sttMonitoring) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
        status.textContent = 'Dieser Browser kann kein lokales Mikrofon-Audio aufnehmen.';
        return;
    }
    ensureMic().then(() => {
        isListening = true;
        sttMonitoring = true;
        setOrbState('listening');
        setMode('Zuhoeren');
        status.textContent = '';
        monitorVoiceActivity();
    }).catch((error) => {
        console.warn('[xeon] microphone unavailable:', error);
        status.textContent = 'Mikrofonzugriff fehlt.';
        setMode('Wartet auf Mikrofon');
    });
}

function stopListening() {
    sttMonitoring = false;
    isListening = false;
    if (vadTimer) window.clearTimeout(vadTimer);
    vadTimer = null;
    if (speechActive && recorder && recorder.state !== 'inactive') {
        recorder.stop();
    }
    speechActive = false;
}

orb.addEventListener('click', () => {
    if (isListening) {
        stopListening();
        setOrbState('idle');
        setMode('Wartet auf Befehl');
        status.textContent = 'Pausiert. Klicke zum Fortsetzen.';
    } else {
        startListening();
    }
});

function attachmentLabel(item) {
    return item.relative_path || item.original_name || item.path || 'Anhang';
}

function addSelectedAttachments(items) {
    const existing = new Set(selectedAttachments.map(item => item.path || attachmentLabel(item)));
    for (const item of Array.from(items || [])) {
        const key = item.path || attachmentLabel(item);
        if (!existing.has(key)) {
            selectedAttachments.push(item);
            existing.add(key);
        }
    }
    renderAttachments();
}

function renderAttachments() {
    if (!attachmentList) return;
    if (selectedAttachments.length === 0) {
        attachmentList.classList.remove('has-items');
        attachmentList.textContent = 'Keine lokalen Dateien/Ordner';
        return;
    }
    attachmentList.classList.add('has-items');
    const totalBytes = selectedAttachments.reduce((sum, item) => sum + Number(item.size || 0), 0);
    const shown = selectedAttachments.slice(0, 6).map(item => attachmentLabel(item));
    const more = selectedAttachments.length > shown.length ? `, +${selectedAttachments.length - shown.length} weitere` : '';
    const sizeMb = (totalBytes / 1024 / 1024).toLocaleString('de-DE', { maximumFractionDigits: 1 });
    attachmentList.textContent = `${selectedAttachments.length} lokale Pfade (${sizeMb} MB Dateien): ${shown.join(', ')}${more}`;
}

async function pickLocalAttachments(mode) {
    setBusy('Ausfuehren', mode === 'folder' ? 'Ordnerdialog wird geoeffnet...' : 'Dateidialog wird geoeffnet...');
    const response = await fetch('/api/local-attachments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    });
    if (!response.ok) throw new Error(`Auswahl fehlgeschlagen: ${response.status}`);
    const data = await response.json();
    addSelectedAttachments(data.attachments || []);
    appBusy = false;
    setOrbState('idle');
    setMode('Wartet auf Befehl');
    status.textContent = '';
}

async function resolveSelectedAttachments() {
    if (selectedAttachments.length === 0) return [];
    return selectedAttachments;
}

attachFilesButton?.addEventListener('click', () => pickLocalAttachments('files').catch((error) => {
    console.warn('[xeon] local file pick failed:', error);
    status.textContent = 'Dateiauswahl ist fehlgeschlagen.';
    appBusy = false;
    setOrbState('idle');
    setMode('Wartet auf Befehl');
}));
attachFolderButton?.addEventListener('click', () => pickLocalAttachments('folder').catch((error) => {
    console.warn('[xeon] local folder pick failed:', error);
    status.textContent = 'Ordnerauswahl ist fehlgeschlagen.';
    appBusy = false;
    setOrbState('idle');
    setMode('Wartet auf Befehl');
}));
clearAttachmentsButton?.addEventListener('click', () => {
    selectedAttachments = [];
    if (fileInput) fileInput.value = '';
    if (folderInput) folderInput.value = '';
    renderAttachments();
});

chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = chatInput.value.trim();
    if ((!text && selectedAttachments.length === 0) || !ws || ws.readyState !== WebSocket.OPEN) return;

    const visibleText = text || 'Arbeite mit den angehaengten Dateien.';
    addTranscript('user', selectedAttachments.length ? `${visibleText} (${selectedAttachments.length} Anhaenge)` : visibleText);
    chatInput.value = '';
    setBusy('Nachdenken', selectedAttachments.length ? 'Lokale Pfade werden eingebunden...' : 'XEON denkt nach...');
    resolveSelectedAttachments().then((attachments) => {
        selectedAttachments = [];
        if (fileInput) fileInput.value = '';
        if (folderInput) folderInput.value = '';
        renderAttachments();
        ws.send(JSON.stringify({ text: visibleText, speak: speakOutput.checked, attachments }));
    }).catch((error) => {
        console.warn('[xeon] attachment resolve failed:', error);
        status.textContent = 'Lokale Pfade konnten nicht eingebunden werden.';
        appBusy = false;
        setOrbState('idle');
        setMode('Wartet auf Befehl');
    });
});

function setBusy(modeText, statusText) {
    appBusy = true;
    busyMode = modeText;
    if (isListening) {
        stopListening();
    }
    setOrbState('thinking');
    setMode(modeText);
    status.textContent = statusText;
}

function setOrbState(state) {
    orb.className = state;
    setBackgroundMusicDucked(state === 'listening' || state === 'speaking');
}
function setMode(text) { mode.textContent = text; }

function formatMoney(value) {
    const amount = Number(value || 0);
    return amount.toLocaleString('de-DE', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function formatModelShares(meta) {
    if (!meta || !Array.isArray(meta.model_shares) || meta.model_shares.length === 0) {
        return 'noch keine Monatsdaten';
    }
    return meta.model_shares
        .map(item => `${item.model}: ${Number(item.percent || 0).toLocaleString('de-DE', { maximumFractionDigits: 1 })}%`)
        .join(', ');
}

function formatAnswerMeta(meta) {
    if (!meta) return '';
    const model = meta.model || 'unbekannt';
    const note = meta.monthly_spend_note === 'api key missing' ? ' (OpenAI-Key fehlt)' : '';
    return `Modell: ${model}${note}`;
}

function updateUsagePanel(meta) {
    if (!meta || !usageTotal || !usageModels) return;
    const note = meta.monthly_spend_note === 'api key missing' ? ' · Key fehlt' : '';
    usageTotal.textContent = `${formatMoney(meta.monthly_spend_usd)} USD${note}`;
    usageModels.textContent = `Modelle: ${formatModelShares(meta)}`;
}

async function refreshUsagePanel() {
    try {
        const response = await fetch('/api/usage', { cache: 'no-store' });
        if (!response.ok) return;
        updateUsagePanel(await response.json());
    } catch (error) {
        console.warn('[xeon] usage panel failed:', error);
    }
}

function addTranscript(role, text, meta = null) {
    const div = document.createElement('div');
    div.className = role;
    if (role === 'user') {
        div.textContent = `Du: ${text}`;
    } else {
        const label = document.createElement('div');
        label.className = 'xeon-label';
        label.textContent = `XEON`;
        const metaText = formatAnswerMeta(meta);
        if (metaText) {
            const metaLine = document.createElement('span');
            metaLine.className = 'xeon-meta';
            metaLine.textContent = metaText;
            label.appendChild(metaLine);
        }
        const body = document.createElement('div');
        body.className = 'xeon-text';
        body.textContent = text;
        div.appendChild(label);
        div.appendChild(body);
    }
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

refreshUsagePanel();
renderAttachments();
window.setInterval(refreshUsagePanel, 60000);
connect();
refreshAccountability();
window.setInterval(refreshAccountability, 60000);

