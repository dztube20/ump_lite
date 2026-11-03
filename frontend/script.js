// ========== DOM References ==========
const urlInput = document.getElementById('url-input');
const fetchBtn = document.getElementById('fetch-btn');
const formatsContainer = document.getElementById('formats-container');
const pendingList = document.getElementById('pending-list');
const downloadingList = document.getElementById('downloading-list');
const completedList = document.getElementById('completed-list');
const pendingCount = document.getElementById('pending-count');
const downloadingCount = document.getElementById('downloading-count');
const completedCount = document.getElementById('completed-count');
const logContainer = document.getElementById('log-container');

// ========== State ==========
let pendingQueue = [];
let downloadingJobs = [];
let completedJobs = [];
let jobEventSources = {};
let activeDownloads = 0;
const MAX_CONCURRENT = 3;
let queuedSet = new Set();

// ========== Sample links ==========
document.querySelectorAll('.sample-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        urlInput.value = link.getAttribute('data-url');
        fetchBtn.click();
    });
});

// ========== Event Listeners ==========
fetchBtn.addEventListener('click', () => {
    const url = urlInput.value.trim();
    if (!url) return alert('Enter a URL');
    fetchFormats(url);
});

urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') fetchBtn.click();
});

// ========== Logging ==========
function addLog(message, type = 'info') {
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    logContainer.appendChild(entry);
    logContainer.scrollTop = logContainer.scrollHeight;
}

// ========== Format Fetching ==========
async function fetchFormats(url) {
    formatsContainer.innerHTML = '';
    addLog(`⏳ Fetching formats for ${url}...`, 'info');
    try {
        const resp = await fetch('/api/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Failed to fetch');
        }
        const data = await resp.json();
        addLog(`✅ Found ${data.formats.length} formats`, 'success');
        displayFormats(data.formats, url);
    } catch (err) {
        addLog(`❌ Error: ${err.message}`, 'error');
        formatsContainer.innerHTML = `<div class="error-msg">${err.message}</div>`;
    }
}

// ========== displayFormats ==========
function displayFormats(formats, pageUrl) {
    let html = '<div class="format-grid">';
    formats.forEach((f) => {
        const hasVideo = f.has_video;
        const hasAudio = f.has_audio;
        let badge = '';
        let typeLabel = '';
        if (hasVideo && hasAudio) {
            badge = '<span class="badge both">✓ Both</span>';
            typeLabel = 'Video + Audio';
        } else if (hasVideo) {
            badge = '<span class="badge video">🎬 Video</span>';
            typeLabel = 'Video only';
        } else if (hasAudio) {
            badge = '<span class="badge audio">🎵 Audio</span>';
            typeLabel = 'Audio only';
        } else {
            badge = '<span class="badge">?</span>';
            typeLabel = 'Unknown';
        }

        const quality = f.quality || 'unknown';
        const size = f.size ? (f.size / 1024 / 1024).toFixed(1) + ' MB' : '';
        const formatId = f.format_id;
        const height = f.height ? `${f.height}p` : '';
        const fps = f.fps ? `${f.fps}fps` : '';
        const details = [height, fps, f.ext].filter(Boolean).join(' · ');
        const videoUrl = f.url || '';

        html += `
            <div class="format-card" data-format-id="${formatId}">
                <div>${badge} <span style="font-size:0.8rem;color:#8b949e;">${typeLabel}</span></div>
                <div class="format-quality">${quality}</div>
                <div class="format-details">
                    <span>${details || 'unknown'}</span>
                    ${size ? `<span>${size}</span>` : ''}
                    ${f.note ? `<span>${f.note}</span>` : ''}
                </div>
                <button class="format-select-btn" 
                        data-page-url="${pageUrl}" 
                        data-format-id="${formatId}"
                        data-video-url="${videoUrl}">
                    Add to Queue
                </button>
            </div>
        `;
    });
    html += '</div>';
    formatsContainer.innerHTML = html;

    document.querySelectorAll('.format-select-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const pageUrl = btn.getAttribute('data-page-url');
            const formatId = btn.getAttribute('data-format-id');
            const videoUrl = btn.getAttribute('data-video-url');
            addToQueue(pageUrl, formatId, videoUrl);
        });
    });
}

// ========== Queue Management ==========
function addToQueue(pageUrl, formatId, videoUrl) {
    const key = `${pageUrl}::${formatId}`;
    if (queuedSet.has(key)) {
        addLog('⚠️ Already in queue', 'error');
        return;
    }
    queuedSet.add(key);

    const job = {
        id: `job-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
        pageUrl,
        formatId,
        videoUrl,
        title: pageUrl,
        status: 'pending',
        progress: 0,
        error: null,
        fileUrl: null,
        jobId: null,
    };
    pendingQueue.push(job);
    updateUI();
    addLog(`📥 Added to queue: ${pageUrl}`, 'info');
    processQueue();
}

function processQueue() {
    while (activeDownloads < MAX_CONCURRENT && pendingQueue.length > 0) {
        const job = pendingQueue.shift();
        job.status = 'downloading';
        downloadingJobs.push(job);
        activeDownloads++;
        startDownload(job);
        updateUI();
    }
}

function startDownload(job) {
    addLog(`⏳ Starting download: ${job.title}`, 'info');
    const payload = {
        url: job.pageUrl,
        format_id: job.formatId,
        video_url: job.videoUrl || undefined
    };
    fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            job.status = 'error';
            job.error = data.error;
            activeDownloads--;
            addLog(`❌ ${data.error}`, 'error');
            const idx = downloadingJobs.indexOf(job);
            if (idx !== -1) downloadingJobs.splice(idx, 1);
            queuedSet.delete(`${job.pageUrl}::${job.formatId}`);
            updateUI();
            processQueue();
            return;
        }
        job.jobId = data.job_id;
        connectSSE(job);
        updateUI();
    })
    .catch(err => {
        job.status = 'error';
        job.error = err.message;
        activeDownloads--;
        addLog(`❌ Failed to start: ${err.message}`, 'error');
        const idx = downloadingJobs.indexOf(job);
        if (idx !== -1) downloadingJobs.splice(idx, 1);
        queuedSet.delete(`${job.pageUrl}::${job.formatId}`);
        updateUI();
        processQueue();
    });
}

function connectSSE(job) {
    if (jobEventSources[job.jobId]) {
        jobEventSources[job.jobId].close();
    }
    const es = new EventSource(`/api/progress/${job.jobId}`);
    jobEventSources[job.jobId] = es;

    es.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.error) {
                job.status = 'error';
                job.error = data.error;
                es.close();
                activeDownloads--;
                addLog(`❌ ${data.error}`, 'error');
                const idx = downloadingJobs.indexOf(job);
                if (idx !== -1) downloadingJobs.splice(idx, 1);
                queuedSet.delete(`${job.pageUrl}::${job.formatId}`);
                updateUI();
                processQueue();
                return;
            }
            if (data.progress !== undefined) {
                job.progress = data.progress;
                updateUI();
            }
            if (data.complete && data.file_url) {
                job.status = 'completed';
                job.fileUrl = data.file_url;
                es.close();
                activeDownloads--;
                addLog(`✅ Download complete: ${job.title}`, 'success');
                const idx = downloadingJobs.indexOf(job);
                if (idx !== -1) downloadingJobs.splice(idx, 1);
                completedJobs.push(job);
                updateUI();
                processQueue();
            }
        } catch (err) {
            console.error('SSE parse error', err);
        }
    };

    es.onerror = () => {
        if (job.status === 'downloading') {
            setTimeout(() => {
                if (es.readyState !== EventSource.CLOSED) {
                    es.close();
                    connectSSE(job);
                }
            }, 3000);
        }
    };
}

// ========== Actions: Delete, Retry, Save ==========
function deleteJob(jobId) {
    let job = pendingQueue.find(j => j.id === jobId);
    if (job) {
        pendingQueue = pendingQueue.filter(j => j.id !== jobId);
        queuedSet.delete(`${job.pageUrl}::${job.formatId}`);
        updateUI();
        addLog(`🗑️ Removed from pending: ${job.title}`, 'info');
        return;
    }
    job = downloadingJobs.find(j => j.id === jobId);
    if (job) {
        if (job.jobId) {
            fetch(`/api/delete/${job.jobId}`, { method: 'DELETE' })
                .catch(err => console.error(err));
        }
        downloadingJobs = downloadingJobs.filter(j => j.id !== jobId);
        queuedSet.delete(`${job.pageUrl}::${job.formatId}`);
        activeDownloads--;
        updateUI();
        addLog(`🗑️ Removed from downloading: ${job.title}`, 'info');
        processQueue();
        return;
    }
    job = completedJobs.find(j => j.id === jobId);
    if (job) {
        if (job.jobId) {
            fetch(`/api/delete/${job.jobId}`, { method: 'DELETE' })
                .catch(err => console.error(err));
        }
        completedJobs = completedJobs.filter(j => j.id !== jobId);
        queuedSet.delete(`${job.pageUrl}::${job.formatId}`);
        updateUI();
        addLog(`🗑️ Removed from completed: ${job.title}`, 'info');
        return;
    }
}

function retryJob(jobId) {
    let job = completedJobs.find(j => j.id === jobId);
    if (!job) return;
    completedJobs = completedJobs.filter(j => j.id !== jobId);
    job.status = 'pending';
    job.progress = 0;
    job.error = null;
    job.fileUrl = null;
    job.jobId = null;
    pendingQueue.push(job);
    updateUI();
    addLog(`↻ Retrying: ${job.title}`, 'info');
    processQueue();
}

function saveFile(fileUrl) {
    const a = document.createElement('a');
    a.href = fileUrl;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    addLog('📂 File download started', 'info');
}

// ========== UI Update ==========
function updateUI() {
    pendingList.innerHTML = pendingQueue.map(j => `
        <div class="download-item">
            <div class="title">${j.title}</div>
            <div class="status">⏳ Pending</div>
            <div class="actions">
                <button class="delete-btn" onclick="deleteJob('${j.id}')">✕</button>
            </div>
        </div>
    `).join('');
    pendingCount.textContent = pendingQueue.length;

    downloadingList.innerHTML = downloadingJobs.map(j => `
        <div class="download-item">
            <div class="title">${j.title}</div>
            <div class="progress-track"><div class="progress-bar" style="width:${j.progress}%"></div></div>
            <div class="status">${j.progress}%</div>
            <div class="actions">
                <button class="delete-btn" onclick="deleteJob('${j.id}')">✕</button>
            </div>
        </div>
    `).join('');
    downloadingCount.textContent = `${downloadingJobs.length}/${MAX_CONCURRENT}`;

    completedList.innerHTML = completedJobs.map(j => `
        <div class="download-item">
            <div class="title">${j.title}</div>
            <div class="status">✅ Complete</div>
            <div class="actions">
                ${j.fileUrl ? `<button class="save-btn" onclick="saveFile('${j.fileUrl}')">💾 Save</button>` : ''}
                <button class="retry-btn" onclick="retryJob('${j.id}')">↻ Retry</button>
                <button class="delete-btn" onclick="deleteJob('${j.id}')">✕</button>
            </div>
        </div>
    `).join('');
    completedCount.textContent = completedJobs.length;
}

// ========== Log Export & Clear ==========
document.getElementById('export-log-btn')?.addEventListener('click', () => {
    const entries = logContainer.querySelectorAll('.log-entry');
    const lines = Array.from(entries).map(e => e.textContent);
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `ump-log-${new Date().toISOString().slice(0,10)}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
});

document.getElementById('clear-log-btn')?.addEventListener('click', () => {
    logContainer.innerHTML = '';
});

// ========== Initial Log ==========
addLog('🔄 Ready – enter a URL and click Fetch', 'info');