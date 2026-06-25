// XEON V2 - Frontend
const orb = document.getElementById('orb');
const status = document.getElementById('status');
const transcript = document.getElementById('transcript');
const mode = document.getElementById('mode');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const speakOutput = document.getElementById('speak-output');

let ws;
let audioQueue = [];
let isPlaying = false;
let audioUnlocked = false;
let appBusy = false;
let busyMode = 'Nachdenken';
let pendingAudio = null;

// Unlock audio on ANY user interaction
function unlockAudio() {
    if (!audioUnlocked) {
        const silent = new Audio('data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA');
        silent.play().then(() => {
            audioUnlocked = true;
            console.log('[xeon] Audio unlocked');
        }).catch(() => {});
    }
}
document.addEventListener('click', unlockAudio, { once: false });
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
        status.textContent = 'Audio ist blockiert. Klicken oder Taste drücken, Sir.';
        setMode('Wartet auf Audio');
    });
}
document.addEventListener('click', retryPendingAudio, { once: false });
document.addEventListener('touchstart', retryPendingAudio, { once: false });
document.addEventListener('keydown', retryPendingAudio, { once: false });

function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => {
        console.log('[xeon] WebSocket connected');
        setBusy('Nachdenken', 'XEON startet...');
        ws.send(JSON.stringify({ text: 'XEON activate', speak: true }));
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'response') {
            addTranscript('xeon', data.text);
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
            if (!appBusy && !isPlaying && audioQueue.length === 0) {
                setTimeout(startListening, 300);
            }
        }
    };
    ws.onclose = () => {
        status.textContent = 'Verbindung verloren...';
        setTimeout(connect, 3000);
    };
}

function queueAudio(base64Audio) {
    audioQueue.push(base64Audio);
    if (!isPlaying) playNext();
}

function playNext() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        if (appBusy) {
            setOrbState('thinking');
            setMode(busyMode);
        } else {
            setOrbState('listening');
            setMode('Zuhören');
            status.textContent = '';
            setTimeout(startListening, 500);
        }
        return;
    }
    isPlaying = true;
    setOrbState('speaking');
    setMode('Spricht');
    status.textContent = '';
    if (isListening && recognition) {
        recognition.stop();
        isListening = false;
    }

    const b64 = audioQueue.shift();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.preload = 'auto';
    audio.volume = 1;
    audio.onended = () => { URL.revokeObjectURL(url); playNext(); };
    audio.onerror = () => { URL.revokeObjectURL(url); playNext(); };
    audio.play().catch(err => {
        console.warn('[xeon] Audio playback blocked or failed:', err);
        pendingAudio = audio;
        status.textContent = 'Audio ist blockiert. Klicken oder Taste drücken, Sir.';
        setOrbState('idle');
        setMode('Wartet auf Audio');
    });
}

// Speech Recognition
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let isListening = false;

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'de-DE';
    recognition.continuous = true;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
        const last = event.results[event.results.length - 1];
        if (last.isFinal) {
            const text = last[0].transcript.trim();
            if (text) {
                addTranscript('user', text);
                setBusy('Nachdenken', 'XEON denkt nach...');
                ws.send(JSON.stringify({ text, speak: true }));
            }
        }
    };

    recognition.onend = () => {
        isListening = false;
        if (!isPlaying && !appBusy) setTimeout(startListening, 300);
    };

    recognition.onerror = (event) => {
        isListening = false;
        if (event.error === 'no-speech' || event.error === 'aborted') {
            if (!isPlaying && !appBusy) setTimeout(startListening, 300);
        } else {
            if (!appBusy) setTimeout(startListening, 1000);
        }
    };
}

function startListening() {
    if (isPlaying || appBusy) return;
    try {
        recognition.start();
        isListening = true;
        setOrbState('listening');
        setMode('Zuhören');
        status.textContent = '';
    } catch(e) {}
}

orb.addEventListener('click', () => {
    if (isPlaying) return;
    if (isListening) {
        recognition.stop();
        isListening = false;
        setOrbState('idle');
        setMode('Wartet auf Befehl');
        status.textContent = 'Pausiert. Klicke zum Fortsetzen.';
    } else {
        startListening();
    }
});

chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = chatInput.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

    addTranscript('user', text);
    chatInput.value = '';
    setBusy('Nachdenken', 'XEON denkt nach...');
    ws.send(JSON.stringify({ text, speak: speakOutput.checked }));
});

function setBusy(modeText, statusText) {
    appBusy = true;
    busyMode = modeText;
    if (isListening) {
        recognition.stop();
        isListening = false;
    }
    setOrbState('thinking');
    setMode(modeText);
    status.textContent = statusText;
}

function setOrbState(state) { orb.className = state; }
function setMode(text) { mode.textContent = text; }

function addTranscript(role, text) {
    const div = document.createElement('div');
    div.className = role;
    div.textContent = role === 'user' ? `Du: ${text}` : `XEON: ${text}`;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

connect();
