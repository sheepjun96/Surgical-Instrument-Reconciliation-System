const { createApp, ref, computed, onMounted, onUnmounted } = Vue;

const TOOL_PALETTE = {
  "forceps": { name: "Forceps", color: "#ef4444" },
  "hand_instrument": { name: "Hand Instrument", color: "#3b82f6" },
  "retractor": { name: "Retractor", color: "#a855f7" },
  "trocar": { name: "Trocar", color: "#22c55e" },

  "needle_holder": { name: "Needle Holder", color: "#ef4444" },
  "grasper": { name: "Grasper", color: "#3b82f6" },
  "clip_applier": { name: "Clip Applier", color: "#a855f7" },
  "scissors": { name: "Scissors", color: "#22c55e" },
  "dissector": { name: "Dissector", color: "#f59e0b" },
  "energy_device": { name: "Energy Device", color: "#ec4899" }
};

createApp({
  delimiters: ["[[", "]]"],

  setup() {
    const dashboard = ref({
      session_id: null,
      status: "WAITING_BEFORE",
      captures: { before: null, after: null },
      counts: { before: {}, after: {} }
    });
    const device = ref({ connected: false, seconds_since_last_seen: null });
    const overlayVisible = ref(true);
    const showResetModal = ref(false);
    const resetting = ref(false);
    const loadError = ref(false);
    let pollTimer = null;
    const showAfterStream = ref(false);
    let afterStreamTimer = null;
    const streamSrc = ref("");
    let streamWs = null
    const sessionList = ref([]);
    const showSessionMenu = ref(false);

    const phases = [
      { key: "before", title: "수술 전", eyebrow: "BEFORE SURGERY" },
      { key: "after", title: "수술 후", eyebrow: "AFTER SURGERY" },
    ];

    function toggleSessionMenu() {
      showSessionMenu.value = !showSessionMenu.value;
    }

    function closeSessionMenu() {
      showSessionMenu.value = false;
    }

    async function deleteSession(id) {
      if (confirm(`${id}번 세션을 삭제하시겠습니까?`)) {
        try {
          const res = await fetchJson(`/api/session/${id}/delete`, { method: "POST" });
          if (res.ok) {
            // 삭제 성공 시, 현재 보고 있던 세션이 삭제되었을 수 있으므로 최신 세션으로 새로고침 이동
            window.location.href = `/${res.latest_session_id}`;
          }
        } catch (error) {
          console.error("세션 삭제 실패:", error);
          alert("삭제 중 오류가 발생했습니다.");
        }
      }
    }

    const activeTools = computed(() => {
      const beforeCounts = dashboard.value.counts?.before || {};
      const afterCounts = dashboard.value.counts?.after || {};
      const allKeys = new Set([...Object.keys(beforeCounts), ...Object.keys(afterCounts)]);

      const isCompleted = dashboard.value.status === 'COMPLETED';

      return Array.from(allKeys).map(key => {
        const b = beforeCounts[key] || 0;
        const a = afterCounts[key] || 0;
        return {
          key: key,
          name: TOOL_PALETTE[key]?.name || key,
          color: TOOL_PALETTE[key]?.color || "#aaaaaa",
          before: b,
          after: a,
          difference: isCompleted ? (a - b) : null 
        };
      }).filter(tool => tool.before > 0 || tool.after > 0);
    });

    const totals = computed(() => {
      const bSum = activeTools.value.reduce((sum, t) => sum + t.before, 0);
      const aSum = activeTools.value.reduce((sum, t) => sum + t.after, 0);
      const isCompleted = dashboard.value.status === 'COMPLETED';

      return {
        before: activeTools.value.length ? bSum : "—",
        after: activeTools.value.length ? aSum : "—",
        difference: (isCompleted && activeTools.value.length) ? (aSum - bSum) : null,
      };
    });

    const lastSeenText = computed(() => {
      const seconds = device.value.seconds_since_last_seen;
      if (seconds === null || seconds === undefined) return "—";
      if (seconds < 1) return `${seconds.toFixed(1)}초 전`;
      return `${Math.round(seconds)}초 전`;
    });

    const sessionStatusTitle = computed(() => {
      const titles = {
        WAITING_BEFORE: "수술 전 촬영을 기다리고 있습니다",
        WAITING_AFTER: "수술 후 촬영을 기다리고 있습니다",
        COMPLETED: "수술 전후 비교가 완료되었습니다",
      };
      return titles[dashboard.value.status] || "분석 상태를 확인하고 있습니다";
    });

    const sessionStatusDescription = computed(() => {
      const descriptions = {
        WAITING_BEFORE: "첫 번째 촬영 결과가 수술 전 이미지로 등록됩니다.",
        WAITING_AFTER: "두 번째 촬영 결과가 도착하면 비교표가 완성됩니다.",
        COMPLETED: "수량 차이가 있는 셀을 확인해주세요.",
      };
      return descriptions[dashboard.value.status] || "잠시만 기다려주세요.";
    });

    function captureFor(phase) { return dashboard.value.captures?.[phase] || null; }

    function formatDate(value) {
      if (!value) return "—";
      return new Intl.DateTimeFormat("ko-KR", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      }).format(new Date(value));
    }

    function isStreamActive(phaseKey) {
      if (phaseKey === 'before') {
        return !dashboard.value.captures?.before; // before가 없을 때만 나옴
      } else if (phaseKey === 'after') {
        // before를 찍자마자 1분 대기와 상관없이 즉시 after로 영상이 켜짐
        return !!dashboard.value.captures?.before && !dashboard.value.captures?.after;
      }
      return false;
    }

    function displayCount(value) { return value === null || value === undefined ? "—" : value; }
    function displayDifference(value) {
      if (value === null || value === undefined) return "—";
      return value > 0 ? `+${value}` : `${value}`;
    }

    function differenceClass(value) {
      if (value === null || value === undefined) return "is-pending";
      if (value < 0) return "is-negative";
      if (value > 0) return "is-positive";
      return "is-same";
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return response.json();
    }

    function isBorderActive(phaseKey) {
      // 서버에서 계산한 1분 대기(expected_phase)에 따라 테두리가 남거나 이동함
      return dashboard.value.expected_phase === phaseKey;
    }

    async function loadLatest() {
      try {
        const path = window.location.pathname;
        const match = path.match(/^\/(\d+)$/);
        
        let dashboardUrl = "/api/dashboard/current";
        if (match) {
           dashboardUrl = `/api/dashboard/${match[1]}`;
        }

        const [deviceData, dashboardData, sessionsData] = await Promise.all([
          fetchJson("/api/device/status"),
          fetchJson(dashboardUrl),
          fetchJson("/api/sessions")
        ]);

        sessionList.value = sessionsData;

        if (path === "/" || (match && dashboardData.session_id != match[1])) {
            window.history.replaceState(null, "", `/${dashboardData.session_id}`);
        }

        if (dashboardData.captures?.before && !dashboardData.captures?.after) {
        if (!showAfterStream.value && !afterStreamTimer) {
            afterStreamTimer = setTimeout(() => {
              showAfterStream.value = true;
            }, 60000);
          }
        } else {
          clearTimeout(afterStreamTimer);
          afterStreamTimer = null;
          showAfterStream.value = false;
        }

        device.value = deviceData;
        dashboard.value = dashboardData;
        loadError.value = false;
      } catch (error) {
        console.error(error);
        loadError.value = true;
      }
    }

    function getTimestampedUrl(url, captured_at) {
      if (!url) return "";
      if (!captured_at) return `${url}?t=${new Date().getTime()}`;
      
      const t = new Date(captured_at).getTime();
      return `${url}?t=${t}`;
    }

    function countCellHighlight(diff) {
      if (diff === null || diff === undefined || diff === 0) return "";
      if (diff < 0) return "is-negative"; 
      if (diff > 0) return "is-positive"; 
      return "";
    }

    function connectStreamWebSocket() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/stream/view`;
      
      streamWs = new WebSocket(wsUrl);
      streamWs.binaryType = "blob";

      streamWs.onmessage = (event) => {
        if (streamSrc.value) {
          URL.revokeObjectURL(streamSrc.value);
        }
        streamSrc.value = URL.createObjectURL(event.data);
      };

      streamWs.onclose = () => {
        // 끊어지면 2초 뒤 재접속 시도
        setTimeout(connectStreamWebSocket, 2000);
      };
    }

    onMounted(() => {
      loadLatest();
      pollTimer = window.setInterval(loadLatest, 1000);
      connectStreamWebSocket(); // 컴포넌트 로드 시 웹소켓 연결 시작
    });

    onUnmounted(() => {
      if (pollTimer) window.clearInterval(pollTimer);
      if (streamWs) streamWs.close();
    });

    async function resetSession() {
      resetting.value = true;
      try {
        const res = await fetchJson("/api/session/reset", { method: "POST" });
        
        // 새 세션을 발급받은 뒤, 브라우저 URL을 해당 세션 번호로 강제 이동
        window.location.href = `/${res.session_id}`;
      } catch (error) {
        console.error(error);
        loadError.value = true;
      } finally {
        resetting.value = false;
      }
    }

    onMounted(() => {
      loadLatest();
      pollTimer = window.setInterval(loadLatest, 1000);
    });

    onUnmounted(() => {
      if (pollTimer) window.clearInterval(pollTimer);
    });

return {
      dashboard, device, phases, activeTools, totals,
      lastSeenText, sessionStatusTitle, sessionStatusDescription,
      overlayVisible, showResetModal, resetting, loadError,
      captureFor, formatDate, displayCount, displayDifference,
      differenceClass, countCellHighlight, resetSession, getTimestampedUrl, 
      isStreamActive, streamSrc, isBorderActive, sessionList, showSessionMenu, toggleSessionMenu, closeSessionMenu, deleteSession
    };
  },
}).mount("#app");