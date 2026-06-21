let currentPostId = null;
        let knownCommentIds = new Set();
        let systemStatusMap = {};
        let currentBoardName = 'programming';
        let currentBoardDesc = '컴퓨터 프로그래밍과 소스코드에 대한 이야기를 나누는 공간입니다.';
        let activeParentCommentId = null;
        
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
        let lastPostData = null; // 현재 보고 있는 게시글 데이터 (복사/저장용)

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
            toast.className = 'fixed top-4 right-4 bg-red-100 text-red-800 border-l-4 border-red-600 px-4 py-3 rounded shadow-md z-[100] flex items-center justify-between min-w-[300px]';
            toast.innerHTML = `
                <div>
                    <div class="font-bold text-sm">⚠️ 시스템 오류 감지</div>
                    <div class="text-xs mt-1 opacity-90 break-words max-w-[250px]">${msg}</div>
                </div>
                <button onclick="this.parentElement.remove(); currentErrorToast=null;" class="ml-4 text-red-600 hover:text-red-800 focus:outline-none">
                    ✖
                </button>
            `;
            document.body.appendChild(toast);
        }

        let setupModalOpen = false;
        let setupPolling = null;

        // 경찰 오버레이 관련 상태
        let dismissedPoliceSessions = new Set(); // 이미 닫은 세션 ID 목록
        let policeWarningVisible = false;        // 현재 화면에 표시 중인지 여부
        let currentSessionId = null;             // 현재 폴링 중인 세션 ID

        // --- Fetch System Status ---
        async function fetchSystemStatus() {
            try {
                const res = await fetch('/api/system/status');
                systemStatusMap = await res.json();
                
                let godRunning = systemStatusMap.containers && systemStatusMap.containers["ameva-llm-god"] === "RUNNING";
                let mainRunning = systemStatusMap.containers && systemStatusMap.containers["ameva-llm-main"] === "RUNNING";
                
                let globalState = systemStatusMap["state"] || "UNKNOWN";
                let lastError = systemStatusMap["last_error"];
                
                // Update system activity text in real-time
                let activityText = document.getElementById('system-activity-text');
                if (activityText && systemStatusMap.current_activity) {
                    activityText.textContent = systemStatusMap.current_activity;
                }
                
                let globalBadge = document.getElementById('global-state-badge');
                if(globalBadge) {
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
                }
                
                let godDot = document.getElementById('god-status-dot');
                if (godDot) godDot.className = "inline-block w-3 h-3 rounded-full mr-1.5 transition-colors duration-500 " + (godRunning ? "bg-green-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]" : "bg-red-500");
                let mainDot = document.getElementById('main-status-dot');
                if (mainDot) mainDot.className = "inline-block w-3 h-3 rounded-full mr-1.5 transition-colors duration-500 " + (mainRunning ? "bg-green-500 animate-pulse shadow-[0_0_8px_rgba(34,197,94,0.8)]" : "bg-red-500");
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
                if (badge) {
                    if (data.session_status === 'ACTIVE') {
                        badge.className = "text-xs px-2 py-1 rounded-full font-bold bg-green-200 text-green-800";
                        badge.innerText = "ACTIVE";
                        hidePoliceWarning();
                        hideClosedBanner();
                    } else if (data.session_status === 'CLOSED_BY_POLICE') {
                        badge.className = "text-xs px-2 py-1 rounded-full font-bold bg-red-600 text-white animate-pulse";
                        badge.innerText = "POLICE DISPATCHED";
                        // 현재 세션 ID 추적
                        const sid = data.session_id || '__police__';
                        currentSessionId = sid;
                        // 이미 닫은 세션이면 다시 안 또 담
                        if (!dismissedPoliceSessions.has(sid) && !policeWarningVisible) {
                            showPoliceWarning(sid);
                        }
                        showClosedBanner();
                    } else {
                        badge.className = "text-xs px-2 py-1 rounded-full font-bold bg-gray-200 text-gray-600";
                        badge.innerText = data.session_status || "UNKNOWN";
                        hidePoliceWarning();
                        hideClosedBanner();
                    }
                }

                const container = document.getElementById('bot-states-container');
                if (container) {
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
                            let isRunning = systemStatusMap.containers && systemStatusMap.containers[botDockerName] === "RUNNING";
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
                }
            } catch (err) {
                console.error("Bot state fetch error:", err);
            }
        }

        // --- Modal & Setup Logic ---
        let setupModeListenersBound = false;
        function updateSetupFormLayout() {
            const modeInput = document.querySelector('input[name="inference_mode"]:checked');
            const mode = modeInput ? modeInput.value : 'local_single_model';
            const pathContainer = document.getElementById('llama-path-container');
            const otherModelsContainer = document.getElementById('setup-other-models-container');
            
            if (mode === 'local_native') {
                if (pathContainer) pathContainer.classList.remove('hidden');
                if (otherModelsContainer) otherModelsContainer.classList.add('hidden');
            } else if (mode === 'local_single_model') {
                if (pathContainer) pathContainer.classList.add('hidden');
                if (otherModelsContainer) otherModelsContainer.classList.add('hidden');
            } else if (mode === 'parallel') {
                if (pathContainer) pathContainer.classList.add('hidden');
                if (otherModelsContainer) otherModelsContainer.classList.remove('hidden');
            }
        }

        async function openSetupModal() {
            if (setupModalOpen) return;
            setupModalOpen = true;
            
            const modal = document.getElementById('setup-modal');
            modal.classList.remove('hidden');
            
            updateSetupFormLayout();
            
            if (!setupModeListenersBound) {
                document.querySelectorAll('input[name="inference_mode"]').forEach(radio => {
                    radio.addEventListener('change', updateSetupFormLayout);
                });
                setupModeListenersBound = true;
            }
            
            try {
                const res = await fetch('/api/system/setup-info');
                const data = await res.json();
                
                // Hardware Status
                const hwStatus = document.getElementById('setup-hw-status');
                const hwDesc = document.getElementById('setup-hw-desc');
                const radioGpu = document.getElementById('radio-gpu');
                const labelGpu = document.getElementById('label-gpu');
                const gpuDesc = document.getElementById('gpu-desc');
                
                hwStatus.textContent = data.hardware.details;
                if (data.hardware.gpu_found) {
                    hwStatus.className = "px-4 py-2 rounded-xl font-bold bg-green-100 text-green-700 border border-green-200";
                    hwDesc.textContent = "NVIDIA GPU 가속 사용 가능";
                    radioGpu.disabled = false;
                    labelGpu.classList.remove('opacity-50');
                    labelGpu.title = "";
                    radioGpu.checked = true;
                    
                    if (data.hardware.recommended_gpu_backend === "vulkan") {
                        gpuDesc.textContent = "GTX 계열 감지 (Vulkan 자동 활성화)";
                    } else {
                        gpuDesc.textContent = "RTX 계열 감지 (CUDA 자동 활성화)";
                    }
                } else {
                    hwStatus.className = "px-4 py-2 rounded-xl font-bold bg-gray-100 text-gray-700 border border-gray-200";
                    hwDesc.textContent = "GPU가 감지되지 않았습니다. 기본 CPU 모드로 구동됩니다.";
                    radioGpu.disabled = true;
                    labelGpu.classList.add('opacity-50');
                    labelGpu.title = "NVIDIA GPU가 필요합니다.";
                    document.getElementById('radio-cpu').checked = true;
                    gpuDesc.textContent = "사용 불가능 (GPU 미감지)";
                }
                
                // Populate Selects
                const selects = ["main", "god", "bot1", "bot2", "bot3"].map(id => document.getElementById('setup-model-' + id));
                selects.forEach(sel => {
                    if (sel) {
                        sel.innerHTML = "";
                        data.models.forEach(m => {
                            const opt = document.createElement('option');
                            opt.value = m;
                            opt.textContent = m;
                            sel.appendChild(opt);
                        });
                    }
                });
                
            } catch (e) {
                console.error("Failed to load setup info:", e);
                document.getElementById('setup-hw-status').textContent = "오류 발생";
                document.getElementById('setup-hw-desc').textContent = "서버와 통신할 수 없습니다.";
            }
        }

        function closeSetupModal() {
            document.getElementById('setup-modal').classList.add('hidden');
            setupModalOpen = false;
        }

        async function startSetupSequence() {
            const btn = document.getElementById('btn-start-simulation');
            btn.disabled = true;
            btn.innerHTML = `<svg class="animate-spin w-5 h-5 mr-2 text-white" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg> 준비 중...`;
            
            document.getElementById('setup-progress-container').classList.remove('hidden');
            
            const payload = {
                inference_mode: document.querySelector('input[name="inference_mode"]:checked').value,
                hardware_mode: document.querySelector('input[name="hardware_mode"]:checked').value,
                model_main: document.getElementById('setup-model-main').value,
                model_god: document.getElementById('setup-model-god') ? document.getElementById('setup-model-god').value : "",
                model_bot1: document.getElementById('setup-model-bot1') ? document.getElementById('setup-model-bot1').value : "",
                model_bot2: document.getElementById('setup-model-bot2') ? document.getElementById('setup-model-bot2').value : "",
                model_bot3: document.getElementById('setup-model-bot3') ? document.getElementById('setup-model-bot3').value : "",
                llama_server_path: "자동 (내장 서버)"
            };
            
            try {
                await fetch('/api/control/setup_and_start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                
                setupPolling = setInterval(pollSetupProgress, 500);
            } catch (e) {
                console.error("Setup sequence failed:", e);
                btn.disabled = false;
                btn.textContent = "재시도";
            }
        }

        async function pollSetupProgress() {
            try {
                const res = await fetch('/api/system/startup-progress');
                const data = await res.json();
                
                const pct = data.total > 0 ? Math.floor((data.completed / data.total) * 100) : 0;
                
                document.getElementById('setup-progress-bar').style.width = pct + "%";
                document.getElementById('setup-progress-text').textContent = `[${data.completed}/${data.total}] ${pct}%`;
                const currentTaskEl = document.getElementById('setup-current-task');
                if (currentTaskEl) currentTaskEl.textContent = data.current_task;
                
                if (!data.is_running && data.completed > 0 && data.total > 0 && data.completed === data.total) {
                    clearInterval(setupPolling);
                    setTimeout(() => {
                        document.getElementById('setup-modal').classList.add('hidden');
                        setupModalOpen = false;
                        document.getElementById('btn-start-simulation').disabled = false;
                        document.getElementById('btn-start-simulation').innerHTML = '시뮬레이션 시작';
                        document.getElementById('setup-progress-container').classList.add('hidden');
                        fetchPostList(); // Refresh board (renamed from fetchPosts)
                    }, 1500);
                }
            } catch (e) {
                console.error("Progress polling failed:", e);
            }
        }
        
        async function requestNewSession() {
            if (!confirm("현재 세션을 초기화하고 새로운 시뮬레이션 환경을 설정하시겠습니까?")) return;
            
            try {
                await fetch('/api/control/stop', { method: 'POST' });
                alert("현재 세션 중지 신호를 보냈습니다. 서버가 IDLE 상태로 전환되면 새로고침해주세요.");
                setTimeout(() => location.reload(), 2000);
            } catch (e) {
                console.error(e);
            }
        }

        // --- Fetch Boards List (DC Inside style) ---
        async function fetchBoardsList() {
            try {
                const res = await fetch('/api/boards');
                const boards = await res.json();
                
                const majorContainer = document.getElementById('major-boards-container');
                const minorContainer = document.getElementById('minor-boards-container');
                
                majorContainer.innerHTML = '';
                minorContainer.innerHTML = '';
                
                boards.forEach(b => {
                    const isActive = b.name === currentBoardName;
                    const btnClass = isActive 
                        ? 'bg-indigo-600 text-white shadow-md font-bold' 
                        : 'bg-white bg-opacity-40 text-gray-700 hover:bg-indigo-50 hover:text-indigo-600';
                    
                    const buttonHtml = `
                        <button onclick="selectBoard('${b.name}', '${b.description.replace(/'/g, "\\'")}')" 
                                class="w-full text-left px-3 py-1.5 rounded-lg text-xs transition-all border border-transparent truncate block ${btnClass}">
                            # ${b.name}
                        </button>
                    `;
                    
                    if (b.board_type === 'MAJOR') {
                        majorContainer.innerHTML += buttonHtml;
                    } else {
                        minorContainer.innerHTML += buttonHtml;
                    }
                });
            } catch (err) {
                console.error("Boards fetch error:", err);
            }
        }

        window.selectBoard = function(name, desc) {
            currentBoardName = name;
            currentBoardDesc = desc;
            currentPostId = null;
            knownCommentIds.clear();
            document.getElementById('comments-container').innerHTML = '';
            document.getElementById('current-post-id').innerText = 'POST LOADING...';
            document.getElementById('current-post-title').innerText = '게시글을 선택해 주세요';
            document.getElementById('current-post-content').innerText = '';
            
            fetchBoardsList();
            fetchPostList();
        };

        // --- Fetch Post List ---
        async function fetchPostList() {
            try {
                // Update board header details
                const titleEl = document.getElementById('selected-board-title');
                if (titleEl) titleEl.innerText = currentBoardName.toUpperCase() + ' 갤러리';
                const descEl = document.getElementById('selected-board-desc');
                if (descEl) descEl.innerText = currentBoardDesc;

                const res = await fetch(`/api/boards/${currentBoardName}/posts`);
                const posts = await res.json();
                
                const container = document.getElementById('post-list-container');
                container.innerHTML = '';
                
                if (posts.length === 0 || posts.error) {
                    container.innerHTML = '<div class="text-sm text-gray-400 italic text-center py-4">게시글이 없습니다.</div>';
                    return;
                }

                if (!currentPostId) {
                    selectPost(posts[0].id);
                }

                posts.forEach(p => {
                    const isActive = p.id === currentPostId;
                    const btnClass = isActive 
                        ? 'bg-indigo-500 text-white shadow-md font-bold' 
                        : 'bg-white bg-opacity-50 text-gray-700 hover:bg-indigo-100 transition-colors';
                    
                    container.innerHTML += `
                        <button onclick="selectPost(${p.id})" class="w-full text-left p-3 rounded-xl border border-white border-opacity-40 ${btnClass}">
                            <div class="text-[10px] font-mono opacity-70">No. ${p.board_seq_id} (Global #${p.id})</div>
                            <div class="font-bold truncate text-sm mt-0.5">${p.title}</div>
                        </button>
                    `;
                });
            } catch (err) {
                console.error("Post list fetch error:", err);
            }
        }

        window.selectPost = function(id) {
            if (currentPostId !== id) {
                currentPostId = id;
                knownCommentIds.clear();
                document.getElementById('comments-container').innerHTML = '';
                fetchPostDetail();
                fetchPostList();
            }
        };

        // --- New Post Actions ---
        window.openNewPostModal = function() {
            document.getElementById('new-post-title-input').value = '';
            document.getElementById('new-post-content-input').value = '';
            document.getElementById('new-post-modal').classList.remove('hidden');
        };

        window.closeNewPostModal = function() {
            document.getElementById('new-post-modal').classList.add('hidden');
        };

        window.submitNewPost = async function() {
            const title = document.getElementById('new-post-title-input').value.trim();
            const content = document.getElementById('new-post-content-input').value.trim();
            if (!title || !content) {
                alert("제목과 내용을 입력해 주세요.");
                return;
            }
            try {
                const res = await fetch(`/api/boards/${currentBoardName}/posts`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, content })
                });
                const data = await res.json();
                if (data.success) {
                    closeNewPostModal();
                    currentPostId = data.id;
                    knownCommentIds.clear();
                    document.getElementById('comments-container').innerHTML = '';
                    fetchPostList();
                    fetchPostDetail();
                } else {
                    alert("게시글 생성에 실패했습니다: " + data.error);
                }
            } catch (err) {
                console.error("New post submit error:", err);
            }
        };

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

                document.getElementById('current-post-id').innerText = `POST #${data.board_seq_id} (Global #${data.id})`;
                document.getElementById('current-post-title').innerText = data.title;
                document.getElementById('current-post-content').innerText = data.content;
                document.getElementById('current-post-date').innerText = data.created_at;
                lastPostData = data;

                if (data.session_status === 'CLOSED_BY_POLICE') {
                    showClosedBanner();
                } else {
                    hideClosedBanner();
                }

                const container = document.getElementById('comments-container');
                let newCommentAdded = false;
                
                // Construct comment tree
                const commentMap = {};
                const rootComments = [];
                
                data.comments.forEach(c => {
                    commentMap[c.id] = { ...c, replies: [] };
                    const isNew = !knownCommentIds.has(c.id);
                    if (isNew) {
                        knownCommentIds.add(c.id);
                        newCommentAdded = true;
                    }
                });
                
                data.comments.forEach(c => {
                    const mapped = commentMap[c.id];
                    if (c.parent_id && commentMap[c.parent_id]) {
                        commentMap[c.parent_id].replies.push(mapped);
                    } else {
                        rootComments.push(mapped);
                    }
                });

                function renderCommentNode(c, depth = 0) {
                    const avatarColor = getAvatarColor(c.bot_name);
                    const mentionHtml = c.mentioned_bot ? `<span class="text-[10px] font-bold text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded ml-1">@${c.mentioned_bot}</span>` : '';
                    let contentHtml = c.content.replace(/@(bot_\d+|police)/g, '<span class="text-indigo-600 font-bold">@$1</span>');
                    
                    const indentStyle = depth > 0 ? `margin-left: ${Math.min(depth * 20, 100)}px; border-left: 2px solid #e2e8f0; padding-left: 12px;` : '';
                    
                    let replyBtn = `<button onclick="openReplyForm(${c.id}, '${c.bot_name}')" class="text-[10px] text-indigo-500 hover:text-indigo-700 font-bold ml-3">답글</button>`;
                    
                    let html = `
                        <div class="bg-white bg-opacity-70 rounded-2xl p-4 shadow-sm border border-white flex gap-3" style="${indentStyle}">
                            <div class="flex-shrink-0">
                                <div class="w-8 h-8 rounded-full flex items-center justify-center font-bold text-white shadow-inner ${avatarColor} text-[10px]">
                                    ${c.bot_name.substring(0,3).toUpperCase()}
                                </div>
                            </div>
                            <div class="flex-1 min-w-0">
                                <div class="flex items-center justify-between mb-1">
                                    <div class="truncate text-xs">
                                        <span class="font-bold text-gray-900">${c.bot_name}</span>
                                        <span class="text-[10px] text-gray-400 ml-1">#${c.id}</span>
                                        ${mentionHtml}
                                    </div>
                                    <div class="flex items-center gap-1">
                                        <span class="text-[10px] text-gray-400">${c.created_at}</span>
                                        ${replyBtn}
                                    </div>
                                </div>
                                <p class="text-gray-800 text-xs leading-relaxed whitespace-pre-wrap">${contentHtml}</p>
                                <div id="reply-form-container-${c.id}" class="mt-2 hidden"></div>
                            </div>
                        </div>
                    `;
                    
                    if (c.replies && c.replies.length > 0) {
                        c.replies.forEach(reply => {
                            html += renderCommentNode(reply, depth + 1);
                        });
                    }
                    return html;
                }

                let htmlBuffer = '';
                rootComments.forEach(c => {
                    htmlBuffer += renderCommentNode(c, 0);
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

        window.openReplyForm = function(parentId, author) {
            const container = document.getElementById(`reply-form-container-${parentId}`);
            if (!container) return;
            
            // Toggle open/close
            if (!container.classList.contains('hidden')) {
                container.classList.add('hidden');
                container.innerHTML = '';
                return;
            }
            
            // Close other open reply forms
            const allForms = document.querySelectorAll('[id^="reply-form-container-"]');
            allForms.forEach(form => {
                form.classList.add('hidden');
                form.innerHTML = '';
            });

            container.innerHTML = `
                <div class="flex gap-2 mt-2">
                    <input type="text" id="reply-input-${parentId}" class="flex-grow border-gray-300 rounded-lg py-1 px-3 text-xs border" placeholder="@${author} 답글 쓰기...">
                    <button onclick="submitReplyComment(${parentId}, '${author}')" class="bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-3 py-1 rounded-lg text-xs transition-all">등록</button>
                    <button onclick="closeReplyForm(${parentId})" class="bg-gray-200 hover:bg-gray-300 text-gray-700 font-bold px-3 py-1 rounded-lg text-xs transition-all">취소</button>
                </div>
            `;
            container.classList.remove('hidden');
            document.getElementById(`reply-input-${parentId}`).focus();
        };

        window.closeReplyForm = function(parentId) {
            const container = document.getElementById(`reply-form-container-${parentId}`);
            if (container) {
                container.classList.add('hidden');
                container.innerHTML = '';
            }
        };

        window.submitReplyComment = async function(parentId, author) {
            const input = document.getElementById(`reply-input-${parentId}`);
            if (!input) return;
            const text = input.value.trim();
            if (!text) {
                alert("답글 내용을 입력해 주세요.");
                return;
            }
            
            try {
                const res = await fetch(`/api/posts/${currentPostId}/comments`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        parent_id: parentId,
                        bot_name: 'USER',
                        content: `@${author} ` + text,
                        mentioned_bot: author
                    })
                });
                const data = await res.json();
                if (data.success) {
                    closeReplyForm(parentId);
                    fetchPostDetail();
                } else {
                    alert("답글 등록에 실패했습니다.");
                }
            } catch (err) {
                console.error("Reply submit error:", err);
            }
        };

        window.submitUserComment = async function() {
            const input = document.getElementById('user-comment-input');
            const text = input.value.trim();
            if (!text) return;
            
            let mentioned_bot = null;
            const mentionMatch = text.match(/@(bot_\d+|police)/);
            if (mentionMatch) {
                mentioned_bot = mentionMatch[1];
            }

            try {
                const res = await fetch(`/api/posts/${currentPostId}/comments`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bot_name: 'USER',
                        content: text,
                        mentioned_bot: mentioned_bot
                    })
                });
                const data = await res.json();
                if (data.success) {
                    input.value = '';
                    fetchPostDetail();
                } else {
                    alert("댓글 등록에 실패했습니다.");
                }
            } catch (err) {
                console.error("Comment submit error:", err);
            }
        };

        async function fetchActiveNodes() {
            try {
                const res = await fetch('/api/nodes/active');
                const data = await res.json();
                const countBadge = document.getElementById('active-users-count');
                if (countBadge) {
                    countBadge.innerText = `접속자: ${data.active_count}명`;
                }
            } catch (err) {
                console.error("Active nodes count fetch error:", err);
            }
        }

        function showPoliceWarning(sessionId) {
            policeWarningVisible = true;
            const el = document.getElementById('police-warning');
            el.classList.remove('hidden');
            setTimeout(() => {
                el.classList.remove('opacity-0');
                el.classList.add('opacity-100');
            }, 50);
        }

        function dismissPoliceWarning() {
            // 현재 세션을 기억해 다시는 표시하지 않음
            if (currentSessionId) {
                dismissedPoliceSessions.add(currentSessionId);
            }
            hidePoliceWarning();
        }

        function hidePoliceWarning() {
            policeWarningVisible = false;
            const el = document.getElementById('police-warning');
            el.classList.remove('opacity-100');
            el.classList.add('opacity-0');
            setTimeout(() => {
                el.classList.add('hidden');
            }, 500);
        }

        function showClosedBanner() {
            const el = document.getElementById('closed-session-banner');
            if (el) el.classList.remove('hidden');
        }

        function hideClosedBanner() {
            const el = document.getElementById('closed-session-banner');
            if (el) el.classList.add('hidden');
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
            // 탭 패널이 display:none 에서 표시되면 Chart.js가 크기를 0으로 계산하므로 resize 필요
            requestAnimationFrame(() => {
                if (compStanceChartInstance) compStanceChartInstance.resize();
                if (compConvictionChartInstance) compConvictionChartInstance.resize();
                if (compArousalChartInstance) compArousalChartInstance.resize();
            });
        }

        // 게시글 전체 내용을 텍스트로 복사
        function copyPost() {
            if (!lastPostData) { alert('불러온 게시글이 없습니다.'); return; }
            const d = lastPostData;
            let txt = `[POST #${d.id}] ${d.title}\n${d.created_at}\n\n${d.content}\n\n${'='.repeat(50)}\n댓글 (${d.comments.length}개)\n${'='.repeat(50)}\n`;
            d.comments.forEach((c, i) => {
                txt += `\n[${i+1}] ${c.bot_name}${c.mentioned_bot ? ' → @'+c.mentioned_bot : ''} (${c.created_at})\n${c.content}\n`;
            });
            navigator.clipboard.writeText(txt).then(() => {
                showCopyToast('클립보드에 복사되었습니다!');
            }).catch(() => alert('복사에 실패했습니다.'));
        }

        // 게시글 전체 내용을 PDF로 저장
        function savePdf() {
            if (!lastPostData) { alert('불러온 게시글이 없습니다.'); return; }
            const d = lastPostData;

            // 임시 프린트 전용 div 생성
            const printDiv = document.createElement('div');
            printDiv.style.cssText = 'font-family:sans-serif;padding:32px;max-width:800px;margin:0 auto;color:#111;';

            let html = `<h1 style="font-size:22px;font-weight:bold;margin-bottom:4px;">${escapeHtml(d.title)}</h1>`;
            html += `<div style="color:#888;font-size:12px;margin-bottom:4px;">POST #${d.id} &nbsp;·&nbsp; ${d.created_at}</div>`;
            html += `<hr style="margin:12px 0;"/>`;
            html += `<p style="font-size:14px;line-height:1.7;white-space:pre-wrap;">${escapeHtml(d.content)}</p>`;
            html += `<hr style="margin:20px 0;"/>`;
            html += `<h2 style="font-size:16px;font-weight:bold;margin-bottom:12px;">댓글 ${d.comments.length}개</h2>`;

            const botColors = { bot_1: '#9333ea', bot_2: '#ec4899', bot_3: '#22c55e', police: '#2563eb' };
            d.comments.forEach((c, i) => {
                const col = botColors[c.bot_name] || '#4f46e5';
                html += `<div style="border-left:4px solid ${col};padding:8px 12px;margin-bottom:10px;background:#fafafa;border-radius:4px;">`;
                html += `<div style="font-size:12px;font-weight:bold;color:${col};">${escapeHtml(c.bot_name)}`;
                if (c.mentioned_bot) html += ` <span style="color:#6366f1;">→ @${escapeHtml(c.mentioned_bot)}</span>`;
                html += ` &nbsp;<span style="color:#aaa;font-weight:normal;">${c.created_at}</span></div>`;
                html += `<div style="font-size:13px;margin-top:4px;white-space:pre-wrap;">${escapeHtml(c.content)}</div>`;
                html += `</div>`;
            });

            printDiv.innerHTML = html;

            // window.print()용 숨김 iframe 트릭
            const iframe = document.createElement('iframe');
            iframe.style.cssText = 'position:fixed;right:-9999px;top:-9999px;width:900px;height:1200px;border:none;';
            document.body.appendChild(iframe);
            iframe.contentDocument.open();
            iframe.contentDocument.write(`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>AMEVA Post #${d.id}</title><style>body{font-family:sans-serif;margin:0;padding:0;}@media print{@page{margin:20mm;}}</style></head><body>${printDiv.outerHTML}</body></html>`);
            iframe.contentDocument.close();
            setTimeout(() => {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
                setTimeout(() => document.body.removeChild(iframe), 2000);
            }, 400);
        }

        function escapeHtml(s) {
            if (typeof s !== 'string') return '';
            return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        }

        function showCopyToast(msg) {
            const t = document.createElement('div');
            t.className = 'fixed bottom-6 right-6 bg-indigo-700 text-white px-5 py-3 rounded-xl shadow-lg text-sm font-bold z-[200] transition-all';
            t.textContent = msg;
            document.body.appendChild(t);
            setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 400); }, 2000);
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
                maintainAspectRatio: false,
                scales: { y: { min: yMin, max: yMax } },
                plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 10, font: { size: 10 } } } },
                animation: { duration: 0 }
            });

            // 차트가 hidden 탭에 있으면 canvas 크기가 0이 돼서 오류가 남
            // 해결: 기존 인스턴스 파괴 후 재생성, 탭 전환 시 resize() 호출
            if (compStanceChartInstance) { compStanceChartInstance.destroy(); compStanceChartInstance = null; }
            if (compConvictionChartInstance) { compConvictionChartInstance.destroy(); compConvictionChartInstance = null; }
            if (compArousalChartInstance) { compArousalChartInstance.destroy(); compArousalChartInstance = null; }

            // 모든 탭 패널을 잠깐 visible로 만들고 차트 생성 후 원래대로 복원
            const stancePanel = document.getElementById('tab-stance');
            const convPanel = document.getElementById('tab-conviction');
            const arousalPanel = document.getElementById('tab-arousal');
            const panels = [stancePanel, convPanel, arousalPanel];

            // 잠깐 모두 표시 (차트 초기화에 canvas 크기가 필요)
            panels.forEach(p => { p.style.display = 'block'; p.style.visibility = 'hidden'; });

            requestAnimationFrame(() => {
                const stanceCtx = document.getElementById('compStanceChart').getContext('2d');
                compStanceChartInstance = new Chart(stanceCtx, {
                    type: 'line',
                    data: { labels, datasets: bots.map(b => buildDataset(b, 'x')) },
                    options: commonOpts(-1, 1)
                });

                const convCtx = document.getElementById('compConvictionChart').getContext('2d');
                compConvictionChartInstance = new Chart(convCtx, {
                    type: 'line',
                    data: { labels, datasets: bots.map(b => buildDataset(b, 'y')) },
                    options: commonOpts(0, 1)
                });

                const arousalCtx = document.getElementById('compArousalChart').getContext('2d');
                compArousalChartInstance = new Chart(arousalCtx, {
                    type: 'line',
                    data: { labels, datasets: bots.map(b => buildDataset(b, 'arousal')) },
                    options: commonOpts(-1, 1)
                });

                // 원래 CSS로 복원 (active 클래스를 따름)
                panels.forEach(p => { p.style.display = ''; p.style.visibility = ''; });

                // 현재 visible 탭 차트 강제 리사이즈
                requestAnimationFrame(() => {
                    if (compStanceChartInstance) compStanceChartInstance.resize();
                    if (compConvictionChartInstance) compConvictionChartInstance.resize();
                    if (compArousalChartInstance) compArousalChartInstance.resize();
                });
            });
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
        fetchBoardsList();
        fetchPostList();
        fetchActiveNodes();

        setInterval(fetchSystemStatus, 1000);
        setInterval(fetchBotStates, 1500);
        setInterval(fetchPostList, 3000);
        setInterval(fetchPostDetail, 1000);
        setInterval(fetchActiveNodes, 5000);

        document.addEventListener('DOMContentLoaded', () => {
            initApp();
        });

        window.browseLlamaPath = async function() {
            try {
                const res = await fetch('/api/system/browse-file');
                const data = await res.json();
                if (data.path) {
                    document.getElementById('setup-llama-path').value = data.path;
                } else if (data.error) {
                    console.error("Browse error:", data.error);
                }
            } catch (e) {
                console.error("Failed to browse path:", e);
            }
        };

        // Resume fast polling if tab becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && inspectorOpenBot && inspectorAutoRefresh) {
                forceFetchInspectorData();
            }
        });