/**
 * 7L 核心監控台客戶端互動邏輯 (Pure Black Frosted Glass Edition)
 * 高性能版：
 * 1. 智慧髒檢查 (Dirty Checking) 杜絕無謂 DOM 重排與掉幀，鎖定 60+ FPS
 * 2. 視覺圖片非同步預載入，避免主線程卡死或閃爍
 * 3. 避免過度頻繁計時器，釋放 CPU/GPU 資源
 * 4. 單一 WebSocket 通道渲染，徹底杜絕連發兩次
 */

// 輕量高效率 DOM 賦值 Helper (僅在值改變時觸發瀏覽器重繪)
function safeSetText(el, text) {
  if (el && el.textContent !== text) {
    el.textContent = text;
  }
}

function safeSetWidth(el, widthVal) {
  if (!el) return;
  if (el.style.width === widthVal) return;
  // 若為百分比數值，過濾小於 0.5% 的無感抖動，避免觸發多餘 Layout 重排
  if (typeof widthVal === 'string' && widthVal.endsWith('%') && typeof el.style.width === 'string' && el.style.width.endsWith('%')) {
    const cur = parseFloat(el.style.width);
    const target = parseFloat(widthVal);
    if (!isNaN(cur) && !isNaN(target) && Math.abs(cur - target) < 0.5 && target !== 0 && target !== 100) {
      return;
    }
  }
  el.style.width = widthVal;
}

function safeSetClass(el, className) {
  if (el && el.className !== className) {
    el.className = className;
  }
}

class SevenLMonitorApp {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.lastVisionTimestamp = Date.now() / 1000;
    this.isMicEnabled = true;
    this.isSleeping = false;
    this.silenceTicks = 0;
    this.uptimeTicks = 0;
    this.loadedMemoryIds = new Set();
    this.isSending = false;
    this.lastRenderedVisionTime = 0;
    this.isImgLoading = false;
    this.activeExpression = null;

    // 提示詞庫資料暫存
    this.cloudKnowledge = null;
    this.bannedPhrases = [];
    this.memesList = [];
    this.fewShotExamples = [];
    this.toastTimer = null;

    // 🛠️ 工具調用中樞資料暫存
    this.toolsCatalog = [];
    this.selectedTool = null;
    this.toolHistory = [];
    this.toolsCategory = 'all';
    this.toolCallerFilter = 'all';
    this.toolSearchQuery = '';

    // 🧠 記憶管理中樞資料暫存
    this.memoryItems = [];
    this.memoryFilterRole = 'all';
    this.memorySearchKeyword = '';
    this.editingMemoryIndex = -1;

    // 🎛️ 系統開關資料暫存
    this.switchesList = [];

    // 📭 TikTok 直播留言未讀追蹤：儲存所有未讀的 tiktok bubble DOM 元素
    this._pendingTiktokBubbles = [];

    this.initElements();
    this.bindEvents();
    this.startTimers();
    this.connectWebSocket();
    this.loadMemoryHistory();
    this.triggerVisionImageReload(true);
    this.loadPrompts();
    this.loadTools();
    this.loadToolHistory();
    this.loadMemoryManagerList();
    this.loadSwitches();
  }

  initElements() {
    // 頂部導覽
    this.menuTabs = document.querySelectorAll('.menu-tab');
    this.tabPanes = document.querySelectorAll('.tab-pane');
    this.topDot = document.getElementById('topDot');
    this.topStatusText = document.getElementById('topStatusText');
    this.clockText = document.getElementById('clockText');
    this.topModelBadge = document.getElementById('topModelBadge');

    // 🎛️ 系統開關 DOM
    this.switchesGrid = document.getElementById('switchesGrid');
    this.switchesActiveCount = document.getElementById('switchesActiveCount');
    this.btnRefreshSwitches = document.getElementById('btnRefreshSwitches');

    // 🧠 左側即時心流分頁 (Mind Stream Panel & Resizer)
    this.chatMindSplit = document.getElementById('chatMindSplit');
    this.mindStreamPanel = document.getElementById('mindStreamPanel');
    this.mindStreamScroll = document.getElementById('mindStreamScroll');
    this.mindCountBadge = document.getElementById('mindCountBadge');
    this.mindLatestText = document.getElementById('mindLatestText');
    this.mindSplitResizer = document.getElementById('mindSplitResizer');
    this.btnToggleMindDrawer = document.getElementById('btnToggleMindDrawer');
    this.mindTabArrow = document.getElementById('mindTabArrow');
    this.btnPinMindStream = document.getElementById('btnPinMindStream');
    this.btnClearMindStream = document.getElementById('btnClearMindStream');
    this.mindEmptyState = document.getElementById('mindEmptyState');
    this.isMindDrawerCollapsed = false;
    this.isMindPinAutoScroll = true;
    this.mindThoughts = [];
    this.isDraggingResizer = false;

    // ⚡ DeepSeek 沉浸式思考視窗 DOM 與打字機引擎
    this.deepseekThinkingBox = document.getElementById('deepseekThinkingBox');
    this.thinkingStatusLabel = document.getElementById('thinkingStatusLabel');
    this.thinkingTimerPill = document.getElementById('thinkingTimerPill');
    this.thinkingContentBody = document.getElementById('thinkingContentBody');
    this.thinkingStreamText = document.getElementById('thinkingStreamText');
    this.thinkingCursor = document.getElementById('thinkingCursor');
    this.mindHistoryStream = document.getElementById('mindHistoryStream');
    this.mindHistoryDivider = document.getElementById('mindHistoryDivider');
    this.currentThinkingStartTime = null;
    this.thinkingTimerInterval = null;
    this.typewriterQueue = [];
    this.isTypewriting = false;
    this.isStreamingThought = false;

    // 對話串流區
    this.chatStream = document.getElementById('chatStream');
    this.actionChips = document.querySelectorAll('.action-chip');
    this.chatForm = document.getElementById('chatForm');
    this.chatInputField = document.getElementById('chatInputField');
    this.btnSend = document.getElementById('btnSend');

    // 🎙️ 語音生成即時進度 HUD
    this.ttsProgressHud = document.getElementById('ttsProgressHud');
    this.ttsHudIcon = document.getElementById('ttsHudIcon');
    this.ttsHudTitle = document.getElementById('ttsHudTitle');
    this.ttsHudStage = document.getElementById('ttsHudStage');
    this.ttsHudPct = document.getElementById('ttsHudPct');
    this.ttsHudBarFill = document.getElementById('ttsHudBarFill');
    this.ttsHudDetail = document.getElementById('ttsHudDetail');
    this.ttsHideTimer = null;

    // 🔄 RVC 音色轉換即時進度 HUD（下）
    this.rvcProgressHud = document.getElementById('rvcProgressHud');
    this.rvcHudIcon = document.getElementById('rvcHudIcon');
    this.rvcHudTitle = document.getElementById('rvcHudTitle');
    this.rvcHudStage = document.getElementById('rvcHudStage');
    this.rvcHudPct = document.getElementById('rvcHudPct');
    this.rvcHudBarFill = document.getElementById('rvcHudBarFill');
    this.rvcHudDetail = document.getElementById('rvcHudDetail');
    this.rvcHideTimer = null;

    // 核心狀態卡片 (移除壓力，聚焦 API 能量與調用次數)
    this.valMode = document.getElementById('valMode');
    this.valSleepStatus = document.getElementById('valSleepStatus');
    this.energyBar = document.getElementById('energyBar');
    this.valEnergyPercent = document.getElementById('valEnergyPercent');
    this.stressBar = document.getElementById('stressBar');
    this.valStressBadge = document.getElementById('valStressBadge');
    this.valStressPercent = document.getElementById('valStressPercent');
    this.valStressLatency = document.getElementById('valStressLatency');
    this.valApiCalls = document.getElementById('valApiCalls');
    this.valSilence = document.getElementById('valSilence');
    this.liveTimerCard = document.getElementById('liveTimerCard');
    this.valLiveTimerStatus = document.getElementById('valLiveTimerStatus');
    this.liveTimerBody = document.getElementById('liveTimerBody');
    this.valLiveTimerMessage = document.getElementById('valLiveTimerMessage');
    this.valLiveTimerCountdown = document.getElementById('valLiveTimerCountdown');
    this.liveTimerProgress = document.getElementById('liveTimerProgress');

    // 視覺感知卡片 (含即時截圖相框)
    this.visionScene = document.getElementById('visionScene');
    this.visionChange = document.getElementById('visionChange');
    this.visionUpdateTimer = document.getElementById('visionUpdateTimer');
    this.visionDescription = document.getElementById('visionDescription');
    this.visionHistoryCount = document.getElementById('visionHistoryCount');
    this.visionHistory = [];
    this.isUserScrollingVision = false;
    this.visionImgPreview = document.getElementById('visionImgPreview');
    this.visionImgFallback = document.getElementById('visionImgFallback');
    this.visionImgTimestamp = document.getElementById('visionImgTimestamp');

    // 聲音感知中樞
    this.valAudioGeneralStatus = document.getElementById('valAudioGeneralStatus');
    this.valSysAudioTag = document.getElementById('valSysAudioTag');
    this.valSysAudioDetail = document.getElementById('valSysAudioDetail');
    this.meterSysAudio = document.getElementById('meterSysAudio');
    this.valRealAudioTag = document.getElementById('valRealAudioTag');
    this.valRealAudioDetail = document.getElementById('valRealAudioDetail');
    this.meterRealAudio = document.getElementById('meterRealAudio');

    // 監控分頁
    this.monTkBadge = document.getElementById('monTkBadge');
    this.monViewerCount = document.getElementById('monViewerCount');
    this.monLikeCount = document.getElementById('monLikeCount');
    this.monTkTelemetry = document.getElementById('monTkTelemetry');
    this.btnToggleMic = document.getElementById('btnToggleMic');
    this.vuMeterInner = document.getElementById('vuMeterInner');
    this.monMicStatus = document.getElementById('monMicStatus');
    this.monModelName = document.getElementById('monModelName');
    this.monVtsExpression = document.getElementById('monVtsExpression');
    this.exprChips = document.querySelectorAll('.expr-chip');
    this.monMindBoard = document.getElementById('monMindBoard');

    // 日誌分頁
    this.terminalLogs = document.getElementById('terminalLogs');
    this.btnClearLogs = document.getElementById('btnClearLogs');

    // 提示詞庫分頁
    this.promptSyncDot = document.getElementById('promptSyncDot');
    this.promptSyncStatus = document.getElementById('promptSyncStatus');
    this.promptSyncTime = document.getElementById('promptSyncTime');
    this.btnReloadPrompts = document.getElementById('btnReloadPrompts');
    this.btnResetPrompts = document.getElementById('btnResetPrompts');
    this.btnSavePrompts = document.getElementById('btnSavePrompts');
    this.promptPersonaCore = document.getElementById('promptPersonaCore');
    this.promptConversationStyle = document.getElementById('promptConversationStyle');
    this.promptStreamerBio = document.getElementById('promptStreamerBio');
    this.promptProactiveGuide = document.getElementById('promptProactiveGuide');
    this.promptCustomRules = document.getElementById('promptCustomRules');
    this.bannedPhrasesList = document.getElementById('bannedPhrasesList');
    this.inputNewBanned = document.getElementById('inputNewBanned');
    this.btnAddBanned = document.getElementById('btnAddBanned');
    this.memesListEl = document.getElementById('memesList');
    this.inputNewMeme = document.getElementById('inputNewMeme');
    this.btnAddMeme = document.getElementById('btnAddMeme');
    this.promptLearnedFacts = document.getElementById('promptLearnedFacts');
    this.fewShotList = document.getElementById('fewShotList');
    this.btnAddFewShot = document.getElementById('btnAddFewShot');
    this.glassToast = document.getElementById('glassToast');

    // 工具調用中樞
    this.toolsActiveCount = document.getElementById('toolsActiveCount');
    this.toolsTotalCalls = document.getElementById('toolsTotalCalls');
    this.toolsManualCalls = document.getElementById('toolsManualCalls');
    this.toolsAutonomousCalls = document.getElementById('toolsAutonomousCalls');
    this.toolCategoryChips = document.querySelectorAll('.category-chip');
    this.toolSelect = document.getElementById('toolSelect');
    this.toolSelectedName = document.getElementById('toolSelectedName');
    this.toolSelectedCat = document.getElementById('toolSelectedCat');
    this.toolSelectedDesc = document.getElementById('toolSelectedDesc');
    this.toolParamForm = document.getElementById('toolParamForm');
    this.toolParamsContainer = document.getElementById('toolParamsContainer');
    this.btnResetToolParams = document.getElementById('btnResetToolParams');
    this.btnExecuteTool = document.getElementById('btnExecuteTool');
    this.toolResultBox = document.getElementById('toolResultBox');
    this.toolResultStatus = document.getElementById('toolResultStatus');
    this.toolResultDuration = document.getElementById('toolResultDuration');
    this.toolResultContent = document.getElementById('toolResultContent');
    this.btnClearToolHistory = document.getElementById('btnClearToolHistory');
    this.toolHistorySearch = document.getElementById('toolHistorySearch');
    this.callerFilterChips = document.querySelectorAll('.filter-chip');
    this.toolHistoryList = document.getElementById('toolHistoryList');

    // 🧠 記憶管理中樞 DOM
    this.memTotalBadge = document.getElementById('memTotalBadge');
    this.memCapacityCurrent = document.getElementById('memCapacityCurrent');
    this.inputMemCapacity = document.getElementById('inputMemCapacity');
    this.btnSaveMemCapacity = document.getElementById('btnSaveMemCapacity');
    this.capacityPresetChips = document.querySelectorAll('.capacity-presets .preset-chip');
    this.memorySearchInput = document.getElementById('memorySearchInput');
    this.btnClearMemorySearch = document.getElementById('btnClearMemorySearch');
    this.memoryRoleChips = document.querySelectorAll('.memory-role-chips .filter-chip');
    this.memoryCardList = document.getElementById('memoryCardList');
    this.memoryListMeta = document.getElementById('memoryListMeta');
    this.btnOpenAddMemory = document.getElementById('btnOpenAddMemory');
    this.btnCleanDuplicates = document.getElementById('btnCleanDuplicates');
    this.btnReloadMemoryList = document.getElementById('btnReloadMemoryList');
    this.btnClearAllMemories = document.getElementById('btnClearAllMemories');
    this.memCountAll = document.getElementById('memCountAll');
    this.memCountThought = document.getElementById('memCountThought');
    this.memCountAi = document.getElementById('memCountAi');
    this.memCountUser = document.getElementById('memCountUser');
    this.memCountTiktok = document.getElementById('memCountTiktok');

    // 編輯記憶 Modal
    this.editMemoryModal = document.getElementById('editMemoryModal');
    this.editMemIndexBadge = document.getElementById('editMemIndexBadge');
    this.editMemRoleBadge = document.getElementById('editMemRoleBadge');
    this.editMemTimeBadge = document.getElementById('editMemTimeBadge');
    this.editMemSpeaker = document.getElementById('editMemSpeaker');
    this.editMemContent = document.getElementById('editMemContent');
    this.btnSaveEditMemory = document.getElementById('btnSaveEditMemory');
    this.btnCancelEditModal = document.getElementById('btnCancelEditModal');
    this.btnCloseEditModal = document.getElementById('btnCloseEditModal');

    // 新增記憶 Modal
    this.addMemoryModal = document.getElementById('addMemoryModal');
    this.addMemRole = document.getElementById('addMemRole');
    this.addMemSpeaker = document.getElementById('addMemSpeaker');
    this.addMemContent = document.getElementById('addMemContent');
    this.btnSubmitAddMemory = document.getElementById('btnSubmitAddMemory');
    this.btnCancelAddModal = document.getElementById('btnCancelAddModal');
    this.btnCloseAddModal = document.getElementById('btnCloseAddModal');

    // 底部狀態列
    this.footMode = document.getElementById('footMode');
    this.footUptime = document.getElementById('footUptime');
    this.footEnergy = document.getElementById('footEnergy');
    this.footCalls = document.getElementById('footCalls');
    this.footTiktok = document.getElementById('footTiktok');
    this.footVision = document.getElementById('footVision');

    // 🛡️ 物理鎖死：徹底肅清右側對話框任何殘留的 [7L 內心流動] 氣泡 (安全跨瀏覽器標準)
    if (this.chatStream) {
      try {
        const cleanOldThoughts = () => {
          this.chatStream.querySelectorAll('.bubble-thought').forEach(el => {
            const row = el.closest('.bubble-row');
            if (row) row.remove();
            else el.remove();
          });
        };
        cleanOldThoughts();
        const thoughtObserver = new MutationObserver(() => {
          cleanOldThoughts();
        });
        thoughtObserver.observe(this.chatStream, { childList: true, subtree: true });
      } catch (e) {
        console.warn('Thought cleaner fallback:', e);
      }
    }
  }

  // ⏱️ 將 Tick 心跳秒數轉換為直觀好讀的時間描述 (1 Tick = 1 秒)
  formatTicksToHuman(ticks) {
    if (!ticks || ticks <= 0) return '剛剛';
    if (ticks < 60) return `${ticks}s`;
    const m = Math.floor(ticks / 60);
    const s = ticks % 60;
    if (m < 60) {
      return s > 0 ? `${m}m ${s}s` : `${m}m`;
    }
    const h = Math.floor(m / 60);
    const remM = m % 60;
    return remM > 0 ? `${h}h ${remM}m` : `${h}h`;
  }

  // ⏱️ API Live 持續時間感測 UI 渲染
  updateLiveTimerUI(sensor) {
    if (!this.liveTimerCard) return;
    if (sensor && sensor.has_active_timer && sensor.nearest_timer) {
      const nearest = sensor.nearest_timer;
      this.liveTimerCard.classList.add('active');
      if (this.liveTimerBody) this.liveTimerBody.style.display = 'flex';
      safeSetText(this.valLiveTimerStatus, '感測中');
      safeSetText(this.valLiveTimerMessage, nearest.message || '提醒老爸');
      safeSetText(this.valLiveTimerCountdown, `${nearest.remaining_ticks} tick (${nearest.remaining_human})`);
      safeSetWidth(this.liveTimerProgress, `${Math.min(100, Math.max(0, nearest.progress_pct))}%`);
    } else {
      this.liveTimerCard.classList.remove('active');
      if (this.liveTimerBody) this.liveTimerBody.style.display = 'none';
      safeSetText(this.valLiveTimerStatus, '待命中');
    }
  }

  bindEvents() {
    // 頂部導覽選單切換 (流暢頁面動效)
    this.menuTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        if (tab.classList.contains('active')) return;

        this.menuTabs.forEach(t => t.classList.remove('active'));
        this.tabPanes.forEach(p => p.classList.remove('active'));

        tab.classList.add('active');
        const targetId = `pane-${tab.dataset.tab}`;
        const targetPane = document.getElementById(targetId);
        if (targetPane) {
          targetPane.classList.add('active');
          // 切換新分頁時平順重設至頂部，確保開場動畫居中展現
          window.scrollTo({ top: 0, behavior: 'instant' });
        }

        // 切換至記憶管理時自動載入最新記憶
        if (tab.dataset.tab === 'memory') {
          this.loadMemoryManagerList();
        }

        // 切換至系統開關時自動載入最新狀態
        if (tab.dataset.tab === 'switches') {
          this.loadSwitches();
        }
      });
    });

    // 重新整理系統開關按鈕
    if (this.btnRefreshSwitches) {
      this.btnRefreshSwitches.addEventListener('click', () => {
        this.loadSwitches();
        this.showToast('🔄 已重新整理系統開關狀態');
      });
    }

    // 🌊 全域微互動：按鈕點擊水波光漣漪 (Tactile Liquid Glow Ripple)
    document.addEventListener('pointerdown', (e) => {
      const target = e.target.closest('button, .action-chip, .menu-tab, .expr-chip, .category-chip, .filter-chip, .glass-send-btn, .glass-btn, .glass-mini-btn, .switch-card');
      if (!target) return;

      const rect = target.getBoundingClientRect();
      const ripple = document.createElement('span');
      ripple.className = 'glass-click-ripple';
      const diameter = Math.max(rect.width, rect.height) * 2.2;
      const radius = diameter / 2;
      const x = e.clientX - rect.left - radius;
      const y = e.clientY - rect.top - radius;

      ripple.style.width = `${diameter}px`;
      ripple.style.height = `${diameter}px`;
      ripple.style.left = `${x}px`;
      ripple.style.top = `${y}px`;

      target.appendChild(ripple);
      setTimeout(() => {
        if (ripple.parentNode) ripple.parentNode.removeChild(ripple);
      }, 600);
    });

    // 快捷動作膠囊列 - 防連點與點擊震盪回饋 (含 try-finally 絕對防鎖死)
    this.actionChips.forEach(chip => {
      chip.addEventListener('click', () => {
        if (this.isSending) return;
        this.isSending = true;
        chip.classList.add('chip-activated');
        setTimeout(() => chip.classList.remove('chip-activated'), 450);

        try {
          const action = chip.dataset.action;
          const msg = chip.dataset.msg;

          if (action === 'sleep') {
            this.setSleepMode(true);
          } else if (action === 'wake') {
            this.setSleepMode(false);
          } else if (action === 'reward') {
            this.reward7L();
          } else if (action === 'hug') {
            this.reward7L("老爸給予 7L 深情緊緊擁抱與終極寵溺", 3);
          } else if (action === 'punish') {
            this.punish7L("老爸按下了微電流刺激", false);
          } else if (action === 'shock_heavy') {
            this.punish7L("老爸按下了強力電擊處分！", true);
          } else if (action === 'restart') {
            this.restartSystem();
          } else if (action === 'shutdown') {
            this.shutdownSystem();
          } else if (action === 'mic_on') {
            this.setMicMode(true);
          } else if (action === 'mic_off') {
            this.setMicMode(false);
          } else if (msg) {
            this.sendMessage(msg);
          }
        } catch (err) {
          console.error('Action chip error:', err);
        } finally {
          setTimeout(() => { this.isSending = false; }, 350);
        }
      });
    });

    // 訊息輸入框送出 - 防重複送出與箭頭飛馳回饋 (含 try-finally 絕對防鎖死)
    if (this.chatForm) {
      this.chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        if (this.isSending) return;
        const text = this.chatInputField ? this.chatInputField.value.trim() : '';
        if (text) {
          this.isSending = true;
          if (this.btnSend) {
            this.btnSend.classList.add('btn-sent');
            setTimeout(() => this.btnSend && this.btnSend.classList.remove('btn-sent'), 450);
          }
          try {
            this.sendMessage(text);
            if (this.chatInputField) this.chatInputField.value = '';
          } catch (err) {
            console.error('Chat submit error:', err);
          } finally {
            setTimeout(() => { this.isSending = false; }, 350);
          }
        }
      });
    }

    // 麥克風切換
    if (this.btnToggleMic) {
      this.btnToggleMic.addEventListener('click', () => {
        this.toggleMic();
      });
    }

    // Live2D 表情切換按鈕 - 開關式 (Toggle Switch: 點擊開啟，再點擊關閉)
    this.exprChips.forEach(chip => {
      chip.addEventListener('click', () => {
        const expr = chip.dataset.expr;
        if (!expr) return;

        if (expr === '_RESET_') {
          // 點擊「重置預設」：全部關閉，恢復自然
          this.activeExpression = null;
          this.exprChips.forEach(c => c.classList.remove('active'));
          this.triggerExpression('_RESET_');
          this.appendLog('[表情控制] 關閉所有表情，恢復預設自然狀態', 'line-info');
        } else if (this.activeExpression === expr) {
          // 再次點擊已開啟的同一個表情：開關式關閉 (Toggle OFF)
          this.activeExpression = null;
          chip.classList.remove('active');
          this.triggerExpression('_RESET_');
          this.appendLog(`[表情開關] 關閉表情「${chip.innerText.trim()}」，恢復自然狀態`, 'line-info');
        } else {
          // 點擊未開啟的表情：開關式開啟 (Toggle ON)，並關閉其他表情
          this.activeExpression = expr;
          this.exprChips.forEach(c => {
            if (c.dataset.expr === expr && expr !== '_RESET_') {
              c.classList.add('active');
            } else {
              c.classList.remove('active');
            }
          });
          this.triggerExpression(expr);
          this.appendLog(`[表情開關] 開啟表情「${chip.innerText.trim()}」`, 'line-info');
        }
      });
    });

    // 視覺相框放大檢視與手動刷新
    const box = document.getElementById('visionPreviewBox');
    const modal = document.getElementById('visionModal');
    const modalImg = document.getElementById('visionModalImg');
    const btnCloseModal = document.getElementById('btnVisionModalClose');

    if (box && modal && modalImg) {
      box.addEventListener('click', () => {
        const hdUrl = `/api/last_vision_image?hd=1&t=${Date.now()}`;
        modalImg.src = hdUrl;
        const openRawBtn = document.getElementById('btnVisionOpenRaw');
        if (openRawBtn) openRawBtn.href = hdUrl;
        modal.classList.add('active');
      });

      if (btnCloseModal) {
        btnCloseModal.addEventListener('click', () => {
          modal.classList.remove('active');
        });
      }

      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          modal.classList.remove('active');
        }
      });

      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('active')) {
          modal.classList.remove('active');
        }
      });
    }

    // 📜 視覺感知歷史串流滾動監聽 (確保使用者往上滑看歷史時不被新訊息強行打斷)
    if (this.visionDescription) {
      this.visionDescription.addEventListener('scroll', () => {
        const atBottom = this.visionDescription.scrollHeight - this.visionDescription.scrollTop <= this.visionDescription.clientHeight + 35;
        this.isUserScrollingVision = !atBottom;
      }, { passive: true });
    }

    // 提示詞庫操作事件
    if (this.btnSavePrompts) {
      this.btnSavePrompts.addEventListener('click', () => this.savePrompts());
    }
    if (this.btnReloadPrompts) {
      this.btnReloadPrompts.addEventListener('click', () => this.loadPrompts());
    }
    if (this.btnResetPrompts) {
      this.btnResetPrompts.addEventListener('click', () => this.resetPrompts());
    }

    // 新增禁用詞彙
    if (this.btnAddBanned && this.inputNewBanned) {
      this.btnAddBanned.addEventListener('click', () => {
        this.addBannedPhrase(this.inputNewBanned.value);
      });
      this.inputNewBanned.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.addBannedPhrase(this.inputNewBanned.value);
        }
      });
    }

    // 新增網路梗
    if (this.btnAddMeme && this.inputNewMeme) {
      this.btnAddMeme.addEventListener('click', () => {
        this.addMeme(this.inputNewMeme.value);
      });
      this.inputNewMeme.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.addMeme(this.inputNewMeme.value);
        }
      });
    }

    // 新增示範
    if (this.btnAddFewShot) {
      this.btnAddFewShot.addEventListener('click', () => this.addNewFewShot());
    }

    // 🛠️ 工具調用分類標籤切換
    if (this.toolCategoryChips) {
      this.toolCategoryChips.forEach(chip => {
        chip.addEventListener('click', () => {
          this.toolCategoryChips.forEach(c => c.classList.remove('active'));
          chip.classList.add('active');
          this.toolsCategory = chip.dataset.category || 'all';
          this.renderToolDropdown(this.toolsCategory);
        });
      });
    }

    // 工具選擇變更
    if (this.toolSelect) {
      this.toolSelect.addEventListener('change', (e) => {
        this.selectTool(e.target.value);
      });
    }

    // 重置工具參數
    if (this.btnResetToolParams) {
      this.btnResetToolParams.addEventListener('click', () => {
        if (this.selectedTool) {
          this.renderToolParamInputs(this.selectedTool);
          this.showToast('已重置工具參數為預設值');
        }
      });
    }

    // 執行工具表單提交
    if (this.toolParamForm) {
      this.toolParamForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.executeSelectedTool();
      });
    }

    // 清空工具調用歷史紀錄
    if (this.btnClearToolHistory) {
      this.btnClearToolHistory.addEventListener('click', () => {
        if (confirm('老爸，確定要清空所有工具調用紀錄嗎？')) {
          this.clearToolHistory();
        }
      });
    }

    // 工具紀錄搜尋過濾
    if (this.toolHistorySearch) {
      this.toolHistorySearch.addEventListener('input', (e) => {
        this.toolSearchQuery = e.target.value.trim().toLowerCase();
        this.renderToolHistoryList();
      });
    }

    // 工具紀錄發起者過濾
    if (this.callerFilterChips) {
      this.callerFilterChips.forEach(chip => {
        chip.addEventListener('click', () => {
          this.callerFilterChips.forEach(c => c.classList.remove('active'));
          chip.classList.add('active');
          this.toolCallerFilter = chip.dataset.caller || 'all';
          this.renderToolHistoryList();
        });
      });
    }

    // 🧠 記憶管理中樞事件綁定
    if (this.memoryRoleChips) {
      this.memoryRoleChips.forEach(chip => {
        chip.addEventListener('click', () => {
          this.memoryRoleChips.forEach(c => c.classList.remove('active'));
          chip.classList.add('active');
          this.memoryFilterRole = chip.dataset.role || 'all';
          this.renderMemoryList();
        });
      });
    }

    if (this.memorySearchInput) {
      this.memorySearchInput.addEventListener('input', (e) => {
        this.memorySearchKeyword = e.target.value.trim();
        if (this.btnClearMemorySearch) {
          this.btnClearMemorySearch.style.display = this.memorySearchKeyword ? 'block' : 'none';
        }
        this.renderMemoryList();
      });
    }

    if (this.btnClearMemorySearch) {
      this.btnClearMemorySearch.addEventListener('click', () => {
        if (this.memorySearchInput) this.memorySearchInput.value = '';
        this.memorySearchKeyword = '';
        this.btnClearMemorySearch.style.display = 'none';
        this.renderMemoryList();
      });
    }

    if (this.btnReloadMemoryList) {
      this.btnReloadMemoryList.addEventListener('click', () => {
        this.loadMemoryManagerList();
        this.showToast('🔄 正在同步最新記憶庫...');
      });
    }

    if (this.btnCleanDuplicates) {
      this.btnCleanDuplicates.addEventListener('click', () => {
        this.cleanDuplicateMemories();
      });
    }

    if (this.btnClearAllMemories) {
      this.btnClearAllMemories.addEventListener('click', () => {
        this.clearAllMemories();
      });
    }

    // 🧠 記憶池容量設定事件綁定
    if (this.capacityPresetChips) {
      this.capacityPresetChips.forEach(btn => {
        btn.addEventListener('click', () => {
          const val = btn.dataset.val;
          if (this.inputMemCapacity) {
            this.inputMemCapacity.value = val;
            this.saveMemoryCapacity(parseInt(val, 10));
          }
        });
      });
    }

    if (this.btnSaveMemCapacity) {
      this.btnSaveMemCapacity.addEventListener('click', () => {
        const val = this.inputMemCapacity ? parseInt(this.inputMemCapacity.value, 10) : 500;
        this.saveMemoryCapacity(isNaN(val) ? 500 : val);
      });
    }

    if (this.btnOpenAddMemory) {
      this.btnOpenAddMemory.addEventListener('click', () => {
        this.openAddMemoryModal();
      });
    }

    if (this.btnCancelAddModal) {
      this.btnCancelAddModal.addEventListener('click', () => this.closeAddMemoryModal());
    }
    if (this.btnCloseAddModal) {
      this.btnCloseAddModal.addEventListener('click', () => this.closeAddMemoryModal());
    }
    if (this.btnSubmitAddMemory) {
      this.btnSubmitAddMemory.addEventListener('click', () => this.submitAddMemory());
    }

    if (this.btnCancelEditModal) {
      this.btnCancelEditModal.addEventListener('click', () => this.closeEditMemoryModal());
    }
    if (this.btnCloseEditModal) {
      this.btnCloseEditModal.addEventListener('click', () => this.closeEditMemoryModal());
    }
    if (this.btnSaveEditMemory) {
      this.btnSaveEditMemory.addEventListener('click', () => this.saveEditMemory());
    }

    // 🧠 即時心流抽屜折疊 / 展開
    if (this.btnToggleMindDrawer) {
      this.btnToggleMindDrawer.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleMindDrawer();
      });
    }

    // 📌 心流固定釘選滾動
    if (this.btnPinMindStream) {
      this.btnPinMindStream.addEventListener('click', () => {
        this.isMindPinAutoScroll = !this.isMindPinAutoScroll;
        this.btnPinMindStream.classList.toggle('active', this.isMindPinAutoScroll);
        this.showToast(this.isMindPinAutoScroll ? '📌 已開啟心流自動滾動' : '⏸️ 已暫停心流自動滾動');
      });
    }

    // 🧹 清空心流紀錄
    if (this.btnClearMindStream) {
      this.btnClearMindStream.addEventListener('click', () => {
        if (this.mindHistoryStream) this.mindHistoryStream.innerHTML = '';
        if (this.thinkingStreamText) this.thinkingStreamText.textContent = '';
        this.showToast('🧹 已清空心流紀錄');
      });
    }

    // ↔️ 心流面板寬度拖曳調整 (Resizer)
    if (this.mindSplitResizer && this.mindStreamPanel) {
      this.mindSplitResizer.addEventListener('mousedown', (e) => {
        if (e.target.closest('#btnToggleMindDrawer')) return;
        this.isDraggingResizer = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      });

      document.addEventListener('mousemove', (e) => {
        if (!this.isDraggingResizer || !this.mindStreamPanel) return;
        const containerRect = this.chatMindSplit ? this.chatMindSplit.getBoundingClientRect() : { left: 0, width: window.innerWidth };
        const newWidth = e.clientX - containerRect.left;
        if (newWidth > 180 && newWidth < (containerRect.width - 250)) {
          this.mindStreamPanel.style.width = `${newWidth}px`;
          this.mindStreamPanel.style.flex = `0 0 ${newWidth}px`;
        }
      });

      document.addEventListener('mouseup', () => {
        if (this.isDraggingResizer) {
          this.isDraggingResizer = false;
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
        }
      });
    }
  }

  startTimers() {
    // 頂部時鐘每秒更新一次
    const updateClock = () => {
      const now = new Date();
      safeSetText(this.clockText, now.toLocaleTimeString('zh-TW', { hour12: false }));
    };
    updateClock();
    setInterval(updateClock, 1000);

    // 視覺感知計時器 (每 1 秒更新一次，不再無謂 500ms 狂刷新)
    setInterval(() => {
      if (!this.visionUpdateTimer) return;
      if (this.isSleeping) {
        safeSetText(this.visionUpdateTimer, '暫停中');
        return;
      }
      const diffSec = Math.max(0, (Date.now() / 1000) - this.lastVisionTimestamp);
      const text = diffSec < 2 ? '剛剛' : `${Math.round(diffSec)} 秒前`;
      safeSetText(this.visionUpdateTimer, text);
    }, 1000);

    // 沉默 tick 計時 (每 1 秒一次，平滑過渡並同步後端)
    setInterval(() => {
      this.silenceTicks += 1;
      const human = this.formatTicksToHuman(this.silenceTicks);
      safeSetText(this.valSilence, `${this.silenceTicks} tick (${human})`);
      if (typeof this.uptimeTicks === 'number' && this.uptimeTicks > 0) {
        this.uptimeTicks += 1;
        safeSetText(this.footUptime, `${this.uptimeTicks} tick`);
      }
    }, 1000);

    // 視覺截圖保底同步 (每 6 秒一次，若有新截圖時間戳會即時更新，此處僅作為保底)
    setInterval(() => {
      if (!this.isSleeping && !this.isImgLoading) {
        this.triggerVisionImageReload(false);
      }
    }, 6000);
  }

  // 🚀 高性能圖片非同步預載入，絕不卡死瀏覽器主線程
  triggerVisionImageReload(force = false) {
    if (!this.visionImgPreview || this.isSleeping || this.isImgLoading) return;

    this.isImgLoading = true;
    const preload = new Image();
    const targetUrl = `/api/last_vision_image?t=${Date.now()}`;

    preload.onload = () => {
      if (this.visionImgPreview && !this.isSleeping) {
        this.visionImgPreview.src = targetUrl;
        this.visionImgPreview.style.display = 'block';
        if (this.visionImgFallback) this.visionImgFallback.style.display = 'none';
        if (this.visionImgTimestamp) {
          const now = new Date();
          safeSetText(this.visionImgTimestamp, now.toLocaleTimeString('zh-TW', { hour12: false }));
        }
      }
      this.isImgLoading = false;
    };

    preload.onerror = () => {
      if (this.visionImgFallback && !this.isSleeping) {
        this.visionImgFallback.style.display = 'flex';
        if (this.visionImgPreview) this.visionImgPreview.style.display = 'none';
      }
      this.isImgLoading = false;
    };

    preload.src = targetUrl;
  }

  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    if (this.ws) {
      try {
        this.ws.onclose = null;
        this.ws.onerror = null;
        this.ws.close();
      } catch (e) {}
    }

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.setOnlineStatus(true);
        this.appendLog('WebSocket 監控連線已建立', 'line-success');
        this.stopFallbackPolling();
        this.startWsPing();
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          this.handleServerMessage(payload);
        } catch (err) {
          console.error(err);
        }
      };

      this.ws.onclose = () => {
        this.setOnlineStatus(false);
        this.stopWsPing();
        this.startFallbackPolling();
        this.appendLog('WebSocket 連線中斷，正在重新連接...', 'line-warn');
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.setOnlineStatus(false);
        this.stopWsPing();
        this.startFallbackPolling();
      };
    } catch (err) {
      this.setOnlineStatus(false);
      this.startFallbackPolling();
      this.scheduleReconnect();
    }
  }

  startWsPing() {
    this.stopWsPing();
    this.wsPingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ action: 'ping' }));
        } catch (e) {}
      }
    }, 12000);
  }

  stopWsPing() {
    if (this.wsPingInterval) {
      clearInterval(this.wsPingInterval);
      this.wsPingInterval = null;
    }
  }

  startFallbackPolling() {
    if (this.fallbackPollTimer) return;
    this.fallbackPollTimer = setInterval(async () => {
      try {
        const resp = await fetch('/api/status');
        if (resp.ok) {
          const data = await resp.json();
          this.updateTelemetry(data);
          // 若後端已活過來且 WS 仍斷開，嘗試重連 WS
          if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
            this.connectWebSocket();
          }
        }
      } catch (e) {}
    }, 3000);
  }

  stopFallbackPolling() {
    if (this.fallbackPollTimer) {
      clearInterval(this.fallbackPollTimer);
      this.fallbackPollTimer = null;
    }
  }

  scheduleReconnect() {
    if (!this.reconnectTimer) {
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.connectWebSocket();
      }, 2000);
    }
  }

  setOnlineStatus(isOnline) {
    if (!this.topDot || !this.topStatusText) return;
    if (isOnline) {
      this.topDot.style.background = '#10b981';
      this.topDot.style.boxShadow = '0 0 10px rgba(16, 185, 129, 0.6)';
      safeSetText(this.topStatusText, this.isSleeping ? '休眠中' : '正常運作');
    } else {
      this.topDot.style.background = '#f43f5e';
      this.topDot.style.boxShadow = '0 0 10px rgba(244, 63, 94, 0.6)';
      safeSetText(this.topStatusText, '重連中...');
    }
  }

  handleServerMessage(payload) {
    const { type, data } = payload;

    if (type === 'init') {
      this.updateTelemetry(data);
      if (data && Array.isArray(data.recent_memory)) {
        this.loadConversationHistory(data.recent_memory);
      }
      if (data && Array.isArray(data.mind_board) && data.mind_board.length > 0) {
        data.mind_board.forEach(latestMind => {
          const mText = typeof latestMind === 'object' ? (latestMind.content || latestMind.text || '') : String(latestMind);
          if (mText && !mText.includes('7L 正在待命')) {
            if (this.thinkingStreamText && !this.thinkingStreamText.textContent.includes(mText.trim())) {
              this.thinkingStreamText.textContent += ('\n\n' + mText.trim());
            }
          }
        });
      }
      if (payload && Array.isArray(payload.tool_history) && payload.tool_history.length > 0) {
        this.toolHistory = payload.tool_history;
        this.renderToolHistoryList();
        this.updateToolStats();
      }
      this.triggerVisionImageReload(true);
    } else if (type === 'telemetry') {
      this.updateTelemetry(data);
    } else if (type === 'vision_update') {
      if (data) {
        this.addVisionHistoryEntry(data);
      }
    } else if (type === 'ai_speech') {
      this.appendChatBubble('ai', data.text, true, true, false, null, data.model || '');
      this.appendLog(`[7L 發言] ${data.text}${data.model ? ` (${data.model})` : ''}`, 'line-info');
      this.silenceTicks = 0;
      safeSetText(this.valSilence, '0 tick (剛剛)');
      // 🟢 7L 說話 → 把所有「未讀」直播留言標記為已讀
      this._markTiktokCommentsRead();
    } else if (type === 'ai_thought_start' || type === 'ai_thought_chunk' || type === 'ai_thought_end' || type === 'ai_thought') {
      // 🧠 心流已停用，不處理
    } else if (type === 'chat_sent') {
      const lastUserBubble = this.chatStream ? this.chatStream.querySelector('.bubble-row.bubble-user:last-child .bubble-text, .bubble-row.bubble-user:last-child .bubble-content') : null;
      if (!lastUserBubble || lastUserBubble.textContent.trim() !== (data.text || '').trim()) {
        this.appendChatBubble('user', data.text);
      }
      this.silenceTicks = 0;
      safeSetText(this.valSilence, '0 tick (剛剛)');
    } else if (type === 'tiktok_comment') {
      this.appendChatBubble('tiktok', data.user, data.text);
      this.appendLog(`[TikTok 彈幕] ${data.user}: ${data.text}`, 'line-info');
    } else if (type === 'tiktok_gift') {
      this.appendChatBubble('tiktok', `🎁 ${data.user}`, `送出 ${data.count} 個 ${data.gift_name}`);
      this.appendLog(`[TikTok 送禮] ${data.user} 送出 ${data.count} 個 ${data.gift_name}`, 'line-success');
    } else if (type === 'ai_punished') {
      this.appendLog(`[電擊懲罰] ⚡ ${data.reason} ➔ ${data.text || ''}`, 'line-warn');
      this.showToast(`⚡ 7L 受到電擊處分：${data.reason}`, 4000);
    } else if (type === 'ai_rewarded') {
      this.appendLog(`[摸頭獎勵] 💖 ${data.reason} ➔ ${data.text || ''}`, 'line-success');
      this.showToast(`💖 7L 獲得摸頭獎勵：${data.reason}`, 4000);
    } else if (type === 'sleep_changed') {
      this.updateSleepUI(data.is_sleeping);
    } else if (type === 'mic_changed') {
      this.updateMicUI(data.is_mic_enabled);
    } else if (type === 'switch_update') {
      if (data) {
        if (data.switches && Array.isArray(data.switches)) {
          this.switchesList = data.switches;
          this.renderSwitches(this.switchesList);
        } else if (data.key !== undefined) {
          this.updateSingleSwitchUI(data.key, data.value);
        }
      }
    } else if (type === 'expression_changed') {
      if (this.monVtsExpression) {
        safeSetText(this.monVtsExpression, `目前：${data.expression}`);
      }
    } else if (type === 'timer_added') {
      if (data) {
        this.updateLiveTimerUI(data);
        const txt = data.status_text || '定時感測已啟動';
        this.showToast(`⏱️ API Live 定時感測啟動：${txt}`);
      }
    } else if (type === 'timer_triggered') {
      if (data) {
        this.showToast(`🔔 定時提醒到期：${data.message || ''}`);
        this.updateLiveTimerUI({ has_active_timer: false });
      }
    } else if (type === 'prompts_updated') {
      safeSetText(this.promptSyncStatus, '雲端已同步');
      if (data && data.last_updated) {
        safeSetText(this.promptSyncTime, data.last_updated.split(' ')[1] || data.last_updated);
      }
      this.showToast('🔔 收到雲端提示詞庫同步廣播');
    } else if (type === 'tool_call') {
      if (data) {
        this.addToolCallRecord(data);
        const statusText = data.status === 'success' ? '成功' : '失敗';
        this.appendLog(`[工具調用] ${data.caller}: ${data.tool} (${statusText})`, data.status === 'success' ? 'line-success' : 'line-warn');
      }
    } else if (type === 'tools_cleared') {
      this.toolHistory = [];
      this.renderToolHistoryList();
      this.updateToolStats();
      this.appendLog('[工具中樞] 工具調用歷史紀錄已清空', 'line-info');
    } else if (type === 'memory_cleared') {
      this.loadedMemoryIds.clear();
      if (this.chatStream) this.chatStream.innerHTML = '';
      if (this.mindStreamList) this.mindStreamList.innerHTML = '';
      this.memoryItems = [];
      this.renderMemoryList();
      this.loadMemoryManagerList();
      this.loadMemoryHistory();
      this.appendLog('[記憶中樞] 7L 雲端與本地記憶已徹底清空', 'line-warn');
    } else if (type === 'memory_capacity_updated') {
      this.loadMemoryCapacity();
      this.loadMemoryManagerList();
      const capDesc = (payload && payload.dialogue_capacity <= 0) ? '⚡ 無上限' : `${payload ? payload.dialogue_capacity : ''} 句`;
      this.appendLog(`[記憶中樞] 底層對話記憶池上限已更新為: ${capDesc}`, 'line-info');
    } else if (type === 'system_restart') {
      this.showToast('🔄 7L 系統正在重新啟動...', 5000);
      this.appendLog('[系統] 7L 系統正在重新啟動中...', 'line-warn');
      if (this.topDot) {
        this.topDot.style.background = '#f59e0b';
        this.topDot.style.boxShadow = '0 0 10px rgba(245, 158, 11, 0.6)';
      }
      if (this.topStatusText) {
        safeSetText(this.topStatusText, '重啟中...');
      }
    } else if (type === 'system_shutdown') {
      this.showToast('👋 7L 系統已安全關閉', 5000);
      this.appendLog('[系統] 7L 系統已安全退出', 'line-warn');
      if (this.topDot) {
        this.topDot.style.background = '#64748b';
        this.topDot.style.boxShadow = 'none';
      }
      if (this.topStatusText) {
        safeSetText(this.topStatusText, '已關機 (離線)');
      }
    } else if (type === 'tts_log') {
      if (data && data.text) {
        this.appendLog(data.text, 'line-info');
      }
    } else if (type === 'tts_progress') {
      this.updateTtsProgress(data);
    } else if (type === 'rvc_progress') {
      this.updateRvcProgress(data);
    } else if (type === 'yt_companion_request') {
      // 🎬 伴看授權請求：右下角跳出審批通知卡
      this.showCompanionApprovalToast(data);
      this.appendLog(`[伴看授權] 偵測到影片視窗《${(data && data.short_title) || ''}》，等待老爸授權...`, 'line-info');
    } else if (type === 'yt_companion_approved') {
      this.hideCompanionApprovalToast();
      this.showToast('✅ 已授權伴看！7L 感官串流啟動中...', 4000);
      this.appendLog('[伴看授權] ✅ 老爸已授權，伴看感官串流啟動中', 'line-success');
    } else if (type === 'yt_companion_rejected') {
      this.hideCompanionApprovalToast();
      this.showToast('❌ 已拒絕伴看請求，本次跳過', 3000);
      this.appendLog('[伴看授權] ❌ 老爸已拒絕伴看', 'line-warn');
    }
  }

  updateTtsProgress(data) {
    if (!this.ttsProgressHud) return;
    if (!data) return;

    if (this.ttsHideTimer) {
      clearTimeout(this.ttsHideTimer);
      this.ttsHideTimer = null;
    }

    const isRvc = data.mode === 'rvc' || (data.stage && data.stage.includes('RVC')) || (data.detail && data.detail.includes('RVC'));
    if (this.ttsHudIcon) safeSetText(this.ttsHudIcon, isRvc ? '🎤' : '🎙️');
    if (this.ttsHudTitle) safeSetText(this.ttsHudTitle, isRvc ? '7L 歌聲置換中 (RVC)' : '7L 聲音合成中');

    if (data.active) {
      this.ttsProgressHud.style.display = 'flex';
      const pct = typeof data.percent === 'number' ? Math.max(5, Math.min(100, data.percent)) : 10;
      if (this.ttsHudPct) safeSetText(this.ttsHudPct, `${pct}%`);
      if (this.ttsHudBarFill) safeSetWidth(this.ttsHudBarFill, `${pct}%`);
      if (this.ttsHudStage && data.stage) safeSetText(this.ttsHudStage, data.stage);
      if (this.ttsHudDetail && data.detail) safeSetText(this.ttsHudDetail, data.detail);
    } else {
      // 合成結束或異常
      if (this.ttsHudPct) safeSetText(this.ttsHudPct, '100%');
      if (this.ttsHudBarFill) safeSetWidth(this.ttsHudBarFill, '100%');
      if (this.ttsHudStage) safeSetText(this.ttsHudStage, data.stage || '完成');

      // 3.5 秒後平滑隱藏，確保老爸能看清楚完成狀態
      this.ttsHideTimer = setTimeout(() => {
        if (this.ttsProgressHud) {
          this.ttsProgressHud.style.display = 'none';
          if (this.ttsHudBarFill) safeSetWidth(this.ttsHudBarFill, '0%');
        }
        this.ttsHideTimer = null;
      }, 3500);
    }
  }

  updateRvcProgress(data) {
    if (!this.rvcProgressHud) return;
    if (!data) return;

    if (this.rvcHideTimer) {
      clearTimeout(this.rvcHideTimer);
      this.rvcHideTimer = null;
    }

    if (this.rvcHudIcon) safeSetText(this.rvcHudIcon, '🔄');
    if (this.rvcHudTitle) safeSetText(this.rvcHudTitle, '7L 音色轉換中 (RVC)');

    if (data.active && data.stage) {
      this.rvcProgressHud.style.display = 'flex';
      if (this.rvcHudStage) safeSetText(this.rvcHudStage, data.stage);
      const pct = typeof data.percent === 'number' ? Math.max(5, Math.min(100, data.percent)) : 50;
      if (this.rvcHudPct) safeSetText(this.rvcHudPct, `${pct}%`);
      if (this.rvcHudBarFill) safeSetWidth(this.rvcHudBarFill, `${pct}%`);
      if (this.rvcHudDetail && data.detail) safeSetText(this.rvcHudDetail, data.detail);
    } else {
      // RVC 完成
      if (this.rvcHudPct) safeSetText(this.rvcHudPct, '100%');
      if (this.rvcHudBarFill) safeSetWidth(this.rvcHudBarFill, '100%');
      if (this.rvcHudStage) safeSetText(this.rvcHudStage, data.stage || '音色轉換完成');

      this.rvcHideTimer = setTimeout(() => {
        if (this.rvcProgressHud) {
          this.rvcProgressHud.style.display = 'none';
          if (this.rvcHudBarFill) safeSetWidth(this.rvcHudBarFill, '0%');
        }
        this.rvcHideTimer = null;
      }, 3500);
    }
  }

  async loadMemoryHistory() {
    try {
      const resp = await fetch('/api/memory');
      const res = await resp.json();
      if (res.ok && Array.isArray(res.memories) && res.memories.length > 0) {
        this.loadConversationHistory(res.memories);
      }
    } catch (e) {
      console.warn('載入全景記憶時間線失敗:', e);
    }
  }

  loadConversationHistory(memories) {
    if (!memories || memories.length === 0 || !this.chatStream) return;
    this.chatStream.innerHTML = '';
    this.loadedMemoryIds.clear();

    // 載入全景記憶時間線 (最多 300 句完整歷史，使用 DocumentFragment 單次掛載避免重排)
    const frag = document.createDocumentFragment();
    const historicalThoughts = [];
    const recent = memories.slice(-300);

    recent.forEach((item, index) => {
      const content = item.content || item.text || '';
      const role = item.role || '';
      const speaker = item.speaker || '';
      const timeVal = item.time || item.timestamp || item.time_str || index;

      if (!content) return;
      const memKey = `${role}_${speaker}_${content}_${timeVal}`;
      if (this.loadedMemoryIds.has(memKey)) return;
      this.loadedMemoryIds.add(memKey);

      const isThought = (role === 'thought' || item.source === 'thought' || item.target === '內心流動' || speaker === '內心流動');

      if (isThought) {
        // 🧠 左側即時心流：收集歷史思緒，稍後直接「靜態載入」，不跑打字機動畫
        historicalThoughts.push(content);
      } else if (role === 'assistant' || speaker === '7L') {
        this.appendChatBubble('ai', content, false, false, false, frag, item.model || '');
      } else if (speaker.includes('TikTok') || item.source === 'tiktok') {
        this.appendChatBubble('tiktok', speaker, content, false, true /* historyRead */, frag);
      } else if (role === 'system' || speaker === '系統' || item.source === 'system' || item.source === 'piano') {
        this.appendChatBubble('system', content, false, false, false, frag);
      } else {
        this.appendChatBubble('user', content, false, false, false, frag);
      }
    });

    // 🧠 左側「即時心流」面板已依老爸要求徹底停用
    // if (historicalThoughts.length > 0 && this.thinkingStreamText && !this.isStreamingThought) { ... }


    // 💬 右側主對話框：成功掛載所有正式對話（老爸、7L 發言、TikTok 彈幕、系統通知）
    this.chatStream.appendChild(frag);
    this.renderVisionHistory();
    this.chatStream.scrollTop = this.chatStream.scrollHeight;
  }

  updateTelemetry(data) {
    if (!data) return;

    // 1. 核心狀態
    if (data.core) {
      const core = data.core;

      if (typeof core.is_sleeping === 'boolean' && core.is_sleeping !== this.isSleeping) {
        this.updateSleepUI(core.is_sleeping);
      }

      // 運行模式
      const mode = (core.ai_state || (this.isSleeping ? 'sleep' : 'idle')).toLowerCase();
      safeSetText(this.valMode, mode);
      safeSetText(this.footMode, mode);

      // API 能量與調用次數
      const apiCalls = core.api_calls !== undefined ? core.api_calls : 0;
      const apiEnergy = core.api_energy !== undefined ? core.api_energy : Math.max(5, (100 - apiCalls * 0.4)).toFixed(1);

      safeSetText(this.valApiCalls, `${apiCalls} 次`);
      safeSetText(this.footCalls, `${apiCalls} 次`);
      safeSetText(this.valEnergyPercent, `${apiEnergy}%`);
      safeSetText(this.footEnergy, `${apiEnergy}%`);
      safeSetWidth(this.energyBar, `${Math.min(100, Math.max(0, apiEnergy))}%`);

      // ⏱️ 7L 統一神經時間感知 (Unified Tick Clock)
      if (typeof core.silence_ticks === 'number') {
        this.silenceTicks = core.silence_ticks;
        const human = core.silence_human || this.formatTicksToHuman(this.silenceTicks);
        safeSetText(this.valSilence, `${this.silenceTicks} tick (${human})`);
      }
      if (typeof core.uptime_ticks === 'number') {
        this.uptimeTicks = core.uptime_ticks;
        safeSetText(this.footUptime, `${this.uptimeTicks} tick`);
      }

      // ⏱️ API Live 持續時間感測哨兵
      if (core.timer_sensor) {
        this.updateLiveTimerUI(core.timer_sensor);
      }

      // ⚡ 大腦壓力值量表 (耗時越長壓力越大)
      if (core.api_stress) {
        const stress = core.api_stress;
        const pct = stress.stress_percent !== undefined ? stress.stress_percent : 15;
        safeSetText(this.valStressPercent, `${pct}%`);
        safeSetText(this.valStressLatency, `(均速 ${stress.latency_str || '0.0s'})`);
        safeSetText(this.valStressBadge, stress.stress_tag || '🟢 輕鬆');
        if (this.valStressBadge) {
          safeSetClass(this.valStressBadge, `stress-badge ${stress.stress_level || 'relaxed'}`);
        }
        if (this.stressBar) {
          safeSetWidth(this.stressBar, `${Math.min(100, Math.max(0, pct))}%`);
          safeSetClass(this.stressBar, `glass-progress-fill fill-stress ${stress.stress_level || 'relaxed'}`);
        }
      }

      if (this.valSleepStatus) {
        if (this.isSleeping) {
          safeSetText(this.valSleepStatus, '閉眼沉睡中 (0 API)');
          safeSetClass(this.valSleepStatus, 'status-tag tag-sleeping');
        } else if (mode === 'talking') {
          safeSetText(this.valSleepStatus, '發言中');
          safeSetClass(this.valSleepStatus, 'status-tag tag-talking');
        } else if (mode === 'thinking') {
          safeSetText(this.valSleepStatus, '思考中');
          safeSetClass(this.valSleepStatus, 'status-tag tag-thinking');
        } else {
          safeSetText(this.valSleepStatus, '全速運作');
          safeSetClass(this.valSleepStatus, 'status-tag');
        }
      }

      // 麥克風音量 (VU Meter)
      if (core.mic_volume !== undefined && this.vuMeterInner) {
        const pct = Math.min(100, Math.max(0, core.mic_volume * 100));
        safeSetWidth(this.vuMeterInner, `${pct}%`);
      }

      // 麥克風開關狀態
      if (typeof core.is_mic_enabled === 'boolean' && core.is_mic_enabled !== this.isMicEnabled) {
        this.updateMicUI(core.is_mic_enabled);
      }

      // 模型名稱
      if (core.model_name) {
        safeSetText(this.monModelName, core.model_name);
        safeSetText(this.topModelBadge, core.model_name.split(' ')[0] + ' ' + (core.model_name.split(' ')[1] || ''));
      }

      // 視覺感知文字情報
      if (this.visionScene && this.visionChange) {
        if (this.isSleeping) {
          safeSetText(this.visionScene, '休眠中');
          safeSetText(this.visionChange, 'none (0%)');
          if (this.visionHistory.length === 0) {
            this.addVisionHistoryEntry({ text: '7L 正在休眠中，已暫停畫面視覺掃描以節省額度。', time_str: '休眠', scene: '休眠中' });
          }
        } else {
          // 支援後端完整時序視覺感知歷史 (vision_history)
          if (Array.isArray(core.vision_history) && core.vision_history.length > 0) {
            let hasNewVision = false;
            core.vision_history.forEach(item => {
              if (item && item.text) {
                const exists = this.visionHistory.some(v => v.text === item.text);
                if (!exists) {
                  this.visionHistory.push(item);
                  hasNewVision = true;
                }
              }
            });
            if (hasNewVision) {
              if (this.visionHistory.length > 60) {
                this.visionHistory = this.visionHistory.slice(-60);
              }
              this.renderVisionHistory();
            }
          } else if (core.screen_context && core.screen_context !== '目前沒有特別的畫面動態。') {
            const lastTimeStr = core.last_vision_time ? (new Date(core.last_vision_time * 1000)).toTimeString().split(' ')[0] : '即時';
            this.addVisionHistoryEntry({
              text: core.screen_context,
              time_str: lastTimeStr,
              scene: '畫面動態'
            });
          }

          if (core.screen_context) {
            if (core.screen_context.includes('YouTube') || core.screen_context.includes('影片') || core.screen_context.includes('video')) {
              safeSetText(this.visionScene, '觀賞影片');
            } else if (core.screen_context.includes('鋼琴') || core.screen_context.includes('音樂') || core.screen_context.includes('Campanella') || core.screen_context.includes('piano')) {
              safeSetText(this.visionScene, '音樂/鋼琴');
            } else if (core.screen_context.includes('程式碼') || core.screen_context.includes('Code') || core.screen_context.includes('VS Code') || core.screen_context.includes('Python')) {
              safeSetText(this.visionScene, '編寫程式');
            } else if (core.screen_context.includes('網頁') || core.screen_context.includes('瀏覽器')) {
              safeSetText(this.visionScene, '瀏覽網頁');
            } else if (core.screen_context.includes('桌面')) {
              safeSetText(this.visionScene, '電腦桌面');
            } else {
              safeSetText(this.visionScene, '螢幕動態');
            }

            const vChange = core.vision_change || 'low';
            const vScore = core.vision_change_score !== undefined ? core.vision_change_score : (vChange === 'high' ? 80 : (vChange === 'med' ? 35 : (vChange === 'low' ? 15 : 0)));
            safeSetText(this.visionChange, `${vChange} (${vScore}%)`);
          }
        }
      }

      // 視覺截圖：只有在時間戳真正更新時才預載入新圖
      if (core.last_vision_time && core.last_vision_time > 0) {
        if (this.lastVisionTimestamp !== core.last_vision_time) {
          this.lastVisionTimestamp = core.last_vision_time;
          this.triggerVisionImageReload(false);
        }
      }

      if (core.vts_expression && this.monVtsExpression) {
        safeSetText(this.monVtsExpression, `目前：${core.vts_expression}`);
        if (core.vts_expression === '自然' || core.vts_expression === '預設') {
          this.activeExpression = null;
          this.exprChips.forEach(c => c.classList.remove('active'));
        }
      }

      // 🎧 聲音感知中樞即時動態更新 (電腦 WASAPI Loopback & 現實環境人聲)
      const audio = core.audio_perception || {};
      const isSleeping = this.isSleeping;

      if (this.valAudioGeneralStatus) {
        if (isSleeping) {
          safeSetText(this.valAudioGeneralStatus, '休眠暫停');
        } else if (audio.status_text) {
          safeSetText(this.valAudioGeneralStatus, audio.status_text);
        } else {
          safeSetText(this.valAudioGeneralStatus, '雙向監聽中');
        }
      }

      // 電腦聲音 (WASAPI Loopback)
      if (this.valSysAudioTag && this.valSysAudioDetail && this.meterSysAudio) {
        if (isSleeping) {
          safeSetText(this.valSysAudioTag, '休眠靜音');
          safeSetText(this.valSysAudioDetail, '休眠中未主動監聽電腦聲音。');
          safeSetWidth(this.meterSysAudio, '0%');
        } else {
          const sysTag = audio.sys_tag || (core.audio_context && core.audio_context !== '目前沒有播放特別的聲音。' ? '播放中' : '安靜無聲');
          const sysDetail = audio.sys_detail || core.audio_context || '目前沒有播放特別的聲音。';
          const sysLevel = audio.sys_level !== undefined ? Math.min(100, Math.max(0, audio.sys_level)) : 0;

          safeSetText(this.valSysAudioTag, sysTag);
          safeSetText(this.valSysAudioDetail, sysDetail);
          safeSetWidth(this.meterSysAudio, `${sysLevel}%`);
        }
      }

      // 現實環境聲音 (Microphone)
      if (this.valRealAudioTag && this.valRealAudioDetail && this.meterRealAudio) {
        if (isSleeping || !this.isMicEnabled) {
          safeSetText(this.valRealAudioTag, isSleeping ? '休眠暫停' : '麥克風靜音');
          safeSetText(this.valRealAudioDetail, isSleeping ? '7L 正在睡覺，暫停接收現實人聲。' : '麥克風目前已手動關閉。');
          safeSetWidth(this.meterRealAudio, '0%');
        } else {
          const micVol = (core.mic_volume !== undefined ? core.mic_volume : (audio.real_level ? audio.real_level / 100 : 0));
          const realLevel = audio.real_level !== undefined ? Math.min(100, Math.max(0, audio.real_level)) : Math.min(100, Math.round(micVol * 100));
          const realTag = audio.real_tag || (realLevel > 15 ? '捕捉到聲音' : '靈敏傾聽中');
          const realDetail = audio.real_detail || (audio.user_speaking ? `老爸正在說話：『${audio.user_speaking}』` : '現實環境安靜，等待老爸說話中...');

          safeSetText(this.valRealAudioTag, realTag);
          safeSetText(this.valRealAudioDetail, realDetail);
          safeSetWidth(this.meterRealAudio, `${realLevel}%`);
        }
      }
    }

    // 2. TikTok 直播情報
    if (data.tiktok) {
      const tk = data.tiktok;
      const isLive = tk.is_streaming;

      if (this.monTkBadge && this.footTiktok) {
        if (isLive) {
          safeSetText(this.monTkBadge, `直播中 (${tk.active_id || ''})`);
          safeSetClass(this.monTkBadge, 'status-tag');
          safeSetText(this.footTiktok, `${tk.active_id || '直播中'} (${tk.viewer_count || 0}人)`);
        } else {
          safeSetText(this.monTkBadge, '離線巡檢中');
          safeSetClass(this.monTkBadge, 'status-tag tag-offline');
          safeSetText(this.footTiktok, '雙帳號巡檢中 (@e5alr9qub2, @e_7l_9)');
        }
      }

      safeSetText(this.monViewerCount, (tk.viewer_count || 0).toLocaleString());
      safeSetText(this.monLikeCount, (tk.like_count || 0).toLocaleString());
      if (this.monTkTelemetry && tk.telemetry_text) {
        safeSetText(this.monTkTelemetry, tk.telemetry_text);
      }
    }

    // 3. 7L 思維黑板
    if (data.mind_board && Array.isArray(data.mind_board) && data.mind_board.length > 0 && this.monMindBoard) {
      const latest = data.mind_board[data.mind_board.length - 1];
      const thoughtText = typeof latest === 'object' ? (latest.content || latest.text || JSON.stringify(latest)) : String(latest);
      safeSetText(this.monMindBoard, thoughtText);
    }
  }

  addVisionHistoryEntry(entry, shouldRender = true) {
    if (!entry || !entry.text) return;
    const cleanText = entry.text.trim();
    if (!cleanText || cleanText === '目前沒有特別的畫面動態。') return;

    // 避免與最新一筆相鄰重複
    if (this.visionHistory.length > 0) {
      const last = this.visionHistory[this.visionHistory.length - 1];
      if (last.text === cleanText) return;
    }

    // 避免歷史中完全相同文字且時間相近
    const existsRecent = this.visionHistory.slice(-4).some(v => v.text === cleanText);
    if (existsRecent) return;

    const nowStr = entry.time_str || (new Date()).toTimeString().split(' ')[0];
    const scene = entry.scene || '畫面感知';
    const newEntry = {
      text: cleanText,
      time_str: nowStr,
      scene: scene
    };

    this.visionHistory.push(newEntry);

    if (this.visionHistory.length > 60) {
      this.visionHistory.shift();
    }

    if (shouldRender) {
      this.appendVisionHistoryItem(newEntry);
    }
  }

  // 🚀 高性能增量掛載：不再摧毀重建 60 個節點，直接 O(1) 增量 Append
  appendVisionHistoryItem(item) {
    if (!this.visionDescription) return;
    const wasAtBottom = !this.isUserScrollingVision;

    const prevFocus = this.visionDescription.querySelector('.vision-history-item.current-focus');
    if (prevFocus) prevFocus.classList.remove('current-focus');

    const row = document.createElement('div');
    row.className = 'vision-history-item current-focus';

    const meta = document.createElement('div');
    meta.className = 'item-meta font-mono';
    meta.innerHTML = `
      <span class="item-time">${this.escapeHtml(item.time_str || '')}</span>
      <span class="item-badge">${this.escapeHtml(item.scene || '最新感知')}</span>
    `;

    const cnt = document.createElement('div');
    cnt.className = 'item-content';
    cnt.textContent = item.text;

    row.appendChild(meta);
    row.appendChild(cnt);
    this.visionDescription.appendChild(row);

    while (this.visionDescription.children.length > 60) {
      this.visionDescription.removeChild(this.visionDescription.firstElementChild);
    }

    if (this.visionHistoryCount) {
      safeSetText(this.visionHistoryCount, `${this.visionHistory.length} 筆感知紀錄`);
    }

    if (wasAtBottom) {
      this.visionDescription.scrollTop = this.visionDescription.scrollHeight;
    }
  }

  renderVisionHistory() {
    if (!this.visionDescription) return;
    if (this.visionHistory.length === 0) return;

    // 判斷當前使用者是否在底部 (如果在底部才自動下滾，若使用者往上滑看歷史，絕不強行拉下打擾！)
    const wasAtBottom = !this.isUserScrollingVision;

    const frag = document.createDocumentFragment();
    this.visionHistory.forEach((item, idx) => {
      const isLatest = idx === this.visionHistory.length - 1;
      const row = document.createElement('div');
      row.className = `vision-history-item ${isLatest ? 'current-focus' : ''}`;

      const meta = document.createElement('div');
      meta.className = 'item-meta font-mono';
      meta.innerHTML = `
        <span class="item-time">${this.escapeHtml(item.time_str || '')}</span>
        <span class="item-badge">${isLatest ? '最新感知' : this.escapeHtml(item.scene || '畫面動態')}</span>
      `;

      const cnt = document.createElement('div');
      cnt.className = 'item-content';
      cnt.textContent = item.text;

      row.appendChild(meta);
      row.appendChild(cnt);
      frag.appendChild(row);
    });

    this.visionDescription.innerHTML = '';
    this.visionDescription.appendChild(frag);

    if (this.visionHistoryCount) {
      safeSetText(this.visionHistoryCount, `${this.visionHistory.length} 筆感知紀錄`);
    }

    if (wasAtBottom) {
      this.visionDescription.scrollTop = this.visionDescription.scrollHeight;
    }
  }

  // ──────────────────────────────────────────────
  // 🧠 DeepSeek 即時心流思考串流方法群 (不間斷連續流淌・逐字打字機)
  // ──────────────────────────────────────────────

  startThinkingStream(timeStr) {
    if (!this.deepseekThinkingBox) return;
    this.isStreamingThought = true;
    if (!this.currentThinkingStartTime) {
      this.currentThinkingStartTime = Date.now();
    }
    if (this.deepseekThinkingBox) {
      this.deepseekThinkingBox.classList.add('is-thinking');
    }
    if (this.thinkingCursor) {
      this.thinkingCursor.style.display = 'inline-block';
    }
    if (this.thinkingStatusLabel) {
      safeSetText(this.thinkingStatusLabel, '● 深度思緒持續推導中...');
    }

    // 若原本有初始佔位提示文字，準備在新字元進入時清除
    if (this.thinkingStreamText) {
      const cur = this.thinkingStreamText.textContent.trim();
      if (cur.startsWith('正在連接 7L 潛意識腦神經元')) {
        this.thinkingStreamText.textContent = '';
      } else if (cur.length > 0 && !cur.endsWith('\n\n')) {
        // 段與段之間不分卡片，以雙換行無縫自然接續
        this.typewriterQueue.push('\n\n');
        this.processTypewriterQueue();
      }
    }

    // 思考總計時器（持續計時）
    if (!this.thinkingTimerInterval) {
      this.thinkingTimerInterval = setInterval(() => {
        const secs = ((Date.now() - this.currentThinkingStartTime) / 1000).toFixed(1);
        if (this.thinkingTimerPill) safeSetText(this.thinkingTimerPill, `${secs}s`);
      }, 100);
    }
  }

  appendThinkingChunk(chunk) {
    if (!chunk) return;
    // 將 chunk 拆解為單一字元推入打字機佇列，實現「一個字一個字」流暢顯示
    for (const char of chunk) {
      this.typewriterQueue.push(char);
    }
    this.processTypewriterQueue();
  }

  processTypewriterQueue() {
    if (this.isTypewriting) return;
    this.isTypewriting = true;

    const typeStep = () => {
      if (!this.typewriterQueue || this.typewriterQueue.length === 0) {
        this.isTypewriting = false;
        return;
      }

      // 若積壓較多（> 30 字元），每次彈出 2~3 字以防延遲堆積；平常 1 字 1 字敲擊
      const charsToTake = this.typewriterQueue.length > 50 ? 4 : (this.typewriterQueue.length > 20 ? 2 : 1);
      const chars = this.typewriterQueue.splice(0, charsToTake).join('');

      if (this.thinkingStreamText) {
        // 首次輸入時清除佔位符
        if (this.thinkingStreamText.textContent.startsWith('正在連接 7L 潛意識腦神經元')) {
          this.thinkingStreamText.textContent = '';
        }
        this.thinkingStreamText.textContent += chars;

        // 長度防爆安全保護（超過 25,000 字元平滑裁剪前端）
        if (this.thinkingStreamText.textContent.length > 25000) {
          this.thinkingStreamText.textContent = this.thinkingStreamText.textContent.slice(-20000);
        }
      }

      // 更新底部 CURRENT MIND
      if (this.mindLatestText && this.thinkingStreamText) {
        const raw = this.thinkingStreamText.textContent.trim();
        const snippet = raw.slice(-50).replace(/\n+/g, ' ');
        safeSetText(this.mindLatestText, snippet || '沉浸式連續思考中...');
      }

      // 平滑向下滾動跟隨打字游標
      if (this.isMindPinAutoScroll) {
        if (this.mindStreamScroll) {
          this.mindStreamScroll.scrollTop = this.mindStreamScroll.scrollHeight;
        }
        if (this.thinkingContentBody) {
          this.thinkingContentBody.scrollTop = this.thinkingContentBody.scrollHeight;
        }
      }

      // 每隔 20~26ms 打出一個字元，呈現 DeepSeek 思考手感
      setTimeout(typeStep, 22);
    };

    typeStep();
  }

  endThinkingStream(thought, duration, timeStr) {
    this.isStreamingThought = false;
    // 不清除文字！不切出卡片！游標依然保持發光閃爍，直接等待下一段無縫接續
    if (this.thinkingCursor) {
      this.thinkingCursor.style.display = 'inline-block';
    }
    if (this.thinkingStatusLabel) {
      safeSetText(this.thinkingStatusLabel, '● 思緒流淌・持續連貫中');
    }
    if (this.deepseekThinkingBox) {
      this.deepseekThinkingBox.classList.add('is-thinking');
    }
  }

  appendMindThought(text, timeStr, label, autoScroll) {
    if (!text) return;
    const cur = this.thinkingStreamText ? this.thinkingStreamText.textContent : '';
    if (cur.slice(-300).includes(text.trim())) return;
    this.appendThinkingChunk('\n\n' + text);
  }

  addThoughtToHistory(text, timeStr, label) {
    // 🛡️ 歷史方法安全防禦：絕不將歷史紀錄推入打字機佇列，避免打開網頁時重跑高速刷屏
  }

  toggleMindDrawer() {
    if (!this.mindStreamPanel) return;
    this.isMindDrawerCollapsed = !this.isMindDrawerCollapsed;
    this.mindStreamPanel.classList.toggle('collapsed', this.isMindDrawerCollapsed);
    if (this.mindTabArrow) {
      this.mindTabArrow.textContent = this.isMindDrawerCollapsed ? '▶' : '◀';
    }
    if (this.mindSplitResizer) {
      this.mindSplitResizer.classList.toggle('drawer-collapsed', this.isMindDrawerCollapsed);
    }
  }

  appendChatBubble(role, textOrUser, textOrAuto, autoScroll = true, isHistoryRead = false, targetContainer = null, modelName = '') {
    // 🧠 徹底禁止將「7L 內心流動」思緒渲染至右側對話框，專注留存於左側「即時心流」面板與底部心流條
    if (role === 'thought') return;

    const container = targetContainer || this.chatStream;
    if (!container) return;

    // 參數處理 (向下相容)
    let user = '', text = '', actualAutoScroll = true, historyRead = false;
    if (role === 'tiktok') {
      // tiktok: (role, user, text, autoScroll, isHistoryRead)
      user = textOrUser || '';
      text = typeof textOrAuto === 'string' ? textOrAuto : '';
      actualAutoScroll = typeof autoScroll === 'boolean' ? autoScroll : true;
      historyRead = isHistoryRead;
    } else {
      // 其他: (role, text, autoScroll)
      text = textOrUser || '';
      actualAutoScroll = typeof textOrAuto === 'boolean' ? textOrAuto : (typeof autoScroll === 'boolean' ? autoScroll : true);
    }

    const row = document.createElement('div');
    // 🔄 ai/thought 靠左, system 置中, user/tiktok 靠右
    const rowClass = role === 'ai' || role === 'thought' ? 'bubble-ai' : (role === 'system' ? 'bubble-system' : 'bubble-user');
    row.className = `bubble-row ${rowClass}${actualAutoScroll ? ' new-entry' : ''}`;

    const content = document.createElement('div');
    if (role === 'ai') {
      content.className = 'bubble-content bubble-purple';
      const textSpan = document.createElement('span');
      textSpan.textContent = text;
      content.appendChild(textSpan);
      
      let cleanModel = (modelName || '').trim();
      cleanModel = cleanModel.replace(/^gemini-/, '').replace(/^groq\//, '');
      if (!cleanModel) {
        if (this.monModelName && this.monModelName.textContent) {
          cleanModel = this.monModelName.textContent.replace(/^Gemini\s*/i, '').replace(/^gemini-/, '').replace(/^groq\//, '').trim();
        } else if (this.topModelBadge && this.topModelBadge.textContent) {
          cleanModel = this.topModelBadge.textContent.replace(/^Gemini\s*/i, '').replace(/^gemini-/, '').replace(/^groq\//, '').trim();
        }
      }
      cleanModel = cleanModel || '3.8-flash';
      const modelTag = document.createElement('span');
      modelTag.className = 'bubble-model-tag';
      modelTag.textContent = cleanModel;
      content.appendChild(modelTag);
    } else if (role === 'thought') {
      content.className = 'bubble-content bubble-thought';
      content.innerHTML = `
        <div class="bubble-speaker-tag">[7L 內心流動]</div>
        <div>${this.escapeHtml(text)}</div>
      `;
    } else if (role === 'tiktok') {
      content.className = 'bubble-content bubble-tiktok';
      // 📭 未讀/已讀徽章
      const readBadge = document.createElement('span');
      readBadge.className = historyRead ? 'tiktok-read-badge read' : 'tiktok-read-badge unread';
      readBadge.textContent = historyRead ? '✓✓ 已讀' : '● 未讀';
      content.innerHTML = `
        <div class="bubble-speaker-tag tiktok-tag">🔴 直播留言 · <span class="tiktok-user">${this.escapeHtml(user)}</span></div>
        <div class="tiktok-msg-text">${this.escapeHtml(text)}</div>
      `;
      content.appendChild(readBadge);
      if (!historyRead) {
        this._pendingTiktokBubbles.push(readBadge);
      }
    } else if (role === 'system') {
      content.className = 'bubble-content bubble-system-notice';
      const icon = (text && (text.includes('鋼琴') || text.includes('演奏') || text.includes('曲目'))) ? '🎹' : '⚙️';
      content.innerHTML = `<span class="system-icon">${icon}</span> <span class="system-text">${this.escapeHtml(text)}</span>`;
    } else {
      content.className = 'bubble-content bubble-dark';
      content.textContent = text;
    }

    row.appendChild(content);
    container.appendChild(row);

    if (actualAutoScroll && container === this.chatStream) {
      this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }
  }

  // 🟢 把所有未讀的 TikTok 留言標記為已讀
  _markTiktokCommentsRead() {
    if (!this._pendingTiktokBubbles || this._pendingTiktokBubbles.length === 0) return;
    this._pendingTiktokBubbles.forEach(badge => {
      badge.textContent = '✓✓ 已讀';
      badge.className = 'tiktok-read-badge read';
    });
    this._pendingTiktokBubbles = [];
  }

  async sendMessage(text) {
    if (!text || !text.trim()) return;
    const cleanText = text.trim();

    // 🚀 立即樂觀渲染老爸發言氣泡 (100% 保證點擊/Enter 當下立即有反饋，絕不因網路延遲讓使用者以為沒反應)
    this.appendChatBubble('user', cleanText);
    this.silenceTicks = 0;
    safeSetText(this.valSilence, '0 tick (剛剛)');

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({
          action: 'send_chat',
          text: cleanText
        }));
      } catch (err) {
        console.warn('WS send failed, fallback to HTTP:', err);
        await this.sendChatMessageHttp(cleanText);
      }
    } else {
      // WebSocket 尚未就緒或重連中，走 HTTP API 保底通道
      await this.sendChatMessageHttp(cleanText);
      // 順便嘗試觸發重連
      if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
        this.connectWebSocket();
      }
    }
  }

  async sendChatMessageHttp(text) {
    try {
      const resp = await fetch('/api/send_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text })
      });
      const res = await resp.json();
      if (!res.ok) {
        this.showToast(`⚠️ 發送失敗: ${res.error || '後端佇列異常'}`);
      }
    } catch (err) {
      console.error('HTTP send_message error:', err);
      this.showToast('❌ 無法連線至 7L 後端，請確認主程式是否在運行');
    }
  }

  setSleepMode(enable) {
    this.updateSleepUI(enable);
    if (enable) {
      this.appendLog('7L 進入休眠模式：停止視覺感知與大腦自主運算 (0 API 額度消耗)', 'line-warn');
    } else {
      this.appendLog('7L 已喚醒，神經系統與視覺感知全速恢復', 'line-success');
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'set_sleep',
        enable: enable
      }));
    } else {
      fetch('/api/set_sleep', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: enable })
      });
    }
  }

  async shutdownSystem() {
    if (!confirm('老爸，確定要關閉 7L 系統並退出程式嗎？')) {
      return;
    }

    this.showToast('👋 7L 系統正在安全關機退出...', 4000);
    this.appendLog('[系統] 老爸觸發了關機指令，系統正在安全退出...', 'line-warn');

    if (this.topDot) {
      this.topDot.style.background = '#64748b';
      this.topDot.style.boxShadow = 'none';
    }
    if (this.topStatusText) {
      safeSetText(this.topStatusText, '已關機 (離線)');
    }

    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'shutdown' }));
      }
      await fetch('/api/shutdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
    } catch (e) {
      console.warn('Shutdown request dispatched:', e);
    }
  }

  async punish7L(reason = "老爸按下了微電流刺激", is_severe = false) {
    const title = is_severe ? '⚡⚡ 強力電擊' : '⚡ 微電刺激';
    this.showToast(`⚡ 正在對 7L 實施${title}...`, 3000);
    this.appendLog(`[${title}] 老爸按下了對 7L 的電擊：${reason}`, 'line-warn');
    try {
      const resp = await fetch('/api/action/punish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason, is_severe: is_severe })
      });
      const data = await resp.json();
      if (data.status === 'success') {
        const msg = is_severe ? '⚡⚡ 強烈電流竄過！7L 渾身發軟哭哭討饒！' : '⚡ 已成功微電 7L！全身酥麻臉紅中！';
        this.showToast(msg, 3500);
      } else {
        this.showToast(`⚠️ 電擊執行失敗: ${data.error || data.message}`, 4000);
      }
    } catch (e) {
      console.error('Punish request error:', e);
      this.showToast(`❌ 懲罰連線異常: ${e.message}`, 4000);
    }
  }

  async reward7L(reason = "表現優異 / 乖巧聽話", level = 1) {
    const levelName = level === 3 ? '終極深情擁抱 (Lv.3)' : (level === 2 ? '熱情揉頭大獎 (Lv.2)' : '溫柔摸頭獎勵 (Lv.1)');
    this.showToast(`💖 正在給予 7L ${levelName}...`, 3000);
    this.appendLog(`[獎勵中樞] 老爸給予了 7L ${levelName}：${reason}`, 'line-success');
    try {
      const resp = await fetch('/api/action/reward', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason, level: level })
      });
      const data = await resp.json();
      if (data.status === 'success') {
        this.showToast(`💖 已成功給予 7L ${levelName}！好感度爆表！`, 3500);
      } else {
        this.showToast(`⚠️ 獎勵執行失敗: ${data.error || data.message}`, 4000);
      }
    } catch (e) {
      console.error('Reward request error:', e);
      this.showToast(`❌ 獎勵連線異常: ${e.message}`, 4000);
    }
  }

  async restartSystem() {
    if (!confirm('老爸，確定要重新啟動 7L 系統嗎？')) {
      return;
    }

    this.showToast('🔄 7L 系統正在重新啟動中，請稍候...', 5000);
    this.appendLog('[系統] 老爸觸發了重啟指令，系統正在重新載入...', 'line-warn');

    if (this.topDot) {
      this.topDot.style.background = '#f59e0b';
      this.topDot.style.boxShadow = '0 0 10px rgba(245, 158, 11, 0.6)';
    }
    if (this.topStatusText) {
      safeSetText(this.topStatusText, '重啟中...');
    }

    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'restart' }));
      }
      await fetch('/api/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
    } catch (e) {
      console.warn('Restart request dispatched:', e);
    }
  }

  updateSleepUI(isSleeping) {
    this.isSleeping = isSleeping;
    const btnSleep = document.getElementById('btnChipSleep');
    const btnWake = document.getElementById('btnChipWake');

    if (isSleeping) {
      if (btnSleep) btnSleep.classList.add('active');
      if (btnWake) btnWake.classList.remove('active');
      safeSetText(this.valMode, 'sleep');
      if (this.valSleepStatus) {
        safeSetText(this.valSleepStatus, '休眠中 (0 API)');
        safeSetClass(this.valSleepStatus, 'status-tag tag-sleeping');
      }
      safeSetText(this.topStatusText, '休眠中');
      if (this.topDot) {
        this.topDot.style.background = '#8b5cf6';
        this.topDot.style.boxShadow = '0 0 10px rgba(139, 92, 246, 0.6)';
      }
      if (this.visionImgFallback) {
        this.visionImgFallback.style.display = 'flex';
        const txt = this.visionImgFallback.querySelector('.fallback-text');
        if (txt) safeSetText(txt, '休眠中 (已暫停畫面感知以節省額度)');
      }
      if (this.visionImgPreview) this.visionImgPreview.style.display = 'none';
      if (this.visionImgTimestamp) safeSetText(this.visionImgTimestamp, '休眠暫停');
    } else {
      if (btnSleep) btnSleep.classList.remove('active');
      if (btnWake) btnWake.classList.add('active');
      safeSetText(this.valMode, 'idle');
      if (this.valSleepStatus) {
        safeSetText(this.valSleepStatus, '全速運作');
        safeSetClass(this.valSleepStatus, 'status-tag');
      }
      safeSetText(this.topStatusText, '正常運作');
      if (this.topDot) {
        this.topDot.style.background = '#10b981';
        this.topDot.style.boxShadow = '0 0 10px rgba(16, 185, 129, 0.6)';
      }
      this.triggerVisionImageReload(true);
    }
  }

  toggleMic() {
    this.setMicMode(!this.isMicEnabled);
  }

  setMicMode(enable) {
    this.updateMicUI(enable);

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'toggle_mic',
        enable: enable
      }));
    } else {
      fetch('/api/toggle_mic', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: enable })
      });
    }
    this.showToast(enable ? '🎙️ 麥克風已開啟收音' : '🔇 麥克風已關閉靜音');
  }

  updateMicUI(enabled) {
    this.isMicEnabled = enabled;
    const btnMicOn = document.getElementById('btnChipMicOn');
    const btnMicOff = document.getElementById('btnChipMicOff');
    if (btnMicOn) {
      if (enabled) btnMicOn.classList.add('active');
      else btnMicOn.classList.remove('active');
    }
    if (btnMicOff) {
      if (!enabled) btnMicOff.classList.add('active');
      else btnMicOff.classList.remove('active');
    }

    if (!this.btnToggleMic || !this.monMicStatus) return;
    if (enabled) {
      safeSetClass(this.btnToggleMic, 'glass-btn-toggle');
      safeSetText(this.btnToggleMic, '收音中');
      safeSetText(this.monMicStatus, '開啟收音中');
    } else {
      safeSetClass(this.btnToggleMic, 'glass-btn-toggle muted');
      safeSetText(this.btnToggleMic, '已靜音');
      safeSetText(this.monMicStatus, '麥克風已關閉');
    }
  }

  triggerExpression(expr) {
    if (this.monVtsExpression) {
      if (expr === '_RESET_') {
        safeSetText(this.monVtsExpression, '目前：自然');
      } else {
        const chip = Array.from(this.exprChips).find(c => c.dataset.expr === expr);
        const name = chip ? chip.childNodes[0].textContent.trim() : expr;
        safeSetText(this.monVtsExpression, `目前：${name}`);
      }
    }
    this.appendLog(`[表情指令] 切換 Live2D 表情: ${expr}`, 'line-info');

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'set_expression',
        expression: expr
      }));
    } else {
      fetch('/api/trigger_expression', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expression: expr })
      });
    }
  }

  appendLog(msg, level = 'line-info') {
    if (!this.terminalLogs) return;
    const line = document.createElement('div');
    line.className = `term-line ${level}`;
    const timeStr = new Date().toLocaleTimeString('zh-TW', { hour12: false });
    line.textContent = `[${timeStr}] ${msg}`;
    this.terminalLogs.appendChild(line);
    this.terminalLogs.scrollTop = this.terminalLogs.scrollHeight;
  }

  // ==========================================================================
  // 🧠 提示詞庫 (Prompt Hub & Cloud Knowledge) 操作與同步邏輯
  // ==========================================================================
  showToast(text, duration = 3000) {
    if (!this.glassToast) return;
    this.glassToast.textContent = text;
    this.glassToast.classList.add('active');
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      this.glassToast.classList.remove('active');
    }, duration);
  }

  // 🎬 伴看授權通知卡（帶按鈕，固定在右下角）
  showCompanionApprovalToast(data) {
    // 如已存在則先移除
    this.hideCompanionApprovalToast();

    const title = (data && data.short_title) ? data.short_title : '影片視窗';
    const card = document.createElement('div');
    card.id = 'companionApprovalToast';
    card.className = 'companion-approval-toast';
    card.innerHTML = `
      <div class="cat-icon">🎬</div>
      <div class="cat-body">
        <div class="cat-title">偵測到影片視窗</div>
        <div class="cat-desc">《${title}》<br>是否允許 7L 啟動伴看感官串流？</div>
        <div class="cat-actions">
          <button class="cat-btn cat-allow" id="btnCompanionAllow">✅ 允許</button>
          <button class="cat-btn cat-deny" id="btnCompanionDeny">❌ 拒絕</button>
        </div>
      </div>
      <div class="cat-progress-track">
        <div class="cat-progress-bar" id="companionProgressBar"></div>
      </div>
    `;
    document.body.appendChild(card);

    // 動畫進場與進度條啟動
    requestAnimationFrame(() => {
      card.classList.add('active');
      const progressBar = card.querySelector('#companionProgressBar');
      if (progressBar) {
        progressBar.style.animation = 'cat-countdown 60s linear forwards';
      }
    });

    // 綁定按鈕事件
    const btnAllow = card.querySelector('#btnCompanionAllow');
    const btnDeny = card.querySelector('#btnCompanionDeny');
    if (btnAllow) {
      btnAllow.addEventListener('click', () => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: 'approve_yt_companion', title: title }));
        } else {
          fetch('/api/yt_companion/approve', { method: 'POST' }).catch(() => {});
        }
        this.hideCompanionApprovalToast();
      });
    }
    if (btnDeny) {
      btnDeny.addEventListener('click', () => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: 'reject_yt_companion', title: title }));
        } else {
          fetch('/api/yt_companion/reject', { method: 'POST' }).catch(() => {});
        }
        this.hideCompanionApprovalToast();
      });
    }

    // 60 秒後自動消失（與後端等待超時同步）
    this._companionToastTimeout = setTimeout(() => this.hideCompanionApprovalToast(), 62000);
  }

  hideCompanionApprovalToast() {
    if (this._companionToastTimeout) {
      clearTimeout(this._companionToastTimeout);
      this._companionToastTimeout = null;
    }
    const card = document.getElementById('companionApprovalToast');
    if (card) {
      card.classList.remove('active');
      setTimeout(() => { if (card.parentNode) card.parentNode.removeChild(card); }, 350);
    }
  }



  async loadPrompts() {
    if (this.promptSyncDot) this.promptSyncDot.classList.add('syncing');
    safeSetText(this.promptSyncStatus, '讀取雲端中...');

    try {
      const resp = await fetch('/api/prompts');
      const res = await resp.json();
      if (res.ok && res.data) {
        this.cloudKnowledge = res.data;
        this.renderPromptsData(res.data);
        safeSetText(this.promptSyncStatus, '雲端已同步');
        if (res.data.last_updated) {
          safeSetText(this.promptSyncTime, res.data.last_updated.split(' ')[1] || res.data.last_updated);
        }
      } else {
        safeSetText(this.promptSyncStatus, '讀取失敗');
      }
    } catch (e) {
      console.error(e);
      safeSetText(this.promptSyncStatus, '連線異常');
    } finally {
      if (this.promptSyncDot) this.promptSyncDot.classList.remove('syncing');
    }
  }

  renderPromptsData(data) {
    if (!data) return;
    if (this.promptPersonaCore) this.promptPersonaCore.value = data.persona_core || '';
    if (this.promptConversationStyle) this.promptConversationStyle.value = data.conversation_style || '';
    if (this.promptStreamerBio) this.promptStreamerBio.value = data.streamer_bio || '';
    if (this.promptProactiveGuide) this.promptProactiveGuide.value = data.proactive_guide || '';
    
    // custom_rules (每行一條)
    if (this.promptCustomRules) {
      const rules = Array.isArray(data.custom_rules) ? data.custom_rules : [];
      this.promptCustomRules.value = rules.join('\n');
    }

    // learned_facts (每行一條)
    if (this.promptLearnedFacts) {
      const facts = Array.isArray(data.learned_facts) ? data.learned_facts : [];
      this.promptLearnedFacts.value = facts.join('\n');
    }

    // banned_phrases tags
    this.bannedPhrases = Array.isArray(data.banned_phrases) ? [...data.banned_phrases] : [];
    this.renderBannedTags();

    // memes_and_slang tags
    this.memesList = Array.isArray(data.memes_and_slang) ? [...data.memes_and_slang] : [];
    this.renderMemeTags();

    // few_shot_examples
    this.fewShotExamples = Array.isArray(data.few_shot_examples) ? JSON.parse(JSON.stringify(data.few_shot_examples)) : [];
    this.renderFewShotList();
  }

  renderBannedTags() {
    if (!this.bannedPhrasesList) return;
    this.bannedPhrasesList.innerHTML = '';
    this.bannedPhrases.forEach((phrase, idx) => {
      const pill = document.createElement('span');
      pill.className = 'tag-pill tag-banned';
      pill.innerHTML = `<span>${this.escapeHtml(phrase)}</span><button type="button" class="tag-remove" data-idx="${idx}">×</button>`;
      const btn = pill.querySelector('.tag-remove');
      btn.addEventListener('click', () => {
        this.bannedPhrases.splice(idx, 1);
        this.renderBannedTags();
      });
      this.bannedPhrasesList.appendChild(pill);
    });
  }

  addBannedPhrase(text) {
    const val = (text || '').trim();
    if (!val || this.bannedPhrases.includes(val)) return;
    this.bannedPhrases.push(val);
    this.renderBannedTags();
    if (this.inputNewBanned) this.inputNewBanned.value = '';
  }

  renderMemeTags() {
    if (!this.memesListEl) return;
    this.memesListEl.innerHTML = '';
    this.memesList.forEach((meme, idx) => {
      const pill = document.createElement('span');
      pill.className = 'tag-pill tag-meme';
      pill.innerHTML = `<span>${this.escapeHtml(meme)}</span><button type="button" class="tag-remove" data-idx="${idx}">×</button>`;
      const btn = pill.querySelector('.tag-remove');
      btn.addEventListener('click', () => {
        this.memesList.splice(idx, 1);
        this.renderMemeTags();
      });
      this.memesListEl.appendChild(pill);
    });
  }

  addMeme(text) {
    const val = (text || '').trim();
    if (!val || this.memesList.includes(val)) return;
    this.memesList.push(val);
    this.renderMemeTags();
    if (this.inputNewMeme) this.inputNewMeme.value = '';
  }

  renderFewShotList() {
    if (!this.fewShotList) return;
    this.fewShotList.innerHTML = '';
    if (this.fewShotExamples.length === 0) {
      this.fewShotList.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem;padding:8px 0;">目前無自訂示範，點擊上方按鈕新增。</div>';
      return;
    }

    this.fewShotExamples.forEach((ex, idx) => {
      const item = document.createElement('div');
      item.className = 'few-shot-item';
      item.innerHTML = `
        <div class="few-shot-item-head">
          <div style="display:flex;align-items:center;gap:6px;">
            <span style="font-size:0.75rem;color:var(--text-muted);">示範 #${idx+1}</span>
            <input type="text" class="few-shot-scenario-input" value="${this.escapeHtml(ex.scenario || '日常')}" placeholder="情境" data-field="scenario" data-idx="${idx}" />
          </div>
          <button type="button" class="btn-delete-fewshot" data-idx="${idx}">✕ 刪除</button>
        </div>
        <div class="few-shot-row">
          <label>對方輸入 (Input)：</label>
          <input type="text" value="${this.escapeHtml(ex.input || '')}" placeholder="老爸/觀眾說的話" data-field="input" data-idx="${idx}" />
        </div>
        <div class="few-shot-row">
          <label>腦內心想 (Thought)：</label>
          <input type="text" value="${this.escapeHtml(ex.thought || '')}" placeholder="7L 大腦內心流動" data-field="thought" data-idx="${idx}" />
        </div>
        <div class="few-shot-row">
          <label>口語回覆 (Reply)：</label>
          <input type="text" value="${this.escapeHtml(ex.reply || '')}" placeholder="7L 開口說出的台詞" data-field="reply" data-idx="${idx}" />
        </div>
      `;

      item.querySelectorAll('input').forEach(inp => {
        inp.addEventListener('input', (e) => {
          const field = e.target.dataset.field;
          const i = parseInt(e.target.dataset.idx, 10);
          if (this.fewShotExamples[i]) {
            this.fewShotExamples[i][field] = e.target.value;
          }
        });
      });

      item.querySelector('.btn-delete-fewshot').addEventListener('click', () => {
        this.fewShotExamples.splice(idx, 1);
        this.renderFewShotList();
      });

      this.fewShotList.appendChild(item);
    });
  }

  addNewFewShot() {
    this.fewShotExamples.unshift({
      scenario: '日常',
      input: '',
      thought: '',
      reply: ''
    });
    this.renderFewShotList();
  }

  async savePrompts() {
    if (this.promptSyncDot) this.promptSyncDot.classList.add('syncing');
    safeSetText(this.promptSyncStatus, '同步雲端中...');

    // 收集所有欄位
    const rules = (this.promptCustomRules ? this.promptCustomRules.value : '')
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean);

    const facts = (this.promptLearnedFacts ? this.promptLearnedFacts.value : '')
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean);

    const payload = {
      persona_core: (this.promptPersonaCore ? this.promptPersonaCore.value : '').trim(),
      conversation_style: (this.promptConversationStyle ? this.promptConversationStyle.value : '').trim(),
      streamer_bio: (this.promptStreamerBio ? this.promptStreamerBio.value : '').trim(),
      proactive_guide: (this.promptProactiveGuide ? this.promptProactiveGuide.value : '').trim(),
      custom_rules: rules,
      banned_phrases: this.bannedPhrases,
      learned_facts: facts,
      memes_and_slang: this.memesList,
      few_shot_examples: this.fewShotExamples.filter(ex => ex.input || ex.reply),
      last_updated: new Date().toLocaleString('zh-TW', { hour12: false })
    };

    try {
      const resp = await fetch('/api/prompts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const res = await resp.json();
      if (res.ok) {
        safeSetText(this.promptSyncStatus, '雲端已同步');
        const now = new Date();
        safeSetText(this.promptSyncTime, now.toLocaleTimeString('zh-TW', { hour12: false }));
        this.showToast('✨ 雲端提示詞已成功同步至 Firestore 永久大腦！');
        this.appendLog('[提示詞] 雲端認知庫已成功更新並即時同步', 'line-success');
      } else {
        safeSetText(this.promptSyncStatus, '同步失敗');
        this.showToast(`❌ 同步失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      safeSetText(this.promptSyncStatus, '網路異常');
      this.showToast('❌ 無法連線至伺服器');
    } finally {
      if (this.promptSyncDot) this.promptSyncDot.classList.remove('syncing');
    }
  }

  async resetPrompts() {
    if (!confirm('確定要將提示詞庫恢復為系統預設值嗎？此操作將覆蓋當前自訂設定。')) return;

    if (this.promptSyncDot) this.promptSyncDot.classList.add('syncing');
    safeSetText(this.promptSyncStatus, '重置中...');

    try {
      const resp = await fetch('/api/prompts/reset', { method: 'POST' });
      const res = await resp.json();
      if (res.ok && res.data) {
        this.renderPromptsData(res.data);
        safeSetText(this.promptSyncStatus, '已恢復預設');
        const now = new Date();
        safeSetText(this.promptSyncTime, now.toLocaleTimeString('zh-TW', { hour12: false }));
        this.showToast('↺ 已成功恢復為預設提示詞庫並同步至雲端！');
        this.appendLog('[提示詞] 已重置為出廠預設設定並同步', 'line-info');
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 重置失敗');
    } finally {
      if (this.promptSyncDot) this.promptSyncDot.classList.remove('syncing');
    }
  }

  // ========================================================
  // 🛠️ 工具調用中樞 (Tools Hub) 業務邏輯
  // ========================================================
  async loadTools() {
    try {
      const resp = await fetch('/api/tools');
      const data = await resp.json();
      if (data.ok && Array.isArray(data.tools)) {
        this.toolsCatalog = data.tools;
        if (this.toolsActiveCount) {
          safeSetText(this.toolsActiveCount, `${this.toolsCatalog.length} 個工具就緒`);
        }
        this.renderToolDropdown('all');
      }
    } catch (e) {
      console.warn('載入工具目錄異常:', e);
    }
  }

  async loadToolHistory() {
    try {
      const resp = await fetch('/api/tools/history');
      const data = await resp.json();
      if (data.ok && Array.isArray(data.history)) {
        this.toolHistory = data.history;
        this.renderToolHistoryList();
        this.updateToolStats();
      }
    } catch (e) {
      console.warn('載入工具歷史紀錄異常:', e);
    }
  }

  renderToolDropdown(category = 'all') {
    if (!this.toolSelect) return;
    const filtered = category === 'all'
      ? this.toolsCatalog
      : this.toolsCatalog.filter(t => t.category === category);

    this.toolSelect.innerHTML = '';
    filtered.forEach(tool => {
      const opt = document.createElement('option');
      opt.value = tool.name;
      opt.textContent = `[${tool.category_name || tool.category}] ${tool.label || tool.name} (${tool.name})`;
      this.toolSelect.appendChild(opt);
    });

    if (filtered.length > 0) {
      this.selectTool(filtered[0].name);
    } else {
      this.selectedTool = null;
      if (this.toolParamsContainer) {
        this.toolParamsContainer.innerHTML = '<div class="tool-empty-hint">此分類暫無可用工具</div>';
      }
    }
  }

  selectTool(toolName) {
    const tool = this.toolsCatalog.find(t => t.name === toolName);
    if (!tool) return;
    this.selectedTool = tool;

    if (this.toolSelectedName) safeSetText(this.toolSelectedName, tool.name);
    if (this.toolSelectedCat) safeSetText(this.toolSelectedCat, tool.category_name || tool.category);
    if (this.toolSelectedDesc) safeSetText(this.toolSelectedDesc, tool.description || '');

    this.renderToolParamInputs(tool);
    if (this.toolResultBox) this.toolResultBox.style.display = 'none';
  }

  renderToolParamInputs(tool) {
    if (!this.toolParamsContainer) return;
    this.toolParamsContainer.innerHTML = '';

    const params = tool.parameters || [];
    if (params.length === 0) {
      const emptyDiv = document.createElement('div');
      emptyDiv.className = 'tool-empty-hint';
      emptyDiv.style.padding = '14px 0';
      emptyDiv.textContent = '此工具無需任何參數即可直接執行。點擊下方按鈕立即調用！';
      this.toolParamsContainer.appendChild(emptyDiv);
      return;
    }

    params.forEach(p => {
      const group = document.createElement('div');
      group.className = 'param-group';

      const labelRow = document.createElement('div');
      labelRow.className = 'param-label-row';

      const lbl = document.createElement('label');
      lbl.className = 'param-label';
      lbl.textContent = `${p.label || p.name} ${p.required ? '*' : ''}`;

      const nameSpan = document.createElement('span');
      nameSpan.className = 'param-name font-mono';
      nameSpan.textContent = p.name;

      labelRow.appendChild(lbl);
      labelRow.appendChild(nameSpan);
      group.appendChild(labelRow);

      let inputEl;
      if (p.type === 'boolean') {
        inputEl = document.createElement('select');
        inputEl.className = 'glass-select font-mono';
        inputEl.name = p.name;
        inputEl.innerHTML = `
          <option value="true" ${p.default === true ? 'selected' : ''}>True (開啟)</option>
          <option value="false" ${p.default === false ? 'selected' : ''}>False (關閉)</option>
        `;
      } else if (p.type === 'select') {
        inputEl = document.createElement('select');
        inputEl.className = 'glass-select font-mono';
        inputEl.name = p.name;
        (p.options || []).forEach(opt => {
          const optEl = document.createElement('option');
          optEl.value = opt;
          optEl.textContent = opt;
          if (opt === p.default) optEl.selected = true;
          inputEl.appendChild(optEl);
        });
      } else if (p.type === 'number') {
        inputEl = document.createElement('input');
        inputEl.type = 'number';
        inputEl.className = 'glass-input font-mono';
        inputEl.name = p.name;
        inputEl.value = p.default !== undefined ? p.default : 0;
        if (p.min !== undefined) inputEl.min = p.min;
        if (p.max !== undefined) inputEl.max = p.max;
        if (p.step !== undefined) inputEl.step = p.step;
      } else if (p.type === 'textarea') {
        inputEl = document.createElement('textarea');
        inputEl.className = 'glass-textarea font-mono';
        inputEl.name = p.name;
        inputEl.rows = 4;
        inputEl.placeholder = p.placeholder || '';
        inputEl.value = p.default || '';
      } else {
        inputEl = document.createElement('input');
        inputEl.type = 'text';
        inputEl.className = 'glass-input font-mono';
        inputEl.name = p.name;
        inputEl.placeholder = p.placeholder || '';
        inputEl.value = p.default || '';
        if (p.required) inputEl.required = true;
      }

      group.appendChild(inputEl);

      // 快捷預設預設選項藥丸 (Presets)
      if (Array.isArray(p.presets) && p.presets.length > 0) {
        const presetsRow = document.createElement('div');
        presetsRow.className = 'param-presets-row';
        p.presets.forEach(presetVal => {
          const pill = document.createElement('button');
          pill.type = 'button';
          pill.className = 'preset-pill font-mono';
          pill.textContent = String(presetVal);
          pill.addEventListener('click', () => {
            inputEl.value = presetVal;
            inputEl.dispatchEvent(new Event('input'));
          });
          presetsRow.appendChild(pill);
        });
        group.appendChild(presetsRow);
      }

      this.toolParamsContainer.appendChild(group);
    });
  }

  async executeSelectedTool() {
    if (!this.selectedTool) return;
    if (!this.toolParamForm) return;

    const formData = new FormData(this.toolParamForm);
    const args = {};
    const params = this.selectedTool.parameters || [];

    params.forEach(p => {
      const val = formData.get(p.name);
      if (p.type === 'boolean') {
        args[p.name] = val === 'true';
      } else if (p.type === 'number') {
        args[p.name] = val !== null && val !== '' ? Number(val) : (p.default || 0);
      } else {
        args[p.name] = val !== null ? String(val).trim() : '';
      }
    });

    // 禁用按鈕顯示執行狀態
    if (this.btnExecuteTool) {
      this.btnExecuteTool.disabled = true;
      this.btnExecuteTool.innerHTML = '<span class="btn-sparkle">⏳</span><span>執行中...</span>';
    }

    try {
      const resp = await fetch('/api/tools/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool: this.selectedTool.name,
          args: args
        })
      });

      const res = await resp.json();

      if (this.toolResultBox) {
        this.toolResultBox.style.display = 'flex';
      }

      if (res.ok) {
        if (this.toolResultStatus) {
          safeSetText(this.toolResultStatus, 'SUCCESS');
          this.toolResultStatus.className = 'badge-status status-success';
        }
        if (this.toolResultDuration) {
          safeSetText(this.toolResultDuration, `${res.record ? res.record.duration_ms : 0}ms`);
        }
        if (this.toolResultContent) {
          const formatted = typeof res.result === 'object' 
            ? JSON.stringify(res.result, null, 2) 
            : String(res.result || '執行成功');
          safeSetText(this.toolResultContent, formatted);
        }

        if (res.record) {
          this.addToolCallRecord(res.record);
        }
        this.showToast(`⚡ ${this.selectedTool.label || this.selectedTool.name} 調用成功！`);
      } else {
        if (this.toolResultStatus) {
          safeSetText(this.toolResultStatus, 'ERROR');
          this.toolResultStatus.className = 'badge-status status-error';
        }
        if (this.toolResultDuration) {
          safeSetText(this.toolResultDuration, '0ms');
        }
        if (this.toolResultContent) {
          safeSetText(this.toolResultContent, `錯誤: ${res.error || '未知錯誤'}`);
        }
        if (res.record) {
          this.addToolCallRecord(res.record);
        }
        this.showToast(`❌ 工具執行失敗: ${res.error || '異常'}`);
      }
    } catch (e) {
      console.error(e);
      if (this.toolResultBox) this.toolResultBox.style.display = 'flex';
      if (this.toolResultStatus) {
        safeSetText(this.toolResultStatus, 'NETWORK ERROR');
        this.toolResultStatus.className = 'badge-status status-error';
      }
      if (this.toolResultContent) {
        safeSetText(this.toolResultContent, `網路或伺服器異常: ${e.message}`);
      }
      this.showToast('❌ 無法連線至工具執行伺服器');
    } finally {
      if (this.btnExecuteTool) {
        this.btnExecuteTool.disabled = false;
        this.btnExecuteTool.innerHTML = '<span class="btn-sparkle">⚡</span><span>立即執行調用</span>';
      }
    }
  }

  addToolCallRecord(record) {
    if (!record || !record.id) return;
    const existingIdx = this.toolHistory.findIndex(r => r.id === record.id);
    if (existingIdx >= 0) {
      this.toolHistory[existingIdx] = record;
    } else {
      this.toolHistory.unshift(record);
      if (this.toolHistory.length > 200) {
        this.toolHistory.pop();
      }
    }
    this.updateToolStats();
    this.renderToolHistoryList();
  }

  updateToolStats() {
    const total = this.toolHistory.length;
    const manual = this.toolHistory.filter(r => r.caller && r.caller.includes('老爸')).length;
    const auto = this.toolHistory.filter(r => r.caller && r.caller.includes('7L')).length;

    if (this.toolsTotalCalls) safeSetText(this.toolsTotalCalls, String(total));
    if (this.toolsManualCalls) safeSetText(this.toolsManualCalls, String(manual));
    if (this.toolsAutonomousCalls) safeSetText(this.toolsAutonomousCalls, String(auto));
  }

  renderToolHistoryList() {
    if (!this.toolHistoryList) return;

    let filtered = this.toolHistory;

    // 發起者過濾
    if (this.toolCallerFilter === 'dad') {
      filtered = filtered.filter(r => r.caller && r.caller.includes('老爸'));
    } else if (this.toolCallerFilter === '7l') {
      filtered = filtered.filter(r => r.caller && r.caller.includes('7L'));
    }

    // 關鍵字搜尋過濾
    if (this.toolSearchQuery) {
      const q = this.toolSearchQuery;
      filtered = filtered.filter(r => {
        const toolMatch = (r.tool || '').toLowerCase().includes(q);
        const callerMatch = (r.caller || '').toLowerCase().includes(q);
        const argsMatch = JSON.stringify(r.args || {}).toLowerCase().includes(q);
        const resMatch = String(r.result || '').toLowerCase().includes(q);
        const errMatch = (r.error || '').toLowerCase().includes(q);
        return toolMatch || callerMatch || argsMatch || resMatch || errMatch;
      });
    }

    if (filtered.length === 0) {
      this.toolHistoryList.innerHTML = '<div class="tool-empty-hint">無匹配的工具調用紀錄</div>';
      return;
    }

    this.toolHistoryList.innerHTML = '';
    filtered.forEach(record => {
      const card = document.createElement('div');
      const isDad = record.caller && record.caller.includes('老爸');
      card.className = `tool-history-item ${isDad ? 'caller-dad' : 'caller-7l'}`;

      const argsStr = record.args && Object.keys(record.args).length > 0
        ? JSON.stringify(record.args, null, 2)
        : '{}';

      const isErr = record.status === 'error';
      const statusTagClass = isErr ? 'badge-status status-error' : 'badge-status status-success';
      const statusText = isErr ? 'FAILED' : 'SUCCESS';

      card.innerHTML = `
        <div class="item-top">
          <div class="item-badges">
            <span class="item-caller-badge ${isDad ? 'dad' : 'ai'}">${this.escapeHtml(record.caller || '未知')}</span>
            <span class="item-tool-name font-mono">${this.escapeHtml(record.tool || 'function')}</span>
            <span class="${statusTagClass}">${statusText}</span>
          </div>
          <div class="item-time-meta font-mono">
            <span class="item-time">${record.time_str || ''}</span>
            <span class="item-duration">${record.duration_ms ? record.duration_ms + 'ms' : ''}</span>
          </div>
        </div>
        <div class="item-args-block font-mono">${this.escapeHtml(argsStr)}</div>
        <div class="item-result-block ${isErr ? 'has-error' : ''}">
          <span class="res-label font-mono">回傳:</span>
          <span class="res-val font-mono">${this.escapeHtml(record.error || (typeof record.result === 'object' ? JSON.stringify(record.result) : String(record.result || '已完成')))}</span>
        </div>
      `;

      this.toolHistoryList.appendChild(card);
    });
  }

  async clearToolHistory() {
    try {
      await fetch('/api/tools/clear_history', { method: 'POST' });
      this.toolHistory = [];
      this.updateToolStats();
      this.renderToolHistoryList();
      this.showToast('🗑️ 工具調用紀錄已全部清空');
    } catch (e) {
      console.error(e);
      this.showToast('❌ 清空紀錄失敗');
    }
  }

  // ==========================================================================
  // 🧠 記憶管理中樞 (Memory Manager Methods)
  // ==========================================================================
  async loadMemoryCapacity() {
    try {
      const resp = await fetch('/api/memory/capacity');
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.ok) {
        const cap = data.dialogue_capacity !== undefined ? data.dialogue_capacity : 500;
        if (this.inputMemCapacity) {
          this.inputMemCapacity.value = cap;
        }
        if (this.memCapacityCurrent) {
          if (cap <= 0) {
            safeSetText(this.memCapacityCurrent, `⚡ 無上限 (已存 ${data.dialogue_count || 0} 句)`);
            this.memCapacityCurrent.classList.add('unlimited-badge');
          } else {
            safeSetText(this.memCapacityCurrent, `${cap} 句上限 (已存 ${data.dialogue_count || 0} 句)`);
            this.memCapacityCurrent.classList.remove('unlimited-badge');
          }
        }
      }
    } catch (e) {
      console.warn('載入記憶容量配置失敗:', e);
    }
  }

  async saveMemoryCapacity(capacity) {
    try {
      let capNum = parseInt(capacity, 10);
      if (isNaN(capNum) || capNum < 0) capNum = 0;
      if (this.btnSaveMemCapacity) {
        this.btnSaveMemCapacity.disabled = true;
        safeSetText(this.btnSaveMemCapacity.querySelector('span') || this.btnSaveMemCapacity, '儲存中...');
      }
      const resp = await fetch('/api/memory/capacity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capacity: capNum })
      });
      const data = await resp.json();
      if (data.ok) {
        const capStr = capNum <= 0 ? '⚡ 無上限（永久保留所有對話）' : `${capNum} 句`;
        this.showToast(`✅ 底層記憶池上限已成功設定為: ${capStr}`);
        if (this.memCapacityCurrent) {
          if (capNum <= 0) {
            safeSetText(this.memCapacityCurrent, `⚡ 無上限 (已存 ${data.dialogue_count || 0} 句)`);
            this.memCapacityCurrent.classList.add('unlimited-badge');
          } else {
            safeSetText(this.memCapacityCurrent, `${capNum} 句上限 (已存 ${data.dialogue_count || 0} 句)`);
            this.memCapacityCurrent.classList.remove('unlimited-badge');
          }
        }
        if (this.inputMemCapacity) {
          this.inputMemCapacity.value = capNum;
        }
        this.loadMemoryManagerList();
      } else {
        throw new Error(data.error || '儲存失敗');
      }
    } catch (e) {
      console.error('儲存記憶容量失敗:', e);
      this.showToast(`❌ 儲存記憶容量失敗: ${e.message}`);
    } finally {
      if (this.btnSaveMemCapacity) {
        this.btnSaveMemCapacity.disabled = false;
        safeSetText(this.btnSaveMemCapacity.querySelector('span') || this.btnSaveMemCapacity, '💾 儲存上限');
      }
    }
  }

  async loadMemoryManagerList() {
    try {
      this.loadMemoryCapacity();
      if (this.memTotalBadge) safeSetText(this.memTotalBadge, '讀取中...');
      const resp = await fetch('/api/memory/all');
      if (!resp.ok) {
        throw new Error(`伺服器回應 ${resp.status}`);
      }
      const data = await resp.json();
      if (data.ok && Array.isArray(data.memories)) {
        this.memoryItems = data.memories;
        this.renderMemoryList();
      } else {
        throw new Error(data.error || '記憶資料解析失敗');
      }
    } catch (e) {
      console.error('載入記憶清單失敗:', e);
      if (this.memTotalBadge) safeSetText(this.memTotalBadge, '連線異常');
      if (this.memoryCardList && (!this.memoryItems || this.memoryItems.length === 0)) {
        this.memoryCardList.innerHTML = `
          <div class="memory-empty-hint" style="color:var(--neon-pink); padding: 35px 20px; text-align: center;">
            <div style="font-size: 1.1rem; margin-bottom: 10px;">⚠️ 載入記憶中樞失敗 (${this.escapeHtml(e.message)})</div>
            <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 18px;">可能是後台服務正在熱重啟或連線短暫中斷</p>
            <button type="button" class="glass-btn btn-primary" style="padding: 6px 18px; margin: 0 auto; display: inline-flex;" onclick="window.sevenLApp.loadMemoryManagerList()">
              🔄 立即重新讀取
            </button>
          </div>
        `;
      }
    }
  }

  renderMemoryList() {
    if (!this.memoryCardList) return;

    // 統計各身分筆數
    const totalCount = this.memoryItems.length;
    let countThought = 0, countAi = 0, countUser = 0, countTiktok = 0;
    this.memoryItems.forEach(it => {
      const r = (it.role || '').toLowerCase();
      const s = (it.speaker || '').toLowerCase();
      if (r === 'thought' || it.source === 'thought' || it.target === '內心流動' || s === '內心流動') countThought++;
      else if (r === 'assistant' || s === '7l') countAi++;
      else if (s.includes('tiktok') || it.source === 'tiktok') countTiktok++;
      else countUser++;
    });

    if (this.memTotalBadge) safeSetText(this.memTotalBadge, `${totalCount} 句記憶中樞`);
    if (this.memCountAll) safeSetText(this.memCountAll, String(totalCount));
    if (this.memCountThought) safeSetText(this.memCountThought, String(countThought));
    if (this.memCountAi) safeSetText(this.memCountAi, String(countAi));
    if (this.memCountUser) safeSetText(this.memCountUser, String(countUser));
    if (this.memCountTiktok) safeSetText(this.memCountTiktok, String(countTiktok));

    // 過濾角色與搜尋詞
    const roleFilter = this.memoryFilterRole;
    const query = (this.memorySearchKeyword || '').toLowerCase();

    const filtered = this.memoryItems.filter(item => {
      const r = (item.role || '').toLowerCase();
      const s = (item.speaker || '').toLowerCase();
      const content = (item.content || '').toLowerCase();

      // 角色分類比對
      let matchRole = true;
      if (roleFilter === 'thought') {
        matchRole = (r === 'thought' || item.source === 'thought' || item.target === '內心流動' || s === '內心流動');
      } else if (roleFilter === 'ai') {
        matchRole = (r === 'assistant' || s === '7l') && (r !== 'thought' && s !== '內心流動');
      } else if (roleFilter === 'user') {
        matchRole = (r === 'user' || s === '老爸') && (!s.includes('tiktok') && item.source !== 'tiktok');
      } else if (roleFilter === 'tiktok') {
        matchRole = (s.includes('tiktok') || item.source === 'tiktok');
      }

      // 關鍵字搜尋比對
      let matchQuery = true;
      if (query) {
        matchQuery = content.includes(query) || s.includes(query) || (item.time_str && item.time_str.includes(query));
      }

      return matchRole && matchQuery;
    });

    if (this.memoryListMeta) {
      safeSetText(this.memoryListMeta, `顯示 ${filtered.length} / ${totalCount} 筆記憶 (時序最新排最後)`);
    }

    if (filtered.length === 0) {
      this.memoryCardList.innerHTML = '<div class="memory-empty-hint">無符合條件的記憶項目</div>';
      return;
    }

    const frag = document.createDocumentFragment();
    // 預設將最新記憶排在上方供快速審閱與刪除
    const displayList = [...filtered].reverse();

    displayList.forEach(item => {
      const idx = item.index !== undefined ? item.index : this.memoryItems.indexOf(item);
      const r = (item.role || '').toLowerCase();
      const s = item.speaker || '未知';
      const content = item.content || '';
      const timeStr = item.time_str || (item.time ? new Date(item.time * 1000).toTimeString().split(' ')[0] : '即時');

      let roleClass = 'role-user';
      let badgeClass = 'badge-user';
      let roleLabel = '👨‍💻 老爸';

      if (r === 'thought' || item.source === 'thought' || item.target === '內心流動' || s === '內心流動') {
        roleClass = 'role-thought';
        badgeClass = 'badge-thought';
        roleLabel = '💭 內心流動';
      } else if (r === 'assistant' || s === '7L') {
        roleClass = 'role-assistant';
        badgeClass = 'badge-assistant';
        roleLabel = '🤖 7L 發言';
      } else if (s.includes('TikTok') || item.source === 'tiktok') {
        roleClass = 'role-tiktok';
        badgeClass = 'badge-tiktok';
        roleLabel = '🔴 直播留言';
      }

      const card = document.createElement('div');
      card.className = `memory-card-item ${roleClass}`;
      card.innerHTML = `
        <div class="memory-card-main">
          <div class="memory-item-meta font-mono">
            <span class="memory-idx-tag">#${idx}</span>
            <span class="memory-role-badge ${badgeClass}">${roleLabel}</span>
            <span class="memory-speaker-tag">【${this.escapeHtml(s)}】</span>
            <span class="memory-time-tag">${this.escapeHtml(timeStr)}</span>
          </div>
          <div class="memory-card-text">${this.escapeHtml(content)}</div>
        </div>
        <div class="memory-card-actions">
          <button type="button" class="memory-btn-action btn-edit" data-idx="${idx}">✏️ 編輯</button>
          <button type="button" class="memory-btn-action btn-delete" data-idx="${idx}">🗑️ 刪除</button>
        </div>
      `;

      card.querySelector('.btn-edit').addEventListener('click', () => {
        this.openEditMemoryModal(idx, item);
      });

      card.querySelector('.btn-delete').addEventListener('click', () => {
        this.deleteMemoryItem(idx, content);
      });

      frag.appendChild(card);
    });

    this.memoryCardList.innerHTML = '';
    this.memoryCardList.appendChild(frag);
  }

  openEditMemoryModal(index, item) {
    this.editingMemoryIndex = index;
    if (!item) {
      item = this.memoryItems.find(m => m.index === index) || {};
    }

    if (this.editMemIndexBadge) safeSetText(this.editMemIndexBadge, `#${index}`);
    if (this.editMemRoleBadge) safeSetText(this.editMemRoleBadge, item.role || 'user');
    if (this.editMemTimeBadge) safeSetText(this.editMemTimeBadge, item.time_str || '');
    if (this.editMemSpeaker) this.editMemSpeaker.value = item.speaker || '';
    if (this.editMemContent) this.editMemContent.value = item.content || '';

    if (this.editMemoryModal) {
      this.editMemoryModal.style.display = 'flex';
    }
  }

  closeEditMemoryModal() {
    if (this.editMemoryModal) {
      this.editMemoryModal.style.display = 'none';
    }
    this.editingMemoryIndex = -1;
  }

  async saveEditMemory() {
    if (this.editingMemoryIndex < 0) return;
    const newContent = this.editMemContent ? this.editMemContent.value.trim() : '';
    const newSpeaker = this.editMemSpeaker ? this.editMemSpeaker.value.trim() : '老爸';

    if (!newContent) {
      this.showToast('⚠️ 記憶內容不能為空！');
      return;
    }

    try {
      const resp = await fetch('/api/memory/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          index: this.editingMemoryIndex,
          content: newContent,
          speaker: newSpeaker
        })
      });
      const res = await resp.json();
      if (res.ok) {
        this.showToast('✅ 記憶已成功修改並即時生效！');
        this.closeEditMemoryModal();
        await this.loadMemoryManagerList();
        // 重新同步對話中樞串流
        await this.loadMemoryHistory();
      } else {
        this.showToast(`❌ 修改失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 網路或伺服器異常');
    }
  }

  async deleteMemoryItem(index, contentPreview = '') {
    const preview = contentPreview ? `「${contentPreview.slice(0, 25)}...」` : `#${index}`;
    if (!confirm(`確定要從 7L 大腦永久刪除這筆記憶嗎？\n\n${preview}`)) {
      return;
    }

    try {
      const resp = await fetch('/api/memory/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index })
      });
      const res = await resp.json();
      if (res.ok) {
        this.showToast('🗑️ 記憶已成功移除！');
        await this.loadMemoryManagerList();
        // 重新同步對話中樞串流
        await this.loadMemoryHistory();
      } else {
        this.showToast(`❌ 刪除失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 網路或伺服器異常');
    }
  }

  openAddMemoryModal() {
    if (this.addMemContent) this.addMemContent.value = '';
    if (this.addMemSpeaker) this.addMemSpeaker.value = '老爸';
    if (this.addMemoryModal) {
      this.addMemoryModal.style.display = 'flex';
    }
  }

  closeAddMemoryModal() {
    if (this.addMemoryModal) {
      this.addMemoryModal.style.display = 'none';
    }
  }

  async submitAddMemory() {
    const role = this.addMemRole ? this.addMemRole.value : 'user';
    const speaker = this.addMemSpeaker ? this.addMemSpeaker.value.trim() : '老爸';
    const content = this.addMemContent ? this.addMemContent.value.trim() : '';

    if (!content) {
      this.showToast('⚠️ 記憶內容不能為空！');
      return;
    }

    try {
      const resp = await fetch('/api/memory/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: role,
          speaker: speaker,
          target: role === 'thought' ? '內心流動' : '7L',
          content: content,
          source: 'dashboard_manual'
        })
      });
      const res = await resp.json();
      if (res.ok) {
        this.showToast('🌟 新記憶已成功注入 7L 大腦！');
        this.closeAddMemoryModal();
        await this.loadMemoryManagerList();
        await this.loadMemoryHistory();
      } else {
        this.showToast(`❌ 寫入失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 網路或伺服器異常');
    }
  }

  async cleanDuplicateMemories() {
    if (!confirm('是否要對 7L 記憶庫進行「智慧去重」？\n系統將自動掃描並移除連續跳針的重複思緒。')) {
      return;
    }

    try {
      const resp = await fetch('/api/memory/clean_duplicates', { method: 'POST' });
      const res = await resp.json();
      if (res.ok) {
        this.showToast(`🧹 去重完成！共清理了 ${res.removed_count} 筆重複跳針記憶。`);
        await this.loadMemoryManagerList();
        await this.loadMemoryHistory();
      } else {
        this.showToast(`❌ 去重失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 網路或伺服器異常');
    }
  }

  async clearAllMemories() {
    if (!confirm('⚠️ 警告：確定要徹底清空 7L 的所有雲端與本地記憶嗎？\n\n此操作將清空所有對話紀錄、心流思緒與歷史快取，且無法復原！')) {
      return;
    }

    try {
      const resp = await fetch('/api/memory/clear', { method: 'POST' });
      const res = await resp.json();
      if (res.ok) {
        this.showToast('🗑️ 記憶已徹底清空！');
        this.loadedMemoryIds.clear();
        if (this.chatStream) this.chatStream.innerHTML = '';
        if (this.mindStreamList) this.mindStreamList.innerHTML = '';
        this.memoryItems = [];
        this.renderMemoryList();
        await this.loadMemoryManagerList();
        await this.loadMemoryHistory();
      } else {
        this.showToast(`❌ 清除失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 網路或伺服器異常');
    }
  }

  // =========================================================================
  // 🎛️ 系統開關與自主行為中樞 (System Switches Hub)
  // =========================================================================
  async loadSwitches() {
    try {
      const resp = await fetch('/api/switches');
      const data = await resp.json();
      if (data && data.status === 'ok' && Array.isArray(data.switches)) {
        this.switchesList = data.switches;
        this.renderSwitches(this.switchesList);
      }
    } catch (e) {
      console.error('載入系統開關失敗:', e);
    }
  }

  renderSwitches(switches) {
    if (!this.switchesGrid) return;
    if (!switches || switches.length === 0) {
      this.switchesGrid.innerHTML = '<div class="stream-empty-hint">暫無可用的系統開關配置</div>';
      return;
    }

    // 計算啟用開關總數
    const activeCount = switches.filter(s => s.value).length;
    if (this.switchesActiveCount) {
      safeSetText(this.switchesActiveCount, String(activeCount));
    }

    // 依 category 分組
    const groups = {};
    switches.forEach(sw => {
      const cat = sw.category || 'other';
      if (!groups[cat]) {
        groups[cat] = {
          name: sw.category_name || cat,
          items: []
        };
      }
      groups[cat].items.push(sw);
    });

    let html = '';
    for (const [catKey, group] of Object.entries(groups)) {
      const groupActive = group.items.filter(i => i.value).length;
      html += `
        <div class="switches-group">
          <div class="switches-group-header">
            <span class="switches-group-title">${this.escapeHtml(group.name)}</span>
            <span class="switches-group-count">${groupActive} / ${group.items.length} 已啟用</span>
          </div>
          <div class="switches-cards-grid">
      `;

      group.items.forEach(sw => {
        const isActive = Boolean(sw.value);
        const cardClass = isActive ? 'switch-card active' : 'switch-card';
        const toggleClass = isActive ? 'switch-toggle active' : 'switch-toggle';
        const badgeClass = isActive ? 'switch-badge switch-badge-active' : 'switch-badge switch-badge-inactive';
        const badgeText = isActive ? '🟢 已開啟' : '⚪ 已關閉';
        const ariaChecked = isActive ? 'true' : 'false';

        html += `
          <div class="${cardClass}" id="card-sw-${sw.key}" data-key="${sw.key}">
            <div class="switch-card-top">
              <div class="switch-info-main">
                <div class="switch-card-name-row">
                  <h3 class="switch-card-title">${this.escapeHtml(sw.name)}</h3>
                  <span class="switch-card-key font-mono">${this.escapeHtml(sw.key)}</span>
                </div>
                <p class="switch-card-desc">${this.escapeHtml(sw.description)}</p>
              </div>
              <div class="switch-control-area">
                <button 
                  type="button" 
                  class="${toggleClass}" 
                  id="btn-sw-${sw.key}" 
                  role="switch" 
                  aria-checked="${ariaChecked}" 
                  data-key="${sw.key}"
                  title="點擊切換 ${this.escapeHtml(sw.name)}"
                >
                  <span class="switch-thumb"></span>
                </button>
              </div>
            </div>
            <div class="switch-card-footer">
              <span class="${badgeClass}" id="badge-sw-${sw.key}">${badgeText}</span>
              <span class="switch-action-hint" data-key="${sw.key}">點擊開關切換</span>
            </div>
          </div>
        `;
      });

      html += `
          </div>
        </div>
      `;
    }

    this.switchesGrid.innerHTML = html;

    // 綁定所有開關按鈕與卡片輔助點擊
    this.switchesGrid.querySelectorAll('.switch-toggle, .switch-action-hint').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const key = btn.dataset.key;
        if (!key) return;
        const currentItem = this.switchesList.find(s => s.key === key);
        const curVal = currentItem ? Boolean(currentItem.value) : false;
        this.toggleSwitch(key, curVal);
      });
    });
  }

  async toggleSwitch(key, currentValue) {
    const targetVal = !currentValue;
    const toggleBtn = document.getElementById(`btn-sw-${key}`);
    if (toggleBtn) toggleBtn.disabled = true;

    try {
      const resp = await fetch('/api/switches/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key, value: targetVal })
      });
      const res = await resp.json();
      if (res && res.status === 'ok') {
        const item = this.switchesList.find(s => s.key === key);
        if (item) {
          item.value = res.value;
        }
        if (res.switches && Array.isArray(res.switches)) {
          this.switchesList = res.switches;
        }
        this.renderSwitches(this.switchesList);
        const name = item ? item.name : key;
        const statusStr = res.value ? '已開啟' : '已關閉';
        this.showToast(`🎛️ ${name} ${statusStr}`);
        this.appendLog(`[系統開關] ${name} (${key}) ➔ ${statusStr}`, res.value ? 'line-success' : 'line-warn');
      } else {
        this.showToast(`❌ 切換失敗: ${res.error || '未知錯誤'}`);
      }
    } catch (e) {
      console.error(e);
      this.showToast('❌ 網路連線異常，無法更新開關');
    } finally {
      if (toggleBtn) toggleBtn.disabled = false;
    }
  }

  updateSingleSwitchUI(key, value) {
    const item = this.switchesList.find(s => s.key === key);
    if (item) {
      item.value = Boolean(value);
      this.renderSwitches(this.switchesList);
    }
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

// 🛡️ 雙重保險啟動器：相容所有瀏覽器狀態，防止重整/快取時 DOMContentLoaded 已觸發導致按鈕全失效
function bootSevenLApp() {
  if (!window.sevenLApp) {
    try {
      window.sevenLApp = new SevenLMonitorApp();
    } catch (err) {
      console.error('🚨 [7L Web 後台] 初始化嚴重異常:', err);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootSevenLApp);
} else {
  // DOM 已經準備好 (例如快取恢復、延遲載入或重整時)，立即啟動！
  bootSevenLApp();
}

