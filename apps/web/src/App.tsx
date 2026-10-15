import { useCallback, useEffect, useMemo, useState } from "react";
import { Api, loadToken, saveToken, type Call, type Campaign, type SystemStatus } from "./api";
import { CallSetup, type Draft } from "./components/CallSetup";
import { CallSheet } from "./components/CallSheet";
import { CallView } from "./components/CallView";
import { History } from "./components/History";
import { Login } from "./components/Login";
import { ClockIcon, LogoutIcon, PhoneIcon } from "./icons";
import { ThemeToggle } from "./ui/ThemeToggle";
import { transition } from "./ui/theme";

type Tab = "call" | "history";

export function App() {
  const [token, setToken] = useState<string | null>(loadToken);
  const logout = useCallback(() => {
    saveToken(null);
    setToken(null);
  }, []);
  const api = useMemo(() => (token ? new Api(token, logout) : null), [token, logout]);

  if (!api) {
    return (
      <Login
        onLogin={(t) => {
          saveToken(t);
          setToken(t);
        }}
      />
    );
  }
  return <Console api={api} onLogout={logout} />;
}

function Console({ api, onLogout }: { api: Api; onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>("call");
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [call, setCall] = useState<Call | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({ campaignId: "pa_confirmation", name: "", phone: "" });

  useEffect(() => {
    api.campaigns().then(setCampaigns, (e: Error) => setLoadError(e.message));
  }, [api]);

  useEffect(() => {
    let stop = false;
    const tick = () =>
      api.status().then(
        (s) => {
          if (stop) return;
          setStatus(s);
          if (s.active_call_id) setFocusId((current) => current ?? s.active_call_id);
        },
        () => undefined,
      );
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [api]);

  useEffect(() => {
    if (!focusId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.call(focusId);
        if (stop) return;
        setCall(next);
        if (next.active) timer = setTimeout(poll, 900);
        else setRefreshKey((k) => k + 1);
      } catch {
        if (!stop) timer = setTimeout(poll, 2000);
      }
    };
    poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [api, focusId]);

  // Screen changes cross-fade (view transitions) instead of cutting.
  const go = (next: Tab) => {
    if (next !== tab) void transition(() => setTab(next));
  };

  const activeElsewhere = Boolean(status?.active_call_id && status.active_call_id !== call?.call_id);
  const showCall = Boolean(call && call.call_id === focusId);

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <img className="brand-logo" src="/brand/kpi-logo.svg" alt="กรุงไทยพานิชประกันภัย (KPI)" width={138} height={67} />
            <span className="brand-name">Voicebot</span>
          </div>
          <nav className="tabs" role="tablist" aria-label="เมนูหลัก">
            <button className="tab" role="tab" aria-selected={tab === "call"} onClick={() => go("call")}>
              <PhoneIcon size={16} />
              โทรออก
              {call?.active && <span className="dot" aria-label="มีสายกำลังดำเนินการ" />}
            </button>
            <button className="tab" role="tab" aria-selected={tab === "history"} onClick={() => go("history")}>
              <ClockIcon size={16} />
              ประวัติการโทร
            </button>
          </nav>
          <div className="topbar-actions">
            {status && !status.live_calls_enabled && (
              <span className="mode-chip" title={status.interpreter === "llm" ? "เข้าใจคำตอบด้วย Qwen" : "เข้าใจคำตอบด้วยกฎ"}>
                โหมดจำลอง{status.interpreter === "llm" ? " · Qwen" : ""}
              </span>
            )}
            <ThemeToggle />
            <button className="icon-btn" onClick={onLogout} aria-label="ออกจากระบบ" title="ออกจากระบบ">
              <LogoutIcon size={18} />
            </button>
          </div>
        </div>
      </header>

      {loadError && (
        <div className="page page-narrow" style={{ paddingBottom: 0 }}>
          <div className="alert err" role="alert">
            {loadError}
          </div>
        </div>
      )}

      {tab === "call" &&
        (showCall && call ? (
          <main className="page">
            <CallView
              api={api}
              call={call}
              onNewCall={() =>
                void transition(() => {
                  setFocusId(null);
                  setCall(null);
                })
              }
              onOpenDetail={setDetailId}
            />
          </main>
        ) : (
          <main className="page page-narrow">
            <CallSetup
              draft={draft}
              onDraft={setDraft}
              api={api}
              campaigns={campaigns}
              status={status}
              busy={activeElsewhere}
              onShowActive={() => status?.active_call_id && setFocusId(status.active_call_id)}
              onCreated={(created) =>
                void transition(() => {
                  setCall(created);
                  setFocusId(created.call_id);
                })
              }
            />
          </main>
        ))}

      {tab === "history" && (
        <main className="page">
          <History api={api} refreshKey={refreshKey} onOpen={setDetailId} onGoCall={() => go("call")} />
        </main>
      )}

      {detailId && (
        <CallSheet
          api={api}
          callId={detailId}
          onClose={() => setDetailId(null)}
          onDeleted={() => {
            setDetailId(null);
            setRefreshKey((k) => k + 1);
          }}
        />
      )}
    </>
  );
}
