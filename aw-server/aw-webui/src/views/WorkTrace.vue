<template>
  <main class="wt">
    <aside class="wt-sidebar">
      <div class="wt-brand"><img src="/worktrace.svg" alt="藏羚" /><span>Work trace</span></div>
      <nav aria-label="工作台导航">
        <button
          v-for="item in tabs"
          :key="item.id"
          :class="{ active: tab === item.id }"
          :aria-current="tab === item.id ? 'page' : null"
          @click="tab = item.id"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            aria-hidden="true"
          >
            <path :d="navPaths[item.id]" />
          </svg>
          <span>{{ item.name }}</span>
        </button>
      </nav>
      <div class="wt-sidebar-context">
        <label class="wt-project-selector"
          >当前项目<select
            :value="state.project_id || ''"
            :disabled="busy || !connected"
            @change="switchProject($event.target.value)"
          >
            <option value="">未关联项目</option>
            <option v-for="p in activeProjects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select></label
        >
        <div class="wt-capture">
          <span class="wt-status" :class="{ paused: state.paused || !connected }">{{
            !connected ? '未连接' : state.paused ? '已暂停' : '记录中'
          }}</span
          ><button
            class="wt-icon-button"
            :disabled="busy || !connected"
            :title="state.paused ? '继续记录' : '暂停记录'"
            :aria-label="state.paused ? '继续记录' : '暂停记录'"
            @click="togglePause"
          >
            {{ state.paused ? '▷' : 'Ⅱ' }}
          </button>
        </div>
      </div>
    </aside>
    <div class="wt-main">
      <header class="wt-heading">
        <h1>{{ tabs.find(item => item.id === tab).name }}</h1>
        <div class="wt-actions">
          <template v-if="tab === 'journal'"
            ><button :aria-expanded="showFilters" @click="showFilters = !showFilters">筛选</button
            ><button class="wt-primary" :disabled="!connected" @click="openNote()">
              ＋ 记一笔
            </button></template
          ><button v-if="tab === 'projects'" class="wt-primary" @click="openProject()">
            ＋ 新建项目</button
          ><button
            v-if="tab === 'reports' && !selectedReport"
            class="wt-primary"
            @click="reportDialog = true"
          >
            生成总结
          </button>
        </div>
      </header>
      <div v-if="error" class="wt-error" role="alert">
        {{ error }} <button @click="load">重试</button>
      </div>
      <div v-if="message" class="wt-toast" role="status">{{ message }}</div>

      <section v-if="tab === 'journal'">
        <div v-if="showFilters" class="wt-filter-panel">
          <label>开始日期<input v-model="from" type="date" /></label
          ><label>结束日期<input v-model="through" type="date" /></label
          ><label
            >项目<select v-model="filterProject">
              <option value="">全部项目</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select></label
          ><button :disabled="busy" @click="applyFilters">应用</button>
        </div>
        <div class="wt-section-label">
          <span>{{ dateLabel }}</span
          ><button class="wt-link-button" :disabled="busy" @click="loadOverview">刷新</button>
        </div>
        <div class="wt-stats">
          <div>
            <span>活跃时间</span><strong>{{ duration(overview.activity.seconds) }}</strong>
          </div>
          <div>
            <span>补录时长</span><strong>{{ overview.manual_minutes }} <small>分钟</small></strong>
          </div>
          <div>
            <span>工作记录</span><strong>{{ overview.notes.length }} <small>条</small></strong>
          </div>
        </div>
        <div class="wt-section-label"><h2>记录</h2></div>
        <div class="wt-list">
          <p v-if="!overview.notes.length" class="wt-empty">暂无记录</p>
          <article v-for="note in overview.notes" :key="note.id" class="wt-note wt-row">
            <div class="wt-note-content">
              <p>{{ note.content }}</p>
              <div class="wt-meta">
                <span>{{ kindName(note.kind) }}</span
                ><time>{{ timeText(note.occurred) }}</time
                ><span v-if="note.project_id">{{ projectName(note.project_id) }}</span
                ><span v-if="note.minutes">{{ note.minutes }} 分钟</span>
              </div>
            </div>
            <details class="wt-menu">
              <summary aria-label="记录操作" title="更多操作">⋯</summary>
              <div>
                <button @click="editNote(note)">编辑</button
                ><button :disabled="busy" @click="deleteNote(note)">删除</button>
              </div>
            </details>
          </article>
        </div>
        <details class="wt-disclosure">
          <summary>
            应用活动 <span>{{ overview.activity.apps.length }}</span>
          </summary>
          <div class="wt-list">
            <p v-if="!overview.activity.apps.length" class="wt-empty">暂无活动</p>
            <div v-for="app in overview.activity.apps" :key="app.app" class="wt-row">
              <span>{{ app.app }}</span
              ><span>{{ duration(app.seconds) }}</span>
            </div>
          </div>
          <details class="wt-timeline">
            <summary>活动明细</summary>
            <div v-for="(event, index) in overview.activity.timeline" :key="index" class="wt-event">
              <time>{{ timeText(event.start) }}</time
              ><strong>{{ event.app }}</strong
              ><span>{{ event.title }}</span
              ><small>{{ duration(event.end - event.start) }}</small>
            </div>
          </details>
        </details>
      </section>

      <section v-if="tab === 'projects'">
        <div class="wt-list">
          <p v-if="!visibleProjects.length" class="wt-empty">暂无项目</p>
          <article v-for="p in visibleProjects" :key="p.id" class="wt-row wt-project">
            <div class="wt-project-info">
              <h2>{{ p.name }} <span v-if="p.archived" class="wt-badge">已归档</span></h2>
              <p v-if="p.description">{{ p.description }}</p>
            </div>
            <div class="wt-actions">
              <button
                v-if="!p.archived"
                :disabled="busy || state.project_id === p.id"
                @click="switchProject(p.id)"
              >
                {{ state.project_id === p.id ? '当前项目' : '开始记录' }}
              </button>
              <details class="wt-menu">
                <summary aria-label="项目操作" title="更多操作">⋯</summary>
                <div>
                  <button @click="projectReport(p)">项目总结</button
                  ><button @click="openProject(p)">编辑</button
                  ><button :disabled="busy" @click="archiveProject(p)">
                    {{ p.archived ? '恢复' : '归档' }}
                  </button>
                </div>
              </details>
            </div>
          </article>
        </div>
        <label v-if="projects.some(p => p.archived)" class="wt-check wt-archived"
          ><input v-model="showArchived" type="checkbox" /> 显示已归档</label
        >
      </section>

      <section v-if="tab === 'reports'">
        <template v-if="!selectedReport"
          ><div class="wt-list">
            <p v-if="!reports.length" class="wt-empty">暂无总结</p>
            <button
              v-for="r in reports"
              :key="r.id"
              class="wt-report-item"
              @click="selectReport(r)"
            >
              <div>
                <strong>{{ r.title }}</strong
                ><small>{{ timeText(r.updated) }}{{ r.edited ? ' · 已编辑' : '' }}</small>
              </div>
              <span aria-hidden="true">›</span>
            </button>
          </div></template
        >
        <template v-else
          ><div class="wt-report-tools">
            <button class="wt-link-button" @click="closeReport">‹ 返回</button>
            <div class="wt-actions">
              <button v-if="!reportEditing" @click="reportEditing = true">编辑</button
              ><button v-else class="wt-primary" :disabled="busy" @click="saveReport">保存</button>
              <details class="wt-menu">
                <summary aria-label="总结操作" title="更多操作">⋯</summary>
                <div><button :disabled="busy" @click="regenerateSelected">重新生成</button></div>
              </details>
            </div>
          </div>
          <article class="wt-report-paper">
            <h2>{{ selectedReport.title }}</h2>
            <textarea
              v-if="reportEditing"
              v-model="reportBody"
              aria-label="总结内容"
              class="wt-report-editor"
              rows="20"
            ></textarea>
            <div v-else class="wt-report-preview">
              <template v-for="(block, i) in reportBlocks"
                ><h3 v-if="block.kind === 'heading'" :key="i">{{ block.text }}</h3>
                <p v-else :key="i" :class="{ 'wt-bullet': block.kind === 'bullet' }">
                  {{ block.text }}
                </p></template
              >
            </div>
          </article></template
        >
      </section>

      <section v-if="tab === 'settings'" class="wt-settings">
        <div class="wt-list">
          <div class="wt-row">
            <span>自动生成日 / 周 / 月总结</span
            ><label class="wt-switch"
              ><input
                type="checkbox"
                aria-label="自动总结"
                :checked="state.auto_reports"
                :disabled="busy"
                @change="setAuto($event.target.checked)" /><span></span
            ></label>
          </div>
          <div class="wt-row">
            <div class="wt-setting-text">
              <span>保存位置</span
              ><small class="wt-path" :title="state.storage">{{ state.storage }}</small>
            </div>
            <button @click="copyStorage">复制路径</button>
          </div>
          <div class="wt-row"><span>登录后自动启动</span><small>在托盘菜单中设置</small></div>
        </div>
        <div class="wt-section-label"><h2>更多</h2></div>
        <div class="wt-list">
          <router-link to="/home" class="wt-row"
            ><span>活动分析</span><span aria-hidden="true">›</span></router-link
          ><router-link to="/settings" class="wt-row"
            ><span>高级设置</span><span aria-hidden="true">›</span></router-link
          >
        </div>
        <p class="wt-about">Work trace · 基于 ActivityWatch</p>
      </section>
    </div>

    <div v-if="noteForm" class="wt-overlay" @click.self="closeNote">
      <section class="wt-dialog" role="dialog" aria-modal="true" aria-labelledby="note-title">
        <h2 id="note-title">{{ noteForm.id ? '编辑记录' : '记一笔' }}</h2>
        <form @submit.prevent="saveNote">
          <textarea
            ref="noteContent"
            v-model="noteForm.content"
            aria-label="工作内容"
            rows="4"
            maxlength="20000"
            placeholder="记录工作内容"
            required
          ></textarea>
          <div class="wt-fields">
            <label
              >类型<select v-model="noteForm.kind">
                <option v-for="(label, key) in kinds" :key="key" :value="key">{{ label }}</option>
              </select></label
            ><label
              >项目<select v-model="noteForm.project_id">
                <option value="">未关联项目</option>
                <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select></label
            >
          </div>
          <details class="wt-more-options" :open="!!noteForm.id">
            <summary>更多选项</summary>
            <div class="wt-fields">
              <label
                >发生时间<input v-model="noteForm.occurred" type="datetime-local" required /></label
              ><label
                >补录时长（分钟）<input
                  v-model.number="noteForm.minutes"
                  type="number"
                  min="0"
                  max="1440"
                  step="0.5"
              /></label>
            </div>
          </details>
          <p v-if="error" class="wt-error" role="alert">{{ error }}</p>
          <div class="wt-dialog-footer">
            <button type="button" @click="closeNote">取消</button
            ><button class="wt-primary" :disabled="busy">保存记录</button>
          </div>
        </form>
      </section>
    </div>
    <div v-if="projectForm" class="wt-overlay" @click.self="projectForm = null">
      <section class="wt-dialog" role="dialog" aria-modal="true" aria-labelledby="project-title">
        <h2 id="project-title">{{ projectForm.id ? '编辑项目' : '新建项目' }}</h2>
        <form @submit.prevent="saveProject">
          <label
            >项目名称<input ref="projectName" v-model="projectForm.name" maxlength="100" required
          /></label>
          <details class="wt-more-options" :open="!!projectForm.description">
            <summary>项目说明</summary>
            <textarea
              v-model="projectForm.description"
              aria-label="项目说明"
              rows="3"
              maxlength="4000"
            ></textarea>
          </details>
          <p v-if="error" class="wt-error" role="alert">{{ error }}</p>
          <div class="wt-dialog-footer">
            <button type="button" @click="projectForm = null">取消</button
            ><button class="wt-primary" :disabled="busy">保存项目</button>
          </div>
        </form>
      </section>
    </div>
    <div v-if="reportDialog" class="wt-overlay" @click.self="reportDialog = false">
      <section class="wt-dialog" role="dialog" aria-modal="true" aria-labelledby="report-title">
        <h2 id="report-title">生成总结</h2>
        <form @submit.prevent="generateReport">
          <div class="wt-fields">
            <label
              >类型<select v-model="reportKind">
                <option value="day">每日总结</option>
                <option value="week">每周总结</option>
                <option value="month">每月总结</option>
                <option value="project">项目总结</option>
              </select></label
            ><label
              >项目<select v-model="reportProject">
                <option v-if="reportKind !== 'project'" value="">全部项目</option>
                <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select></label
            >
          </div>
          <label v-if="reportKind !== 'project'"
            >日期<input v-model="reportDate" type="date" required
          /></label>
          <div v-else class="wt-fields">
            <label>开始日期<input v-model="reportFrom" type="date" required /></label
            ><label>结束日期<input v-model="reportThrough" type="date" required /></label>
          </div>
          <p v-if="error" class="wt-error" role="alert">{{ error }}</p>
          <div class="wt-dialog-footer">
            <button type="button" @click="reportDialog = false">取消</button
            ><button class="wt-primary" :disabled="busy">生成</button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<script>
import { getClient } from '~/util/awclient';

function localInput(value = new Date()) {
  const day = new Date(value);
  return new Date(day.getTime() - day.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function nextDay(value) {
  const day = new Date(value + 'T00:00:00');
  day.setDate(day.getDate() + 1);
  return localInput(day).slice(0, 10);
}

export default {
  beforeRouteLeave(to, from, next) {
    next(this.canLeaveReport());
  },
  data() {
    const today = localInput().slice(0, 10);
    return {
      tab: 'journal',
      showFilters: false,
      showArchived: false,
      reportDialog: false,
      reportEditing: false,
      navPaths: {
        journal: 'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',
        projects: 'M3 6h7l2 2h9v12H3z M3 6V4h7l2 2',
        reports: 'M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6',
        settings:
          'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
      },
      tabs: [
        { id: 'journal', name: '工作记录' },
        { id: 'projects', name: '项目管理' },
        { id: 'reports', name: '总结中心' },
        { id: 'settings', name: '设置' },
      ],
      kinds: {
        note: '工作记录',
        done: '完成事项',
        milestone: '里程碑',
        issue: '问题',
        todo: '下一步',
      },
      state: {},
      projects: [],
      reports: [],
      connected: false,
      busy: false,
      error: '',
      message: '',
      from: today,
      through: today,
      filterProject: '',
      reportKind: 'day',
      reportDate: today,
      reportFrom: today,
      reportThrough: today,
      reportProject: '',
      selectedReport: null,
      reportBody: '',
      reportPath: '',
      overview: { notes: [], manual_minutes: 0, activity: { seconds: 0, apps: [], timeline: [] } },
      noteForm: null,
      projectForm: null,
    };
  },
  computed: {
    visibleProjects() {
      return this.projects.filter(p => this.showArchived || !p.archived);
    },
    dateLabel() {
      if (this.from !== this.through) return `${this.from} — ${this.through}`;
      return this.from === localInput().slice(0, 10) ? '今天' : this.from;
    },
    reportBlocks() {
      return this.reportBody
        .split('\n')
        .filter(line => line.trim() && !line.startsWith('# '))
        .map(line => ({
          kind: line.startsWith('## ') ? 'heading' : line.startsWith('- ') ? 'bullet' : 'text',
          text: line.replace(/^(## |- )/, ''),
        }));
    },
    activeProjects() {
      return this.projects.filter(p => !p.archived);
    },
  },
  watch: {
    message(value) {
      clearTimeout(this.messageTimer);
      if (value)
        this.messageTimer = setTimeout(() => {
          this.message = '';
        }, 3200);
    },
    reportDialog(value) {
      if (value) this.$nextTick(() => this.$el.querySelector('.wt-dialog select')?.focus());
    },
  },
  mounted() {
    document.title = 'Work trace · 工作留痕';
    this.load();
    this.refreshTimer = setInterval(async () => {
      if (!this.busy && !this.noteForm && !this.projectForm && !this.reportDialog) {
        await this.refreshState();
        if (this.connected && this.tab === 'journal') {
          try {
            await this.fetchOverview();
          } catch (e) {
            this.error = e.message;
          }
        }
      }
    }, 10000);
    document.addEventListener('keydown', this.dialogKeys);
    document.addEventListener('click', this.dismissMenus);
    window.addEventListener('beforeunload', this.beforeUnload);
  },
  beforeDestroy() {
    clearInterval(this.refreshTimer);
    clearTimeout(this.messageTimer);
    document.removeEventListener('click', this.dismissMenus);
    document.removeEventListener('keydown', this.dialogKeys);
    window.removeEventListener('beforeunload', this.beforeUnload);
  },
  methods: {
    dismissMenus(event) {
      this.$el.querySelectorAll('.wt-menu[open]').forEach(menu => {
        if (!menu.contains(event.target) || event.target.closest('button')) menu.open = false;
      });
    },
    async applyFilters() {
      await this.loadOverview();
      if (!this.error) this.showFilters = false;
    },
    closeReport() {
      if (!this.canLeaveReport()) return;
      this.selectedReport = null;
      this.reportBody = '';
      this.reportEditing = false;
    },
    copyStorage() {
      return this.perform(async () => {
        await navigator.clipboard.writeText(this.state.storage);
        this.message = '路径已复制';
      });
    },
    beforeUnload(event) {
      if (
        (this.selectedReport && this.reportBody !== this.selectedReport.body) ||
        this.noteForm ||
        this.projectForm
      ) {
        event.preventDefault();
        event.returnValue = '';
      }
    },
    async api(method, path, data) {
      const result = await getClient().req.request({ method, url: '/0/worktrace' + path, data });
      return result.data;
    },
    async perform(action) {
      if (this.busy) return;
      this.busy = true;
      this.error = '';
      this.message = '';
      try {
        await action();
      } catch (e) {
        this.error = e.response?.data?.message || e.message || '操作失败，请重试';
      } finally {
        this.busy = false;
      }
    },
    async load() {
      await this.perform(async () => {
        await this.refreshState();
        this.reports = await this.api('get', '/reports');
        await this.fetchOverview();
      });
    },
    async refreshState() {
      try {
        const [state, projects] = await Promise.all([
          this.api('get', '/state'),
          this.api('get', '/projects'),
        ]);
        this.state = state;
        this.projects = projects;
        this.connected = true;
      } catch (e) {
        this.connected = false;
        this.error = '服务未连接，请启动 Work trace。';
      }
    },
    async fetchOverview() {
      if (!this.from || !this.through || this.from > this.through)
        throw new Error('请选择有效的日期范围');
      const query = new URLSearchParams({
        start: this.from,
        end: nextDay(this.through),
        project_id: this.filterProject,
      });
      this.overview = await this.api('get', '/overview?' + query);
    },
    loadOverview() {
      return this.perform(() => this.fetchOverview());
    },
    switchProject(id) {
      return this.perform(async () => {
        this.state = await this.api('patch', '/state', { project_id: id || null });
        this.message = '已切换记录项目';
      });
    },
    togglePause() {
      return this.perform(async () => {
        this.state = await this.api('patch', '/state', { paused: !this.state.paused });
      });
    },
    setAuto(value) {
      return this.perform(async () => {
        this.state = await this.api('patch', '/state', { auto_reports: value });
      });
    },
    duration(seconds) {
      const minutes = Math.round((seconds || 0) / 60);
      return minutes >= 60
        ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
        : `${minutes} 分钟`;
    },
    timeText(seconds) {
      return new Date(seconds * 1000).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
    },
    kindName(kind) {
      return this.kinds[kind] || kind;
    },
    projectName(id) {
      return this.projects.find(p => p.id === id)?.name || '未关联项目';
    },
    openNote(kind = 'note') {
      this.error = '';
      this.noteForm = {
        kind,
        project_id: this.state.project_id || '',
        occurred: localInput(),
        minutes: 0,
        content: '',
      };
      this.$nextTick(() => this.$refs.noteContent.focus());
    },
    editNote(note) {
      this.error = '';
      this.noteForm = {
        ...note,
        project_id: note.project_id || '',
        occurred: localInput(new Date(note.occurred * 1000)),
      };
      this.$nextTick(() => this.$refs.noteContent.focus());
    },
    closeNote() {
      if (
        !this.busy &&
        (!this.noteForm?.content || window.confirm('关闭后，本次未保存的修改将丢失。继续关闭？'))
      )
        this.noteForm = null;
    },
    saveNote() {
      return this.perform(async () => {
        const data = {
          ...this.noteForm,
          project_id: this.noteForm.project_id || null,
          occurred: new Date(this.noteForm.occurred).toISOString(),
        };
        await this.api(data.id ? 'put' : 'post', '/notes' + (data.id ? '/' + data.id : ''), data);
        this.noteForm = null;
        await this.fetchOverview();
        this.message = '工作记录已保存';
      });
    },
    deleteNote(note) {
      if (window.confirm('删除这条工作记录？此操作不能撤销。'))
        return this.perform(async () => {
          await this.api('delete', '/notes/' + note.id, {});
          await this.fetchOverview();
        });
    },
    openProject(project) {
      this.error = '';
      this.projectForm = project
        ? { ...project, archived: !!project.archived }
        : { name: '', description: '', archived: false };
      this.$nextTick(() => this.$refs.projectName.focus());
    },
    saveProject() {
      return this.perform(async () => {
        const data = this.projectForm;
        await this.api(
          data.id ? 'put' : 'post',
          '/projects' + (data.id ? '/' + data.id : ''),
          data
        );
        this.projects = await this.api('get', '/projects');
        this.projectForm = null;
        this.message = '项目已保存';
      });
    },
    archiveProject(project) {
      return this.perform(async () => {
        await this.api('put', '/projects/' + project.id, {
          ...project,
          archived: !project.archived,
        });
        this.projects = await this.api('get', '/projects');
      });
    },
    projectReport(project) {
      if (!this.canLeaveReport()) return;
      this.tab = 'reports';
      this.reportDialog = true;
      this.reportKind = 'project';
      this.reportProject = project.id;
      this.reportFrom = localInput(new Date(project.created * 1000)).slice(0, 10);
      this.reportThrough = localInput().slice(0, 10);
    },
    canLeaveReport() {
      return (
        !this.selectedReport ||
        this.reportBody === this.selectedReport.body ||
        window.confirm('当前总结有未保存修改，确定离开？')
      );
    },
    selectReport(report) {
      if (this.canLeaveReport()) {
        this.reportEditing = false;
        this.selectedReport = { ...report };
        this.reportBody = report.body;
        this.reportPath = report.path || '';
      }
    },
    generateReport() {
      if (!this.canLeaveReport()) return;
      return this.perform(async () => {
        if (this.reportKind === 'project' && !this.reportProject)
          throw new Error('请选择要总结的项目');
        const report = await this.api('post', '/reports', {
          kind: this.reportKind,
          date: this.reportDate,
          start: this.reportFrom,
          end: nextDay(this.reportThrough),
          project_id: this.reportProject,
        });
        this.selectedReport = report;
        this.reportDialog = false;
        this.reportEditing = false;
        this.reportBody = report.body;
        this.reportPath = report.path;
        this.reports = await this.api('get', '/reports');
        this.message = '总结已保存';
      });
    },
    regenerateSelected() {
      if (!window.confirm('重新生成将覆盖这份总结的人工修改，是否继续？')) return;
      return this.perform(async () => {
        const old = this.selectedReport;
        const report = await this.api('post', '/reports', {
          kind: old.kind,
          date: old.start,
          start: old.start,
          end: old.end,
          project_id: old.project_id,
          regenerate: true,
        });
        this.selectedReport = report;
        this.reportBody = report.body;
        this.reportPath = report.path;
        this.reports = await this.api('get', '/reports');
      });
    },
    saveReport() {
      return this.perform(async () => {
        const report = await this.api('put', '/reports/' + this.selectedReport.id, {
          body: this.reportBody,
        });
        this.selectedReport = report;
        this.reportPath = report.path;
        this.reports = await this.api('get', '/reports');
        this.reportEditing = false;
        this.message = '总结已保存';
      });
    },
    dialogKeys(event) {
      if (!this.noteForm && !this.projectForm && !this.reportDialog) return;
      if (event.key === 'Escape') {
        if (this.noteForm) this.closeNote();
        else if (!this.busy) {
          this.projectForm = null;
          this.reportDialog = false;
        }
      }
      if (event.key === 'Tab') {
        const dialog = this.$el.querySelector('.wt-dialog');
        const nodes = Array.from(dialog.querySelectorAll('input,select,textarea,button')).filter(
          el => !el.disabled && el.getClientRects().length
        );
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    },
  },
};
</script>

<style scoped>
.wt {
  --bg: #f3f3f3;
  --surface: #fbfbfb;
  --input: #fff;
  --line: #e5e5e5;
  --text: #202020;
  --muted: #666;
  --hover: #eaeaea;
  --selected: #e4e4e4;
  --accent: #0067c0;
  background: var(--bg);
  color: var(--text);
  font: 14px 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei UI', sans-serif;
  min-height: 100vh;
  display: grid;
  grid-template-columns: 246px minmax(0, 1fr);
}
.wt * {
  box-sizing: border-box;
}
.wt-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}
.wt-brand {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 8px 12px;
  font-weight: 600;
  font-size: 17px;
}
.wt-brand img {
  width: 36px;
  height: 36px;
  object-fit: contain;
}
.wt-sidebar nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.wt-sidebar nav button {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  height: 42px;
  width: 100%;
  background: transparent;
  border: none;
  text-align: left;
  padding: 0 16px;
}
.wt-sidebar nav button.active {
  background: var(--selected);
}
.wt-sidebar nav button.active::before {
  content: '';
  position: absolute;
  left: 0;
  height: 18px;
  width: 3px;
  border-radius: 2px;
  background: var(--accent);
}
.wt-sidebar nav svg {
  width: 19px;
  height: 19px;
}
.wt-sidebar-context {
  margin-top: auto;
  padding: 0 12px;
}
.wt-capture {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}
.wt-status {
  font-size: 12px;
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.wt-status::before {
  content: '';
  width: 6px;
  height: 6px;
  background: #16834b;
  border-radius: 50%;
}
.wt-status.paused::before {
  background: #a07830;
}
.wt-main {
  padding: 48px 48px 80px 32px;
  width: 100%;
  max-width: 1160px;
}
.wt-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
  min-height: 40px;
}
.wt h1 {
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.5px;
  margin: 0;
}
.wt h2 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}
.wt h3 {
  font-size: 16px;
  font-weight: 600;
}
.wt p {
  line-height: 1.7;
}
.wt button {
  color: var(--text);
  font: inherit;
  background: var(--input);
  border: 1px solid var(--line);
  border-bottom-color: #d1d1d1;
  border-radius: 4px;
  padding: 6px 14px;
  min-height: 32px;
  cursor: pointer;
  white-space: nowrap;
}
.wt button:hover {
  background: var(--hover);
}
.wt button:active {
  opacity: 0.8;
}
.wt button:disabled {
  opacity: 0.45;
  cursor: default;
}
.wt button:focus-visible,
.wt summary:focus-visible,
.wt a:focus-visible {
  outline: 2px solid var(--text);
  outline-offset: 2px;
}
.wt .wt-primary {
  color: #fff;
  background: var(--accent);
  border-color: transparent;
}
.wt .wt-primary:hover {
  filter: brightness(1.1);
}
.wt .wt-link-button,
.wt .wt-icon-button {
  background: transparent;
  border-color: transparent;
  padding: 4px 8px;
}
.wt .wt-link-button {
  color: var(--accent);
}
.wt .wt-icon-button {
  min-width: 32px;
}
.wt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.wt label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  font-size: 12px;
}
.wt input,
.wt select,
.wt textarea {
  font: inherit;
  font-size: 14px;
  width: 100%;
  min-width: 0;
  color: var(--text);
  background: var(--input);
  border: 1px solid var(--line);
  border-bottom-color: #909090;
  padding: 7px 10px;
  border-radius: 4px;
}
.wt input:focus,
.wt select:focus,
.wt textarea:focus {
  outline: none;
  border-bottom: 2px solid var(--accent);
}
.wt textarea {
  resize: vertical;
  line-height: 1.75;
}
.wt-section-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 26px;
  margin: 22px 0 10px;
  font-size: 12px;
  color: var(--muted);
}
.wt-section-label h2 {
  color: var(--text);
}
.wt-filter-panel {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 20px;
  background: var(--surface);
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.wt-filter-panel label {
  flex: 1;
  min-width: 130px;
}
.wt-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 22px 0;
}
.wt-stats > div {
  padding: 0 24px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.wt-stats > div + div {
  border-left: 1px solid var(--line);
}
.wt-stats span {
  font-size: 12px;
  color: var(--muted);
}
.wt-stats strong {
  font-size: 24px;
  font-weight: 600;
}
.wt-stats small {
  font-size: 12px;
  font-weight: 400;
  color: var(--muted);
}
.wt-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.wt-row,
.wt-report-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 19px 22px;
  background: var(--surface);
  min-height: 70px;
}
.wt-note-content,
.wt-project-info {
  min-width: 0;
  flex: 1;
}
.wt-note p {
  margin: 0 0 7px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.wt-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--muted);
}
.wt-empty {
  margin: 0;
  padding: 52px 24px;
  text-align: center;
  color: var(--muted);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 5px;
  font-size: 13px;
}
.wt-menu {
  position: relative;
  flex: 0 0 auto;
}
.wt-menu summary {
  list-style: none;
  cursor: pointer;
  border-radius: 4px;
  text-align: center;
  font-size: 22px;
  line-height: 30px;
  width: 32px;
  height: 32px;
}
.wt-menu summary::-webkit-details-marker {
  display: none;
}
.wt-menu summary:hover,
.wt-menu[open] summary {
  background: var(--hover);
}
.wt-menu > div {
  position: absolute;
  right: 0;
  top: 36px;
  min-width: 128px;
  z-index: 10;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px;
  box-shadow: 0 5px 18px #0002;
}
.wt-menu button {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 0;
}
.wt-disclosure {
  margin-top: 24px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
}
.wt-disclosure > summary {
  padding: 19px 22px;
  cursor: pointer;
  font-size: 13px;
}
.wt-disclosure > summary span {
  float: right;
  color: var(--muted);
}
.wt-disclosure > .wt-list {
  margin: 0 18px 16px;
}
.wt-disclosure .wt-row {
  min-height: 44px;
  padding: 10px 12px;
  font-size: 12px;
}
.wt-timeline {
  margin: 16px 22px;
  font-size: 12px;
}
.wt-timeline summary {
  cursor: pointer;
  margin-bottom: 10px;
}
.wt-event {
  display: grid;
  grid-template-columns: 104px 130px 1fr 70px;
  gap: 10px;
  padding: 10px 0;
  border-top: 1px solid var(--line);
}
.wt-event span {
  overflow-wrap: anywhere;
}
.wt-project-info p {
  color: var(--muted);
  font-size: 12px;
  margin: 6px 0 0;
  white-space: pre-wrap;
}
.wt-badge {
  font-size: 11px;
  font-weight: normal;
  color: var(--muted);
  margin-left: 8px;
}
.wt .wt-check {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.wt-check input {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
.wt-archived {
  margin-top: 18px !important;
  color: var(--muted);
}
.wt .wt-report-item {
  padding: 20px 22px;
  width: 100%;
  text-align: left;
  white-space: normal;
}
.wt-report-item strong {
  display: block;
  font-weight: 400;
  font-size: 14px;
}
.wt-report-item small {
  display: block;
  color: var(--muted);
  margin-top: 6px;
  font-size: 11px;
}
.wt-report-item > span {
  font-size: 22px;
  color: var(--muted);
}
.wt-report-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -12px 0 16px;
}
.wt-report-paper {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 32px 36px;
}
.wt-report-paper > h2 {
  font-size: 20px;
  margin-bottom: 24px;
}
.wt-report-preview h3 {
  margin: 26px 0 12px;
}
.wt-report-preview p {
  margin: 8px 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.wt-bullet {
  position: relative;
  padding-left: 16px;
}
.wt-bullet::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--muted);
}
.wt-report-editor {
  min-height: 460px;
}
.wt-settings .wt-row {
  min-height: 76px;
}
.wt-setting-text {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.wt-settings small {
  font-size: 12px;
  color: var(--muted);
}
.wt-path {
  overflow-wrap: anywhere;
}
.wt-settings a {
  text-decoration: none;
  color: var(--text);
}
.wt-settings a:hover {
  background: var(--hover);
}
.wt-about {
  color: var(--muted);
  font-size: 11px;
  margin-top: 28px;
}
.wt-switch {
  position: relative;
  flex-shrink: 0;
}
.wt-switch input {
  position: absolute;
  opacity: 0;
  width: 40px;
  height: 22px;
  cursor: pointer;
  z-index: 1;
}
.wt-switch span {
  display: block;
  width: 40px;
  height: 22px;
  border-radius: 12px;
  border: 1px solid var(--muted);
  position: relative;
}
.wt-switch span::after {
  content: '';
  position: absolute;
  width: 12px;
  height: 12px;
  top: 4px;
  left: 4px;
  background: var(--muted);
  border-radius: 50%;
  transition: transform 0.12s;
}
.wt-switch input:checked + span {
  background: var(--accent);
  border-color: var(--accent);
}
.wt-switch input:checked + span::after {
  background: #fff;
  transform: translateX(18px);
}
.wt-switch input:focus-visible + span {
  outline: 2px solid var(--text);
  outline-offset: 3px;
}
.wt-error {
  color: #b3261e;
  background: #fff4f3;
  padding: 12px 16px;
  border-radius: 5px;
  margin: 0 0 16px;
  font-size: 13px;
}
.wt-toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  border-radius: 6px;
  box-shadow: 0 4px 18px #0002;
  z-index: 2100;
  font-size: 13px;
}
.wt-overlay {
  position: fixed;
  inset: 0;
  background: #0005;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.wt-dialog {
  width: 460px;
  max-width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 16px 48px #0003;
}
.wt-dialog h2 {
  font-size: 20px;
  margin-bottom: 20px;
}
.wt-fields {
  display: flex;
  gap: 14px;
  margin: 18px 0;
}
.wt-fields label {
  flex: 1;
  min-width: 0;
}
.wt-more-options {
  margin-top: 18px;
  font-size: 12px;
}
.wt-more-options summary {
  cursor: pointer;
  color: var(--muted);
  margin-bottom: 12px;
}
.wt-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 22px;
}
.wt-dialog-footer button {
  min-width: 84px;
}
@media (prefers-color-scheme: dark) {
  .wt {
    --bg: #202020;
    --surface: #2b2b2b;
    --input: #323232;
    --line: #3b3b3b;
    --text: #f5f5f5;
    --muted: #b0b0b0;
    --hover: #363636;
    --selected: #383838;
    --accent: #60b4ff;
    color-scheme: dark;
  }
  .wt .wt-primary {
    color: #102334;
  }
  .wt-error {
    background: #3e2929;
    color: #ffb4ab;
  }
}
@media (max-width: 1000px) {
  .wt {
    grid-template-columns: 210px minmax(0, 1fr);
  }
  .wt-main {
    padding: 38px 24px 60px;
  }
  .wt-stats > div {
    padding: 0 16px;
  }
  .wt-stats strong {
    font-size: 20px;
  }
}
@media (max-width: 720px) {
  .wt {
    grid-template-columns: 1fr;
    align-content: start;
  }
  .wt-sidebar {
    position: static;
    height: auto;
    padding: 12px 16px 0;
    gap: 12px;
  }
  .wt-brand {
    padding: 2px 0;
    font-size: 15px;
  }
  .wt-brand img {
    width: 25px;
    height: 25px;
  }
  .wt-sidebar nav {
    flex-direction: row;
    gap: 2px;
  }
  .wt-sidebar nav button {
    justify-content: center;
    gap: 7px;
    padding: 0 9px;
    font-size: 12px;
  }
  .wt-sidebar nav svg {
    width: 16px;
    height: 16px;
  }
  .wt-sidebar nav button.active::before {
    bottom: 0;
    left: calc(50% - 10px);
    height: 3px;
    width: 20px;
  }
  .wt-sidebar-context {
    display: flex;
    margin-top: 0;
    align-items: center;
    gap: 18px;
    padding: 0;
  }
  .wt-project-selector {
    flex-direction: row !important;
    align-items: center;
    flex: 1;
    white-space: nowrap;
  }
  .wt-project-selector select {
    flex: 1;
  }
  .wt-capture {
    margin-top: 0;
    gap: 8px;
  }
  .wt-main {
    padding: 26px 16px 48px;
  }
  .wt-heading {
    margin-bottom: 20px;
  }
  .wt h1 {
    font-size: 24px;
  }
  .wt-stats {
    padding: 18px 0;
  }
  .wt-stats > div {
    padding: 0 12px;
  }
  .wt-stats strong {
    font-size: 18px;
  }
  .wt-stats span {
    font-size: 11px;
  }
  .wt-row {
    padding: 16px;
    gap: 12px;
  }
  .wt-event {
    grid-template-columns: 1fr 1fr;
  }
  .wt-report-paper {
    padding: 22px;
  }
  .wt-settings .wt-row {
    flex-wrap: wrap;
  }
  .wt-toast {
    max-width: calc(100vw - 32px);
    right: 16px;
    bottom: 16px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .wt * {
    transition: none !important;
  }
}
</style>
