"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = { tasks: [], task: null, health: null, csrf: "", run: null, busy: false, sample: 0, hints: {}, quizzes: [], quizIndex: 0, quizChoice: null, quizResult: null, view: "workspace", provider: null, taskFilter: "core", artifactUrl: "" };
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const valueLabel = (value) => value === -999 ? "U / X" : String(value);
const statusNames = { passed: "通过", failed: "有反例", compile_error: "编译未通过", runtime_error: "运行未完成", limit: "执行超限" };
let toastTimer;

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5000);
}

async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Zhidian-Token": state.csrf }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function readLocal(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeLocal(key, value) { try { localStorage.setItem(key, value); } catch { /* The app also works with browser storage disabled. */ } }
function removeLocal(key) { try { localStorage.removeItem(key); } catch { /* optional */ } }

function updateCodeGutter() {
  const editor = $("#source-code");
  $("#line-numbers").textContent = Array.from({ length: editor.value.split("\n").length }, (_, index) => index + 1).join("\n");
  $("#line-numbers").scrollTop = editor.scrollTop;
  const changed = state.run && editor.value !== state.run.source;
  $("#code-state").textContent = state.busy ? "源码已锁定 · 本次检查完成后可编辑" : changed ? (state.run.reference_run ? "结果对应参考版本 · 可在右侧应用" : "代码已修改 · 请重新检查") : state.run ? "当前代码已有实验记录 · Ctrl + Enter 重新运行" : "可编辑示例 · Ctrl + Enter 运行";
  $("#code-state").classList.toggle("stale-note", Boolean(changed));
}

function setSource(source, save = true) {
  $("#source-code").value = source;
  $("#source-code").scrollTop = 0;
  updateCodeGutter();
  if (save && state.task) writeLocal(`zhidian-draft-${state.task.id}`, source);
}

function renderTasks() {
  const tasks = state.tasks.filter(task => state.taskFilter === "all" || Boolean(task.chapter) === (state.taskFilter === "extended"));
  const counts = {core:state.tasks.filter(task=>!task.chapter).length,extended:state.tasks.filter(task=>task.chapter).length,all:state.tasks.length};
  const names = {core:"基础实验",extended:"课程扩展",all:"全部实验"};
  $$("[data-task-filter]").forEach(button=>{ const group=button.dataset.taskFilter; button.textContent=`${names[group]} ${counts[group]}`; button.classList.toggle("active",state.taskFilter===group); button.setAttribute("aria-pressed",String(state.taskFilter===group)); button.disabled=state.busy; });
  $("#task-grid").innerHTML = tasks.map((task) => `<button class="task-card ${state.task?.id === task.id ? "selected" : ""}" data-task="${task.id}" aria-pressed="${state.task?.id === task.id}" ${state.busy ? "disabled" : ""}><span class="task-top"><span class="task-number">LAB / ${task.number}</span><span class="task-category">${escapeHTML(task.category)}</span></span><span class="task-title">${escapeHTML(task.title)}</span><span class="task-subtitle">${escapeHTML(task.subtitle)}</span><span class="selected-indicator" aria-hidden="true">↗</span></button>`).join("");
}

async function selectTask(taskId, sourceOverride, keepRun = false) {
  if (state.busy && !keepRun) return;
  const task = state.tasks.find((item) => item.id === taskId);
  if (!task) return;
  state.task = task;
  if(state.taskFilter !== "all") state.taskFilter = task.chapter ? "extended" : "core";
  if (!keepRun) {
    state.run = null;
    state.hints = {};
    state.sample = 0;
    $("#diagnosis-content").hidden = true;
    $("#empty-state").hidden = false;
    $("#trace-list").innerHTML = "";
    $("#trace-count").textContent = "0";
    $("#run-status").textContent = "等待运行";
    $("#run-status").className = "live-label";
    $("#export-button").disabled = true;
    setEvidenceTab("diagnosis");
    renderWave();
  }
  renderTasks();
  $("#task-description").textContent = task.description;
  $("#task-basis").hidden = !task.chapter;
  $("#task-basis").textContent = task.chapter ? `标题映射：${task.chapter}。${task.basis} 验证范围：${task.verification_limit}` : "";
  $("#contract-title").textContent = task.title + " · 实验约束";
  $("#requirements").innerHTML = task.requirements.map((line) => `<li>${escapeHTML(line)}</li>`).join("");
  $("#task-ports").textContent = task.ports;
  $("#filename").textContent = task.filename;
  setSource(sourceOverride ?? readLocal(`zhidian-draft-${task.id}`) ?? task.starter, false);
  state.quizIndex = 0;
  state.quizChoice = null;
  state.quizResult = null;
  try {
    const result = await api(`/api/quizzes?task_id=${task.id}`);
    if (state.task.id !== task.id) return;
    state.quizzes = result.quizzes;
    renderQuiz();
  } catch (error) { toast(error.message); }
}

function setBusy(busy) {
  state.busy = busy;
  $("#run-button").disabled = busy || !state.health?.ghdl;
  $("#run-button").classList.toggle("running", busy);
  $("#run-button span").textContent = busy ? "正在检查" : "检查并诊断";
  $("#source-code").readOnly = busy;
  ["#reset-button", "#import-button", "#run-mode", "#student-question", "#start-demo"].forEach((selector) => { $(selector).disabled = busy; });
  renderTasks();
  updateCodeGutter();
}

function setEvidenceTab(tab) {
  $$("[data-evidence]").forEach((button) => { button.setAttribute("aria-selected", String(button.dataset.evidence === tab)); });
  $("#diagnosis-panel").hidden = tab !== "diagnosis";
  $("#trace-panel").hidden = tab !== "trace";
}

function renderTrace() {
  const events = state.run?.events || [];
  $("#trace-count").textContent = String(events.length);
  $("#trace-list").innerHTML = events.length ? events.map((event) => `<li><span class="trace-icon ${escapeHTML(event.state)}" aria-label="${event.state === "running" ? "运行中" : "已返回"}">${({ done: "✓", attention: "!", skipped: "–", running: "" })[event.state] || "·"}</span><div class="trace-title"><span>${escapeHTML(event.title)}</span><small>${escapeHTML(event.at.slice(11, 19))}</small></div><p>${escapeHTML(event.detail)}</p></li>`).join("") : '<li class="muted">运行后显示工具轨迹。</li>';
}

function renderDiagnosis() {
  const job = state.run;
  if (!job) return;
  $("#empty-state").hidden = true;
  const container = $("#diagnosis-content");
  container.hidden = false;
  if (job.status === "error") {
    container.innerHTML = `<div class="diagnosis-inner"><div class="result-banner compile"><div class="result-eyebrow">本次执行未完成</div><h3>请检查运行条件</h3><p>${escapeHTML(job.error)}</p></div></div>`;
    return;
  }
  if (!job.result) {
    container.innerHTML = '<div class="working-message"><span class="spinner"></span><p>正在调用本机 GHDL…<br>检查点与结论将在真实结果返回后显示。</p></div>';
    return;
  }
  const result = job.result;
  const diagnosis = job.diagnosis;
  const isPass = result.passed;
  const kind = isPass ? "pass" : result.compiled && result.completed ? "" : "compile";
  const improvedCoverage = job.smoke?.passed && !result.passed && result.completed;
  let html = `<div class="diagnosis-inner"><div class="result-banner ${kind}"><div class="result-eyebrow">${job.reference_run ? "教学参考版本 · 独立验证" : job.mode === "model" ? "真实仿真结果 · 模型增强" : "真实仿真结果 · 本地证据诊断"}</div><h3>${escapeHTML(diagnosis.title)}</h3><p>${escapeHTML(diagnosis.explanation)}</p></div>`;
  if (result.completed) {
    html += `<div class="result-metrics"><div class="metric-box"><strong>${result.total - result.failed}<span> / ${result.total}</span></strong><span>检查点通过</span></div><div class="metric-box"><strong>${result.failed}</strong><span>不一致检查点</span></div><div class="metric-box"><strong>${(result.duration_ms / 1000).toFixed(1)}<span> s</span></strong><span>完整测试耗时</span></div></div>`;
  }
  if (improvedCoverage) html += '<p class="run-summary-note">基础检查通过，补充边界后发现反例。普通输入通过，仍可能遗漏关键条件。</p>';
  html += `<div class="evidence-fact"><span>${escapeHTML(diagnosis.evidence)}${diagnosis.line ? `<button class="line-button" data-line="${diagnosis.line}">查看相关行 L${diagnosis.line}</button>` : ""}</span></div>`;
  if (job.status === "running" && job.mode === "model") html += '<div class="faint-note"><span class="spinner"></span> 模型正在结合证据选择工具，已有仿真结果可先查看。</div>';
  if (job.model) html += `<div class="model-copy"><strong>模型教学解释 · ${escapeHTML(job.model.model)}</strong>${escapeHTML(job.model.text)}</div>`;
  if (job.model_error) html += `<div class="model-error">${escapeHTML(job.model_error)}</div>`;
  if (job.candidate) {
    const candidate = job.candidate;
    const challenges = candidate.challenges || [];
    const challengeInfo = challenges.length ? `<div class="challenge-summary"><p>公开测试：${candidate.result.total - candidate.result.failed}/${candidate.result.total}；追加验证：${challenges.filter(row => row.passed).length}/${challenges.length} 组通过。</p><p>${candidate.challenge_kind === "exhaustive_reorder" ? "有限输入已穷举，追加验证重排输入顺序。" : "接收候选代码后生成新种子，补充随机输入与时序序列。"}</p><details><summary class="text-button">查看追加验证证据</summary>${challenges.map((row, i) => `<p>第 ${i + 1} 组：${row.total - row.failed}/${row.total}，种子 ${row.seed}${row.wave_url ? ` · <a href="${escapeHTML(row.wave_url)}" download>下载 VCD</a>` : ""}</p><code>测试平台 SHA-256：${escapeHTML(row.testbench_hash)}</code>`).join("")}</details></div>` : "";
    html += `<div class="candidate-card"><strong>${candidate.verified ? (challenges.length ? "候选修改通过公开测试与两组追加验证" : "候选修改已通过完整测试") : "候选修改尚未通过验证"}</strong><p>${escapeHTML(candidate.explanation)}</p>${challengeInfo}<details><summary class="text-button">查看候选源码</summary><pre>${escapeHTML(candidate.source)}</pre></details>${candidate.verified ? '<button class="button button-outline small" data-apply="candidate">应用已验证的候选版本</button>' : '<p>不能标记为已修复。请继续依据实际证据检查。</p>'}</div>`;
  }
  if (job.reference_run) {
    html += `<div class="candidate-card"><strong>内置教学参考实现</strong><p>参考代码在独立目录完成仿真。当前编辑器仍可保留原来的代码。</p><details><summary class="text-button">查看参考源码</summary><pre>${escapeHTML(job.source)}</pre></details><button class="button button-outline small" data-apply="reference" ${result.passed ? "" : "disabled"}>应用本次已验证参考版本</button></div>`;
  }
  html += '<div class="hints-header">分层提示<span>先观察，再逐步展开</span></div>';
  for (let level = 1; level <= 3; level++) {
    const hint = state.hints[level];
    html += `<div class="hint-row"><button class="hint-toggle" data-hint="${level}" aria-expanded="${Boolean(hint)}"><span><span class="hint-level">0${level}</span>${["", "先观察反例", "联系核心概念", "查看修改方向"][level]}</span><span>${hint ? "−" : "+"}</span></button>${hint ? `<p class="hint-text">${escapeHTML(hint)}</p>` : ""}</div>`;
  }
  if (!job.reference_run && !isPass && job.status === "complete") html += '<div class="reference-action"><p>卡住时，可对照独立验证的教学参考实现。</p><button class="text-button" data-reference>参考修复并验证 ↗</button></div>';
  html += '<p class="faint-note">证据只覆盖本题测试范围；相关行提示属于候选定位。</p></div>';
  container.innerHTML = html;
}

function renderRun() {
  const job = state.run;
  if (!job) return;
  renderTrace();
  renderDiagnosis();
  const label = $("#run-status");
  if (job.status === "running") {
    label.textContent = "工具运行中";
    label.className = "live-label busy";
  } else if (job.status === "error") {
    label.textContent = "执行未完成";
    label.className = "live-label failed";
  } else {
    label.textContent = statusNames[job.result.status] || "检查已结束";
    label.className = "live-label " + (job.result.passed ? "passed" : "failed");
  }
  $("#export-button").disabled = job.status !== "complete";
  renderWave();
  updateCodeGutter();
}

async function pollRun(runId) {
  let failures = 0;
  while (true) {
    try {
      const job = await api(`/api/runs/${runId}`);
      if (state.run && state.run.id !== runId) return;
      failures = 0;
      const hadResult = Boolean(state.run?.result);
      state.run = job;
      if (!hadResult && job.result?.checks?.length) {
        const first = job.result.checks.findIndex((check) => !check.passed);
        state.sample = first >= 0 ? first : 0;
      }
      renderRun();
      if (job.status !== "running") {
        setBusy(false);
        removeLocal("zhidian-pending");
        if (job.status === "complete") {
          setEvidenceTab("diagnosis");
          toast(job.result.passed ? "当前测试集已通过。再用变式题检验理解。" : "已取得真实检查结果，可查看反例与分层提示。");
        } else toast(job.error || "实验未完成。");
        return;
      }
    } catch (error) {
      failures += 1;
      if (failures >= 3) {
        setBusy(false);
        toast("服务连接中断。刷新页面可尝试恢复这次实验。");
        return;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 650));
  }
}

async function startRun(action) {
  if (state.busy) return;
  const mode = action === "reference" ? "local" : $("#run-mode").value;
  if (mode === "model" && !state.provider?.configured) { openSettings(); return; }
  const source = $("#source-code").value;
  writeLocal(`zhidian-draft-${state.task.id}`, source);
  try {
    const run = await api("/api/run", { task_id: state.task.id, source, mode, question: $("#student-question").value, action });
    state.run = { id: run.id, status: "running", events: [], result: null, source };
    state.hints = {};
    state.sample = 0;
    setBusy(true);
    renderRun();
    setEvidenceTab("trace");
    writeLocal("zhidian-pending", run.id);
    pollRun(run.id);
  } catch (error) { toast(error.message); }
}

function setDataTab(tab) {
  $$("[data-data]").forEach((button) => { const selected = button.dataset.data === tab; button.classList.toggle("active", selected); button.setAttribute("aria-selected", String(selected)); });
  ["wave", "checks", "logs", "artifacts"].forEach((name) => { $(`#${name}-data-panel`).hidden = name !== tab; });
  if(tab === "artifacts") showArtifact();
}

async function showArtifact() {
  const url = $("#artifact-select").value;
  const download = $("#artifact-download");
  download.hidden = !url;
  if(!url) { $("#artifact-source").textContent="本次运行暂无验证资料。"; return; }
  download.href=url; download.download=url.split("/").pop();
  if(state.artifactUrl === url) return;
  state.artifactUrl=url;
  $("#artifact-source").textContent="正在读取本次实验文件…";
  try {
    const response = await fetch(url);
    if(!response.ok) throw new Error("验证文件读取失败。");
    const content = await response.text();
    if(state.artifactUrl===url) $("#artifact-source").textContent=content.length>80000 ? content.slice(0,80000)+"\n[预览已截断，完整文件可下载]" : content;
  } catch(error) { if(state.artifactUrl===url) { state.artifactUrl=""; $("#artifact-source").textContent=error.message; } }
}

function renderWave() {
  const result = state.run?.result;
  const checks = result?.checks || [];
  $("#wave-placeholder").hidden = checks.length > 0;
  $("#wave-content").hidden = checks.length === 0;
  const failed = checks.some((check) => !check.passed);
  $("#previous-failure").disabled = !failed;
  $("#next-failure").disabled = !failed;
  const link = $("#vcd-download");
  link.hidden = !result?.wave_url;
  if (result?.wave_url) { link.href = result.wave_url; link.download = "wave.vcd"; }
  $("#tool-log").textContent = result?.log || "尚未取得 GHDL 工具输出。";
  const artifactSelect=$("#artifact-select"), previousArtifact=artifactSelect.value;
  artifactSelect.innerHTML=(result?.files||[]).map(file=>`<option value="${escapeHTML(file.url)}">${escapeHTML(file.label)}</option>`).join("");
  if((result?.files||[]).some(file=>file.url===previousArtifact)) artifactSelect.value=previousArtifact;
  if(!$("#artifacts-data-panel").hidden) showArtifact();
  $("#checks-body").innerHTML = checks.length ? checks.map((row, index) => `<tr class="${row.passed ? "" : "failed-row"}"><td><button class="text-button" data-sample="${index}">#${row.index}</button></td><td>${row.time_ns} ns</td><td>${escapeHTML(row.inputs)}</td><td>${row.expected}</td><td>${escapeHTML(valueLabel(row.actual))}</td><td>${row.passed ? "✓ 一致" : "! 不一致"}</td></tr>`).join("") : '<tr><td colspan="6">尚无功能检查点。</td></tr>';
  if (!checks.length) return;
  state.sample = Math.min(Math.max(0, state.sample), checks.length - 1);
  const width = 1000, left = 88, right = 25, plotWidth = width - left - right;
  const minTime = 0, maxTime = Math.max(checks[checks.length - 1].time_ns, 1);
  const values = checks.flatMap((row) => [row.actual, row.expected]).filter((value) => value !== -999);
  const minValue = Math.min(0, ...values), maxValue = Math.max(1, ...values), range = maxValue - minValue;
  const x = (time) => left + ((time - minTime) / maxTime) * plotWidth;
  const y = (value, lane) => lane + 22 - ((value - minValue) / range) * 42;
  const path = (field, lane) => checks.map((row, index) => `${index ? "H" : "M"}${x(row.time_ns).toFixed(2)}${index ? " V" : " "}${y(row[field] === -999 ? minValue : row[field], lane).toFixed(2)}`).join(" ");
  let svg = `<svg viewBox="0 0 ${width} 205" role="img" aria-label="参考输出与实际输出的离散采样图，点击选择检查点"><rect x="${left}" y="22" width="${plotWidth}" height="148" rx="3" fill="#fbfcf8"/>`;
  for (let tick = 0; tick <= 8; tick++) {
    const position = left + tick / 8 * plotWidth;
    svg += `<line x1="${position}" x2="${position}" y1="22" y2="170" stroke="#e9eee3" stroke-width="1" stroke-dasharray="3 5"/><text x="${position}" y="189" text-anchor="middle">${Math.round(tick / 8 * maxTime)}</text>`;
  }
  checks.forEach((row) => { if (!row.passed) svg += `<rect x="${x(row.time_ns)-2.5}" y="25" width="5" height="140" fill="#e6b994" opacity=".2"/>`; });
  svg += `<text x="16" y="61">参考值</text><text x="16" y="136">实际值</text><text x="991" y="189" text-anchor="end">ns</text><line x1="${left}" y1="96" x2="${width-right}" y2="96" stroke="#e6eddd" stroke-width="1"/><path d="${path("expected", 57)}" fill="none" stroke="#779b69" stroke-width="2.1"/><path d="${path("actual", 132)}" fill="none" stroke="#c79169" stroke-width="2.1"/>`;
  const current = checks[state.sample], cursorX = x(current.time_ns);
  svg += `<line x1="${cursorX}" x2="${cursorX}" y1="16" y2="171" stroke="#879c77" stroke-width="1.1" stroke-dasharray="4 3"/><circle cx="${cursorX}" cy="${y(current.expected,57)}" r="3.7" fill="#fff" stroke="#779b69" stroke-width="1.5"/><circle cx="${cursorX}" cy="${y(current.actual === -999 ? minValue : current.actual,132)}" r="3.7" fill="#fff" stroke="#c79169" stroke-width="1.5"/><text x="${Math.min(cursorX+8,930)}" y="15">#${current.index} · ${current.time_ns} ns</text></svg>`;
  $("#wave-chart").innerHTML = svg;
  $("#sample-inspector").innerHTML = `<span>检查点 <strong>#${current.index}</strong></span><span>时间 <strong>${current.time_ns} ns</strong></span><span>${escapeHTML(current.inputs)}</span><span>预期 <strong>${current.expected}</strong></span><span>实际 <strong>${escapeHTML(valueLabel(current.actual))}</strong></span><span class="sample-status ${current.passed ? "pass" : ""}">${current.passed ? "输出一致" : "发现反例"}</span>`;
}

function nextFailure(direction) {
  const checks = state.run?.result?.checks || [];
  if (!checks.length) return;
  let index = state.sample;
  for (let count = 0; count < checks.length; count++) {
    index = (index + direction + checks.length) % checks.length;
    if (!checks[index].passed) { state.sample = index; renderWave(); setDataTab("wave"); return; }
  }
}

function renderQuiz() {
  const quiz = state.quizzes[state.quizIndex];
  if (!quiz) { $("#quiz-area").textContent = "暂无练习。"; return; }
  $("#practice-progress").textContent = `${String(state.quizIndex + 1).padStart(2, "0")} / ${String(state.quizzes.length).padStart(2, "0")} · ${state.task.concept_name}`;
  const done = Boolean(state.quizResult);
  $("#quiz-area").innerHTML = `<h3 class="quiz-title">${escapeHTML(quiz.question)}</h3><div class="quiz-options">${quiz.options.map((option, index) => `<button class="quiz-option ${state.quizChoice === index ? "selected" : ""} ${done && state.quizResult.answer === index ? "correct" : ""} ${done && !state.quizResult.correct && state.quizChoice === index ? "wrong" : ""}" data-choice="${index}" aria-pressed="${state.quizChoice === index}" ${done ? "disabled" : ""}><span>${String.fromCharCode(65 + index)}</span>${escapeHTML(option)}</button>`).join("")}</div>${done ? `<p class="quiz-feedback">${state.quizResult.correct ? "✓ 本题回答正确。" : "再想一步："}${escapeHTML(state.quizResult.explanation)}</p>` : ""}<div class="quiz-bottom"><span class="muted">${done ? "本次练习结果已记入学习轨迹" : "按本题规格推理，再做选择"}</span>${done ? '<button class="button button-outline" id="next-quiz">换一道变式题 →</button>' : `<button class="button button-outline" id="submit-quiz" ${state.quizChoice === null ? "disabled" : ""}>检验理解</button>`}</div>`;
}

async function submitQuiz() {
  if (state.quizChoice === null || state.quizResult) return;
  const button = $("#submit-quiz");
  if (button) button.disabled = true;
  try {
    state.quizResult = await api("/api/quiz", { quiz_id: state.quizzes[state.quizIndex].id, choice: state.quizChoice });
    renderQuiz();
  } catch (error) { toast(error.message); if (button) button.disabled = false; }
}

function navigate(view) {
  const names = { workspace: "实验工作台", learning: "学习轨迹", about: "作品说明" };
  state.view = names[view] ? view : "workspace";
  ["workspace", "learning", "about"].forEach((name) => { $(`#${name}-view`).hidden = state.view !== name; });
  $$("[data-view]").forEach((link) => { link.classList.toggle("active", link.dataset.view === state.view); link.setAttribute("aria-current", link.dataset.view === state.view ? "page" : "false"); });
  $("#page-name").textContent = names[state.view];
  if (state.view === "learning") refreshLearning();
}

async function refreshLearning() {
  try {
    const [profile, history] = await Promise.all([api("/api/profile"), api("/api/history")]);
    $("#learning-stats").innerHTML = [[profile.run_count, "已保存实验"], [profile.passed_runs, "非参考运行通过"], [profile.quiz_count, "理解检查作答"], [profile.quiz_correct, "本次作答正确累计"]].map(([value, label]) => `<div class="stat-card"><strong>${value}</strong><span>${label}</span></div>`).join("");
    $("#concept-grid").innerHTML = profile.concepts.map((concept) => `<article class="concept-card"><span class="concept-state">${escapeHTML(concept.state)}</span><h3>${escapeHTML(concept.name)}</h3><p>实验 ${concept.runs} 次 · 非参考通过 ${concept.passed_runs} 次<br>理解检查 ${concept.quiz_correct} / ${concept.quiz_count} 次答对</p><button class="text-button" data-practice="${concept.task_id}">回到实验与练习 ↗</button></article>`).join("");
    $("#history-list").innerHTML = history.runs.length ? history.runs.map((run) => `<button class="history-row" data-history="${run.id}"><span class="task-number">${escapeHTML(state.tasks.find((task) => task.id === run.task_id)?.number || "")}</span><div><strong>${escapeHTML(run.task_title)}${run.reference_run ? " · 参考验证" : ""}</strong><small>${escapeHTML(run.summary.title)}</small></div><span class="history-status ${run.status === "passed" ? "pass" : ""}">${escapeHTML(statusNames[run.status] || run.status)} · ${run.total - run.failed}/${run.total}</span><time>${escapeHTML(run.created.slice(0, 16).replace("T", " "))}</time><span>↗</span></button>`).join("") : '<div class="empty-history">完成第一次实验后，你的运行记录会出现在这里。</div>';
  } catch (error) { toast(error.message); }
}

async function loadHistory(runId) {
  if (state.busy) { toast("请等待当前实验完成后再查看历史。"); return; }
  try {
    const run = await api(`/api/runs/${runId}`);
    state.run = run;
    state.hints = {};
    await selectTask(run.task_id, run.source, true);
    $("#run-mode").value = run.mode;
    $("#question-wrap").hidden = run.mode !== "model";
    $("#student-question").value = run.question || "";
    const failure = run.result.checks.findIndex((check) => !check.passed);
    state.sample = failure >= 0 ? failure : 0;
    location.hash = "workspace";
    navigate("workspace");
    renderRun();
    setEvidenceTab("diagnosis");
  } catch (error) { toast(error.message); }
}

function updateProvider(provider) {
  state.provider = provider;
  $("#provider-badge").innerHTML = `<span></span>${provider.configured ? "模型已配置 · 本地工具就绪" : "本地证据模式"}`;
  $("#api-base").value = provider.base;
  $("#api-model").value = provider.model;
  $("#api-protocol").value = provider.protocol;
  syncPreset();
  $("#settings-current").textContent = provider.configured ? `当前：${provider.model} · 配置已就绪，网络调用以实际运行结果为准。` : "当前未配置模型。11 组实验的本地证据诊断仍可使用。";
}

function syncPreset() {
  const free = $("#api-base").value.replace(/\/+$/, "") === "https://openrouter.ai/api/v1" && $("#api-model").value === "openrouter/free" && $("#api-protocol").value === "chat_completions";
  $("#provider-preset").value = free ? "free" : "custom";
  $("#preset-note").textContent = free ? "免费预设使用 openrouter/free，由平台选择支持工具调用的免费模型。需申请 API Key；有额度和可用性限制，不会自动切换付费模型。" : "请在服务商控制台确认免费额度和模型的工具调用支持。接口兼容并不代表模型免费。";
}

function openSettings() { updateProvider(state.provider); $("#api-key").value = ""; $("#settings-dialog").showModal(); }

function downloadText(text, filename, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function bindEvents() {
  $("#task-filters").addEventListener("click",event=>{ const button=event.target.closest("[data-task-filter]"); if(!button || state.busy) return; state.taskFilter=button.dataset.taskFilter; renderTasks(); if(state.taskFilter!=="all" && Boolean(state.task?.chapter)!==(state.taskFilter==="extended")) { const task=state.tasks.find(task=>Boolean(task.chapter)===(state.taskFilter==="extended")); if(task) selectTask(task.id); } });
  $("#artifact-select").addEventListener("change",showArtifact);
  $("#task-grid").addEventListener("click", (event) => { const button = event.target.closest("[data-task]"); if (button) selectTask(button.dataset.task); });
  $("#source-code").addEventListener("input", () => { updateCodeGutter(); writeLocal(`zhidian-draft-${state.task.id}`, $("#source-code").value); });
  $("#source-code").addEventListener("scroll", () => { $("#line-numbers").scrollTop = $("#source-code").scrollTop; });
  $("#source-code").addEventListener("keydown", (event) => {
    if (event.key === "Tab" && !state.busy) { event.preventDefault(); const editor = event.target; editor.setRangeText("  ", editor.selectionStart, editor.selectionEnd, "end"); editor.dispatchEvent(new Event("input")); }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); startRun(); }
  });
  $("#run-button").addEventListener("click", () => startRun());
  $("#reset-button").addEventListener("click", () => { setSource(state.task.starter); toast("已载入含一个教学错误的示例。先预测，再运行检查。"); });
  $("#download-source").addEventListener("click", () => downloadText($("#source-code").value, state.task.filename, "text/plain;charset=utf-8"));
  $("#import-button").addEventListener("click", () => $("#file-input").click());
  $("#file-input").addEventListener("change", async (event) => { const file = event.target.files[0]; if (!file) return; if (file.size > 40000) { toast("源码最多 40 KB。"); return; } try { setSource(await file.text()); toast("源码已导入，请确认 entity 和端口符合当前题目。"); } catch { toast("读取文件失败。"); } event.target.value = ""; });
  $("#run-mode").addEventListener("change", () => { const model = $("#run-mode").value === "model"; $("#question-wrap").hidden = !model; if (model && !state.provider.configured) openSettings(); });
  $$("[data-evidence]").forEach((button) => button.addEventListener("click", () => setEvidenceTab(button.dataset.evidence)));
  $$("[data-data]").forEach((button) => button.addEventListener("click", () => setDataTab(button.dataset.data)));
  $("#diagnosis-content").addEventListener("click", async (event) => {
    const hint = event.target.closest("[data-hint]");
    if (hint) {
      const level = Number(hint.dataset.hint);
      if (state.hints[level]) { delete state.hints[level]; renderDiagnosis(); return; }
      hint.disabled = true;
      try { const result = await api("/api/hint", { run_id: state.run.id, level }); state.hints[level] = result.text; renderDiagnosis(); } catch (error) { toast(error.message); hint.disabled = false; }
    }
    const line = event.target.closest("[data-line]");
    if (line) {
      const editor = $("#source-code"), number = Number(line.dataset.line), lines = editor.value.split("\n");
      const start = lines.slice(0, number - 1).join("\n").length + (number > 1 ? 1 : 0);
      editor.focus(); editor.setSelectionRange(start, start + (lines[number - 1]?.length || 0)); editor.scrollTop = Math.max(0, (number - 5) * parseFloat(getComputedStyle(editor).lineHeight));
    }
    if (event.target.closest("[data-reference]")) startRun("reference");
    const apply = event.target.closest("[data-apply]");
    if (apply && !state.busy) {
      setSource(apply.dataset.apply === "candidate" ? state.run.candidate.source : state.run.source);
      toast("已载入验证过的版本。你可以修改并重新运行，或继续回答变式题。");
    }
  });
  $("#previous-failure").addEventListener("click", () => nextFailure(-1));
  $("#next-failure").addEventListener("click", () => nextFailure(1));
  $("#checks-body").addEventListener("click", (event) => { const button = event.target.closest("[data-sample]"); if (button) { state.sample = Number(button.dataset.sample); renderWave(); setDataTab("wave"); } });
  $("#wave-chart").addEventListener("click", (event) => { const svg = event.target.closest("svg"); const checks = state.run?.result?.checks || []; if (!svg || !checks.length) return; const box = svg.getBoundingClientRect(); const value = ((event.clientX - box.left) / box.width * 1000 - 88) / 887 * checks[checks.length - 1].time_ns; state.sample = checks.reduce((best, row, index) => Math.abs(row.time_ns - value) < Math.abs(checks[best].time_ns - value) ? index : best, 0); renderWave(); });
  $("#export-button").addEventListener("click", () => { if (state.run?.status === "complete") { const link = document.createElement("a"); link.href = `/api/runs/${state.run.id}/report`; link.download = `zhidian-${state.task.id}.md`; link.click(); } });
  $("#quiz-area").addEventListener("click", (event) => { const option = event.target.closest("[data-choice]"); if (option && !state.quizResult) { state.quizChoice = Number(option.dataset.choice); renderQuiz(); } if (event.target.closest("#submit-quiz")) submitQuiz(); if (event.target.closest("#next-quiz")) { state.quizIndex = (state.quizIndex + 1) % state.quizzes.length; state.quizChoice = null; state.quizResult = null; renderQuiz(); } });
  $("#settings-button").addEventListener("click", openSettings);
  $("#provider-preset").addEventListener("change", () => {
    if ($("#provider-preset").value === "free") {
      $("#api-base").value = "https://openrouter.ai/api/v1";
      $("#api-model").value = "openrouter/free";
      $("#api-protocol").value = "chat_completions";
      $("#api-key").value = "";
      syncPreset();
    } else {
      $("#preset-note").textContent = "请在服务商控制台确认免费额度和模型的工具调用支持。接口兼容并不代表模型免费。";
    }
  });
  ["#api-base", "#api-model", "#api-protocol"].forEach(selector => $(selector).addEventListener("input", syncPreset));
  $("#close-settings").addEventListener("click", () => $("#settings-dialog").close());
  $("#settings-dialog").addEventListener("click", (event) => { if (event.target === $("#settings-dialog")) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
  $("#settings-form").addEventListener("submit", async (event) => { event.preventDefault(); const button = $("#settings-form button[type=submit]"); button.disabled = true; try { const config = await api("/api/config", { base: $("#api-base").value, model: $("#api-model").value, protocol: $("#api-protocol").value, key: $("#api-key").value }); updateProvider(config); $("#api-key").value = ""; $("#settings-dialog").close(); toast("模型配置已保存到本次服务内存，尚未进行网络验证。"); } catch (error) { toast(error.message); } finally { button.disabled = false; } });
  $("#clear-key").addEventListener("click", async () => { try { updateProvider(await api("/api/config", { base: state.provider.base, model: state.provider.model, protocol: state.provider.protocol, clear_key: true })); $("#api-key").value = ""; toast("已清除本次服务内存中的模型密钥。"); } catch (error) { toast(error.message); } });
  $("#refresh-learning").addEventListener("click", refreshLearning);
  $("#concept-grid").addEventListener("click", (event) => { const button = event.target.closest("[data-practice]"); if (button && !state.busy) { selectTask(button.dataset.practice); location.hash = "workspace"; navigate("workspace"); $("#practice-section").scrollIntoView({ behavior: "smooth", block: "center" }); } });
  $("#history-list").addEventListener("click", (event) => { const button = event.target.closest("[data-history]"); if (button) loadHistory(button.dataset.history); });
  $("#start-demo").addEventListener("click", async () => { await selectTask("counter", state.tasks.find((task) => task.id === "counter").starter); location.hash = "workspace"; navigate("workspace"); window.scrollTo({ top: 0, behavior: "smooth" }); toast("计数器演示已就绪，点击“检查并诊断”开始。"); });
  window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
}

async function initialize() {
  bindEvents();
  try {
    const [health, catalog] = await Promise.all([api("/api/health"), api("/api/tasks")]);
    state.health = health; state.csrf = health.csrf; state.tasks = catalog.tasks;
    updateProvider(health.provider);
    $("#engine-dot").classList.toggle("ready", health.ghdl);
    $("#engine-label").textContent = health.ghdl ? "GHDL 引擎就绪" : "尚未找到 GHDL";
    setBusy(false);
    await selectTask("counter");
    navigate(location.hash.slice(1));
    if (!health.ghdl) toast("未找到 GHDL。请参考 README 配置 GHDL_PATH 后重启。");
    const pending = readLocal("zhidian-pending");
    if (pending) {
      try {
        const job = await api(`/api/runs/${pending}`);
        state.run = job;
        await selectTask(job.task_id, job.original_source || job.source, true);
        renderRun();
        if (job.status === "running") { setBusy(true); setEvidenceTab("trace"); pollRun(pending); }
        else removeLocal("zhidian-pending");
      } catch { removeLocal("zhidian-pending"); }
    }
  } catch (error) {
    $("#engine-label").textContent = "本地服务连接失败";
    $("#run-button").disabled = true;
    const message = document.createElement("div"); message.className = "native-error"; message.textContent = "无法连接知电服务。请运行项目中的启动脚本，然后刷新页面。"; $("#main").prepend(message);
    toast(error.message);
  }
}

initialize();
