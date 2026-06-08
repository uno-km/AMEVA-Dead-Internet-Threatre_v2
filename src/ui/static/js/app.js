let currentPostId = null;
        let knownCommentIds = new Set();
        let systemStatusMap = {};
        
        // Inspector State
        let inspectorOpenBot = null;
        let inspectorAutoRefresh = true;
        let inspectorPollTimer = null;
        
        let lastSummaryHash = null;
        let lastDetailHash = null;

        let radarChartInstance = null;
        let arousalChartInstance = null;
        let stanceChartInstance = null;
        let convictionChartInstance = null;  // Phase 3

        let lastSummaryData = null;
        let lastDetailData = null;

        // =====================================================================
        // Phase 3: Comparison Panel State
        // =====================================================================
        let compStanceChartInstance = null;
        let compConvictionChartInstance = null;
        let compArousalChartInstance = null;
        let compTrajectoryData = {};  // {bot_1: [...points], bot_2: [...], bot_3: [...]}
        let allTurnIndices = [];

        const ROLE_LABEL_MAP = {
            "pole_a_hardliner":        { label: "Pole A Hardliner", cssClass: "role-pole-a", emoji: "🔴" },
            "pole_b_hardliner":        { label: "Pole B Hardliner", cssClass: "role-pole-b", emoji: "🔵" },
            "swing_moderate":          { label: "Swing Moderate",   cssClass: "role-swing",  emoji: "🟢" },
            "lean_a_soft":             { label: "Lean A Soft",      cssClass: "role-lean",   emoji: "🟡" },
            "lean_b_soft":             { label: "Lean B Soft",      cssClass: "role-lean",   emoji: "🟡" },
            "opportunistic_bandwagon": { label: "Opportunist",      cssClass: "role-opport", emoji: "🟣" },
            "nihilist_observer":       { label: "Nihilist",         cssClass: "role-nihil",  emoji: "⚪" },
        };

        function getRoleInfo(role_label) {
            return ROLE_LABEL_MAP[role_label] || { label: role_label, cssClass: "role-nihil", emoji: "⚫" };
        }

        let currentErrorToast = null;
        function showErrorToast(msg) {
            if (currentErrorToast === msg) return;
            currentErrorToast = msg;
            
            // Remove existing toast if any
            const existing = document.getElementById('error-toast-ui');
            if (existing) existing.remove();
            
            const toast = document.createElement('div');
            toast.id = 'error-toast-ui';
            toast.className = 'fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-red-600 text-white font-bold px-8 py-4 rounded-2xl shadow-[0_0_20px_rgba(220,38,38,0.8)] z-[100] animate-bounce flex flex-col items-center gap-2 border-4 border-red-400';
            toast.innerHTML = `
                <div class="text-4xl mb-2">⚠️</div>
                <div class="text-xl">시스템 오류 감지</div>
                <div class="text-sm opacity-90">${msg}</div>
                <button onclick="this.parentElement.remove(); currentErrorToast=null;" class="mt-4 px-4 py-1 bg-white text-red-600 rounded-full text-xs uppercase hover:bg-gray-100">닫기</button>
            `;
            document.body.appendChild(toast);
        }

        // --- Fetch System Status ---
        async function fetchSystemStatus() {
            try {
                const res = await fetch('/api/system/status');
                systemStatusMap = await res.json();
                
                let godRunning = systemStatusMap["ameva-llm-god"] === "RUNNING";
                let mainRunning = systemStatusMap["ameva-llm-main"] === "RUNNING";
                
                let globalState = systemStatusMap["state"] || systemStatusMap["global_state"] || "UNKNOWN";
                let lastError = systemStatusMap["last_error"];
                
                let globalBadge = document.getElementById('global-state-badge');
                globalBadge.textContent = globalState;
                if(globalState === "RUNNING") {
                    globalBadge.className = "ml-2 text-xs px-2 py-1 rounded-full font-bold bg-green-500 text-white shadow-[0_0_8px_rgba(34,197,94,0.6)] animate-pulse";
                } else if(globalState === "PAUSED" || globalState === "PAUSING") {
                    globalBadge.className = "ml-2 text-xs px-2 py-1 rounded-full font-bold bg-yellow-500 text-white shadow-[0_0_8px_rgba(234,179,8,0.6)]";
                } else if(globalState === "ERROR") {
                    globalBadge.className = "ml-2 text-xs px-2 py-1 rounded-full font-bold bg-red-600 text-white animate-pulse shadow-[0_0_8px_rgba(220,38,38,0.8)]";
                    if (lastError) showErrorToast(lastError);
                } else {
                    globalBadge.className = "ml-2 text-xs px-2 py-1 rounded-full font-bold bg-gray-200 text-gray-600";
                }
                
                document.getElementById('god-status-dot').className = "inline-block w-3 h-3 rounded-full mr-1.5 transition-colors duration-500 " + (godRunning ? "bg-green-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]" : "bg-red-500");
                document.getElementById('main-status-dot').className = "inline-block w-3 h-3 rounded-full mr-1.5 transition-colors duration-500 " + (mainRunning ? "bg-green-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]" : "bg-red-500");
            } catch (err) {
                console.error("System status fetch error:", err);
            }
        }
        
        // --- Fetch Bot States ---
        async function fetchBotStates() {
            try {
                const res = await fetch('/api/bots/state');
                const data = await res.json();
                
                const badge = document.getElementById('session-status-badge');
                if (data.session_status === 'ACTIVE') {
                    badge.className = "text-xs px-2 py-1 rounded-full font-bold bg-green-200 text-green-800";
                    badge.innerText = "ACTIVE";
                    hidePoliceWarning();
                } else if (data.session_status === 'CLOSED_BY_POLICE') {
                    badge.className = "text-xs px-2 py-1 rounded-full font-bold bg-red-600 text-white animate-pulse";
                    badge.innerText = "POLICE DISPATCHED";
                    showPoliceWarning();
                } else {
                    badge.className = "text-xs px-2 py-1 rounded-full font-bold bg-gray-200 text-gray-600";
                    badge.innerText = data.session_status || "UNKNOWN";
                    hidePoliceWarning();
                }

                const container = document.getElementById('bot-states-container');
                container.innerHTML = '';
                
                const bots = data.states || data.bots || [];
                if (bots && bots.length > 0) {
                    bots.forEach(bot => {
                        let eff = bot.effective_anger !== undefined ? bot.effective_anger : (bot.eff_anger || 0);
                        let pct = Math.min(eff, 100);
                        
                        let angerTargets = typeof bot.anger_targets === 'object' ? bot.anger_targets : {};
                        let targetHtml = Object.entries(angerTargets).map(([t, val]) => 
                            `<div class="flex justify-between text-xs text-gray-600"><span>vs ${t}</span><span class="font-bold text-red-500">${val}</span></div>`
                        ).join('');

                        let botDockerName = "ameva-llm-" + bot.bot_name.toLowerCase().replace('_', '-');
                        let isRunning = systemStatusMap[botDockerName] === "RUNNING";
                        let statusDot = isRunning ? '<span class="inline-block w-3 h-3 rounded-full bg-green-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)] mr-1.5"></span>' : '<span class="inline-block w-3 h-3 rounded-full bg-red-500 mr-1.5 transition-colors duration-500"></span>';

                        let directiveText = bot.current_directive ? `<div class="mt-2 text-xs font-medium text-indigo-700 bg-indigo-50 p-2 rounded border border-indigo-100">🗣️ <b>현재 지침:</b> ${bot.current_directive}</div>` : '';

                        container.innerHTML += `
                            <div onclick="openInspector('${bot.bot_name}')" class="cursor-pointer hover:bg-indigo-50 hover:shadow-md bg-white bg-opacity-50 p-3 rounded-xl border-2 ${isRunning ? 'border-green-300' : 'border-transparent'} transition-all duration-300 transform hover:-translate-y-1">
                                <div class="flex justify-between items-end mb-1">
                                    <span class="font-bold text-gray-800 flex items-center">${statusDot}${bot.bot_name.toUpperCase()}</span>
                                    <span class="text-xs font-black ${eff >= 50 ? 'text-red-600' : 'text-gray-500'}">Vector: ${eff.toFixed(1)}</span>
                                </div>
                                <div class="w-full bg-gray-200 rounded-full h-1.5 mb-2">
                                    <div class="bg-gradient-to-r from-yellow-400 to-red-600 h-1.5 rounded-full transition-all duration-1000" style="width: ${pct}%"></div>
                                </div>
                                <div class="space-y-0.5">
                                    ${targetHtml || '<div class="text-xs text-gray-400">평온함</div>'}
                                </div>
                                ${directiveText}
                            </div>
                        `;
                    });
                }
            } catch (err) {
                console.error("Bot state fetch error:", err);
            }
        }

        // --- Fetch Post List ---
        async function fetchPostList() {
            try {
                const res = await fetch('/api/posts');
                const posts = await res.json();
                
                const container = document.getElementById('post-list-container');
                container.innerHTML = '';
                
                if (posts.length === 0) {
                    container.innerHTML = '<div class="text-sm text-gray-400 italic text-center py-4">게시글이 없습니다.</div>';
                    return;
                }

                if (!currentPostId) {
                    selectPost(posts[0].id);
                }

                posts.forEach(p => {
                    const isActive = p.id === currentPostId;
                    const btnClass = isActive 
                        ? 'bg-indigo-500 text-white shadow-md' 
                        : 'bg-white bg-opacity-50 text-gray-700 hover:bg-indigo-100 transition-colors';
                    
                    container.innerHTML += `
                        <button onclick="selectPost(${p.id})" class="w-full text-left p-3 rounded-xl border border-white border-opacity-40 ${btnClass}">
                            <div class="text-xs font-mono opacity-70">#${p.id}</div>
                            <div class="font-bold truncate text-sm mt-0.5">${p.title}</div>
                        </button>
                    `;
                });
            } catch (err) {
                console.error("Post list fetch error:", err);
            }
        }

        function selectPost(id) {
            if (currentPostId !== id) {
                currentPostId = id;
                knownCommentIds.clear();
                document.getElementById('comments-container').innerHTML = '';
                fetchPostDetail();
                fetchPostList();
            }
        }

        function getAvatarColor(name) {
            if(name === 'police') return 'bg-blue-600';
            if(name === 'bot_1') return 'bg-purple-500';
            if(name === 'bot_2') return 'bg-pink-500';
            if(name === 'bot_3') return 'bg-green-500';
            return 'bg-indigo-500';
        }

        async function fetchPostDetail() {
            if (!currentPostId) return;
            try {
                const res = await fetch(`/api/posts/${currentPostId}`);
                const data = await res.json();
                if (data.error) return;

                document.getElementById('current-post-id').innerText = `POST #${data.id}`;
                document.getElementById('current-post-title').innerText = data.title;
                document.getElementById('current-post-content').innerText = data.content;
                document.getElementById('current-post-date').innerText = data.created_at;

                const container = document.getElementById('comments-container');
                let newCommentAdded = false;
                let htmlBuffer = '';
                
                data.comments.forEach(c => {
                    const isNew = !knownCommentIds.has(c.id);
                    if (isNew) {
                        knownCommentIds.add(c.id);
                        newCommentAdded = true;
                    }

                    const animClass = isNew ? 'comment-new' : '';
                    const avatarColor = getAvatarColor(c.bot_name);
                    const mentionHtml = c.mentioned_bot ? `<span class="text-xs font-bold text-indigo-500 bg-indigo-50 px-2 py-0.5 rounded ml-2">@${c.mentioned_bot}</span>` : '';
                    
                    htmlBuffer += `
                        <div class="bg-white bg-opacity-70 rounded-2xl p-4 shadow-sm border border-white flex gap-4 ${animClass}">
                            <div class="flex-shrink-0">
                                <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-white shadow-inner ${avatarColor}">
                                    ${c.bot_name.substring(0,3).toUpperCase()}
                                </div>
                            </div>
                            <div class="flex-1">
                                <div class="flex items-center justify-between mb-1">
                                    <div>
                                        <span class="font-bold text-gray-900">${c.bot_name}</span>
                                        <span class="text-xs text-gray-400 ml-1">#${c.id}</span>
                                        ${mentionHtml}
                                    </div>
                                    <span class="text-xs text-gray-400">${c.created_at}</span>
                                </div>
                                <p class="text-gray-800 text-sm leading-relaxed whitespace-pre-wrap">${c.content}</p>
                            </div>
                        </div>
                    `;
                });

                if (htmlBuffer !== container.innerHTML) {
                    container.innerHTML = htmlBuffer;
                    if (newCommentAdded) {
                        const scrollArea = document.getElementById('comments-scroll-area');
                        scrollArea.scrollTo({ top: scrollArea.scrollHeight, behavior: 'smooth' });
                    }
                }
            } catch (err) {
                console.error("Post detail fetch error:", err);
            }
        }

        function showPoliceWarning() {
            const el = document.getElementById('police-warning');
            el.classList.remove('hidden');
            setTimeout(() => {
                el.classList.remove('opacity-0');
                el.classList.add('opacity-100');
            }, 50);
        }

        function hidePoliceWarning() {
            const el = document.getElementById('police-warning');
            el.classList.remove('opacity-100');
            el.classList.add('opacity-0');
            setTimeout(() => {
                el.classList.add('hidden');
            }, 1000);
        }

        // --- Bot Inspector Logic (단일 봇) ---

        function toggleAutoRefresh() {
            inspectorAutoRefresh = document.getElementById('inspector-auto-refresh').checked;
            if (inspectorAutoRefresh && inspectorOpenBot) {
                forceFetchInspectorData();
            }
        }

        function openInspector(botName) {
            inspectorOpenBot = botName;
            document.getElementById('inspector-bot-name').innerText = botName;
            document.getElementById('inspector-overlay').classList.remove('hidden');
            document.getElementById('inspector-drawer').classList.remove('translate-x-full');
            
            lastSummaryHash = null;
            lastDetailHash = null;

            fetchSessionsList();
            forceFetchInspectorData();
        }

        function closeInspector() {
            inspectorOpenBot = null;
            if (inspectorPollTimer) clearTimeout(inspectorPollTimer);
            document.getElementById('inspector-overlay').classList.add('hidden');
            document.getElementById('inspector-drawer').classList.add('translate-x-full');
        }

        function copyToClipboard(type) {
            let dataToCopy = "";
            if (type === 'summary' && lastSummaryData) dataToCopy = JSON.stringify(lastSummaryData, null, 2);
            else if (type === 'delta' && lastSummaryData) dataToCopy = JSON.stringify(lastSummaryData.deltas, null, 2);
            else if (type === 'detail' && lastDetailData) dataToCopy = JSON.stringify(lastDetailData.raw_tensors, null, 2);
            
            if (dataToCopy) {
                navigator.clipboard.writeText(dataToCopy).then(() => {
                    alert('Copied to clipboard!');
                });
            } else {
                alert('No data available to copy.');
            }
        }

        async function fetchSessionsList() {
            try {
                const res = await fetch('/api/sessions');
                const sessions = await res.json();
                const select = document.getElementById('inspector-session-select');
                const currentVal = select.value;
                
                select.innerHTML = '<option value="">Latest Session</option>';
                sessions.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.id;
                    opt.innerText = `Session #${s.id} (${s.status})`;
                    select.appendChild(opt);
                });
                
                if (currentVal) {
                    select.value = currentVal;
                }

                // Also populate comparison panel session select
                const compSelect = document.getElementById('comparison-session-select');
                if (compSelect) {
                    const compVal = compSelect.value;
                    compSelect.innerHTML = '<option value="">Latest Session</option>';
                    sessions.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s.id;
                        opt.innerText = `Session #${s.id} (${s.status})`;
                        compSelect.appendChild(opt);
                    });
                    if (compVal) compSelect.value = compVal;
                }
            } catch (err) {
                console.error("Failed to fetch sessions:", err);
            }
        }

        function getSafeVal(arr, index) {
            if (!arr || arr.length <= index) return null;
            return arr[index];
        }

        function forceFetchInspectorData() {
            if (inspectorPollTimer) clearTimeout(inspectorPollTimer);
            lastSummaryHash = null;
            lastDetailHash = null;
            fetchInspectorCycle();
        }

        // Adaptive polling cycle
        async function fetchInspectorCycle() {
            if (!inspectorOpenBot) return;

            const isTabVisible = !document.hidden;
            const globalState = systemStatusMap["global_state"] || "UNKNOWN";
            const isRunning = globalState === "RUNNING";

            if (isTabVisible && inspectorAutoRefresh) {
                try {
                    const sessionSelect = document.getElementById('inspector-session-select').value;
                    let baseQuery = sessionSelect ? `?session_id=${sessionSelect}` : '';

                    const resSum = await fetch(`/api/lpde/bot/${inspectorOpenBot}/summary${baseQuery}`);
                    const summaryData = await resSum.json();
                    
                    const newSumHash = JSON.stringify(summaryData);
                    if (newSumHash !== lastSummaryHash) {
                        lastSummaryHash = newSumHash;
                        lastSummaryData = summaryData;
                        renderSummary(summaryData);
                    }

                    if (summaryData.message !== "No LPDE state yet for this session") {
                        let detailQuery = sessionSelect ? `?session_id=${sessionSelect}&limit=50` : '?limit=50';
                        const resDet = await fetch(`/api/lpde/bot/${inspectorOpenBot}/detail${detailQuery}`);
                        const detailData = await resDet.json();
                        
                        const newDetHash = JSON.stringify(detailData);
                        if (newDetHash !== lastDetailHash) {
                            lastDetailHash = newDetHash;
                            lastDetailData = detailData;
                            renderDetail(detailData);
                        }
                    }

                } catch (err) {
                    console.error("Inspector polling error:", err);
                }
            }

            let delay = 10000;
            if (isTabVisible && isRunning) {
                delay = 2500;
            }
            inspectorPollTimer = setTimeout(fetchInspectorCycle, delay);
        }

        function renderSummary(data) {
            const emptyEl = document.getElementById('inspector-empty-msg');
            if (data.message === "No LPDE state yet for this session") {
                emptyEl.classList.remove('hidden');
                document.getElementById('inspector-raw-json').innerText = "Empty";
            } else {
                emptyEl.classList.add('hidden');
            }

            document.getElementById('inspector-phase').innerText = `Phase: ${data.phase || 'Unknown'}`;
            document.getElementById('inspector-persona').innerText = (data.legacy_state && data.legacy_state.persona) || 'None';
            document.getElementById('inspector-directive').innerText = (data.legacy_state && data.legacy_state.current_directive) || 'None';

            // Phase 3: Role Badge
            const roleBadge = document.getElementById('inspector-role-badge');
            if (data.role_label) {
                const roleInfo = getRoleInfo(data.role_label);
                roleBadge.textContent = `${roleInfo.emoji} ${roleInfo.label}`;
                roleBadge.className = `text-xs font-bold px-2 py-0.5 rounded border ${roleInfo.cssClass}`;
                roleBadge.style.display = 'inline-block';
            } else {
                roleBadge.style.display = 'none';
            }

            const activeDims = data.active_dims || [];
            const isAffectActive = activeDims.includes('affect');
            const isOpinionActive = activeDims.includes('opinion');
            const isPowerActive = activeDims.includes('power');

            const t = data.lpde_tensors || {};
            const d = data.deltas || {};

            function buildChip(label, valArr, deltaArr, index, isActive) {
                const val = getSafeVal(valArr, index);
                const delta = getSafeVal(deltaArr, index);
                
                if (!isActive || val === null || val === undefined) {
                    return `
                    <div class="bg-gray-100 p-2 rounded border border-gray-200 opacity-60">
                        <div class="text-[10px] text-gray-500 font-bold uppercase">${label}</div>
                        <div class="text-sm font-bold text-gray-400 mt-1 flex justify-between items-center">
                            N/A <span class="text-[10px] bg-gray-200 px-1 rounded">Inactive</span>
                        </div>
                    </div>`;
                }
                
                const deltaColor = delta > 0 ? 'text-green-600' : (delta < 0 ? 'text-red-600' : 'text-gray-400');
                const deltaSign = delta > 0 ? '▲ +' : (delta < 0 ? '▼ ' : '');
                const deltaText = (delta !== 0 && delta !== null) ? `${deltaSign}${delta}` : (delta === null ? 'N/A' : '-');

                return `
                <div class="bg-white p-2 rounded border border-gray-200 shadow-sm">
                    <div class="text-[10px] text-gray-500 font-bold uppercase">${label}</div>
                    <div class="text-sm font-bold text-gray-900 mt-1 flex justify-between items-center">
                        ${val.toFixed(2)}
                        <span class="text-[10px] font-bold ${deltaColor}">${deltaText}</span>
                    </div>
                </div>`;
            }

            // Phase 3: opinion 차원 재정의 레이블
            const chipsHtml = `
                ${buildChip('Valence', t.affect, d.affect, 0, isAffectActive)}
                ${buildChip('Arousal', t.affect, d.affect, 1, isAffectActive)}
                ${buildChip('Stance Pole', t.opinion, d.opinion, 0, isOpinionActive)}
                ${buildChip('Conviction', t.opinion, d.opinion, 1, isOpinionActive)}
                ${buildChip('Self Appraisal', t.power, d.power, 0, isPowerActive)}
                ${buildChip('Sys. Influence', t.power, d.power, 1, isPowerActive)}
            `;
            document.getElementById('inspector-summary-chips').innerHTML = chipsHtml;

            const rValence = isAffectActive ? (getSafeVal(t.affect, 0) || 0) : 0;
            const rArousal = isAffectActive ? (getSafeVal(t.affect, 1) || 0) : 0;
            const rStance = isOpinionActive ? (getSafeVal(t.opinion, 0) || 0) : 0;
            const rConviction = isOpinionActive ? (getSafeVal(t.opinion, 1) || 0) : 0;
            const rSelf = isPowerActive ? (getSafeVal(t.power, 0) || 0) : 0;
            const rSys = isPowerActive ? (getSafeVal(t.power, 1) || 0) : 0;

            const radarData = [rValence, rArousal, rStance, rConviction, rSelf, rSys];

            if (!radarChartInstance) {
                const ctxR = document.getElementById('radarChart').getContext('2d');
                radarChartInstance = new Chart(ctxR, {
                    type: 'radar',
                    data: {
                        labels: ['Valence', 'Arousal', 'Stance Pole', 'Conviction', 'Self Appr.', 'Sys. Infl.'],
                        datasets: [{
                            label: 'Current State',
                            data: radarData,
                            backgroundColor: 'rgba(99, 102, 241, 0.2)',
                            borderColor: 'rgba(99, 102, 241, 1)',
                            pointBackgroundColor: 'rgba(99, 102, 241, 1)',
                            pointBorderColor: '#fff',
                            spanGaps: false
                        }]
                    },
                    options: {
                        scales: {
                            r: { min: -1, max: 1, ticks: { stepSize: 0.5, display: false } }
                        },
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) { label += ': '; }
                                        if (context.parsed.r !== null) { label += context.parsed.r; }
                                        else { label += 'Inactive / Not used'; }
                                        return label;
                                    }
                                }
                            }
                        }
                    }
                });
            } else {
                radarChartInstance.data.datasets[0].data = radarData;
                radarChartInstance.update('none');
            }
        }

        function renderDetail(data) {
            document.getElementById('inspector-raw-json').innerText = JSON.stringify(data.raw_tensors, null, 2);

            const labels = data.time_series.map(s => `T${s.turn_index}`);
            const arousalData = data.time_series.map(s => getSafeVal(s.affect, 1) || 0);
            const stanceData = data.time_series.map(s => getSafeVal(s.opinion, 0) || 0);
            const convictionData = data.time_series.map(s => getSafeVal(s.opinion, 1) || 0);

            // Primary: Arousal
            if (!arousalChartInstance) {
                const ctxA = document.getElementById('arousalChart').getContext('2d');
                arousalChartInstance = new Chart(ctxA, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Arousal',
                            data: arousalData,
                            borderColor: 'rgb(239, 68, 68)',
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            fill: true, tension: 0.3, borderWidth: 2, pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: { y: { min: -1, max: 1 } },
                        plugins: { legend: { display: false } },
                        animation: { duration: 0 }
                    }
                });
            } else {
                arousalChartInstance.data.labels = labels;
                arousalChartInstance.data.datasets[0].data = arousalData;
                arousalChartInstance.update('none');
            }

            // Stance Pole
            if (!stanceChartInstance) {
                const ctxS = document.getElementById('stanceChart').getContext('2d');
                stanceChartInstance = new Chart(ctxS, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Stance Pole',
                            data: stanceData,
                            borderColor: 'rgb(59, 130, 246)',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            fill: true, tension: 0.3, borderWidth: 2, pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: { y: { min: -1, max: 1 } },
                        plugins: { legend: { display: false } },
                        animation: { duration: 0 }
                    }
                });
            } else {
                stanceChartInstance.data.labels = labels;
                stanceChartInstance.data.datasets[0].data = stanceData;
                stanceChartInstance.update('none');
            }

            // Phase 3: Conviction
            if (!convictionChartInstance) {
                const ctxC = document.getElementById('convictionChart').getContext('2d');
                convictionChartInstance = new Chart(ctxC, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Conviction',
                            data: convictionData,
                            borderColor: 'rgb(168, 85, 247)',
                            backgroundColor: 'rgba(168, 85, 247, 0.1)',
                            fill: true, tension: 0.3, borderWidth: 2, pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: { y: { min: 0, max: 1 } },
                        plugins: { legend: { display: false } },
                        animation: { duration: 0 }
                    }
                });
            } else {
                convictionChartInstance.data.labels = labels;
                convictionChartInstance.data.datasets[0].data = convictionData;
                convictionChartInstance.update('none');
            }

            // Edges Table
            const edgesTbody = document.getElementById('inspector-edges-tbody');
            if (!data.edges || data.edges.length === 0) {
                edgesTbody.innerHTML = '<tr><td colspan="3" class="text-center p-4 text-gray-400 italic">No edges found</td></tr>';
            } else {
                let edgesHtml = '';
                data.edges.forEach(e => {
                    edgesHtml += `
                        <tr class="hover:bg-gray-50">
                            <td class="p-2 font-mono">${e.source}</td>
                            <td class="p-2 font-mono">${e.target}</td>
                            <td class="p-2 text-right">${JSON.stringify(e.relation)}</td>
                        </tr>
                    `;
                });
                edgesTbody.innerHTML = edgesHtml;
            }

            // Interventions
            const intContainer = document.getElementById('inspector-interventions');
            if (!data.interventions || data.interventions.length === 0) {
                intContainer.innerHTML = '<div class="text-gray-400 italic text-center py-2">No recent interventions</div>';
            } else {
                let intHtml = '';
                data.interventions.forEach(inv => {
                    intHtml += `
                    <div class="bg-gray-50 p-2 rounded border border-gray-200">
                        <div class="flex justify-between items-center mb-1">
                            <span class="font-bold text-indigo-700">Turn ${inv.turn_index}</span>
                            <span class="text-[10px] bg-red-100 text-red-700 px-1 rounded uppercase">${inv.kind}</span>
                        </div>
                        <div class="text-gray-700 mb-1 leading-tight">${inv.reason || 'No reason specified'}</div>
                        <div class="text-[10px] text-gray-500 font-mono bg-gray-100 p-1 rounded">Delta: ${JSON.stringify(inv.delta)}</div>
                    </div>`;
                });
                intContainer.innerHTML = intHtml;
            }

            // Recent Events
            const evtContainer = document.getElementById('inspector-recent-events');
            if (evtContainer) {
                if (!data.recent_events || data.recent_events.length === 0) {
                    evtContainer.innerHTML = '<div class="text-gray-400 italic text-center py-2">No recent events</div>';
                } else {
                    let evtHtml = '';
                    data.recent_events.forEach(evt => {
                        let evtsStr = evt.events ? evt.events.join(", ") : "None";
                        evtHtml += `
                        <div class="bg-white p-2 rounded border border-gray-200 shadow-sm mb-2">
                            <div class="flex justify-between items-center mb-1">
                                <span class="font-bold text-blue-700 text-xs">Turn ${evt.turn_index}</span>
                                <span class="text-[10px] bg-blue-100 text-blue-800 px-1 rounded font-mono">${evtsStr}</span>
                            </div>
                            <div class="text-xs text-gray-700">
                                Target: <span class="font-semibold">${evt.target || 'None'}</span> | 
                                Intensity: <span class="font-semibold text-red-600">${evt.intensity.toFixed(2)}</span>
                            </div>
                        </div>`;
                    });
                    evtContainer.innerHTML = evtHtml;
                }
            }
        }

        // =====================================================================
        // Phase 3: 3-Bot Comparison Panel
        // =====================================================================

        function openComparison() {
            document.getElementById('comparison-overlay').classList.remove('hidden');
            document.getElementById('comparison-panel').classList.remove('hidden');
            fetchSessionsList();
            loadComparisonData();
        }

        function closeComparison() {
            document.getElementById('comparison-overlay').classList.add('hidden');
            document.getElementById('comparison-panel').classList.add('hidden');
        }

        function switchComparisonTab(tab, btn) {
            // Hide all panels
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => {
                b.classList.remove('active');
                b.classList.add('text-gray-500', 'bg-gray-50');
            });
            // Show selected
            document.getElementById(`tab-${tab}`).classList.add('active');
            btn.classList.add('active');
            btn.classList.remove('text-gray-500', 'bg-gray-50');
        }

        async function loadComparisonData() {
            const sessionSelect = document.getElementById('comparison-session-select').value;
            const query = sessionSelect ? `?session_id=${sessionSelect}` : '';
            const bots = ['bot_1', 'bot_2', 'bot_3'];

            compTrajectoryData = {};
            let summaryByBot = {};

            // Fetch trajectory + summary for each bot
            for (const bot of bots) {
                try {
                    const [trajRes, sumRes] = await Promise.all([
                        fetch(`/api/lpde/bot/${bot}/trajectory${query}&limit=200`),
                        fetch(`/api/lpde/bot/${bot}/summary${query}`)
                    ]);
                    compTrajectoryData[bot] = (await trajRes.json()).points || [];
                    summaryByBot[bot] = await sumRes.json();
                } catch(e) {
                    compTrajectoryData[bot] = [];
                    summaryByBot[bot] = {};
                }
            }

            // Role badges
            const badgesContainer = document.getElementById('comparison-role-badges');
            const botColors = { bot_1: '#a855f7', bot_2: '#ec4899', bot_3: '#22c55e' };
            badgesContainer.innerHTML = bots.map(bot => {
                const roleLabel = summaryByBot[bot].role_label || 'swing_moderate';
                const roleInfo = getRoleInfo(roleLabel);
                const conviction = summaryByBot[bot].conviction;
                const flexibility = summaryByBot[bot].flexibility;
                const convStr = conviction !== null && conviction !== undefined ? conviction.toFixed(2) : '—';
                const flexStr = flexibility !== null && flexibility !== undefined ? flexibility.toFixed(2) : '—';
                return `
                    <div class="flex items-center gap-2 bg-white rounded-xl px-3 py-2 border shadow-sm">
                        <span class="w-3 h-3 rounded-full" style="background:${botColors[bot]}"></span>
                        <span class="font-bold text-xs">${bot.toUpperCase()}</span>
                        <span class="text-xs px-2 py-0.5 rounded border font-bold ${roleInfo.cssClass}">${roleInfo.emoji} ${roleInfo.label}</span>
                        <span class="text-[10px] text-gray-500">conv: ${convStr} / flex: ${flexStr}</span>
                    </div>
                `;
            }).join('');

            // Compute unified turn labels
            const allTurns = new Set();
            for (const bot of bots) {
                (compTrajectoryData[bot] || []).forEach(p => allTurns.add(p.turn_index));
            }
            allTurnIndices = Array.from(allTurns).sort((a,b)=>a-b);

            // Update slider
            const slider = document.getElementById('turn-slider');
            slider.min = 0;
            slider.max = Math.max(0, allTurnIndices.length - 1);
            slider.value = slider.max;
            onSliderChange(slider.value);

            // Render charts
            renderComparisonCharts(bots, botColors);
        }

        function getValAtTurn(botData, turnIndex, axis) {
            const pt = botData.find(p => p.turn_index === turnIndex);
            if (!pt) return null;
            if (axis === 'x') return pt.x;
            if (axis === 'y') return pt.y;
            if (axis === 'arousal') return pt.arousal;
            return null;
        }

        function renderComparisonCharts(bots, botColors) {
            const labels = allTurnIndices.map(t => `T${t}`);

            function buildDataset(bot, axis) {
                return {
                    label: bot,
                    data: allTurnIndices.map(t => getValAtTurn(compTrajectoryData[bot] || [], t, axis)),
                    borderColor: botColors[bot],
                    backgroundColor: botColors[bot] + '22',
                    fill: false, tension: 0.3, borderWidth: 2, pointRadius: 2,
                    spanGaps: true,
                };
            }

            const commonOpts = (yMin, yMax) => ({
                responsive: true,
                scales: { y: { min: yMin, max: yMax } },
                plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 10, font: { size: 10 } } } },
                animation: { duration: 0 }
            });

            // Stance Chart
            if (!compStanceChartInstance) {
                const ctx = document.getElementById('compStanceChart').getContext('2d');
                compStanceChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: { labels, datasets: bots.map(b => buildDataset(b, 'x')) },
                    options: commonOpts(-1, 1)
                });
            } else {
                compStanceChartInstance.data.labels = labels;
                compStanceChartInstance.data.datasets = bots.map(b => buildDataset(b, 'x'));
                compStanceChartInstance.update('none');
            }

            // Conviction Chart
            if (!compConvictionChartInstance) {
                const ctx = document.getElementById('compConvictionChart').getContext('2d');
                compConvictionChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: { labels, datasets: bots.map(b => buildDataset(b, 'y')) },
                    options: commonOpts(0, 1)
                });
            } else {
                compConvictionChartInstance.data.labels = labels;
                compConvictionChartInstance.data.datasets = bots.map(b => buildDataset(b, 'y'));
                compConvictionChartInstance.update('none');
            }

            // Arousal Chart
            if (!compArousalChartInstance) {
                const ctx = document.getElementById('compArousalChart').getContext('2d');
                compArousalChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: { labels, datasets: bots.map(b => buildDataset(b, 'arousal')) },
                    options: commonOpts(-1, 1)
                });
            } else {
                compArousalChartInstance.data.labels = labels;
                compArousalChartInstance.data.datasets = bots.map(b => buildDataset(b, 'arousal'));
                compArousalChartInstance.update('none');
            }
        }

        function onSliderChange(sliderIdx) {
            const turnIndex = allTurnIndices[parseInt(sliderIdx)];
            const label = document.getElementById('slider-turn-label');
            label.textContent = turnIndex !== undefined ? `Turn: ${turnIndex}` : 'Turn: —';

            if (turnIndex === undefined) return;

            const bots = ['bot_1', 'bot_2', 'bot_3'];
            const botColors = { bot_1: '#a855f7', bot_2: '#ec4899', bot_3: '#22c55e' };
            const snapContainer = document.getElementById('slider-snapshot');

            snapContainer.innerHTML = bots.map(bot => {
                const pt = (compTrajectoryData[bot] || []).find(p => p.turn_index === turnIndex);
                const roleInfo = pt ? getRoleInfo(pt.role_label || 'swing_moderate') : getRoleInfo('swing_moderate');
                if (!pt) {
                    return `<div class="bg-gray-50 rounded-lg p-2 border text-center">
                        <div class="font-bold text-xs" style="color:${botColors[bot]}">${bot.toUpperCase()}</div>
                        <div class="text-[10px] text-gray-400 mt-1">No data</div>
                    </div>`;
                }
                return `<div class="bg-white rounded-lg p-2 border shadow-sm">
                    <div class="font-bold text-xs mb-1 flex items-center gap-1" style="color:${botColors[bot]}">
                        ${bot.toUpperCase()}
                        <span class="text-[9px] px-1 rounded border font-bold ${roleInfo.cssClass}">${roleInfo.emoji}</span>
                    </div>
                    <div class="text-[10px] text-gray-700 space-y-0.5">
                        <div>Stance: <b>${pt.x.toFixed(3)}</b></div>
                        <div>Conv: <b>${pt.y.toFixed(3)}</b></div>
                        <div>Arousal: <b>${pt.arousal.toFixed(3)}</b></div>
                    </div>
                </div>`;
            }).join('');
        }

        // --- Initialization and Global Polling ---
        fetchSystemStatus();
        fetchBotStates();
        fetchPostList();

        setInterval(fetchSystemStatus, 1500);
        setInterval(fetchBotStates, 2000);
        setInterval(fetchPostList, 5000);
        setInterval(fetchPostDetail, 2000);

        // Resume fast polling if tab becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && inspectorOpenBot && inspectorAutoRefresh) {
                forceFetchInspectorData();
            }
        });