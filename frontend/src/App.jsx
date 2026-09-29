import { createSignal, onMount, Show, For, createEffect } from "solid-js";
import {
  clearSession,
  createSubmission,
  distributeTickets,
  fetchSubmission,
  fetchSubmissions,
  fetchTodayTickets,
  fetchVoidedTickets,
  getUser,
  login,
  setSession,
} from "./api";

const statusLabel = {
  pending: "待复核",
  processing: "复核中",
  done: "已完成",
};

const roleLabel = {
  machinist: "操作员",
  auditor: "复核员（只读观察）",
};

const ticketStateLabel = {
  valid: "在用",
  voided: "已作废",
};

function readHash() {
  const raw = (location.hash || "#/").replace(/^#/, "") || "/";
  const m = raw.match(/^\/detail\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  if (raw.startsWith("/tickets")) return { name: "tickets", id: null };
  return { name: "home", id: null };
}

function fmt(ts) {
  return ts ? new Date(ts).toLocaleString() : "—";
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

  const [todayTickets, setTodayTickets] = createSignal([]);
  const [voidedTickets, setVoidedTickets] = createSignal([]);
  const [ticketCode, setTicketCode] = createSignal("");
  const [ticketsLoading, setTicketsLoading] = createSignal(false);
  const [submitting, setSubmitting] = createSignal(false);

  function goHome() {
    location.hash = "#/";
  }

  function goTickets() {
    location.hash = "#/tickets";
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
    setError("");
    try {
      setRows(await fetchSubmissions());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id) {
    setLoading(true);
    setError("");
    try {
      setDetail(await fetchSubmission(id));
    } catch (e) {
      setError(e.message);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadTickets() {
    setTicketsLoading(true);
    try {
      const [today, voided] = await Promise.all([
        fetchTodayTickets(),
        fetchVoidedTickets(),
      ]);
      setTodayTickets(today);
      setVoidedTickets(voided);
      const valid = today.filter((t) => t.valid_today);
      // 保留仍有效的已选券，否则默认选第一张在用券。
      setTicketCode((prev) =>
        valid.some((t) => t.code === prev) ? prev : valid[0]?.code || ""
      );
    } catch (e) {
      flash(e.message, true);
    } finally {
      setTicketsLoading(false);
    }
  }

  onMount(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    if (user()) {
      if (route().name === "detail") loadDetail(route().id);
      else if (route().name === "tickets") loadTickets();
      else loadRows();
    }
    return () => window.removeEventListener("hashchange", onHash);
  });

  createEffect(() => {
    const r = route();
    if (!user()) return;
    if (r.name === "detail" && r.id) loadDetail(r.id);
    if (r.name === "home") loadRows();
    if (r.name === "tickets") loadTickets();
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
      setError(err.message);
    }
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setRows([]);
    setDetail(null);
    setTodayTickets([]);
    setVoidedTickets([]);
    goHome();
  }

  async function handleDistribute(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    try {
      const got = await distributeTickets();
      const valid = got.filter((t) => t.valid_today).length;
      flash(`今日券已就位：共 ${got.length} 张，其中在用 ${valid} 张。按自然日只发一次，重复点击不重发。`);
      await loadTickets();
    } catch (err) {
      flash(err.message, true);
    }
  }

  async function handleSubmitTicket(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    setSubmitting(true);
    try {
      const saved = await createSubmission(ticketCode(), toolCode(), offsetUm());
      setToolCode("");
      setOffsetUm("");
      flash(`已用券 ${saved.ticket_code} 挂单交单，进入待复核；该券同事务作废，不可再用。`);
      await loadTickets();
    } catch (err) {
      flash(err.message, true);
      await loadTickets();
    } finally {
      setSubmitting(false);
    }
  }

  const validTickets = () => todayTickets().filter((t) => t.valid_today);

  return (
    <div class="page">
      <header class="topbar">
        <div class="brand">
          <h1>数控刀补复核台</h1>
          <p class="hint">
            刀补日券按自然日每操作员每日五张；交单必须挂一张当日仍有效的券，挂错、挂旧、挂作废一律挡回。入队与券作废同一事务落库。
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
              href="#/tickets"
              class={route().name === "tickets" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goTickets();
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
            当前用户：<strong>{user().username}</strong>（{roleLabel[user().role] || user().role}）
          </div>
          <button type="button" class="ghost" onClick={handleLogout}>
            退出
          </button>
        </section>

        <Show when={route().name === "home"}>
          <section class="card">
            <div class="toolbar">
              <h2>复核列表</h2>
              <div class="row-actions">
                <Show when={user().can_write}>
                  <button type="button" class="ghost" onClick={goTickets}>
                    去日券台挂券交单
                  </button>
                </Show>
                <button type="button" class="ghost" onClick={loadRows} disabled={loading()}>
                  {loading() ? "刷新中…" : "刷新"}
                </button>
              </div>
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
                      <td>{fmt(row.created_at)}</td>
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

        <Show when={route().name === "tickets"}>
          {/* 分发券区 */}
          <section class="card">
            <div class="toolbar">
              <h2>分发券区</h2>
              <button type="button" class="ghost" onClick={loadTickets} disabled={ticketsLoading()}>
                {ticketsLoading() ? "刷新中…" : "刷新"}
              </button>
            </div>
            <p class="hint">
              今日共 {todayTickets().length} 张券，在用 {validTickets().length} 张，已作废{" "}
              {todayTickets().filter((t) => !t.valid_today).length} 张。
            </p>
            <Show
              when={user().can_write}
              fallback={<p class="hint">只读观察账号：可翻看券，不能发券。</p>}
            >
              <button type="button" onClick={handleDistribute}>
                发放 / 补齐当日五张券
              </button>
            </Show>
          </section>

          {/* 在用券 + 挂券交单 */}
          <section class="card">
            <h2>在用券（当日有效）</h2>
            <Show
              when={user().can_write}
              fallback={<p class="hint">只读观察账号：可查看在用券，不能挂券交单。</p>}
            >
              <Show
                when={validTickets().length}
                fallback={<p class="hint">今日暂无在用券，请到上方「分发券区」发券。</p>}
              >
                <form onSubmit={handleSubmitTicket} class="form">
                  <label>
                    挂用日券
                    <select
                      value={ticketCode()}
                      onChange={(e) => setTicketCode(e.currentTarget.value)}
                    >
                      <For each={validTickets()}>
                        {(t) => <option value={t.code}>{t.code}</option>}
                      </For>
                    </select>
                  </label>
                  <div class="form inline">
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
                  </div>
                  <button type="submit" disabled={submitting() || !ticketCode()}>
                    {submitting() ? "交单中…" : "挂券交单（入待复核）"}
                  </button>
                </form>
              </Show>
            </Show>

            <table>
              <thead>
                <tr>
                  <th>券号</th>
                  <th>自然日</th>
                  <th>属主</th>
                  <th>状态</th>
                  <th>发放时间</th>
                </tr>
              </thead>
              <tbody>
                <For each={todayTickets()}>
                  {(t) => (
                    <tr>
                      <td>{t.code}</td>
                      <td>{t.issue_date}</td>
                      <td>{t.issued_to}</td>
                      <td class={t.valid_today ? "pass" : "muted"}>
                        {ticketStateLabel[t.state] || t.state}
                      </td>
                      <td>{fmt(t.issued_at)}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!todayTickets().length && !ticketsLoading()}>
              <p class="hint">今日尚无券。</p>
            </Show>
          </section>

          {/* 作废簿 */}
          <section class="card">
            <h2>作废簿</h2>
            <table>
              <thead>
                <tr>
                  <th>券号</th>
                  <th>自然日</th>
                  <th>属主</th>
                  <th>作废时间</th>
                  <th>关联交单</th>
                </tr>
              </thead>
              <tbody>
                <For each={voidedTickets()}>
                  {(t) => (
                    <tr>
                      <td>{t.code}</td>
                      <td>{t.issue_date}</td>
                      <td>{t.issued_to}</td>
                      <td>{fmt(t.voided_at)}</td>
                      <td>
                        <Show when={t.submission_id} fallback={"—"}>
                          <button type="button" class="ghost" onClick={() => goDetail(t.submission_id)}>
                            #{t.submission_id}
                          </button>
                        </Show>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!voidedTickets().length && !ticketsLoading()}>
              <p class="hint">作废簿为空。</p>
            </Show>
            <p class="hint">作废券仅作留档，任何人不能在此复活或重用作废券。</p>
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
                  <p>挂用日券：{d().ticket_code || "—"}</p>
                  <p>提交时间：{fmt(d().created_at)}</p>
                  <p>复核时间：{fmt(d().reviewed_at)}</p>
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
