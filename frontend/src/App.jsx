import { createSignal, onMount, Show, For, createEffect } from "solid-js";
import {
  clearSession,
  createSubmission,
  fetchSubmission,
  fetchSubmissions,
  fetchTickets,
  fetchVoidedTickets,
  getUser,
  issueTicket,
  login,
  redeemTicket,
  setSession,
  voidTicket,
} from "./api";

const statusLabel = {
  pending: "待复核",
  processing: "复核中",
  done: "已完成",
};

const ticketStatusLabel = {
  valid: "在用",
  redeemed: "已用",
  voided: "已作废",
};

const roleLabel = {
  machinist: "操作员",
  auditor: "复核员",
};

function localDateStr(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function readHash() {
  const raw = (location.hash || "#/").replace(/^#/, "") || "/";
  let m = raw.match(/^\/detail\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  if (raw === "/desk") return { name: "desk", id: null };
  return { name: "home", id: null };
}

function App() {
  const [user, setUser] = createSignal(getUser());
  const [rows, setRows] = createSignal([]);
  const [detail, setDetail] = createSignal(null);
  const [route, setRoute] = createSignal(readHash());
  const [error, setError] = createSignal("");
  const [notice, setNotice] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  const [loginUser, setLoginUser] = createSignal("machinist");
  const [loginPass, setLoginPass] = createSignal("machine123456");

  const [toolCode, setToolCode] = createSignal("");
  const [offsetUm, setOffsetUm] = createSignal("");

  const [tickets, setTickets] = createSignal([]);
  const [voided, setVoided] = createSignal([]);
  const [redeemDraft, setRedeemDraft] = createSignal({});
  const [voidDraft, setVoidDraft] = createSignal({});

  function goHome() {
    location.hash = "#/";
  }

  function goDesk() {
    location.hash = "#/desk";
  }

  function goDetail(id) {
    location.hash = `#/detail/${id}`;
  }

  function flash(msg, isError = false) {
    if (isError) {
      setError(msg);
      setNotice("");
    } else {
      setNotice(msg);
      setError("");
    }
  }

  async function loadRows() {
    setLoading(true);
    try {
      setRows(await fetchSubmissions());
    } catch (e) {
      flash(e.message, true);
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id) {
    setLoading(true);
    try {
      setDetail(await fetchSubmission(id));
    } catch (e) {
      flash(e.message, true);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadDesk() {
    try {
      const [ts, vs] = await Promise.all([fetchTickets(), fetchVoidedTickets()]);
      setTickets(ts);
      setVoided(vs);
    } catch (e) {
      flash(e.message, true);
    }
  }

  onMount(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    if (user()) {
      if (route().name === "detail") loadDetail(route().id);
      else if (route().name === "desk") loadDesk();
      else loadRows();
    }
    return () => window.removeEventListener("hashchange", onHash);
  });

  createEffect(() => {
    const r = route();
    if (!user()) return;
    if (r.name === "detail" && r.id) loadDetail(r.id);
    else if (r.name === "desk") loadDesk();
    else loadRows();
  });

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    try {
      const data = await login(loginUser(), loginPass());
      setSession(data.token, {
        username: data.username,
        role: data.role,
        can_write: data.can_write,
      });
      setUser(getUser());
      goHome();
      await loadRows();
    } catch (err) {
      flash(err.message, true);
    }
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setRows([]);
    setDetail(null);
    setTickets([]);
    setVoided([]);
    goHome();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await createSubmission(toolCode(), offsetUm());
      setToolCode("");
      setOffsetUm("");
      await loadRows();
    } catch (err) {
      flash(err.message, true);
    }
  }

  async function handleIssue() {
    try {
      const t = await issueTicket();
      await loadDesk();
      flash(`已取得当日券 ${t.code}（每自然日一张）`);
    } catch (err) {
      flash(err.message, true);
    }
  }

  function patchDraft(setter, id, patch) {
    setter((d) => ({ ...d, [id]: { ...(d[id] || {}), ...patch } }));
  }

  async function handleRedeem(ticket) {
    const draft = redeemDraft()[ticket.id] || {};
    const tc = (draft.tool_code || "").trim();
    const um = draft.offset_um;
    if (!tc) return flash("请填写刀具编号", true);
    if (um === "" || um === undefined || um === null)
      return flash("请填写刀补微米值", true);
    if (!Number.isFinite(Number(um))) return flash("刀补须为整数微米值", true);
    try {
      await redeemTicket(ticket.id, tc, um);
      setRedeemDraft((d) => ({ ...d, [ticket.id]: {} }));
      await Promise.all([loadDesk(), loadRows()]);
      flash(`挂券 ${ticket.code} 交单成功，已进待复核`);
    } catch (err) {
      flash(err.message, true);
    }
  }

  async function handleVoid(ticket) {
    const reason = (voidDraft()[ticket.id]?.reason || "").trim();
    try {
      await voidTicket(ticket.id, reason);
      setVoidDraft((d) => ({ ...d, [ticket.id]: {} }));
      await loadDesk();
      flash(`券 ${ticket.code} 已作废并记入作废簿`);
    } catch (err) {
      flash(err.message, true);
    }
  }

  return (
    <div class="page">
      <header class="topbar">
        <div class="brand">
          <h1>数控刀补复核台</h1>
          <p class="hint">
            刀补绝对值不超过十二微米判合格，否则超差。交单须挂当日在用日券，入队与券核销同一事务落库。
          </p>
        </div>
        <Show when={user()}>
          <nav class="topnav">
            <a
              href="#/"
              class={route().name === "home" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goHome();
              }}
            >
              复核总览
            </a>
            <a
              href="#/desk"
              class={route().name === "desk" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goDesk();
              }}
            >
              日券台
            </a>
          </nav>
        </Show>
      </header>

      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>
      <Show when={notice()}>
        <div class="banner ok">{notice()}</div>
      </Show>

      <Show
        when={user()}
        fallback={
          <section class="card">
            <h2>登录</h2>
            <form onSubmit={handleLogin} class="form">
              <label>
                用户名
                <input
                  value={loginUser()}
                  onInput={(e) => setLoginUser(e.currentTarget.value)}
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={loginPass()}
                  onInput={(e) => setLoginPass(e.currentTarget.value)}
                />
              </label>
              <button type="submit">进入系统</button>
            </form>
            <p class="hint">操作员 machinist / machine123456；复核员 auditor / audit123456（只读）</p>
          </section>
        }
      >
        <section class="card toolbar">
          <div>
            当前用户：<strong>{user().username}</strong>（{roleLabel[user().role] || user().role}
            {user().can_write ? "，可发券/交单/作废" : "，只读观察"}）
          </div>
          <button type="button" class="ghost" onClick={handleLogout}>
            退出
          </button>
        </section>

        <Show when={route().name === "home"}>
          <Show when={user().can_write}>
            <section class="card">
              <h2>提交刀补（免券直提）</h2>
              <form onSubmit={handleSubmit} class="form inline">
                <label>
                  刀具编号
                  <input
                    placeholder="如 T01"
                    value={toolCode()}
                    onInput={(e) => setToolCode(e.currentTarget.value)}
                    required
                  />
                </label>
                <label>
                  刀补（微米）
                  <input
                    type="number"
                    value={offsetUm()}
                    onInput={(e) => setOffsetUm(e.currentTarget.value)}
                    required
                  />
                </label>
                <button type="submit">提交待复核</button>
              </form>
              <p class="hint">挂券交单请前往「日券台」。</p>
            </section>
          </Show>

          <section class="card">
            <div class="toolbar">
              <h2>复核列表</h2>
              <button type="button" class="ghost" onClick={loadRows} disabled={loading()}>
                {loading() ? "刷新中…" : "刷新"}
              </button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>刀具</th>
                  <th>刀补 µm</th>
                  <th>状态</th>
                  <th>结论</th>
                  <th>日券</th>
                  <th>提交时间</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <For each={rows()}>
                  {(row) => (
                    <tr>
                      <td>{row.tool_code}</td>
                      <td>{row.offset_um}</td>
                      <td>{statusLabel[row.status] || row.status}</td>
                      <td class={row.verdict === "合格" ? "pass" : row.verdict === "超差" ? "fail" : ""}>
                        {row.verdict || "—"}
                      </td>
                      <td>{row.ticket_code || "—"}</td>
                      <td>{new Date(row.created_at).toLocaleString()}</td>
                      <td>
                        <button type="button" class="ghost" onClick={() => goDetail(row.id)}>
                          详情
                        </button>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!rows().length && !loading()}>
              <p class="hint">暂无记录</p>
            </Show>
          </section>
        </Show>

        <Show when={route().name === "desk"}>
          <section class="card">
            <div class="toolbar">
              <h2>日券台 · 分发券区</h2>
              <Show when={user().can_write} fallback={<span class="hint">只读观察：可翻阅，不能发券/作废/交单</span>}>
                <button type="button" onClick={handleIssue}>
                  领取当日券
                </button>
              </Show>
            </div>
            <p class="hint">日券按自然日每操作员只发一张；仅当日「在用」券可挂单交单，旧券/已用/已作废一律挡回。</p>
            <table>
              <thead>
                <tr>
                  <th>券号</th>
                  <th>自然日</th>
                  <th>状态</th>
                  <th>归属</th>
                  <th>核销时间</th>
                  <Show when={user().can_write}><th>挂券交单 / 作废</th></Show>
                </tr>
              </thead>
              <tbody>
                <For each={tickets()}>
                  {(t) => {
                    const draft = () => redeemDraft()[t.id] || {};
                    const vdraft = () => voidDraft()[t.id] || {};
                    return (
                      <tr class={t.status === "valid" ? "ticket-valid" : ""}>
                        <td>{t.code}</td>
                        <td>{t.ticket_date}</td>
                        <td class={t.status === "valid" ? "pass" : t.status === "voided" ? "fail" : ""}>
                          {ticketStatusLabel[t.status] || t.status}
                          {t.status === "valid" && t.ticket_date !== localDateStr()
                            ? "（旧券）"
                            : ""}
                        </td>
                        <td>{t.issued_to}</td>
                        <td>{t.redeemed_at ? new Date(t.redeemed_at).toLocaleString() : "—"}</td>
                        <Show when={user().can_write}>
                          <td>
                            <Show when={t.status === "valid"} fallback={<span class="hint">不可操作</span>}>
                              <div class="redeem-row">
                                <input
                                  class="mini"
                                  placeholder="刀具如 T05"
                                  value={draft().tool_code || ""}
                                  onInput={(e) =>
                                    patchDraft(setRedeemDraft, t.id, { tool_code: e.currentTarget.value })
                                  }
                                />
                                <input
                                  class="mini"
                                  type="number"
                                  placeholder="µm"
                                  value={draft().offset_um ?? ""}
                                  onInput={(e) =>
                                    patchDraft(setRedeemDraft, t.id, { offset_um: e.currentTarget.value })
                                  }
                                />
                                <button type="button" onClick={() => handleRedeem(t)}>
                                  挂券交单
                                </button>
                                <input
                                  class="mini reason"
                                  placeholder="作废原因（可选）"
                                  value={vdraft().reason || ""}
                                  onInput={(e) =>
                                    patchDraft(setVoidDraft, t.id, { reason: e.currentTarget.value })
                                  }
                                />
                                <button type="button" class="danger" onClick={() => handleVoid(t)}>
                                  作废
                                </button>
                              </div>
                            </Show>
                          </td>
                        </Show>
                      </tr>
                    );
                  }}
                </For>
              </tbody>
            </table>
            <Show when={!tickets().length}>
              <p class="hint">暂无日券</p>
            </Show>
          </section>

          <section class="card">
            <h2>作废簿</h2>
            <table>
              <thead>
                <tr>
                  <th>券号</th>
                  <th>自然日</th>
                  <th>作废人</th>
                  <th>原因</th>
                  <th>作废时间</th>
                </tr>
              </thead>
              <tbody>
                <For each={voided()}>
                  {(v) => (
                    <tr>
                      <td>{v.code}</td>
                      <td>{v.ticket_date}</td>
                      <td>{v.voided_by || "—"}</td>
                      <td>{v.reason || "—"}</td>
                      <td>{new Date(v.voided_at).toLocaleString()}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!voided().length}>
              <p class="hint">暂无作废记录</p>
            </Show>
          </section>
        </Show>

        <Show when={route().name === "detail"}>
          <section class="card">
            <div class="toolbar">
              <h2>刀补详情</h2>
              <button type="button" class="ghost" onClick={goHome}>
                返回总览
              </button>
            </div>
            <Show when={detail()} fallback={<p class="hint">{loading() ? "加载中…" : "未找到记录"}</p>}>
              {(d) => (
                <div class="detail-grid">
                  <p>编号：{d().id}</p>
                  <p>刀具：{d().tool_code}</p>
                  <p>刀补 µm：{d().offset_um}</p>
                  <p>状态：{statusLabel[d().status] || d().status}</p>
                  <p class={d().verdict === "合格" ? "pass" : d().verdict === "超差" ? "fail" : ""}>
                    结论：{d().verdict || "—"}
                  </p>
                  <p>日券：{d().ticket_code || "—"}</p>
                  <p>提交时间：{new Date(d().created_at).toLocaleString()}</p>
                  <p>
                    复核时间：
                    {d().reviewed_at ? new Date(d().reviewed_at).toLocaleString() : "—"}
                  </p>
                </div>
              )}
            </Show>
          </section>
        </Show>
      </Show>
    </div>
  );
}

export default App;
